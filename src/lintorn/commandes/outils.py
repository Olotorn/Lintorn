# Lintorn
"""`lintorn outils` : installer et activer ce que le projet appelle."""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

from .. import base, chemins, confiance, config, noyau

# ─────────────────────────────────────────────────────────────────────────────
# ÉQUIPER LE PROJET — les outils et les audits que SON code appelle
# ─────────────────────────────────────────────────────────────────────────────
# Lintorn regarde ce que le projet CONTIENT et ne propose que ce qui s'y
# applique : pas de pip-audit sans Python, pas de npm audit sans verrou npm.
# Un outil proposé hors de propos finirait en « INDISPONIBLE » à vie — un
# voyant qu'on apprend à ignorer.
#
# Deux gestes, deux accords :
#   INSTALLER un paquet dans le venv du projet — une question pour la liste ;
#   ACTIVER un contrôle opt-in — une question PAR contrôle. Chacun franchit une
#   ligne différente (exécuter le code, ouvrir la base, sortir sur le réseau) :
#   un « oui » à l'un ne vaut pas pour l'autre. `--oui` ne répond donc qu'à la
#   première question, jamais aux secondes.

# (module importé, paquet pip, rôle, clé d'accord — None : toujours actif)
OUTILS_PYTHON = [
    ("ruff",      "ruff",      "lint Python",                          None),
    ("pytest",    "pytest",    "tests - EXECUTE le code du projet",    "tests"),
    ("vulture",   "vulture",   "code mort - consultatif",              "code_mort"),
    ("pip_audit", "pip-audit", "failles connues - sort sur le RESEAU", "failles"),
]

# Fournis par Django lui-même : rien à installer, seul l'accord manque.
OUTILS_DJANGO = [
    ("check",                  "reglages et apps - IMPORTE le code du projet", "django_check"),
    ("makemigrations --check", "migrations manquantes - IMPORTE le code",      "migrations"),
    ("verifier_donnees",       "donnees vs regles metier - ouvre la BASE", "donnees_metier"),
    ("check --deploy",         "reglages de prod - bruyant en dev",       "deploy"),
]


def _importable(module: str) -> bool:
    """Le python DU PROJET sait-il importer ce module ?

    Sans venv du projet, `config.PYTHON` est celui de Lintorn : y sonder les
    modules dirait « installé » de ruff et de pytest pour un projet qui n'a
    aucun environnement. Rien à sonder, rien n'est importable.
    """
    if config.VENV_PROJET is None:
        return False
    trouve = subprocess.run(
        [config.PYTHON, "-c", f"import {module}"],
        capture_output=True, text=True, check=False,
    )
    return trouve.returncode == 0


def _tsc_installe(projet) -> bool:
    """`tsc` vit dans un node_modules/.bin : celui du projet, ou d'un workspace."""
    return config.tsc_de(projet).exists()


def _outillage_du_projet() -> list[dict]:
    """Ce que CE projet appelle, écosystème par écosystème — et rien d'autre.

    `pip` : le paquet que Lintorn sait installer lui-même ; `fourni` : livré
    avec un autre outil (Django, npm), rien à installer ; `sinon` : ce que
    l'utilisateur doit faire quand Lintorn ne le peut pas. On le DIT au lieu
    de le taire : un outil absent qu'on n'annonce pas est un contrôle muet.
    """
    outils: list[dict] = []

    if config.PY_RACINE:
        for module, paquet, role, cle in OUTILS_PYTHON:
            outils.append({"ecosysteme": "Python", "nom": paquet, "role": role, "cle": cle,
                           "present": _importable(module), "fourni": False,
                           "pip": paquet, "sinon": None})

    if config.BACKEND:
        for nom, role, cle in OUTILS_DJANGO:
            # Une commande du projet, pas de Django : proposée seulement s'il l'a.
            if cle == "donnees_metier" and not config.DONNEES_METIER:
                continue
            outils.append({"ecosysteme": "Django", "nom": nom, "role": role, "cle": cle,
                           "present": True, "fourni": True, "pip": None, "sinon": None})

    front = config.FRONTEND
    for projet in config.PROJETS_TS:
        commande, lieu = config.installation_js(projet)
        nom = "tsc" if projet == config.RACINE else f"tsc ({chemins.relatif(projet)})"
        outils.append({"ecosysteme": "JS", "nom": nom, "role": "types TypeScript",
                       "cle": None, "present": _tsc_installe(projet), "fourni": False,
                       "pip": None, "sinon": f"cd {chemins.relatif(lieu)} && {commande}"})
    if front and (front / config.VERROU_NPM).is_file():
        outils.append({"ecosysteme": "JS", "nom": "npm audit",
                       "role": "failles connues - sort sur le RESEAU", "cle": "failles_npm",
                       "present": shutil.which(config.NPM) is not None, "fourni": True,
                       "pip": None, "sinon": "installer Node.js : c'est npm qui fournit l'audit"})

    if config.ECOSYSTEMES_OSV:
        langages = ", ".join(sorted(config.ECOSYSTEMES_OSV))
        outils.append({"ecosysteme": "Autres", "nom": "osv-scanner",
                       "role": f"failles connues ({langages}) - sort sur le RESEAU",
                       "cle": "failles_osv",
                       "present": shutil.which(config.OSV) is not None, "fourni": False,
                       "pip": None,
                       "sinon": "brew install osv-scanner - ou, sans Homebrew : "
                                "https://google.github.io/osv-scanner/installation/"})

    actifs = config.PROJET.get("controles", {})
    for outil in outils:
        outil["actif"] = outil["cle"] is None or bool(actifs.get(outil["cle"]))
    return outils


_RX_ENTETE = re.compile(r"^\s*\[")          # toute table, `[[regles]]` compris
_RX_TABLE = re.compile(r"^\s*\[\s*([^\[\]]+?)\s*\]\s*(#.*)?$")


def _activer_dans(texte: str, table: str, cle: str) -> str:
    """`texte` avec `cle = true` posé dans `[table]`.

    ⚠️ AUCUNE BIBLIOTHÈQUE TOML EN ÉCRITURE : zéro dépendance, et une
    re-sérialisation effacerait les commentaires qui expliquent chaque
    réglage. On touche UNE ligne : celle de la clé si elle existe — même
    commentée, `# deploy = false` devient `deploy = true` —, sinon une ligne
    ajoutée sous l'en-tête. Une table absente est créée en fin de fichier.
    """
    # ⚠️ PAS `splitlines()` : il coupe AUSSI sur U+2028, U+2029 et U+0085.
    # Un commentaire contenant l'un d'eux devenait deux lignes, dont la
    # seconde était du TOML actif — `failles = true` (réseau) posé sans
    # accord, dans un fichier qui reste valide pour `tomllib`.
    lignes = texte.split("\n")
    if lignes and lignes[-1] == "":
        lignes.pop()
    debut = None
    for numero, ligne in enumerate(lignes):
        trouve = _RX_TABLE.match(ligne)
        if trouve and trouve.group(1) == table:
            debut = numero
            break
    if debut is None:
        return texte.rstrip("\n") + f"\n\n[{table}]\n{cle} = true\n"

    fin = next((numero for numero in range(debut + 1, len(lignes))
                if _RX_ENTETE.match(lignes[numero])), len(lignes))
    rx_cle = re.compile(rf"^\s*#?\s*({re.escape(cle)}\s*=\s*)(?:true|false)\b(.*)$")
    for numero in range(debut + 1, fin):
        trouve = rx_cle.match(lignes[numero])
        if trouve:
            lignes[numero] = f"{trouve.group(1)}true{trouve.group(2)}"
            return "\n".join(lignes) + "\n"
    lignes.insert(debut + 1, f"{cle} = true")
    return "\n".join(lignes) + "\n"


def _activer(cles: list[str]) -> str | None:
    """Pose `cle = true` pour chaque clé dans la config que Lintorn a LUE.

    Rend le fichier écrit, ou None — la raison est alors affichée ici.
    """
    if "pyproject.toml" in config.FICHIERS_CONFIG_LUS:
        fichier, table = config.RACINE / "pyproject.toml", "tool.lintorn.controles"
    else:
        fichier, table = config.DOSSIER_LINTORN / "config.toml", "controles"
        if not fichier.is_file():
            print("\nPas encore de configuration : lance `lintorn init`, puis reviens ici.")
            return None
    try:
        texte = fichier.read_text(encoding="utf-8")
    except OSError as erreur:
        print(f"\n{fichier.name} illisible ({erreur}) : rien n'a ete active.")
        return None
    for cle in cles:
        texte = _activer_dans(texte, table, cle)

    # ⚠️ CONTRE-ÉPREUVE AVANT D'ÉCRIRE. Une config que la retouche aurait
    # cassée ferait repartir Lintorn sur ses DÉFAUTS au lancement suivant :
    # tous les contrôles opt-in coupés d'un coup, avec un rapport confiant.
    try:
        lu = tomllib.loads(texte)
        for morceau in table.split("."):
            lu = lu[morceau]
        tenu = all(lu.get(cle) is True for cle in cles)
    except (tomllib.TOMLDecodeError, KeyError, TypeError, AttributeError):
        tenu = False
    if not tenu:
        print(f"\n{fichier.name} n'a PAS ete modifie : sa forme ne permet pas une retouche sure.")
        print(f"A ajouter toi-meme dans [{table}] :")
        for cle in cles:
            print(f"    {cle} = true")
        return None

    try:
        base.ecrire_fichier_du_projet(fichier, texte)
    except OSError as erreur:
        print(f"\n{fichier.name} n'a PAS ete modifie : {erreur}")
        return None
    return chemins.relatif(fichier)


def _oui(question: str) -> bool:
    """Une question fermée. Sans terminal pour répondre, c'est non."""
    try:
        return input(question).strip().lower() in ("o", "oui", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _installer_pip(a_installer: list[dict], sans_demander: bool) -> bool:
    """Installe ces paquets DANS le venv du projet. Rend True si tout est posé.

    ⚠️ POURQUOI PAS DE SIMPLES `dependencies` DANS pyproject.toml : ces outils
    doivent tourner dans le venv du PROJET AUDITÉ. Déclarés comme dépendances
    de Lintorn, ils s'installeraient dans le venv de Lintorn — invisibles pour
    `config.PYTHON`, et pytest n'y verrait aucune dépendance du projet.

    On installe donc là où ça compte, et jamais sans demander : ajouter des
    paquets au venv de quelqu'un est une modification de son environnement.
    """
    if config.VENV_PROJET is None:
        print("\nAucun venv de projet : Lintorn refuse d'installer dans le python courant.")
        print("Cree un venv dans le projet (ou declare le tien : `venv = ...` dans la")
        print("config), puis relance.")
        return False

    print(f"\nA installer dans le venv du projet ({chemins.relatif(Path(str(config.PYTHON)))}) :")
    for outil in a_installer:
        print(f"    {outil['pip']:<12} {outil['role']}")

    # Le contrôle « Dependances vs venv » ne les compte pas, ni ce qu'ils
    # tirent : il les nomme à part. Comptés, ils faisaient refuser le premier
    # push de qui venait de suivre le README.
    print("\nCe sont des outils d'audit : le controle Dependances vs venv ne les")
    print("compte pas dans tes dependances (il les nomme a part dans le rapport).")

    if not sans_demander and not _oui("\nInstaller maintenant ? [o/N] "):
        print("Rien n'a ete installe.")
        return False

    print()
    tout_pose = True
    for outil in a_installer:
        resultat = subprocess.run(
            [config.PYTHON, "-m", "pip", "install", outil["pip"]],
            capture_output=True, text=True, check=False,
        )
        if resultat.returncode == 0:
            outil["present"] = True
            print(f"  OK    {outil['pip']}")
        else:
            tout_pose = False
            print(f"  ECHEC {outil['pip']}")
            derniere = (resultat.stderr or "").strip().splitlines()
            if derniere:
                print(f"        {derniere[-1][:120]}")
    return tout_pose


def _refus_du_venv() -> str | None:
    """Pourquoi Lintorn ne sondera pas le venv du projet. None : il peut, ou il n'y en a pas.

    Sonder les modules, c'est LANCER le python du projet : mêmes gardes que
    pour ruff ou pytest (exécutable suivi par git, accord de l'utilisateur).
    """
    if not config.PY_RACINE or config.VENV_PROJET is None:
        return None
    entree = {"cle": "venv_projet", "titre": "Sonder et equiper le venv du projet",
              "cmd": [config.PYTHON, "-m", "pip"], "cwd": config.RACINE}
    refus = noyau.refus_sans_lancer(entree, rapide=False)
    if refus is not None:
        return refus.resume
    permises, motif = confiance.accordes([entree])
    return None if confiance.identite(entree) in permises else motif


def installer_outils(sans_demander: bool = False) -> int:
    """Équipe le projet : installe et active ce que SON code appelle."""
    refus = _refus_du_venv()
    if refus:
        print(f"Echec : rien n'est lance - {refus}")
        return 1
    outils = _outillage_du_projet()
    if not outils:
        print("Aucun langage que Lintorn sache outiller ici (Python, Django, JS,")
        print("ni aucun fichier de verrou que lise OSV-Scanner).")
        print("Rien a installer : ses controles de doc, de memoire et de regles")
        print("tournent sans aucun outil externe.")
        return 0

    print("Ce qui s'applique a ce projet :\n")
    for outil in outils:
        etat = ("MANQUANT" if not outil["present"]
                else "fourni" if outil["fourni"] else "installe")
        if outil["cle"] is None:
            activation = "toujours actif"
        else:
            activation = "actif" if outil["actif"] else f"inactif ({outil['cle']})"
        print(f"    {outil['ecosysteme']:<7} {outil['nom']:<17} {etat:<9} "
              f"{activation:<26} {outil['role']}")

    front = config.FRONTEND
    if front and not (front / config.VERROU_NPM).is_file():
        commande, _ = config.installation_js(front)
        if commande == "npm install":
            print(f"\n    JS : pas de {config.VERROU_NPM} dans {chemins.relatif(front)} - npm audit")
            print("    n'aurait rien a lire. `npm install` le cree ; il se versionne.")
        else:
            # ⚠️ Surtout pas « npm install le cree » : sur un projet yarn ou
            # pnpm, ce conseil posait un second verrou à côté du vrai.
            print(f"\n    JS : {chemins.relatif(front)} est gere par {commande.split()[0]}, dont "
                  "npm audit ne lit pas")
            print("    le verrou. Ses failles relevent d'osv-scanner (failles_osv).")

    en_ordre = True
    a_installer = [outil for outil in outils if not outil["present"] and outil["pip"]]
    if a_installer:
        en_ordre = _installer_pip(a_installer, sans_demander)

    for outil in outils:
        if not outil["present"] and outil["sinon"]:
            en_ordre = False
            print(f"\n{outil['nom']} : absent, et Lintorn ne l'installe pas lui-meme.")
            print(f"    {outil['sinon']}")

    # On ne propose d'activer que ce qui peut TOURNER : un contrôle activé sur
    # un outil absent passerait directement en « INDISPONIBLE ».
    proposables = [outil for outil in outils
                   if outil["cle"] and not outil["actif"] and outil["present"]]
    acceptees = [outil["cle"] for outil in proposables
                 if _oui(f"\nActiver {outil['nom']} ({outil['role']}) ? [o/N] ")]
    if acceptees:
        ecrit = _activer(acceptees)
        if ecrit is None:
            return 1
        print(f"\nActive dans {ecrit} : {', '.join(acceptees)}")
    elif not proposables and en_ordre:
        print("\nTout ce qui s'applique ici est installe et actif. Rien a faire.")

    return 0 if en_ordre else 1
