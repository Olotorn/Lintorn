# Lintorn
"""L'accord de l'utilisateur : ce que Lintorn a le droit de LANCER dans un projet.

Lire ne demande rien : la doc, la mémoire IA, les règles sont des fichiers.
Lancer un programme, si — ruff, pytest, tsc, une commande du projet sont du
code qui s'exécute avec les droits de l'utilisateur, dans un dossier qu'il
n'a peut-être jamais lu.

  ▸ On demande UNE fois par projet et par chose NOUVELLE : un venv, un outil
    activé, une commande ajoutée. Ce qui a déjà été accordé ne se redemande pas.
  ▸ Le défaut est NON : `[o/N]`, et une touche de travers refuse.
  ▸ Sans terminal pour répondre (hook git, CI), c'est un refus ANNONCÉ, jamais
    un silence. `lintorn confiance` donne l'accord depuis un terminal.

⚠️ L'ACCORD VIT HORS DU PROJET (`~/.config/lintorn/`). Un accord écrit dans le
dépôt — `[tool.lintorn.controles] tests = true`, un `.lintorn/` commité — serait
celui de l'AUTEUR du dépôt, pas de l'utilisateur : le piège l'accorderait
lui-même. `opt_in` dit ce qui est possible ; ce module dit ce qui est permis.

Ce que l'accord vise : la commande et, si le programme est un fichier DU
projet, son contenu — comme celui d'un script du projet que la commande nomme
(`python3 outils/todo.py`). Pas tout ce que la commande lit ensuite : un
`git pull` qui change les tests ne redemande rien.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from . import chemins, config

# Pour un poste où l'on maîtrise le dépôt (CI, banc d'essai) : tout est accordé.
# Une variable d'environnement, parce qu'un dépôt ne peut pas en poser une.
VARIABLE_CI = "LINTORN_CONFIANCE"

SANS_TERMINAL = "aucun terminal pour demander - lancer `lintorn confiance` une fois"
REFUSE = "accord refuse - `lintorn confiance` pour l'accorder"


def fichier() -> Path:
    """Où l'accord est noté : dans la config de l'UTILISATEUR, jamais du projet."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "lintorn" / "confiance.json"


def _lire() -> dict:
    """Illisible ou absent = rien d'accordé : on redemande, on ne devine pas."""
    try:
        lu = json.loads(fichier().read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError):
        return {}
    return lu if isinstance(lu, dict) else {}


def _cle_projet() -> str:
    return str(config.RACINE.resolve())


def _accordes_ici() -> set[str]:
    brut = _lire().get(_cle_projet(), [])
    return {str(i) for i in brut} if isinstance(brut, list) else set()


def _empreinte(programme: Path) -> str:
    """Le contenu du programme, s'il vit DANS le projet ; sinon rien.

    Un `.venv/bin/python` qui est un lien vers le python du système n'est pas du
    code du projet : le chemin suffit. Un script ou une copie posés dans le
    dossier, si — et leur contenu peut changer sans que leur nom bouge.
    """
    try:
        reel = programme.resolve()
        reel.relative_to(config.RACINE.resolve())
        if not reel.is_file():
            return ""
        somme = hashlib.sha256()
        with reel.open("rb") as flux:
            for bloc in iter(lambda: flux.read(1 << 20), b""):
                somme.update(bloc)
        return somme.hexdigest()
    except (ValueError, OSError):
        return ""


def _fichiers_nommes(entree: dict) -> list[Path]:
    """Les fichiers DU projet qu'une commande du projet nomme en argument.

    ⚠️ Dans `python3 outils/todo.py`, le programme est `python3` : son empreinte
    ne dit rien. Le vrai code est `outils/todo.py`. Sans lui dans l'accord, un
    `git pull` qui réécrit le script le faisait tourner sans rien redemander.
    """
    if not entree.get("du_projet"):
        return []
    dossier = Path(str(entree["cwd"]))
    trouves = []
    for morceau in (str(morceau) for morceau in entree["cmd"][1:]):
        if morceau.startswith("-"):
            continue
        chemin = Path(morceau) if Path(morceau).is_absolute() else dossier / morceau
        try:
            if chemin.is_file() and chemin.resolve().is_relative_to(config.RACINE.resolve()):
                trouves.append(chemin)
        except (OSError, ValueError):
            continue
    return trouves


def identite(entree: dict) -> str:
    """Ce que l'accord désigne, pour une commande de `config.COMMANDES`.

    Un outil livré par Lintorn se reconnaît à sa clé et à son programme : quand
    Lintorn change ses options, rien ne se redemande. Une commande DU projet est
    entièrement écrite par le projet : sa ligne complète compte, sinon un
    `cmd` réécrit après coup garderait l'accord de l'ancien.
    """
    commande = [str(morceau) for morceau in entree["cmd"]]
    programme = Path(commande[0])
    if not programme.is_absolute() and ("/" in commande[0] or "\\" in commande[0]):
        programme = Path(str(entree["cwd"])) / programme
    morceaux = [entree["cle"], commande[0],
                _empreinte(programme) if programme.is_absolute() else ""]
    if entree.get("du_projet"):
        morceaux += [commande[1:], str(entree["cwd"]),
                     [[chemins.relatif(fichier), _empreinte(fichier)]
                      for fichier in _fichiers_nommes(entree)]]
    return json.dumps(morceaux, ensure_ascii=False)


def modifies(entree: dict) -> list[str]:
    """Ce qui a changé depuis l'accord donné à CETTE commande : le programme, ses scripts.

    Vide si la commande n'a jamais été accordée, ou si rien n'a changé. Sert à
    dire POURQUOI la question revient — « outils/todo.py modifié » se juge, une
    question sans raison s'accepte à l'aveugle.
    """
    actuelle = json.loads(identite(entree))
    changes: list[str] = []
    for brute in _accordes_ici():
        try:
            ancienne = json.loads(brute)
        except ValueError:
            continue
        if (not isinstance(ancienne, list) or len(ancienne) != len(actuelle)
                or ancienne[:2] != actuelle[:2] or ancienne[3:5] != actuelle[3:5]):
            continue
        if ancienne[2] != actuelle[2]:
            changes.append(chemins.relatif(Path(str(actuelle[1]))))
        if len(actuelle) > 5:
            try:
                avant = dict(ancienne[5])
            except (TypeError, ValueError):
                avant = {}
            changes += [nom for nom, somme in actuelle[5] if avant.get(nom) != somme]
    return sorted(set(changes))


def nouveaux(entrees: list[dict]) -> list[dict]:
    """Ce qui n'a JAMAIS été accordé dans ce projet."""
    deja = _accordes_ici()
    return [entree for entree in entrees if identite(entree) not in deja]


def enregistrer(entrees: list[dict]) -> str | None:
    """Note l'accord. Rend None si c'est fait, sinon pourquoi ça ne l'est pas."""
    tout = _lire()
    liste = tout.get(_cle_projet(), [])
    liste = list(liste) if isinstance(liste, list) else []
    liste += [i for i in map(identite, entrees) if i not in liste]
    tout[_cle_projet()] = liste
    return _ecrire(tout)


def retirer() -> tuple[int, str | None]:
    """Retire tout ce qui a été accordé à CE projet : (combien, pourquoi ça n'a pas pu se faire).

    Les autres projets gardent leur accord. La prochaine commande à lancer
    redemandera, comme la première fois.
    """
    tout = _lire()
    retire = tout.pop(_cle_projet(), None)
    if retire is None:
        return 0, None
    return (len(retire) if isinstance(retire, list) else 1), _ecrire(tout)


def _ecrire(tout: dict) -> str | None:
    cible = fichier()
    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
        # Écriture atomique : un accord à moitié écrit serait illisible, donc oublié.
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=cible.parent, delete=False, suffix=".tmp") as temp:
            json.dump(tout, temp, indent=2, ensure_ascii=False)
        os.replace(temp.name, cible)
    except (OSError, RuntimeError) as erreur:
        return str(erreur)
    return None


def terminal() -> bool:
    """Y a-t-il quelqu'un pour répondre ? Le hook git, lui, lit ses fichiers sur stdin."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _montrer(entree: dict) -> str:
    commande = [str(morceau) for morceau in entree["cmd"]]
    programme = Path(commande[0])
    if programme.is_absolute():
        commande[0] = chemins.relatif(programme)
    ligne = " ".join(commande)
    return ligne if len(ligne) <= 90 else ligne[:87] + "..."


def demander(entrees: list[dict]) -> bool:
    """La question. Tout ce qui n'est pas un oui franc est un non."""
    print(f"\nLintorn a besoin de ton accord pour lancer ceci dans ce projet "
          f"(dossier \"{config.RACINE.name}\") :\n")
    for entree in entrees:
        print(f"  {entree['titre']}")
        print(f"      {_montrer(entree)}")
        changes = modifies(entree)
        if changes:
            print(f"      !! modifie depuis ton accord : {', '.join(changes)}")
    print(
        "\nCe sont des programmes de CE dossier, ou lances avec son environnement :\n"
        "ils s'executent avec tes droits. Si le dossier vient d'ailleurs et que tu\n"
        "ne l'as pas lu, refuse. Lire la doc et la memoire IA, lui, ne lance rien.\n"
        f"(Accord note dans {fichier()} - hors du projet.)")
    try:
        reponse = input("\nLintorn peut-il les lancer ? [o/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return reponse in ("y", "yes", "o", "oui")


def accordes(entrees: list[dict]) -> tuple[set[str], str]:
    """(identités qui peuvent tourner, motif du refus pour les autres).

    Une seule question pour tout ce qui est nouveau, posée AVANT que la
    première commande parte.
    """
    ids = {identite(entree) for entree in entrees}
    if os.environ.get(VARIABLE_CI, "").strip().lower() in ("oui", "1", "true"):
        return ids, ""
    a_demander = nouveaux(entrees)
    if not a_demander:
        return ids, ""
    connus = ids - {identite(entree) for entree in a_demander}
    if not terminal():
        return connus, SANS_TERMINAL
    if not demander(a_demander):
        return connus, REFUSE
    souci = enregistrer(a_demander)
    if souci:
        print(f"Accord valable pour cette fois seulement, il n'a pas pu etre note : {souci}")
    return ids, ""
