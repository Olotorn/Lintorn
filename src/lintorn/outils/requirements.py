# Lintorn
"""Dependances vs venv : `requirements.txt` dit-il la vérité ? (lance ../dependances.py)"""

from __future__ import annotations

from .. import config


# Aucun autre contrôle ne peut le voir : ruff, pytest et Django tournent
# DANS le venv, donc pour eux tout est installé. Le défaut ne se révèle
# qu'au déploiement, quand il coûte le plus cher.
#
# Lancé par CHEMIN et non par `-m lintorn.dependances` : il doit tourner
# avec le python du PROJET (celui dont on inspecte le venv), or ce
# python-là n'a aucune raison d'avoir Lintorn installé.
def commande() -> dict:
    """Compare `requirements.txt` au venv, avec le python DU PROJET."""
    return {
        "cle": "dependances",
        "titre": "Dependances vs venv",
        "cmd": [config.PYTHON, str(config.PAQUET / "dependances.py"), str(config.REQUIREMENTS.parent)],
        "cwd": config.RACINE,
        "bloquant": True,
        "traduction": None,
        "lent": False,
    }
