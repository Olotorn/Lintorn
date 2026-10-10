# Lintorn
"""L'orchestration : qui tourne, dans quel ordre.

Ce fichier ne contient AUCUN controle. Il assemble ce que declare
`config.py` et ce qu'implementent les modules de controles.

  ▸ La mecanique commune  → base.py
  ▸ Les controles PROJET  → controles/projet/
  ▸ Les controles OUTIL   → controles/outillage/
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import confiance, config, outils
from .base import Resultat, lancer
from .controles.outillage import audit_complet, configuration, hook_git, python_projet
from .controles.projet import (
    doc_vs_code,
    fraicheur_memoire,
    memoire_ia,
    regles_enoncees,
    regles_maison,
)

CONTROLES_INTERNES = {
    # En TETE : il dit ce que les autres ont eu le droit de lire. Annonce
    # apres coup, il obligerait a relire tout le rapport.
    "configuration": configuration.controle_configuration,
    "doc_vs_code": doc_vs_code.controle_doc,
    "memoire_ia": memoire_ia.controle_memoire_ia,
    "fraicheur_memoire": fraicheur_memoire.controle_fraicheur_memoire,
    "regles_maison": regles_maison.controle_regles_maison,
    "regles_declarees": regles_enoncees.controle_regles_declarees,
    "hook_git": hook_git.controle_hook_git,
    "audit_complet": audit_complet.controle_audit_complet,
    "python_projet": python_projet.controle_python_projet,
}


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATION
# ─────────────────────────────────────────────────────────────────────────────
def _sans_le_python_du_projet(entree: dict) -> bool:
    """Cette commande tournerait-elle avec un python qui n'est pas celui du projet ?

    Sans venv du projet, `config.PYTHON` est celui de Lintorn. ruff, vulture,
    pip-audit y rendaient un verdict — vert le plus souvent — sur un AUTRE
    environnement : pip-audit auditait les paquets de Lintorn pendant qu'OSV
    trouvait des failles dans les verrous du projet. Annoncer le repli ne
    suffisait pas : chaque ligne d'outil disait OK en dessous.
    """
    return config.VENV_PROJET is None and entree["cmd"][:1] == [str(config.PYTHON)]


def _executable_commite(entree: dict) -> bool:
    """La commande lance-t-elle un exécutable que git SUIT dans le projet ?

    Un dépôt piégé peut commiter un faux `.venv/bin/python` ou un faux
    `node_modules/.bin/tsc` : lancés au premier `lintorn`, ils exécutent le
    code de l'attaquant sans aucun accord. Un vrai venv, un vrai tsc, ne sont
    jamais commités — voir `config.suivi_par_git`. Ce garde-fou couvre tsc, et
    double celui du python (dont `config.PYTHON` retombe déjà sur Lintorn).
    """
    executable = Path(str(entree["cmd"][0]))
    return executable.is_absolute() and config.suivi_par_git(executable)


def refus_sans_lancer(entree: dict, rapide: bool) -> Resultat | None:
    """Pourquoi cette commande ne partira PAS, quoi que réponde l'utilisateur. None = elle peut."""
    if rapide and entree["lent"]:
        # ⚠️ On NE saute PAS en silence : un contrôle absent du rapport
        # laisserait croire qu'il a tourné. C'est grave pour pip-audit
        # (failles de sécurité) — on préfère une ligne explicite.
        return Resultat(
            entree["titre"], "INDISPONIBLE",
            "NON EXECUTE (mode --rapide) — relancer sans --rapide",
            bloquant=False,
        )
    if _sans_le_python_du_projet(entree):
        return Resultat(
            entree["titre"], "INDISPONIBLE",
            "non lance : aucun venv du projet - voir Python du projet (venv)",
            bloquant=False,
        )
    if _executable_commite(entree):
        return Resultat(
            entree["titre"], "INDISPONIBLE",
            "non lance : cet executable est suivi par git - un venv ne se commite pas",
            "Lintorn lance ruff, pytest et tsc avec l'environnement DU PROJET. "
            "Ici, l'executable vise est **commite dans le depot** : un vrai venv "
            "ou un vrai `node_modules` ne l'est jamais.\n\n"
            "Lancer un binaire livre par un depot inconnu, c'est executer son code "
            "au premier contact. Lintorn refuse, avant tout accord.",
            bloquant=False, detail_markdown=True,
        )
    return None


def a_lancer(rapide: bool = False) -> list[dict]:
    """Les commandes qui partiraient si l'utilisateur les accorde."""
    return [entree for entree in config.COMMANDES if refus_sans_lancer(entree, rapide) is None]


def _rien(_nom: str) -> None:
    pass


def executer(rapide: bool = False, etape: Callable[[str], None] = _rien) -> list[Resultat]:
    """Lance tout ce que config.py déclare, dans l'ordre — avec l'accord de l'utilisateur.

    Rien ne part avant la question : elle est posée UNE fois, pour tout ce qui
    est nouveau dans ce projet (voir `confiance`). `etape` reçoit le nom de ce
    qui va tourner, pour l'afficher (`rapport.attente`).
    """
    resultats: list[Resultat] = []
    permises, motif = confiance.accordes(a_lancer(rapide))

    for entree in config.COMMANDES:
        refus = refus_sans_lancer(entree, rapide)
        if refus is not None:
            resultats.append(refus)
            continue
        if confiance.identite(entree) not in permises:
            changes = confiance.modifies(entree)
            pourquoi = f"{', '.join(changes)} modifie depuis ton accord - " if changes else ""
            resultats.append(Resultat(
                entree["titre"], "INDISPONIBLE", f"non lance : {pourquoi}{motif}",
                "Lintorn **lit** sans demander, mais ne **lance** rien dans un projet "
                "sans l'accord de son utilisateur : ces outils tournent avec les droits "
                "de celui qui les appelle, dans un dossier qu'il n'a peut-etre jamais lu.\n\n"
                "Pour l'accorder : `lintorn confiance` dans un terminal, une fois par "
                "projet. Ce qui est deja accorde ne se redemande pas.",
                bloquant=False, detail_markdown=True,
            ))
            continue
        for fichier in entree.get("produit", ()):
            fichier.unlink(missing_ok=True)
        etape(entree["titre"])
        resultat = lancer(
            entree["titre"], entree["cmd"], entree["cwd"],
            bloquant=entree["bloquant"],
            # Chaque outil a sa propre convention de codes de sortie.
            codes_alerte=entree.get("codes_alerte", (1,)),
        )
        traducteur = outils.TRADUCTEURS.get(entree["traduction"])
        if traducteur and resultat.statut == "ALERTE":
            resultat = traducteur(resultat)
        # « outil introuvable : tsc » ne dit pas quoi faire. Le remède dépend du
        # projet (pnpm, yarn…) : c'est la détection qui le connaît, pas `lancer`.
        # Sans code de sortie : l'outil n'a pas démarré. Avec, il a tourné, et
        # « npm install » serait un conseil faux.
        if (resultat.statut == "INDISPONIBLE" and resultat.code_sortie is None
                and entree.get("remede")):
            resultat.resume += f" - {entree['remede']}"
        resultats.append(resultat)

    for nom, actif in config.CONTROLES_INTERNES.items():
        if actif and nom in CONTROLES_INTERNES:
            etape(nom.replace("_", " "))
            resultats.append(CONTROLES_INTERNES[nom]())

    return resultats
