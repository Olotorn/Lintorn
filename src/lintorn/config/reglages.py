# Lintorn
"""Les réglages : config.toml, [tool.lintorn] et .env — les lire, les valider, savoir ce qui est accordé."""

from __future__ import annotations

import difflib
import tomllib
from pathlib import Path

from .. import config


def _lire_env(fichier: Path) -> dict:
    valeurs = {}
    if not fichier.is_file():
        return valeurs
    # `utf-8-sig` : le Bloc-notes de Windows pose un BOM en tête, qui se
    # collait à la première clé — `LINTORN_MEMOIRE` devenait introuvable.
    try:
        texte = fichier.read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as erreur:
        config.SOUCIS_CONFIG.append(f"{fichier.name} illisible ({erreur}) - ses reglages sont ignores")
        return valeurs
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        valeurs[cle.strip()] = valeur.strip().strip('"').strip("'")
    return valeurs


def _retenu(nom: str) -> None:
    """Note que `nom` a fourni de la configuration.

    Idempotent : `_regles_brutes()` est appelable plusieurs fois, et un simple
    `append` afficherait « config.toml + regles.toml + regles.toml ».
    """
    if nom not in config.FICHIERS_CONFIG_LUS:
        config.FICHIERS_CONFIG_LUS.append(nom)


def _charger_toml(fichier: Path) -> dict | None:
    """Le TOML, ou None si absent/illisible (l'erreur est alors signalée).

    Un TOML cassé ne fait PAS planter Lintorn : on le signale par
    `SOUCIS_CONFIG` et on repart sur les défauts. Refuser de démarrer pour une
    virgule manquante priverait l'utilisateur de tous les AUTRES contrôles.

    Se replier en SILENCE, en revanche, laisse un rapport complet et confiant
    alors que `docs_exclus`, les contrôles coupés et les règles maison
    viennent d'être ignorés en bloc.
    """
    if not fichier.is_file():
        return None
    try:
        with fichier.open("rb") as flux:
            charge = tomllib.load(flux)
    # `ValueError` couvre le fichier qui n'est pas de l'UTF-8 : un accent en
    # latin-1 dans un commentaire faisait tomber Lintorn entier à l'import.
    except (OSError, ValueError) as erreur:
        config.SOUCIS_CONFIG.append(f"{fichier.name} illisible ({erreur}) - defauts appliques")
        return None
    return charge


def _config_projet() -> dict:
    """La config du projet audité. Deux emplacements, dans cet ordre.

      1. `pyproject.toml` → section `[tool.lintorn]`
      2. `.lintorn/config.toml` → sections à la racine du fichier

    ⚠️ LE SECOND N'EST PAS UN LUXE. `pyproject.toml` est une convention
    PYTHON : un projet JavaScript, un projet Go ou un monorepo n'en a aucun à
    sa racine — le projet qui a vu naître Lintorn non plus, alors qu'il est en
    partie Django. Sans ce repli, ces projets n'auraient tout simplement
    aucune façon de se configurer.
    """
    charge = config._charger_toml(config.RACINE / "pyproject.toml")
    if charge is not None:
        outil = charge.get("tool")
        valeur = outil.get("lintorn") if isinstance(outil, dict) else None
        if isinstance(valeur, dict):
            config._retenu("pyproject.toml")
            # ⚠️ UNE SEULE SOURCE COMPTE, et ce n'est pas celle que `--init`
            # écrit. Les deux présentes, config.toml était ignoré sans un mot :
            # ses contrôles activés ne tournaient pas, ses exclusions non plus.
            if (config.DOSSIER_LINTORN / "config.toml").is_file():
                config.SOUCIS_CONFIG.append(
                    "config.toml IGNORE : pyproject.toml a une section [tool.lintorn], "
                    "qui a la priorite - n'en garder qu'une")
            return valeur
        if valeur is not None:
            config.SOUCIS_CONFIG.append("pyproject.toml : [tool.lintorn] n'est pas une table - ignore")

    charge = config._charger_toml(config.DOSSIER_LINTORN / "config.toml")
    if isinstance(charge, dict):
        config._retenu("config.toml")
        return charge
    return {}


# Ce que chaque clé de la config doit être. Une valeur d'un autre type n'est
# pas « presque bonne » : c'était un traceback à l'IMPORT — Lintorn entier hors
# service, `--help` et `--init` compris, donc plus aucun moyen de réparer.
_TYPES_CONFIG = {
    "controles": (dict, "une table"),
    "regles": (list, "une liste de [[regles]]"),
    "commandes": (list, "une liste de [[commandes]]"),
    "docs_exclus": (list, "une liste de textes"),
    "fichiers_ia": (list, "une liste de textes"),
    "vulture_ignores": (list, "une liste de textes"),
    "venv": (str, "un texte"),
}


def _valider_config(brute: dict) -> dict:
    """La config débarrassée de ce qui n'a pas le bon type — chaque rejet dit.

    ⚠️ Dans `[controles]`, SEUL un booléen vaut accord. `tests = "false"` —
    un refus, pour qui l'écrit — est une chaîne non vide, donc vraie pour
    Python : le contrôle s'activait et exécutait le code du projet.
    """
    propre: dict = {}
    for cle, valeur in brute.items():
        if cle not in config._TYPES_CONFIG:
            proche = difflib.get_close_matches(str(cle), list(config._TYPES_CONFIG), n=1)
            conseil = f" - voulais-tu dire {proche[0]} ?" if proche else ""
            config.SOUCIS_CONFIG.append(f"{cle} : cle inconnue, ignoree{conseil}")
            continue
        attendu, nom = config._TYPES_CONFIG[cle]
        if not isinstance(valeur, attendu):
            config.SOUCIS_CONFIG.append(f"{cle} : attendu {nom}, trouve {type(valeur).__name__} - ignore")
            continue
        if cle in ("docs_exclus", "fichiers_ia", "vulture_ignores"):
            textes = [element for element in valeur if isinstance(element, str)]
            if len(textes) != len(valeur):
                config.SOUCIS_CONFIG.append(f"{cle} : seuls les textes sont gardes")
            valeur = textes
        if cle == "controles":
            booleens = {}
            for nom_controle, accord in valeur.items():
                if isinstance(accord, bool):
                    booleens[nom_controle] = accord
                else:
                    config.SOUCIS_CONFIG.append(
                        f"[controles] {nom_controle} = {accord!r} : seuls true et false sont "
                        "compris - le controle garde sa valeur par defaut")
            valeur = booleens
        propre[cle] = valeur
    return propre


def _accorde(commande: dict) -> bool:
    return config._actifs.get(commande["cle"], not commande.get("opt_in", False))


def _cles_inconnues(brute: dict, connues: set[str], ou: str) -> list[str]:
    """Les cles mal tapees d'une table, avec la plus proche en conseil.

    ⚠️ `_valider_config` ne regarde que le PREMIER niveau de la config. A
    l'interieur d'une `[[regles]]`, `bloquan = true` laissait la regle NON
    bloquante : la violation etait signalee, et le push partait quand meme.
    `racin = "src"` lui faisait lire le depot entier. Sans un mot, et
    `Configuration` restait au vert.
    """
    soucis = []
    for cle in brute:
        if str(cle) in connues:
            continue
        proche = difflib.get_close_matches(str(cle), sorted(connues), n=1)
        conseil = f" - voulais-tu dire {proche[0]} ?" if proche else ""
        soucis.append(f"{ou} : cle inconnue '{cle}', sans effet{conseil}")
    return soucis


# Tous en lecture seule, donc tous actifs par défaut. Pour en couper un :
#
#     [tool.lintorn.controles]
#     memoire_ia = false
_CONTROLES_DEFAUT = {
    "configuration": True,      # Lintorn a-t-il pu LIRE ses propres consignes ?
    "doc_vs_code": True,        # les chemins cités dans la doc du dépôt existent-ils ?
    "memoire_ia": True,         # idem pour la mémoire de l'IA (consultatif)
    "fraicheur_memoire": True,  # le code cité par la mémoire a-t-il bougé depuis ? (git)
    "regles_maison": True,      # les règles maison sont-elles tenues ?
    "regles_declarees": True,   # les règles ÉCRITES dans la doc ont-elles un contrôle ?
    "hook_git": True,           # le hook pre-push est-il réellement branché ?
    "python_projet": True,      # les outils tournent-ils sur le venv DU projet ?
    "audit_complet": True,      # les outils lents ont-ils tourné depuis 30 jours ?
}


# Deux pannes muettes, cousines d'une option mal tapée en ligne de commande :
#   · une faute de frappe (`faiiles = true`) : aucun contrôle ne tournait, et
#     rien ne le disait ;
#   · un contrôle activé sans rien à contrôler (`failles_npm = true` sans
#     package-lock.json) : absent du rapport, alors qu'on le croit en service.
# Ce qu'il manque au projet quand une clé activée ne peut rien contrôler :
OBJET_DES_CLES = {
    "ruff": "de code Python",
    "dependances": "de requirements.txt, ou de venv de projet",
    "tests": "de code Python",
    "code_mort": "de code Python",
    "failles": "de code Python",
    "django_check": "de projet Django",
    "migrations": "de projet Django",
    "donnees_metier": "de commande manage.py verifier_donnees "
                      "(management/commands/verifier_donnees.py)",
    "deploy": "de projet Django",
    "typescript": "de tsconfig.json",
    "failles_npm": "de package-lock.json",
    "failles_osv": "de fichier que lise OSV-Scanner (Cargo.lock, go.mod, uv.lock, .csproj...)",
}


def _cles_sans_effet(surcharges, en_service: set[str]) -> list[str]:
    """Les clés de [controles] qui ne pilotent rien, dites en clair."""
    if not isinstance(surcharges, dict):
        return []
    soucis = []
    connues = [*config.OBJET_DES_CLES, *config._CONTROLES_DEFAUT]
    for cle, valeur in surcharges.items():
        if cle in config._CONTROLES_DEFAUT:
            continue
        if cle not in config.OBJET_DES_CLES:
            proche = difflib.get_close_matches(cle, connues, n=1)
            conseil = f" - voulais-tu dire {proche[0]} ?" if proche else ""
            soucis.append(f"[controles] {cle} : cle inconnue, elle ne pilote rien{conseil}")
        elif valeur is True and cle not in en_service:
            soucis.append(f"[controles] {cle} = true, mais ce projet n'a pas "
                          f"{config.OBJET_DES_CLES[cle]} : rien n'est controle")
    return soucis
