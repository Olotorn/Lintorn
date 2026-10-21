# Lintorn
"""Les [[commandes]] que le projet branche lui-même : mypy, eslint, un script maison."""

from __future__ import annotations

import difflib

from .. import config

# mypy, eslint, black --check, un script maison : tout outil qui répond par un
# code de sortie a sa place ici.
#
#     [[tool.lintorn.commandes]]
#     cle      = "mypy"
#     titre    = "Types (mypy)"
#     cmd      = ["{python}", "-m", "mypy", "."]   # {python} = celui du projet
#     cwd      = "api"          # relatif à la racine ; absent = la racine
#     bloquant = false
#     lent     = false
#
# ⚠️ CE QUE ÇA IMPLIQUE, ET IL FAUT LE SAVOIR : ces commandes sont EXÉCUTÉES.
# Un `pyproject.toml` cloné depuis un dépôt inconnu peut donc faire tourner ce
# qu'il veut sur ta machine au premier `lintorn`. C'est le même contrat que les
# scripts npm, les hooks git ou un Makefile — d'où la question posée avant le
# premier lancement (voir `confiance`), une fois par commande.
# Les traducteurs de `outils.TRADUCTEURS`, repris ici parce que `config` se
# charge AVANT les outils, qui le lisent. Un test verifie que
# les deux listes restent d'accord.
TRADUCTEURS_CONNUS = ("ruff", "deploy", "npm_audit", "osv", "pip_audit", "tsc",
                      "pytest", "dependances", "vulture")


_CLES_COMMANDE = {"cle", "titre", "cmd", "cwd", "bloquant", "traduction",
                  "lent", "codes_alerte"}


def _commandes_du_projet() -> list[dict]:
    ajoutees, soucis = [], []

    for brute in config.PROJET.get("commandes", []):
        if not isinstance(brute, dict):
            soucis.append("commande ignoree : chaque [[commandes]] doit etre une table")
            continue
        cle = str(brute.get("cle", "")).strip()
        cmd = brute.get("cmd")
        if not cle or not isinstance(cmd, list) or not cmd:
            soucis.append(f"commande '{cle or '(sans cle)'}' : 'cle' et 'cmd' sont obligatoires")
            continue
        if any(commande["cle"] == cle for commande in config.COMMANDES):
            soucis.append(f"commande '{cle}' : cette cle est deja prise")
            continue
        soucis += config._cles_inconnues(brute, config._CLES_COMMANDE, f"commande '{cle}'")

        cwd = config.RACINE / str(brute.get("cwd", "")).strip("/")
        if not cwd.is_dir():
            soucis.append(f"commande '{cle}' : dossier '{brute.get('cwd')}' introuvable")
            continue

        codes = brute.get("codes_alerte", [1])
        if not (isinstance(codes, list) and codes
                and all(isinstance(code, int) and not isinstance(code, bool) for code in codes)):
            soucis.append(f"commande '{cle}' : codes_alerte doit etre une liste d'entiers")
            continue
        # ⚠️ Un 0 n'a de sens que pour un outil qui REUSSIT en ayant trouve
        # quelque chose — et seul un traducteur sait lire sa sortie pour le
        # dire. Sans lui, la commande qui reussit passerait au rouge et
        # bloquerait le push.
        if 0 in codes and not brute.get("traduction"):
            soucis.append(f"commande '{cle}' : codes_alerte contient 0 sans 'traduction' - "
                          "une commande qui reussit passerait pour une alerte")
            continue
        # ⚠️ La cle peut etre bonne et la VALEUR fausse : `traduction =
        # "nawak"` etait ignoree sans un mot, et la sortie restait brute.
        traduction = brute.get("traduction")
        if traduction is not None and traduction not in config.TRADUCTEURS_CONNUS:
            proche = difflib.get_close_matches(str(traduction), config.TRADUCTEURS_CONNUS, n=1)
            conseil = (f" - voulais-tu dire {proche[0]} ?" if proche else
                       f" - connus : {', '.join(config.TRADUCTEURS_CONNUS)}")
            soucis.append(f"commande '{cle}' : traduction '{traduction}' inconnue{conseil}")
            continue
        drapeaux_faux = [nom for nom in ("bloquant", "lent")
                         if nom in brute and not isinstance(brute[nom], bool)]
        if drapeaux_faux:
            soucis.append(f"commande '{cle}' : {', '.join(drapeaux_faux)} n'accepte que "
                          "true ou false")
            continue

        ajoutees.append({
            "cle": cle,
            "titre": str(brute.get("titre", cle)),
            # `{python}` devient le Python DU PROJET — celui qui lance déjà
            # ruff et pytest. Écrire `python` tout court désigne celui du
            # terminal : avec un venv non activé (le hook lancé par VS Code),
            # l'outil installé dans le venv devenait introuvable.
            "cmd": [str(morceau).replace("{python}", str(config.PYTHON)) for morceau in cmd],
            "cwd": cwd,
            "bloquant": bool(brute.get("bloquant", False)),
            "traduction": brute.get("traduction"),
            "lent": bool(brute.get("lent", False)),
            "codes_alerte": tuple(codes),
            # Écrite par le projet : sa ligne entière entre dans l'accord.
            "du_projet": True,
        })

    config.SOUCIS_CONFIG.extend(soucis)
    return ajoutees
