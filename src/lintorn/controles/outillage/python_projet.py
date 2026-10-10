# Lintorn
"""Quel python audite : celui du venv du projet, ou aucun ?"""

from __future__ import annotations

from ... import chemins, config
from ...base import Resultat


def controle_python_projet() -> Resultat:
    """Les outils tournent-ils sur le venv DU PROJET, ou sur celui de la machine ?

    LA PANNE : faute de venv aux emplacements connus, `_python_du_projet()`
    retombait sur `sys.executable` — et ne le disait à personne. Tant que
    Lintorn vivait dans le venv du projet, le repli était sans conséquence.
    Depuis qu'il s'installe par `pip` sur la machine, il désigne le python
    DU SYSTÈME.

    Ce que ça change, et pourquoi ce n'est pas un détail cosmétique :

      * `Dependances vs venv` compare `requirements.txt` aux paquets du
        SYSTÈME. Il répond, avec aplomb, sur un environnement que personne
        n'a demandé à auditer.
      * `pip-audit` audite les failles de la MACHINE, pas celles du projet.
      * `pytest` exécute le code du projet sans aucune de ses dépendances.

    Aucun de ces trois-là ne passe au rouge pour autant : ils rendent un
    verdict plausible sur le mauvais environnement. C'est exactement la panne
    que Lintorn existe pour supprimer, et il l'avait chez lui.

    NON BLOQUANT : un projet peut légitimement n'avoir aucun venv (on
    l'installe à l'instant, la CI monte l'environnement autrement). Bloquer
    ferait de ce contrôle une gêne qu'on apprend à contourner. Il informe —
    mais il ne se tait plus.
    """
    titre = "Python du projet (venv)"

    # Le projet a DÉCLARÉ un venv et il n'est pas là. C'est le cas le plus
    # grave : quelqu'un a pris la peine de répondre à la question, et la
    # réponse est fausse. Passer outre en silence trahirait sa confiance.
    if config.VENV_SOUCI:
        return Resultat(
            titre, "ALERTE", config.VENV_SOUCI,
            "La configuration du projet declare un venv a un emplacement ou "
            "il n'existe pas. Les outils Python (ruff, vulture, pip-audit, "
            "pytest) ne sont donc pas lances : sur un autre python, ils "
            "analyseraient un autre environnement que le tien.\n\n"
            "Corrige `venv` dans `[tool.lintorn]` (ou dans "
            "`.lintorn/config.toml`), ou retire la ligne pour laisser Lintorn "
            "chercher aux emplacements habituels.",
            bloquant=False, detail_markdown=True,
        )

    # Rien a auditer n'est PAS un feu vert : un projet Go ou JavaScript n'a
    # aucun python, et lui reclamer un venv fabriquerait le faux positif
    # qu'on apprend a ignorer.
    if config.PY_RACINE is None and config.PY_SANS_TEMOIN:
        # Gris, pas rouge : rien n'est cassé, mais rien n'est vérifié non plus.
        return Resultat(
            titre, "INDISPONIBLE",
            "des fichiers .py, mais aucun temoin de projet Python - "
            "les outils Python ne tournent pas",
            "Lintorn reconnaît un projet Python à l'un de ces fichiers : "
            "`pyproject.toml`, `requirements.txt`, `setup.py`, `setup.cfg`, "
            "`Pipfile` (Pipenv) ou `environment.yml` (conda). Il n'en a trouvé "
            "aucun : ruff, pytest et pip-audit ne tournent donc pas.\n\n"
            "Si ces fichiers `.py` sont ton projet, ajoute-lui l'un de ces "
            "fichiers — le plus simple :\n\n"
            "```toml\n# pyproject.toml\n[project]\nname = \"mon-projet\"\n```\n\n"
            "Si ce ne sont que quelques scripts d'appoint dans un projet d'un "
            "autre langage, il n'y a rien à faire.",
            bloquant=False, detail_markdown=True,
        )

    if config.PY_RACINE is None:
        return Resultat(
            titre, "INDISPONIBLE",
            "aucun code Python dans ce projet - rien a verifier",
            bloquant=False,
        )

    if config.VENV_PROJET is not None:
        return Resultat(
            titre, "OK", f"venv du projet : {chemins.relatif(config.VENV_PROJET, resoudre=True)}",
            bloquant=False,
        )

    # Repli : aucun venv. Les outils Python ne sont PAS lancés (voir
    # `noyau._sans_le_python_du_projet`) ; c'est ici qu'on dit pourquoi, et
    # comment en sortir.
    dossier, commande = _creer_le_venv()
    return Resultat(
        titre, "ALERTE",
        "aucun venv trouve - les outils Python ne sont pas lances",
        "Lintorn cherche un venv dans `venv/`, `.venv/` et `env/`, a la racine "
        "du projet comme dans son dossier Python. Il n'en a trouve aucun.\n\n"
        "Il ne lance donc **ni ruff, ni vulture, ni pip-audit, ni pytest** : "
        "avec son propre python, ils rendraient un verdict plausible sur un "
        "autre environnement que le tien. pip-audit, par exemple, auditerait "
        "les paquets de Lintorn et pas ceux du projet.\n\n"
        "**Deux facons de regler :**\n\n"
        "```bash\n"
        f"cd {dossier} && {commande}\n"
        "```\n\n"
        "ou, si ton venv vit ailleurs (poetry, pdm, conda, pipenv), dis-lui ou :\n\n"
        "```toml\n"
        "[tool.lintorn]\n"
        'venv = "../.venvs/mon-projet"\n'
        "```",
        bloquant=False, detail_markdown=True,
    )


def _creer_le_venv() -> tuple[str, str]:
    """(dossier, commande) qui crée le venv, avec l'outil que le projet utilise déjà.

    Un projet uv à qui l'on conseille `python3 -m venv` se retrouve avec un
    venv vide, sans aucune de ses dépendances : les outils y tourneraient,
    mais sur rien de ce que le projet installe vraiment.
    """
    for base in dict.fromkeys(filter(None, (config.PY_RACINE, config.RACINE))):
        if (base / "uv.lock").is_file():
            return chemins.relatif(base, resoudre=True) or ".", "uv sync"
    return chemins.relatif(config.PY_RACINE, resoudre=True) or ".", "python3 -m venv .venv"
