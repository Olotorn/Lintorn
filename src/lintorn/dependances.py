#!/usr/bin/env python3
"""
dependances.py — `requirements.txt` dit-il la vérité sur le venv ?

    python -m lintorn.dependances

Lancé par Lintorn, mais utilisable seul.

POURQUOI CE CONTRÔLE EXISTE
    C'est le classique « ça marche chez moi » : un paquet installé à la main
    dans le venv, jamais ajouté à `requirements.txt`. Le
    code tourne sur la machine du dev et casse partout ailleurs (Docker,
    Codespaces, une machine neuve).

    Aucun autre contrôle ne peut le voir : ruff, pytest et Django tournent
    DANS le venv, donc pour eux le paquet est là. Le défaut ne se révèle qu'au
    déploiement, quand il est le plus cher à diagnostiquer.

TROIS ÉCARTS, TROIS GRAVITÉS
    manquant   déclaré mais pas installé   → ImportError garanti ICI
    divergent  version differente          → LE cas « ça marche pas, pourquoi »
    en trop    installé mais non déclaré   → ça casse AILLEURS, pas ici

LES DEUX FAÇONS D'ÉCRIRE requirements.txt
    Complet (`pip freeze`) ou dépendances DIRECTES seulement : les deux sont
    comprises. Un paquet sans ligne que tire une dépendance déclarée, pip
    l'installera partout : il n'est pas « en trop ». Sauf si le code
    l'importe lui-même : ce qu'on importe se déclare. Supposer un fichier
    complet signalait les ~50 sous-dépendances d'un fichier de dépendances
    directes, un rouge bloquant que rien ne levait.

Aucune dépendance : stdlib uniquement.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

try:
    from importlib import metadata
except ImportError:              # le python du projet peut être antérieur à 3.8
    metadata = None


# ⚠️ Le dossier backend est REÇU, jamais deviné.
#
# Ce fichier déduisait autrefois sa position comme le faisait `config.py` :
# `Path(__file__).parents[2] / "<projet>" / "backend"`. Installé par pip, ça
# désigne un dossier qui n'existe pas — et le contrôle sortait en « INDISPONIBLE »
# au lieu de dire la vérité sur les dépendances.
#
# Il reste lançable seul (`python dependances.py <backend>`) : c'est utile pour
# le déboguer sans passer par Lintorn, et le repli sur le dossier courant
# couvre le cas où on le lance depuis le backend lui-même.
def _backend_vise() -> pathlib.Path:
    if len(sys.argv) > 1:
        return pathlib.Path(sys.argv[1]).expanduser().resolve()
    return pathlib.Path.cwd().resolve()


BACKEND = _backend_vise()
REQUIREMENTS = BACKEND / "requirements.txt"

# ⚠️ Le python qui LANCE ce script est celui qu'on interroge. Lintorn le lance
# avec le python DU PROJET (`config.PYTHON`), qui connaît déjà `venv/`,
# `.venv/`, `env/` et la déclaration `venv = "…"`. Ce fichier devinait
# `BACKEND/venv/` en dur : sur un projet en `.venv/`, il sortait « venv
# introuvable » — un faux rouge bloquant qu'aucune config ne corrigeait.
PYTHON = pathlib.Path(sys.executable)

# `pip freeze` exclut pip/setuptools/wheel par défaut, mais pas toujours selon
# la version : on ne juge jamais l'outillage de pip lui-même.
TOUJOURS_IGNORES = {"pip", "setuptools", "wheel", "distribute", "pkg-resources"}

# Les outils que `lintorn outils` installe dans le venv du projet (la liste de
# `config.OUTILS_INSTALLABLES`). Ils auditent le projet, ils ne le font pas
# tourner : comptés « installés mais pas déclarés », avec leurs dépendances,
# ils faisaient refuser le premier push de qui venait de les installer.
OUTILS_D_AUDIT = ("ruff", "pytest", "vulture", "pip-audit")

# Le nom d'une ligne de requirements, quelle que soit sa contrainte.
_NOM = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
# Une exigence de paquet, `CacheControl[filecache]>=0.13`, et le marqueur qui la
# rend optionnelle, `extra == "dev"`.
_EXIGENCE = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?")
_OPTION = re.compile(r"extra\s*==\s*['\"]([^'\"]+)['\"]")


def normaliser(nom: str) -> str:
    """`Django`, `django`, `DJANGO_` → `django` (PEP 503)."""
    return re.sub(r"[-_.]+", "-", nom).strip().lower()


def lire_requirements() -> tuple[dict[str, str], dict[str, str], list[str], str | None]:
    """Retourne ({paquet: version}, {paquet: sa ligne, sans `==`},
    [chaque paquet déclaré, avec ses options : `requests[socks]`], avertissement d'encodage).

    ⚠️ Le fichier peut être en UTF-16 : c'est ce que produit
    `pip freeze > requirements.txt` dans PowerShell. pip sait le lire (il
    détecte le BOM), mais aucun autre outil ne s'y attend — un `grep` dessus
    renvoie des caractères espacés, et tout script qui l'ouvre en UTF-8 plante.
    On le lit quand même, et on le signale.
    """
    brut = REQUIREMENTS.read_bytes()
    avertissement = None

    if brut[:2] in (b"\xff\xfe", b"\xfe\xff"):
        texte = brut.decode("utf-16")
        avertissement = (
            "requirements.txt est encode en UTF-16 (BOM detecte). pip sait le "
            "lire, mais pas les autres outils : un grep dessus renvoie des "
            "caracteres espaces, et tout script qui l'ouvre en UTF-8 plante.\n"
            "    Pour le convertir :\n"
            "      python -c \"import pathlib; p=pathlib.Path('requirements.txt'); "
            "p.write_text(p.read_bytes().decode('utf-16'), encoding='utf-8')\"\n"
            "    Et pour ne plus le reproduire (la redirection > de PowerShell\n"
            "    ecrit en UTF-16, et Out-File -Encoding utf8 ajoute un BOM en 5.1) :\n"
            "      [IO.File]::WriteAllLines(\"$PWD\\requirements.txt\", "
            "(python -m pip freeze))"
        )
    else:
        texte = brut.decode("utf-8-sig")

    paquets: dict[str, str] = {}
    souples: dict[str, str] = {}
    exigences: list[str] = []
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        # On ignore commentaires, options (-r, --index-url) et lignes vides.
        if not ligne or ligne.startswith(("#", "-")):
            continue
        if "==" not in ligne:
            # Contrainte souple (`Django>=5`, `ruff`) : pas de version à
            # comparer, mais le paquet est DÉCLARÉ. Ignorée, la ligne laissait
            # Django « installé mais pas déclaré », un rouge bloquant à tort.
            # Une URL ou un chemin ne dit pas son nom : on ne s'en mêle pas.
            nom = _NOM.match(ligne)
            if nom and "://" not in ligne.split("@", 1)[0]:
                souples[normaliser(nom.group(1))] = ligne
                exigences.append(ligne.split(";", 1)[0])
            continue
        nom, version = ligne.split("==", 1)
        exigences.append(nom)
        # ⚠️ Les EXTRAS ne font pas partie du nom : `psycopg[c,pool]` est
        # installé sous le nom `psycopg`. Gardés, le paquet était déclaré
        # « PAS INSTALLE — ImportError garanti », un rouge bloquant à tort.
        # Même chose pour un marqueur collé à la version (`1.0;python_version…`).
        nom = nom.split("[", 1)[0]
        paquets[normaliser(nom)] = version.split(";", 1)[0].split()[0].strip()

    return paquets, souples, exigences, avertissement


def lire_venv() -> dict[str, str]:
    proc = subprocess.run(
        [str(PYTHON), "-m", "pip", "freeze", "--local"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pip freeze a echoue :\n{proc.stderr}")

    paquets: dict[str, str] = {}
    for ligne in proc.stdout.splitlines():
        ligne = ligne.strip()
        if "==" not in ligne or ligne.startswith(("#", "-")):
            continue
        nom, version = ligne.split("==", 1)
        paquets[normaliser(nom)] = version.strip()
    return paquets


def _nom_et_options(exigence: str) -> tuple[str, set[str]] | None:
    """`CacheControl[filecache]>=0.13` → (`CacheControl`, {`filecache`})."""
    trouve = _EXIGENCE.match(exigence)
    if not trouve:
        return None
    return trouve.group(1), {o.strip() for o in (trouve.group(2) or "").split(",") if o.strip()}


def tires_par(exigences: list[str]) -> set[str]:
    """Ces paquets et tout ce qu'ils tirent, d'après les métadonnées du venv interrogé.

    Une dépendance optionnelle (`extra == ...`) n'est tirée que si quelqu'un la
    demande : `CacheControl[filecache]` tire `filelock`, `CacheControl` seul non.
    """
    a_voir = [lu for lu in map(_nom_et_options, exigences) if lu]
    if metadata is None:
        return {normaliser(nom) for nom, _ in a_voir}
    options: dict[str, set[str]] = {}
    while a_voir:
        nom, demandees = a_voir.pop()
        nom = normaliser(nom)
        if nom in options and demandees <= options[nom]:
            continue
        try:
            requis = metadata.requires(nom) or []
        except metadata.PackageNotFoundError:
            continue
        options[nom] = options.get(nom, set()) | demandees
        for exigence in requis:
            texte, _, marqueur = exigence.partition(";")
            option = _OPTION.search(marqueur)
            if option and option.group(1) not in options[nom]:
                continue
            lu = _nom_et_options(texte)
            if lu:
                a_voir.append(lu)
    return set(options)


# Une ligne d'import, lue comme du texte : rien n'est exécuté ni compilé. Un
# « import x » dans une docstring compte aussi : un paquet de plus est montré,
# aucun n'est caché.
_IMPORT = re.compile(r"^[ \t]*(?:from[ \t]+([A-Za-z_]\w*)|import[ \t]+([^\n#;]+))", re.M)
_SANS_CODE_DU_PROJET = {"node_modules", "__pycache__", "site-packages"}
MAX_FICHIERS = 50_000


def importes(dossier: pathlib.Path) -> set[str]:
    """Les modules de premier niveau que le code de ce dossier importe (venvs exclus).

    Sauf ses propres modules : un `import tests` vise le dossier tests/ du projet,
    pas un paquet installé qui livrerait le sien. Seuls comptent ceux qu'un
    import atteint, à la racine ou sous src/ : un `api/requests.py` ne cache pas
    `import requests`.
    """
    locaux = set()
    for haut in (dossier, dossier / "src"):
        try:
            locaux |= {entree.name[:-3] if entree.name.endswith(".py") else entree.name
                       for entree in os.scandir(haut)
                       if entree.name.endswith(".py") or entree.is_dir()}
        except OSError:
            continue
    vus: set[str] = set()
    lus = 0
    for ici, dossiers, fichiers in os.walk(dossier):
        dossiers[:] = [nom for nom in dossiers
                       if not nom.startswith(".") and nom not in _SANS_CODE_DU_PROJET
                       and not os.path.exists(os.path.join(ici, nom, "pyvenv.cfg"))]
        for nom in fichiers:
            if not nom.endswith(".py"):
                continue
            lus += 1
            if lus > MAX_FICHIERS:
                return vus - locaux
            try:
                with open(os.path.join(ici, nom), encoding="utf-8", errors="replace") as source:
                    texte = source.read()
            except OSError:
                continue
            for depuis, liste in _IMPORT.findall(texte):
                for morceau in [depuis] if depuis else liste.split(","):
                    mot = morceau.strip().split(".")[0].split(" ")[0]
                    if mot.isidentifier():
                        vus.add(mot)
    return vus - locaux


def modules_de(nom: str) -> set[str]:
    """Les modules qu'un paquet installé fournit : `requests` → requests, `PyYAML` → yaml."""
    if metadata is None:
        return set()
    try:
        distribution = metadata.distribution(nom)
    except metadata.PackageNotFoundError:
        return set()
    haut = distribution.read_text("top_level.txt")
    if haut:
        return {ligne.strip() for ligne in haut.splitlines() if ligne.strip()}
    modules = set()
    for fichier in distribution.files or []:
        premier = fichier.parts[0] if fichier.parts else ""
        if premier.endswith(".py"):
            modules.add(premier[:-3])
        elif len(fichier.parts) > 1 and premier.isidentifier() and premier != "__pycache__":
            modules.add(premier)
    return modules


def sans_ligne(installes: dict[str, str], tous_declares: set[str], exigences: list[str],
               dossier: pathlib.Path | None) -> dict[str, str]:
    """Chaque paquet installé que requirements.txt ne déclare pas, et pourquoi il est là.

    « outil »   : un outil d'audit de `lintorn outils`, ou ce qu'eux seuls tirent ;
    « tire »    : une dépendance déclarée le tire, pip l'installera partout ;
    « importe » : ton code l'importe sans le déclarer ;
    « en_trop » : rien ne l'apporte ailleurs.

    L'import passe avant le reste : pip-audit tire requests, et un
    `import requests` jamais déclaré passait pour un paquet de l'outillage.
    """
    candidats = set(installes) - tous_declares - TOUJOURS_IGNORES
    if not candidats:
        return {}
    outils = {normaliser(o) for o in OUTILS_D_AUDIT} & candidats
    par_les_outils = tires_par(sorted(outils))
    par_le_projet = tires_par(exigences)
    vus = importes(dossier) if dossier is not None else set()
    raisons = {}
    for nom in candidats:
        if nom in outils:
            raisons[nom] = "outil"
        elif modules_de(nom) & vus:
            raisons[nom] = "importe"
        elif nom in par_le_projet:
            raisons[nom] = "tire"
        elif nom in par_les_outils:
            raisons[nom] = "outil"
        else:
            raisons[nom] = "en_trop"
    return raisons


def _sans_ligne_seul() -> int:
    """`--sans-ligne` : `{paquet: raison}` en JSON, pour `lintorn pip-audit --appliquer`.

    Un paquet monté là ne s'épingle que s'il n'a ni outil ni dépendance déclarée
    pour l'apporter : la même règle que ce contrôle.
    """
    try:
        declares, souples, exigences, _ = (lire_requirements() if REQUIREMENTS.exists()
                                           else ({}, {}, [], None))
        installes = lire_venv()
    except Exception as e:
        print(f"L'OUTIL A PLANTE : {type(e).__name__} : {e}", file=sys.stderr)
        return 2
    print(json.dumps(sans_ligne(installes, set(declares) | set(souples), exigences, BACKEND)))
    return 0


def main() -> int:
    if "--sans-ligne" in sys.argv[2:]:
        return _sans_ligne_seul()
    if not REQUIREMENTS.exists():
        print(f"INDISPONIBLE : {REQUIREMENTS} est introuvable.")
        return 2

    try:
        declares, souples, exigences, avertissement = lire_requirements()
        installes = lire_venv()
    except Exception as e:
        print(f"L'OUTIL A PLANTE : {type(e).__name__} : {e}")
        return 2

    for ignore in TOUJOURS_IGNORES:
        declares.pop(ignore, None)
        souples.pop(ignore, None)
        installes.pop(ignore, None)

    tous_declares = set(declares) | set(souples)
    # Écartés, mais NOMMÉS plus bas : un paquet du projet que seul un outil
    # tirerait ne passe pas inaperçu sans que personne le sache.
    raisons = sans_ligne(installes, tous_declares, exigences, BACKEND)
    ecartes = sorted(nom for nom, raison in raisons.items() if raison == "outil")
    tires = sorted(nom for nom, raison in raisons.items() if raison == "tire")

    manquants = sorted(tous_declares - set(installes))
    en_trop = sorted(nom for nom, raison in raisons.items() if raison in ("importe", "en_trop"))
    divergents = sorted(
        nom for nom in set(declares) & set(installes)
        if declares[nom] != installes[nom]
    )

    lignes: list[str] = []

    if manquants:
        lignes.append(
            f"DECLARES MAIS PAS INSTALLES ({len(manquants)}) "
            "-- ImportError garanti sur CETTE machine :"
        )
        lignes += [f"    - {n}=={declares[n]}" if n in declares else f"    - {souples[n]}"
                   for n in manquants]
        lignes.append("    -> python -m pip install -r requirements.txt")
        lignes.append("")

    if divergents:
        lignes.append(
            f"VERSIONS DIVERGENTES ({len(divergents)}) "
            "-- le venv ne correspond pas a ce qui est declare :"
        )
        lignes += [
            f"    - {n} : requirements={declares[n]}  venv={installes[n]}"
            for n in divergents
        ]
        lignes.append("")

    if en_trop:
        lignes.append(
            f"INSTALLES MAIS PAS DECLARES ({len(en_trop)}) "
            "-- ca marche ICI, ca cassera AILLEURS :"
        )
        lignes += [f"    - {n}=={installes[n]}"
                   + ("  (ton code l'importe)" if raisons[n] == "importe" else "")
                   for n in en_trop]
        lignes.append(
            "    -> ajoute-leur une ligne, ou fige tout : python -m pip freeze"
            + (" | Out-File requirements.txt -Encoding utf8" if sys.platform == "win32"
               else " > requirements.txt"))
        lignes.append("")

    if avertissement:
        lignes.append(f"ENCODAGE : {avertissement}")
        lignes.append("")

    notes = [f"{titre} ({len(noms)}) : " + ", ".join(noms) for titre, noms in (
        ("Non comptes : les outils d'audit et ce qu'eux seuls tirent", ecartes),
        ("Sans ligne, tires par tes dependances declarees (pip les installera)", tires)) if noms]
    note = "\n".join(notes)

    if not lignes:
        print(f"OK - {len(tous_declares)} paquet(s) declare(s), tous installes a la bonne version."
              + (f"\n{note}" if note else ""))
        return 0

    print("\n".join(lignes + ([note] if note else [])).rstrip())

    # L'encodage seul ne bloque pas un push : pip s'en accommode.
    ecart_reel = bool(manquants or divergents or en_trop)
    return 1 if ecart_reel else 0


if __name__ == "__main__":
    raise SystemExit(main())
