# Lintorn
"""Ruff : le lint Python. Sa commande, et la traduction de ce qu'il répond."""

from __future__ import annotations

import re

from .. import base, config, traductions
from . import commun


def commande() -> dict:
    """Le lint Python — sans jamais rien écrire dans le projet."""
    return {
        "cle": "ruff",
        "titre": "Ruff (lint Python)",
        # ⚠️ `--no-fix` : un projet qui a `fix = true` dans sa config ruff se
        # faisait CORRIGER ses fichiers par l'audit, qui affichait ensuite un
        # vert sur ce qu'il venait d'effacer. `--no-cache` : sans lui, ruff
        # écrit un `.ruff_cache/` dans le projet audité.
        "cmd": [config.PYTHON, "-m", "ruff", "check", ".", "--output-format", "concise",
                "--no-fix", "--no-cache"],
        "cwd": config.PY_RACINE,
        "bloquant": True,
        "traduction": "ruff",
        "lent": False,
    }


# Sortie brute de ruff (format "concise") :
#   accounts\views.py:7:1: F811 redefinition of unused 'x' from line 4
LIGNE_RUFF = re.compile(
    r"^(?P<fichier>.+?):(?P<ligne>\d+):\d+:\s+(?P<code>[A-Z]+\d+)\s+(?P<message>.*)$"
)


def traduire(resultat: base.Resultat) -> base.Resultat:
    """Réécrit la sortie de ruff en français, avec un résumé par type."""
    dico = traductions.RUFF
    traduites: list[str] = []
    compteur: dict[str, int] = {}

    for ligne in resultat.detail.splitlines():
        trouve = LIGNE_RUFF.match(ligne.strip())
        if not trouve:
            continue
        code = trouve["code"]
        compteur[code] = compteur.get(code, 0) + 1
        # Code non traduit → on garde l'anglais plutôt que de perdre l'info
        explication = dico.get(code) or commun.cellule(trouve["message"], 300)
        # Ruff tourne DANS le backend → on repréfixe pour obtenir un chemin
        # depuis la racine du dépôt, sinon le lien ne pointe sur rien.
        # ⚠️ Préfixe DÉDUIT de la détection, jamais écrit en dur : codé en
        # dur, tous les liens du rapport pointaient dans le vide dès que le
        # projet n'avait pas l'arborescence de celui d'origine.
        fichier = config.PREFIXE_BACKEND + trouve["fichier"].replace("\\", "/")
        traduites.append(
            f"- {base.lien(fichier, int(trouve['ligne']))}<br>`{code}` — {explication}"
        )

    if not traduites:
        # Format inattendu (ruff a changé son affichage ?) → on rend le brut.
        # test_Lintorn.py garde ce cas sous surveillance.
        return resultat

    entete = ["**Résumé par type :**", ""]
    for code, nb in sorted(compteur.items(), key=lambda x: -x[1]):
        entete.append(f"- **{nb}** × `{code}` — {dico.get(code, '(non traduit)')}")
    entete += ["", "**Détail :**", ""]

    resultat.detail = "\n".join(entete + traduites)
    resultat.resume = f"{len(traduites)} alerte(s) reelle(s)"
    resultat.detail_markdown = True
    return resultat
