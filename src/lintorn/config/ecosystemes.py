# Lintorn
"""Quels langages ce projet parle-t-il ? Django, Python, front, TypeScript, et les verrous qui le disent."""

from __future__ import annotations

from pathlib import Path

from .. import config


def _candidats(marqueur: str, profondeur: int = 2):
    """Les dossiers contenant `marqueur`, du plus haut au plus profond.

    Profondeur limitée à 2 : au-delà on parcourt des arborescences entières
    pour un gain nul, et on risque de tomber sur le `package.json` d'une
    dépendance oubliée par IGNORES.
    """
    if (config.RACINE / marqueur).is_file():
        yield config.RACINE
    for niveau in range(1, profondeur + 1):
        motif = "/".join(["*"] * niveau) + "/" + marqueur
        for trouve in sorted(config.RACINE.glob(motif)):
            if not config.sous_ignores(trouve):
                yield trouve.parent


def _trouver(marqueur: str, profondeur: int = 2) -> Path | None:
    """Le premier dossier contenant `marqueur`, cherché depuis la racine."""
    return next(config._candidats(marqueur, profondeur), None)


def _racine_python() -> Path | None:
    """Où lancer ruff et pytest. None si le projet n'a pas de Python du tout.

    ⚠️ « projet Python » et « projet Django » sont DEUX choses. Ces contrôles
    ont d'abord été accrochés à la détection de `manage.py` — conséquence :
    sur un projet Python sans Django (Lintorn lui-même !), ruff et pytest
    disparaissaient purement et simplement. L'outil ne savait pas s'auditer.

    Django d'abord quand il existe (c'est là que vit le code métier), sinon
    le dossier qui porte les marqueurs d'un projet Python.

    ⚠️ UN TÉMOIN SEUL NE FAIT PAS UN PROJET PYTHON. Un `pyproject.toml` sert
    aussi à installer des linters de templates ou de YAML dans un dépôt Go ou
    JS : ruff, vulture et pip-audit y tournaient sur zéro fichier Python, et
    ruff bloquait le push sur une fixture `.ipynb` d'un test Go. Il faut du
    code Python sous le dossier du témoin.
    """
    if config.BACKEND:
        return config.BACKEND
    # ⚠️ `Pipfile` (Pipenv) et `environment.yml` (conda) : deux outils
    # courants qui n'écrivent ni pyproject.toml ni requirements.txt. Sans
    # eux, un projet Pipenv était « rien de connu » — ruff ne tournait même
    # pas, et le rapport affirmait qu'il n'y avait aucun code Python.
    for marqueur in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
                     "Pipfile", "environment.yml", "environment.yaml"):
        for dossier in config._candidats(marqueur):
            if any(source.is_relative_to(dossier) for source in config._SOURCES_PY):
                return dossier
    return None


def _requirements() -> Path | None:
    """Le `requirements.txt` du projet Python : à côté de son code, sinon à la racine.

    ⚠️ Pas seulement à côté de `manage.py` : un projet Django rangé dans un
    sous-dossier garde souvent ses dépendances à la racine du dépôt. Cherché
    au seul dossier Django, le fichier était introuvable, et « Dependances vs
    venv » disparaissait du rapport sans un mot.
    """
    if config.PY_RACINE is None:
        return None
    for dossier in dict.fromkeys((config.PY_RACINE, config.RACINE)):
        if (dossier / "requirements.txt").is_file():
            return dossier / "requirements.txt"
    return None


def _prefixe(chemin: Path | None) -> str | None:
    """`/projet/api` → `"api/"`, relatif à la racine. None si hors projet."""
    if chemin is None:
        return None
    try:
        relatif = chemin.relative_to(config.RACINE).as_posix()
    except ValueError:
        return None
    return "" if relatif == "." else relatif + "/"


# Le gestionnaire de paquets JS, c'est son VERROU qui le désigne.
# ⚠️ `npm install` sur un projet yarn ou pnpm ignore son verrou et en pose un
# second, `package-lock.json`, qui se versionne à côté du vrai : un remède
# unique faisait plus de dégâts que pas de remède du tout.
VERROUS_JS = (
    ("pnpm-lock.yaml", "pnpm install"),
    ("yarn.lock", "yarn install"),
    ("bun.lock", "bun install"),
    ("bun.lockb", "bun install"),
    ("package-lock.json", "npm install"),
)


def installation_js(dossier: Path) -> tuple[str, Path]:
    """(commande qui installe les dépendances JS de `dossier`, où la lancer).

    Le verrou est cherché dans le dossier, puis en remontant jusqu'à la
    racine : un workspace n'en a qu'un, à sa racine, et c'est là que
    l'installation se lance. Sans verrou nulle part : `npm install` dans le
    dossier même — c'est le gestionnaire livré avec Node.
    """
    for lieu in (dossier, *dossier.parents):
        if not lieu.is_relative_to(config.RACINE):
            break
        for verrou, commande in config.VERROUS_JS:
            if (lieu / verrou).is_file():
                return commande, lieu
    return "npm install", dossier


def remede_js(dossier: Path) -> str:
    """`yarn install (dans web)` — ce qu'il faut lancer, et où."""
    commande, lieu = config.installation_js(dossier)
    return f"{commande} (dans {(config._prefixe(lieu) or '').rstrip('/') or '.'})"


def tsc_de(projet: Path) -> Path:
    """Le `tsc` d'un projet TS : le sien, sinon celui qu'un workspace a hissé
    plus haut (jusqu'à la racine). Absent partout : le sien, qui s'annoncera
    introuvable avec son remède."""
    for lieu in (projet, *projet.parents):
        if not lieu.is_relative_to(config.RACINE):
            break
        if (lieu / "node_modules" / ".bin" / config.TSC).exists():
            return lieu / "node_modules" / ".bin" / config.TSC
    return projet / "node_modules" / ".bin" / config.TSC


# Les verrous qu'aucun audit natif ne LIT.
# ⚠️ Cette liste sert à DÉTECTER, pas à scanner : OSV-Scanner cherche lui-même
# ses fichiers, et il en connaît plus qu'une liste recopiée ici. Un format
# absent d'ici n'échappe donc jamais à l'audit accordé — seulement à la
# proposition de l'activer. Chaque nom a été soumis à OSV-Scanner 2.6, qui l'a
# reconnu.
#
# ⚠️ Les verrous PYTHON en font partie : pip-audit interroge un venv, jamais
# `uv.lock` ni `poetry.lock`. Sans venv dans le dossier — le cas ordinaire
# d'un projet uv ou poetry —, les dépendances verrouillées n'étaient lues par
# personne, et pip-audit rendait un vert sur un autre environnement.
VERROUS_OSV = {
    "uv.lock": "Python (uv)",
    "poetry.lock": "Python (poetry)",
    "Pipfile.lock": "Python (Pipenv)",
    "pdm.lock": "Python (pdm)",
    "Cargo.lock": "Rust",
    "go.mod": "Go",
    "composer.lock": "PHP",
    "Gemfile.lock": "Ruby",
    "gems.locked": "Ruby",
    "pubspec.lock": "Dart",
    "mix.lock": "Elixir",
    "pnpm-lock.yaml": "JS (pnpm)",
    "yarn.lock": "JS (yarn)",
    "bun.lock": "JS (bun)",
    "packages.lock.json": ".NET",
    "pom.xml": "Java (Maven)",
    "gradle.lockfile": "Java (Gradle)",
    "renv.lock": "R",
    "conan.lock": "C/C++",
    "Package.resolved": "Swift",
    "stack.yaml.lock": "Haskell",
    "cabal.project.freeze": "Haskell",
}


# Ceux dont le NOM varie d'un projet à l'autre : reconnus à leur extension.
# Un projet .NET sans `packages.lock.json` — la gestion centrale des versions
# n'en écrit pas — n'a que ses `.csproj`, et ses dépendances NuGet n'étaient
# auditées par rien.
SUFFIXES_OSV = {
    ".csproj": ".NET",
}


def _ecosystemes_osv(fichiers: list[Path], front: Path | None) -> dict[str, list[Path]]:
    """{écosystème: [ses verrous]} — ce que ni pip-audit ni npm audit ne lisent.

    Le `package-lock.json` du front est à npm audit ; un AUTRE (un second
    front, un outil annexe) n'est vu par personne : il revient à OSV.
    """
    verrou_npm = (front / config.VERROU_NPM) if front else None
    trouves: dict[str, list[Path]] = {}
    for chemin in fichiers:
        if chemin.name == config.VERROU_NPM:
            ecosysteme = None if chemin == verrou_npm else "JS (npm)"
        else:
            ecosysteme = config.VERROUS_OSV.get(chemin.name) or config.SUFFIXES_OSV.get(chemin.suffix)
        if ecosysteme:
            trouves.setdefault(ecosysteme, []).append(chemin)
    return trouves
