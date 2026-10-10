# Lintorn
"""Qu'est-ce qu'un chemin cité dans une doc, et existe-t-il ? (partagé par la doc et la mémoire IA)"""

from __future__ import annotations

import os
import re
import sys
from fnmatch import fnmatchcase
from pathlib import Path
from typing import NamedTuple

from ... import config


def indexer_fichiers() -> set[str]:
    """Parcourt le dépôt une fois et retient chaque nom de fichier."""
    noms: set[str] = set()
    for chemin in config.RACINE.rglob("*"):
        if config.sous_ignores(chemin):
            continue
        if chemin.is_file():
            noms.add(chemin.name)
    return noms


def est_un_chemin(token: str) -> bool:
    """Trie les `backticks` : garde ce qui ressemble à un fichier, jette le code.

    ⚠️ C'est un empilement d'heuristiques, pas une science : chaque règle a été
    ajoutée après un vrai faux positif. Les cas connus sont figés dans
    test_Lintorn.py pour qu'ils ne reviennent pas.
    """
    if not token or len(token) > 120:
        return False
    # Du code, pas un chemin : `tsc --noEmit`, `Facture.emettre()`, `var(--bg)`…
    if any(c in token for c in " ()<>|$*\"'{}[]=,;`"):
        return False
    # Routes d'API (`/api/archives/`), URL, chemins tronqués (`.../debloquer`)
    if token.startswith(("/", "http", "@", "-", ".venv")) or "..." in token:
        return False
    # Une extension citée seule (« en `.tsx` obligatoirement ») n'est pas un fichier
    if token.startswith(".") and "/" not in token:
        return False
    return "/" in token or token.endswith(config.EXTENSIONS)


def existe(token: str, index_noms: set[str], depuis: Path | None = None) -> bool:
    """Le chemin cité correspond-il à quelque chose de réel ?

    `index_noms` est passé en PARAMÈTRE : la fonction ne dépend que de ses
    arguments, donc elle est testable seule et ne peut pas tomber sur un index
    vide (c'était un défaut de la première version).

    ⚠️ `depuis` = le dossier du DOCUMENT qui cite ce chemin, et il est
    indispensable. Un document écrit presque toujours ses liens relativement à
    lui-même : `advanced/nosql.md` cité depuis `docs/fr/` désigne
    `docs/fr/advanced/nosql.md`, pas un fichier à la racine du dépôt.
    Sans cette racine supplémentaire, une documentation organisée en
    sous-dossiers se retrouve massivement — et faussement — signalée comme
    cassée. Constaté sur un projet réel : 474 faux positifs d'un coup, soit
    un quart des chemins cités. À ce niveau de bruit, plus personne ne lit.
    """
    token = re.sub(r":\d+(-\d+)?$", "", token)   # `models.py:17-34` → `models.py`

    # Un import TS s'écrit sans extension (`utils/dataFormatters`) → on les essaie
    candidats = [token]
    if not token.endswith(config.EXTENSIONS):
        candidats += [token + ext for ext in (".ts", ".tsx", ".js", ".jsx", ".py")]

    # Le dossier du document passe EN PREMIER : c'est la lecture la plus
    # naturelle d'un lien écrit dans un document.
    racines = _racines(depuis)

    for candidat in candidats:
        if "/" in candidat:
            if any((racine / candidat).exists() for racine in racines):
                return True
        elif candidat in index_noms:
            return True
    return _sortie_de_lintorn(token)


# `noyau.lancer()`, `_fiches_memoire()` : une fonction citée sous sa forme d'appel.
_RX_FONCTION = re.compile(r"^((?:[A-Za-z_]\w*\.)*)([A-Za-z_]\w*)\(\)$")
_RX_IDENTIFIANT = re.compile(r"[A-Za-z_]\w*")

# Ce qui n'est pas du code : un nom n'y existe pas parce qu'il y est écrit. Une
# fonction se DÉFINIT dans du code ; un réglage (`.toml`, `.ini`, `.cfg`) ne
# fait que la nommer — souvent dans un commentaire resté après son renommage.
_PAS_DU_CODE = (".md", ".mdx", ".rst", ".txt", ".json", ".lock", ".csproj", ".xml",
                ".toml", ".ini", ".cfg")
_TAILLE_MAX_CODE = 2 << 20


class Code(NamedTuple):
    """Les noms écrits dans le code du projet, et les noms de ses modules."""
    identifiants: set[str]
    modules: set[str]


def fonction_citee(token: str) -> tuple[str, str] | None:
    """(qualificatif, nom) d'une fonction citée — `base.lien()` → ("base", "lien").

    Les noms spéciaux (`__init__()`) existent par construction : pas une affirmation.
    """
    trouve = _RX_FONCTION.match(token)
    if not trouve or (trouve[2].startswith("__") and trouve[2].endswith("__")):
        return None
    return trouve[1].rstrip("."), trouve[2]


def indexer_code() -> Code:
    """Chaque nom écrit dans le CODE du projet, et les noms de ses modules.

    ⚠️ La doc est exclue : sinon le document qui cite une fonction disparue la
    ferait exister à lui seul. Un nom présent n'importe où dans le code compte
    (un commentaire, un appel à la bibliothèque standard) : on préfère rater
    un vieux nom resté dans un commentaire que crier sur `isatty()`.
    """
    identifiants: set[str] = set()
    modules: set[str] = set()
    for fichier in config._fichiers_du_projet():
        nom = fichier.name
        if (not nom.endswith(config.EXTENSIONS) or nom.endswith(_PAS_DU_CODE)
                or fichier.is_relative_to(config.DOSSIER_LINTORN)):
            continue
        try:
            if fichier.stat().st_size > _TAILLE_MAX_CODE:
                continue
            texte = fichier.read_text(encoding="utf-8", errors="replace")
            relatif = fichier.relative_to(config.RACINE)
        except (OSError, ValueError):
            continue
        identifiants.update(_RX_IDENTIFIANT.findall(texte))
        modules.add(fichier.stem)
        modules.update(relatif.parts[:-1])
    # Un dossier `os/` ou un fichier `json.py` dans le projet ne fait pas de
    # `os.fdopen()` une fonction DU projet.
    return Code(identifiants, modules - set(sys.stdlib_module_names))


def _sortie_de_lintorn(token: str) -> bool:
    """`rapport.md`, `.lintorn/rapport.html`, `etat.json` : ce que Lintorn ÉCRIT.

    Ces fichiers n'existent qu'une fois Lintorn passé — et le contrôle de la
    doc tourne AVANT que le rapport soit écrit. Sur un clone neuf, une doc qui
    les citait était donc déclarée menteuse : le premier push d'un
    contributeur était bloqué par le contrôle censé l'aider. Ils existent par
    définition.
    """
    sorties = (config.RAPPORT, config.RAPPORT_HTML, config.ETAT)
    return (token in {sortie.name for sortie in sorties}
            or any(token == sortie.relative_to(config.RACINE).as_posix()
                   for sortie in sorties if sortie.is_relative_to(config.RACINE)))


class _Arbre(NamedTuple):
    """Le dépôt tel que git le voit, en chemins relatifs à RACINE."""
    dossiers: set[str]
    par_nom: dict[str, list[str]]   # dernier segment → fichiers ET dossiers
    gitignores: list[str]


def _arborescence() -> _Arbre:
    """Lu dans git (fichiers suivis, et nouveaux non ignorés), pas sur le
    disque : c'est le dépôt qu'on juge, pas la machine qui l'audite."""
    dossiers: set[str] = set()
    par_nom: dict[str, list[str]] = {}
    gitignores: list[str] = []
    for fichier in config._fichiers_du_projet():
        try:
            relatif = fichier.relative_to(config.RACINE).as_posix()
        except ValueError:
            continue
        parties = relatif.split("/")
        for fin in range(1, len(parties)):
            dossier = "/".join(parties[:fin])
            if dossier not in dossiers:
                dossiers.add(dossier)
                par_nom.setdefault(parties[fin - 1], []).append(dossier)
        par_nom.setdefault(parties[-1], []).append(relatif)
        if parties[-1] == ".gitignore":
            gitignores.append(relatif)
    return _Arbre(dossiers, par_nom, gitignores)


def _racines(depuis: Path | None) -> list[Path]:
    """D'où un chemin cité par un document peut être relatif."""
    return ([depuis] if depuis else []) + list(config.RACINES_RESOLUTION)


def _relatif(chemin: Path) -> str | None:
    """`chemin` relatif à RACINE, normalisé — None s'il en sort."""
    propre = Path(os.path.normpath(chemin))
    if not propre.is_relative_to(config.RACINE) or propre == config.RACINE:
        return None
    relatif = propre.relative_to(config.RACINE).as_posix()
    return None if relatif.startswith(":") else relatif


def _vise_le_nom(motif: str, nom: str) -> bool:
    """La règle `.gitignore` désigne-t-elle ce fichier PAR SON NOM ?

    `/netbox/configuration.py` et `*.log` : oui. `var/`, `/scripts/*` : non,
    ils visent tout un dossier et n'apprennent rien sur un nom précis.
    """
    if motif.endswith("/"):
        return False
    dernier = motif.rsplit("/", 1)[-1]
    return bool(dernier.strip("*?")) and fnmatchcase(nom, dernier)


def _noms_vises(gitignores: list[str]) -> set[str]:
    """Les derniers segments des règles qui visent un nom (voir `_vise_le_nom`)."""
    segments: set[str] = set()
    for relatif in gitignores:
        try:
            texte = (config.RACINE / relatif).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ligne in texte.splitlines():
            ligne = ligne.strip()
            if not ligne or ligne.startswith(("#", "!")) or ligne.endswith("/"):
                continue
            dernier = ligne.rsplit("/", 1)[-1]
            if dernier.strip("*?"):
                segments.add(dernier)
    return segments


def _locaux_par_construction(absents: list[tuple[Path | None, str]],
                             arbre: _Arbre) -> set[tuple[Path | None, str]]:
    """Ceux des `(dossier du document, chemin cité)` absents que le
    `.gitignore` du projet déclare LOCAUX : un `configuration.py` à copier,
    un secret, un journal, une sortie de build.

    Local veut dire : la règle qui l'ignore le vise par son NOM, ou tout son
    dossier est hors du dépôt (`var/log/…`). ⚠️ Une règle de DOSSIER posée
    sur un dossier SUIVI (`/scripts/*` à côté d'un `__init__.py` commité)
    ne prouve rien : le fichier manquant a pu être supprimé. Accepter toute
    règle aurait éteint n'importe quel nom cité seul, puisque `d/nom` est
    ignoré dès que `d` l'est.
    """
    noms_vises: set[str] | None = None
    candidats: dict[str, set[tuple[Path | None, str]]] = {}
    for depuis, token in absents:
        propre = re.sub(r":\d+(-\d+)?$", "", token)
        if "/" in propre:
            chemins = {_relatif(racine / propre) for racine in _racines(depuis)}
        else:
            # Un nom seul peut vivre dans n'importe quel dossier : on ne le
            # pose que devant les règles qui visent ce nom, pas partout.
            if noms_vises is None:
                noms_vises = _noms_vises(arbre.gitignores)
            if not any(fnmatchcase(propre, segment) for segment in noms_vises):
                continue
            chemins = {propre, *(f"{dossier}/{propre}" for dossier in arbre.dossiers)}
        for chemin in chemins - {None}:
            candidats.setdefault(chemin, set()).add((depuis, token))

    locaux: set[tuple[Path | None, str]] = set()
    for chemin, motif in config.motifs_gitignore(sorted(candidats)).items():
        dossier, _, nom = chemin.rpartition("/")
        if _vise_le_nom(motif, nom) or (dossier and dossier not in arbre.dossiers):
            locaux |= candidats.get(chemin, set())
    return locaux


# Markdown (et MDX) : le code s'écrit `ainsi`, les exemples dans des ``` .
# reStructuredText : le code s'écrit ``ainsi``, un fichier :file:`ainsi`. Les
# `backticks simples` y sont des RÉFÉRENCES (`Flask`_, :mod:`flask.json`) :
# lus comme en Markdown, `flask.json` passerait pour un fichier.
_RX_CITATION_MD = re.compile(r"`([^`\n]+)`")


_RX_CITATION_RST = re.compile(r"``([^`\n]+?)``|:file:`([^`\n]+)`")


# Ce qui introduit un bloc de code en reST : un paragraphe qui finit par `::`,
# ou une directive de code. `.. note::` aussi finit par `::`, mais son
# contenu est de la prose : il reste lu.
_RX_INTRO_CODE_RST = re.compile(
    r"^\s*(\.\.\s+(code-block|code|sourcecode|parsed-literal)::.*|(?!\.\.).*::)\s*$")


def _sans_blocs_rst(texte: str) -> str:
    """Le texte reST privé de ses blocs de code : tout ce qui est plus indenté
    que la ligne qui les introduit, jusqu'au retour à cette indentation."""
    gardees: list[str] = []
    marge: int | None = None     # indentation de l'intro du bloc en cours
    for ligne in texte.splitlines():
        if marge is not None:
            if not ligne.strip() or len(ligne) - len(ligne.lstrip()) > marge:
                continue
            marge = None
        gardees.append(ligne)
        if _RX_INTRO_CODE_RST.match(ligne):
            marge = len(ligne) - len(ligne.lstrip())
    return "\n".join(gardees)


def _citations(texte: str, suffixe: str) -> tuple[str, list[str]]:
    """(texte sans ses blocs de code, citations `inline`) d'un document."""
    if suffixe == ".rst":
        texte = _sans_blocs_rst(texte)
        return texte, [litteral or fichier
                       for litteral, fichier in _RX_CITATION_RST.findall(texte)]
    # On ignore les blocs ``` (exemples de code) : seuls les `inline` comptent
    texte = re.sub(r"```.*?```", "", texte, flags=re.DOTALL)
    return texte, _RX_CITATION_MD.findall(texte)
