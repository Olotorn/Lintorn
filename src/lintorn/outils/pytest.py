# Lintorn
"""Pytest : les tests du projet. Opt-in — ils exécutent son code."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import base, config
from . import commun


def _rapport() -> Path:
    return config.DOSSIER_LINTORN / "cache" / "pytest-junit.xml"


def _option_rapport() -> list[str]:
    """Où pytest écrit son bilan chiffré — dans `.lintorn/`, jamais dans le projet.

    Le projet règle souvent `addopts = -q` : avec le `-q` de Lintorn, pytest passe
    en `-qq` et n'imprime PLUS sa ligne « 3 passed ». Un bilan lu dans le texte
    serait alors introuvable. Le rapport JUnit, lui, ne dépend d'aucune option
    de bavardage. Si `.lintorn/` est un lien, on n'écrit pas à travers : sans
    rapport, la traduction refuse de conclure au vert.
    """
    try:
        base.dossier_sur(config.DOSSIER_LINTORN)
    except OSError:
        return []
    return [f"--junitxml={_rapport()}"]


def commande() -> dict:
    """Les tests du projet — opt-in : ils EXÉCUTENT son code."""
    return {
        "cle": "tests",
        "opt_in": True,      # EXECUTE le code du projet
        "titre": "Tests (pytest)",
        # `-p no:cacheprovider` : pas de `.pytest_cache/` laissé dans le projet.
        "cmd": [config.PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                *_option_rapport()],
        "cwd": config.PY_RACINE,
        "bloquant": True,
        # 0 aussi : pytest sort en 0 avec zéro test EXÉCUTÉ (tout ignoré, ou un
        # `-k` qui ne choisit rien). 2 = un test ne s'importe pas, 4 = la config
        # du projet est refusée, 5 = aucun test collecté : ce sont des verdicts
        # sur le PROJET, pas un pytest en panne. Seul 3 (erreur interne) l'est.
        "codes_alerte": (0, 1, 2, 4, 5),
        "traduction": "pytest",
        "lent": False,
        # Effacé AVANT le lancement : un pytest qui plante sans écrire son bilan
        # ferait lire celui de la fois d'avant — un vert d'hier pour aujourd'hui.
        "produit": [_rapport()],
    }


def _bilan() -> dict[str, int] | None:
    """Les comptes du rapport JUnit, ou None s'il manque ou n'est pas lisible."""
    try:
        racine = ET.parse(_rapport()).getroot()
    except (OSError, ET.ParseError):
        return None
    suites = [racine] if racine.tag == "testsuite" else list(racine.iter("testsuite"))
    if not suites:
        return None
    bilan = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    try:
        for suite in suites:
            for nom in bilan:
                bilan[nom] += int(suite.get(nom, 0))
    except ValueError:
        return None
    return bilan


def _en_echec() -> list[str]:
    try:
        racine = ET.parse(_rapport()).getroot()
    except (OSError, ET.ParseError):
        return []
    noms = []
    for cas in racine.iter("testcase"):
        if cas.find("failure") is not None or cas.find("error") is not None:
            noms.append(f"{cas.get('classname', '')}::{cas.get('name', '')}".strip(":"))
    return noms


# La ligne de bilan, quand le rapport JUnit manque (`-p no:junitxml`) :
#   3 passed, 1 skipped in 0.12s
_RX_BILAN_TEXTE = re.compile(r"^=*\s*(?:\d+ [a-z]+, )*(\d+) passed\b[^\n]* in [\d.]+s\b", re.MULTILINE)


def _sans_rapport(resultat: base.Resultat) -> base.Resultat:
    """Pas de rapport JUnit : on lit la ligne de bilan, sinon on ne conclut pas.

    Un projet peut couper le plugin (`-p no:junitxml`) : ses tests tournent,
    seul le rapport manque. Un `conftest` qui sort avant tout test, lui, ne
    laisse ni rapport ni bilan.
    """
    titre, bloquant, code = resultat.titre, resultat.bloquant, resultat.code_sortie
    passes = _RX_BILAN_TEXTE.findall(resultat.detail)
    if code == 0 and passes and int(passes[-1]) > 0:
        return base.Resultat(titre, "OK", f"{passes[-1]} test(s) passe(s) (bilan lu dans la sortie)",
                             resultat.detail, bloquant, code_sortie=code)
    if code == 0:
        return base.Resultat(
            titre, "INDISPONIBLE", "pytest a sorti en 0 sans bilan lisible - rien ne prouve qu'un test a tourne",
            "pytest n'a écrit ni son rapport JUnit, ni sa ligne de bilan. Causes connues : "
            "un `conftest.py` qui arrête pytest avant les tests, ou un `addopts` qui coupe "
            "le plugin (`-p no:junitxml`) en rendant pytest muet (`-q`).\n\n"
            + resultat.detail, bloquant=False, code_sortie=code)
    return base.Resultat(
        titre, "ERREUR", f"pytest a sorti en {code} sans bilan lisible - on ne sait pas ce qui a echoue",
        resultat.detail, bloquant, code_sortie=code)


def traduire(resultat: base.Resultat) -> base.Resultat:
    """Lit ce que pytest a VRAIMENT exécuté, pas seulement son code de sortie.

    ⚠️ pytest sort en 0 quand il n'a rien fait : tous les tests ignorés
    (`skip`), ou aucun ne passe le filtre `-k`. « rien a signaler » dirait
    alors que les tests passent alors qu'aucun n'a tourné. Et ses codes 2, 4
    et 5 parlent du projet, pas d'une panne de l'outil.
    """
    titre, bloquant, code = resultat.titre, resultat.bloquant, resultat.code_sortie

    if code == 5:
        return base.Resultat(
            titre, "INDISPONIBLE", "aucun test collecte - rien n'a ete verifie",
            resultat.detail, bloquant=False, code_sortie=code)
    if code == 4:
        return base.Resultat(
            titre, "ERREUR", "pytest refuse sa ligne de commande ou la config du projet (code 4)",
            resultat.detail, bloquant, code_sortie=code)

    bilan = _bilan()
    if bilan is None:
        return _sans_rapport(resultat)

    lances = bilan["tests"] - bilan["skipped"]
    if code == 0:
        if lances <= 0:
            return base.Resultat(
                titre, "INDISPONIBLE",
                f"aucun test execute ({bilan['skipped']} ignore(s)) - rien n'a ete verifie",
                resultat.detail, bloquant=False, code_sortie=code)
        ignores = f", {bilan['skipped']} ignore(s)" if bilan["skipped"] else ""
        return base.Resultat(titre, "OK", f"{lances} test(s) passe(s){ignores}",
                             resultat.detail, bloquant, code_sortie=code)

    noms = _en_echec()
    liste = "\n".join(f"- `{commun.cellule(nom, 200)}`" for nom in noms[:50])
    reste = f"\n- ... et {len(noms) - 50} autre(s)" if len(noms) > 50 else ""
    if code == 2:
        # pytest s'arrête à la première erreur de collecte : les autres tests
        # n'ont PAS tourné, même ceux qui auraient passé.
        resume = f"{bilan['errors']} fichier(s) de test ne s'importent pas - les tests n'ont pas tourne"
    else:
        resume = f"{bilan['failures'] + bilan['errors']} test(s) en echec sur {lances}"
    return base.Resultat(
        titre, "ALERTE", resume,
        (f"**Tests en échec :**\n\n{liste}{reste}\n\n" if noms else "") + resultat.detail,
        bloquant, detail_markdown=bool(noms), code_sortie=code, dossier=resultat.dossier)
