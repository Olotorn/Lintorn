# Lintorn
"""Django : `manage.py check`, les migrations, `check --deploy`, les données métier."""

from __future__ import annotations

import re

from .. import base, config, traductions


# Tous se lancent DEPUIS le dossier qui contient `manage.py`, avec le python du
# projet : c'est la seule façon pour Django de trouver ses réglages et ses apps.
def commandes() -> list[dict]:
    """Les contrôles Django — tous opt-in : ils importent le code du projet."""
    return [
        {
            "cle": "django_check",
            # ⚠️ `manage.py check` IMPORTE settings.py et toutes les apps
            # d'INSTALLED_APPS (modeles, AppConfig.ready(), signaux) : c'est du
            # code du projet qui s'execute. Actif d'office, il contredisait la
            # promesse « rien d'invasif sans ton accord » sur tout projet Django.
            "opt_in": True,
            "titre": "Django check",
            "cmd": [config.PYTHON, "manage.py", "check"],
            "cwd": config.BACKEND,
            "bloquant": True,
            "traduction": None,
            "lent": False,
        },
        {
            "cle": "migrations",
            "opt_in": True,      # meme import que `check` : le code du projet tourne
            "titre": "Migrations manquantes",
            "cmd": [config.PYTHON, "manage.py", "makemigrations", "--check", "--dry-run"],
            "cwd": config.BACKEND,
            "bloquant": True,
            "traduction": None,
            "lent": False,
        },
        {
            "cle": "donnees_metier",
            "opt_in": True,      # ouvre la BASE DE DONNEES
            "titre": "Donnees vs regles metier",
            "cmd": [config.PYTHON, "manage.py", "verifier_donnees"],
            "cwd": config.BACKEND,
            "bloquant": True,
            "traduction": None,
            "lent": False,
        },
        {
            "cle": "deploy",
            "opt_in": True,      # hurle sur tout projet en dev
            "titre": "Django check --deploy",
            # --fail-level WARNING : sans ça la commande sort en 0 malgré ses
            # avertissements de sécurité, et le contrôle passerait au vert pour rien.
            "cmd": [config.PYTHON, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
            "cwd": config.BACKEND,
            "bloquant": False,      # normal en dev, doit être vert le jour de la prod
            "traduction": "deploy",
            "lent": False,
        },
    ]


# Une ligne de `check --deploy` : « ?: (security.W004) Le message… », et son
# éventuel conseil sur la ligne suivante : « \tHINT: Poser … ».
_RX_CHECK_DJANGO = re.compile(r"\((?P<code>\w+\.[A-Z]\d{3})\)\s*(?P<message>.*)")


_RX_CONSEIL_DJANGO = re.compile(r"^\s*HINT:\s*(?P<conseil>.+)$")


def traduire(resultat: base.Resultat) -> base.Resultat:
    """Réécrit les avertissements de `check --deploy` en français.

    ⚠️ La regex accepte N'IMPORTE QUEL préfixe d'app, pas seulement `security.`.
    Restreinte à `security\\.`, elle jetterait SILENCIEUSEMENT les contrôles
    publiés par les applications du projet (`monapp.E002`…) hors du
    rapport. Un contrôle qu'on croit avoir mais qui n'apparaît jamais est pire
    que pas de contrôle du tout.

    ⚠️ Un code absent de `traductions.DEPLOY` garde SON message, et son
    conseil. Remplacés par « (non traduit) », ils disparaissaient du rapport :
    les contrôles qu'un projet écrit pour lui-même — souvent dans sa langue —
    étaient précisément ceux dont on ne lisait plus rien.
    """
    constats: dict[str, str] = {}
    courant = None          # le code dont la ligne suivante peut porter le conseil
    for ligne in resultat.detail.splitlines():
        trouve = _RX_CHECK_DJANGO.search(ligne)
        if trouve:
            code = trouve["code"]
            # Dédoublonne en gardant l'ordre ; un doublon n'apporte pas de conseil.
            courant = None if code in constats else code
            if courant:
                constats[code] = (traductions.DEPLOY.get(code)
                                  or trouve["message"].strip() or "(message vide)")
            continue
        conseil = _RX_CONSEIL_DJANGO.match(ligne)
        if conseil and courant and courant not in traductions.DEPLOY:
            constats[courant] += f"\n      conseil : {conseil['conseil'].strip()}"
        courant = None

    if not constats:
        return resultat

    lignes = ["A REGLER AVANT LA MISE EN PRODUCTION :"]
    lignes += [f"  {code} — {texte}" for code, texte in constats.items()]

    resultat.detail = "\n".join(lignes)
    resultat.resume = f"{len(constats)} point(s) a regler avant la prod"
    return resultat
