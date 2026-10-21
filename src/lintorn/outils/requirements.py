# Lintorn
"""Dependances vs venv : `requirements.txt` dit-il la vérité ? (lance ../dependances.py)"""

from __future__ import annotations

import re

from .. import base, config

# Les titres de section qu'écrit `dependances.py`, et ce qu'en dit le résumé.
_ECARTS = (("DECLARES MAIS PAS INSTALLES", "declare(s) mais pas installe(s)"),
           ("VERSIONS DIVERGENTES", "version(s) divergente(s)"),
           ("INSTALLES MAIS PAS DECLARES", "installe(s) mais pas declare(s)"))


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
        "traduction": "dependances",
        # 0 aussi : même au vert, la sortie nomme ce qui n'est pas compté.
        "codes_alerte": (0, 1),
        "lent": False,
    }


def traduire(resultat: base.Resultat) -> base.Resultat:
    """Quels écarts, et combien : « 33 ligne(s) de sortie » ne disait pas pourquoi le push bloquait.

    Au vert aussi : « rien a signaler » cachait les paquets laissés sans ligne
    (outils d'audit, sous-dépendances) et un requirements.txt en UTF-16.
    """
    if resultat.code_sortie == 0:
        return _au_vert(resultat)
    morceaux = []
    for titre, dit in _ECARTS:
        trouve = re.search(rf"^{titre} \((\d+)\)", resultat.detail, re.M)
        if trouve:
            morceaux.append(f"{trouve.group(1)} {dit}")
    if morceaux:
        resultat.resume = ", ".join(morceaux)
    return resultat


def _au_vert(resultat: base.Resultat) -> base.Resultat:
    sans_ligne = sum(int(nombre) for nombre in re.findall(
        r"^(?:Non comptes|Sans ligne).*\((\d+)\) : ", resultat.detail, re.M))
    morceaux = [f"{sans_ligne} paquet(s) sans ligne, expliques dans le rapport"] if sans_ligne else []
    if "ENCODAGE :" in resultat.detail:
        morceaux.append("requirements.txt en UTF-16, voir le rapport")
    resultat.statut = "OK"
    resultat.resume = " - ".join(["rien a signaler", *morceaux])
    resultat.detail_meme_au_vert = bool(morceaux)
    return resultat

