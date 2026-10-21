# Lintorn
"""Les outils livrés avec Lintorn : un outil = un fichier, avec SA commande et SA traduction.

    ruff.py          le lint Python
    pytest.py        les tests du projet (opt-in : exécute son code)
    vulture.py       le code mort (opt-in, consultatif)
    pip_audit.py     les failles des paquets Python (opt-in : réseau)
    requirements.py  `requirements.txt` dit-il la vérité sur le venv ?
    django.py        check, migrations, check --deploy, données métier
    tsc.py           TypeScript, un `tsc --noEmit` par projet TS
    npm_audit.py     les failles des paquets JS (opt-in : réseau)
    osv.py           les failles des autres langages (opt-in : réseau)
    commun.py        ce que les traductions partagent

Une COMMANDE est un dict : `cle`, `titre`, `cmd`, `cwd`, `bloquant`,
`traduction`, `lent`, et au besoin `opt_in`, `codes_alerte`, `remede` — leur
sens est écrit au-dessus de la liste des outils, dans `config/__init__.py`.

Une TRADUCTION lit la sortie brute d'un outil et la réécrit en français.
Pour qu'une commande s'en serve : `"traduction": "<sa clé dans TRADUCTEURS>"`.
"""

from __future__ import annotations

# `config` D'ABORD : c'est lui qui appelle chaque outil pour monter ses commandes.
# Chargé après, il trouverait un outil à moitié importé, sans ses fonctions.
from .. import config  # noqa: F401
from . import django, npm_audit, osv, pip_audit, pytest as pytest_outil, requirements, ruff, tsc, vulture

# La clé que porte `traduction` dans une commande → la fonction qui lit sa sortie.
# `config.TRADUCTEURS_CONNUS` en garde la liste (un test veille qu'elles restent d'accord).
TRADUCTEURS = {"ruff": ruff.traduire, "deploy": django.traduire,
               "npm_audit": npm_audit.traduire, "osv": osv.traduire,
               "pip_audit": pip_audit.traduire, "tsc": tsc.traduire,
               "pytest": pytest_outil.traduire, "dependances": requirements.traduire,
               "vulture": vulture.traduire}
