# Lintorn
"""Vulture : le code mort. Opt-in, consultatif."""

from __future__ import annotations

import re

from .. import base, config

# Une trouvaille de vulture : `app/vues.py:12: unused function 'x' (60% confidence)`.
_CANDIDAT = re.compile(r"^.+:\d+: unused ", re.M)


# `BACKEND or PY_RACINE` : sur un projet Django, le dossier du `manage.py` ;
# ailleurs, la racine Python. Vulture et pip-audit sont des outils PYTHON,
# pas Django : enfermés derrière la détection de Django, ils disparaissaient
# en silence de tout projet Python qui n'en était pas un.
def commande() -> dict:
    """Le code mort — opt-in, consultatif."""
    return {
        "cle": "code_mort",
        "opt_in": True,      # beaucoup de faux positifs au premier contact
        "titre": "Code mort (vulture, consultatif)",
        # ⚠️ Beaucoup de faux positifs : une app Django n'est parfois citée que
        # dans INSTALLED_APPS, un composant qu'en import paresseux.
        # On NE SUPPRIME JAMAIS sur la seule foi de vulture.
        "cmd": [config.PYTHON, "-m", "vulture", ".", "--min-confidence", "80",
                "--exclude", "venv,migrations",
                "--ignore-names", ",".join(config.VULTURE_IGNORES)],
        "cwd": config.BACKEND or config.PY_RACINE,
        "bloquant": False,
        "traduction": "vulture",
        "lent": True,
        "codes_alerte": (3,),   # vulture : 3 = du code mort a été trouvé
    }


def traduire(resultat: base.Resultat) -> base.Resultat:
    """Combien de candidats : « 2 ligne(s) de sortie » ne disait pas ce que vulture avait trouvé."""
    candidats = len(_CANDIDAT.findall(resultat.detail))
    if candidats:
        resultat.resume = f"{candidats} candidat(s) de code mort - a confirmer a l'oeil"
    return resultat
