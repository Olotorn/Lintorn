# Lintorn
"""Le python qui audite : celui du venv DU PROJET, jamais celui de Lintorn."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import config


# ⚠️ Placé APRÈS `PROJET` exprès : le projet a le dernier mot sur son venv,
#    il faut donc avoir lu sa config avant de chercher.
def _dans_le_projet(chemin: Path) -> bool:
    """Le chemin est-il sous la racine auditée ? (hors projet → False)"""
    try:
        chemin.resolve().relative_to(config.RACINE)
    except (ValueError, OSError):
        return False
    return True


def _interpreteur(dossier: Path) -> Path | None:
    """Le python d'un dossier de venv, façon Unix ou façon Windows. None sinon."""
    for relatif in ("bin/python", "bin/python3", "Scripts/python.exe"):
        candidat = dossier / relatif
        if candidat.exists():
            return candidat
    return None


def _venv_declare() -> Path | None:
    """Le venv que le PROJET déclare. Son avis prime sur toute convention.

    Indispensable : poetry, pdm et conda rangent leur venv HORS du projet,
    dans un cache dont aucune convention de nom ne permet de deviner le
    chemin. Sans cette porte de sortie, ces projets seraient condamnés à
    l'alerte sans aucun moyen de la lever — donc à apprendre à l'ignorer.

        [tool.lintorn]
        venv = "../.venvs/api"
    """
    declare = str(config.PROJET.get("venv", "")).strip()
    if not declare:
        return None
    chemin = Path(declare).expanduser()
    # `resolve()` aplatit les `../` : le message d'erreur doit pouvoir se
    # relire, et un chemin non normalisé se compare mal.
    return (chemin if chemin.is_absolute() else config.RACINE / chemin).resolve()


def _python_du_projet() -> tuple[str, Path | None, str | None]:
    """Le python du projet audité, avec ses dépendances — pas celui de Lintorn.

    Un `ruff` ou un `pytest` lancé avec le python de Lintorn ne verrait aucune
    des dépendances du projet. Et depuis que Lintorn s'installe par `pip`, ce
    python-là peut être celui de la MACHINE : `pip-audit` inspecterait alors
    les paquets du système au lieu de ceux du projet, et répondrait avec
    aplomb sur un environnement que personne n'a demandé à auditer.

    ⚠️ REND TROIS CHOSES, et c'est le cœur du correctif. L'ancienne version ne
    rendait que l'interpréteur : le repli sur `sys.executable` était donc
    indiscernable d'une vraie trouvaille, et aucun contrôle ne pouvait le
    signaler. Un contrôle qui devient muet est plus dangereux qu'un rouge.

        (python, venv retenu ou None si repli, souci de déclaration ou None)
    """
    declare = config._venv_declare()
    if declare is not None:
        interpreteur = config._interpreteur(declare)
        if interpreteur is not None and config.suivi_par_git(interpreteur):
            # Déclaré ET commité : une charge utile, pas un venv. Voir
            # `config.suivi_par_git`. On ne le lance pas, et on le dit.
            return sys.executable, None, (
                f"venv declare suivi par git : {str(config.PROJET.get('venv', '')).strip()}"
                " - un venv ne se commite pas, les outils Python ne tournent pas")
        if interpreteur is not None:
            return str(interpreteur), declare, None
        # Déclaré mais absent : surtout pas un repli muet. Le projet a dit où
        # regarder ; « je n'ai pas trouvé » lui revient de droit.
        brut = str(config.PROJET.get("venv", "")).strip()
        return sys.executable, None, f"venv declare introuvable : {brut}"

    # `VIRTUAL_ENV` seulement s'il pointe DANS le projet. Un `source
    # .venv/bin/activate` fait sur le venv de LINTORN le renseigne tout autant,
    # et on auditerait alors le projet avec l'environnement de l'outil.
    actif = os.environ.get("VIRTUAL_ENV", "").strip()
    if actif:
        dossier = Path(actif)
        interpreteur = config._interpreteur(dossier)
        if (interpreteur is not None and config._dans_le_projet(dossier)
                and not config.suivi_par_git(interpreteur)):
            return str(interpreteur), dossier, None

    # Les emplacements conventionnels. `PY_RACINE` couvre le projet Python
    # rangé dans un sous-dossier sans être Django — il manquait.
    commite = None
    for base in filter(None, (config.BACKEND, config.PY_RACINE, config.RACINE)):
        for nom in ("venv", ".venv", "env"):
            interpreteur = config._interpreteur(base / nom)
            if interpreteur is None:
                continue
            if config.suivi_par_git(interpreteur):
                commite = interpreteur   # charge utile commitée, pas un venv
                continue
            return str(interpreteur), base / nom, None

    if commite is not None:
        return sys.executable, None, (
            f"interpreteur suivi par git ignore : {commite.relative_to(config.RACINE).as_posix()}"
            " - un venv ne se commite pas, les outils Python ne tournent pas")
    return sys.executable, None, None
