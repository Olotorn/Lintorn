# Lintorn
"""Le projet audité : sa racine, git, ce qui est ignoré, les fichiers suivis."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .. import config

# Dossiers qu'on ne parcourt jamais (volumineux ou générés).
# Déclaré en premier : la découverte ci-dessous s'en sert pour ne pas y plonger.
# ⚠️ Ces noms ne se testent JAMAIS sur un chemin absolu : un projet rangé sous
# un dossier `build/` — ce que fait aussi bien un développeur qu'une CI qui
# clone dans `build/<depot>` — se disqualifiait tout entier : contrôles Django
# disparus du rapport, documentation déclarée menteuse sur des fichiers qui
# existent. Toujours `sous_ignores()`.
# `vendor` : les dépendances recopiées DANS le dépôt (Go, PHP, Ruby, un
# typeshed embarqué). C'est le code et la doc des AUTRES, souvent commités.
IGNORES = {"node_modules", "venv", ".venv", ".git", "__pycache__",
           "dist", "build", ".vite", ".tox", "site-packages", ".mypy_cache",
           "vendor"}


def _racine_projet() -> Path:
    """Le dépôt à auditer : on remonte du dossier courant jusqu'au `.git`.

    Sans dépôt git au-dessus, on garde le dossier courant : Lintorn doit
    pouvoir servir sur un dossier non versionné (le contrôle du hook git se
    déclarera simplement indisponible, ce qui est la vérité).

    `LINTORN_RACINE` force la valeur — indispensable pour les tests, et utile
    en CI ou dans un monorepo.
    """
    force = os.environ.get("LINTORN_RACINE", "").strip()
    if force:
        forcee = Path(force).expanduser().resolve()
        if forcee.is_dir():
            return forcee
        # ⚠️ Un dossier qui n'existe pas ne produit pas une erreur claire : git
        # lancé là échoue comme s'il n'était pas installé (« git introuvable
        # sur cette machine », faux), et Lintorn créait une arborescence
        # `.lintorn/` au fond d'un chemin fautif.
        config._SOUCIS_PRECOCES.append(
            f"LINTORN_RACINE ne designe aucun dossier ({forcee.name}) - "
            "Lintorn audite le dossier courant a la place")

    depart = Path.cwd().resolve()
    for candidat in (depart, *depart.parents):
        if (candidat / ".git").exists():
            return candidat
    return depart


def git(*arguments: str, cwd: Path | None = None, timeout: float = 10,
        entree: str | None = None) -> subprocess.CompletedProcess:
    """Lance git et lit sa réponse COMME PYTHON LIT LES CHEMINS.

    ⚠️ C'EST LE SEUL ENDROIT QUI APPELLE GIT. git rend des chemins, et un
    chemin lu par git doit être identique au même chemin lu par Python — sinon
    Lintorn ne reconnaît plus son propre dépôt.

    `text=True` lisait git avec l'encodage de la LANGUE de la machine. Sous
    Windows, c'est cp1252 alors que les chemins sont en UTF-8 : un dossier
    « essai é » revenait « essai Ã© », et un hook qui contrôlait très bien
    chaque push était déclaré « NON BRANCHE ». Trouvé sous Windows 11.

    ⚠️ Et PAS « UTF-8 partout » : sous Linux, les chemins se lisent dans
    l'encodage de la machine, même quand ce n'est pas UTF-8. Forcer UTF-8
    recréait là-bas le décalage qu'on supprimait ici. La seule règle qui tient
    sur tous les systèmes : l'encodage du système de fichiers.

    `core.quotePath=false` : sans lui, git écrit `caf\303\251.py` au lieu
    de `café.py` dans ses listes — un nom qui ne désigne aucun fichier. Vrai
    sous Linux aussi.

    `core.fsmonitor=false` : git LANCE la commande que ce réglage désigne, et
    `.git/config` fait partie d'un dépôt livré en archive. Sans lui, un dépôt
    piégé exécutait son script au premier `git ls-files` de Lintorn — avant
    tout accord, avant même la première question.

    Ne lève JAMAIS sur un code de sortie : c'est souvent la donnée qu'on
    cherche (`git config --get` sort en 1 quand la clé manque). Lève OSError
    (git absent, dossier inexistant) et TimeoutExpired, comme `subprocess`.
    """
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", "-c", "core.fsmonitor=false", *arguments],
        cwd=cwd or config.RACINE, capture_output=True,
        encoding=sys.getfilesystemencoding(), errors="replace",
        input=entree, timeout=timeout, check=False,
    )


def _sous_git() -> bool | None:
    """Le projet audité est-il dans un dépôt git ?

    True = oui · False = non · None = git introuvable sur cette machine.

    La question est posée A GIT, une seule fois. Chercher un `.git` à la main
    se trompe sur les worktrees (où `.git` est un fichier) et sur un
    `LINTORN_RACINE` pointant dans un sous-dossier de dépôt.

    ⚠️ Le troisième état n'est pas un luxe : sans lui, un git absent et un
    dossier non versionné rendaient la même réponse, et les contrôles
    annonçaient « pas de depot git » à quelqu'un qui en a un.
    """
    try:
        sortie = config.git("rev-parse", "--is-inside-work-tree")
    except FileNotFoundError:
        return None
    except (OSError, subprocess.SubprocessError):
        return None
    return sortie.stdout.strip() == "true"


def sous_ignores(chemin: Path) -> bool:
    """`chemin` traverse-t-il un dossier ignoré, DEPUIS la racine du projet ?

    Hors du projet, la question n'a pas de sens : le dossier qui contient le
    dépôt ne se choisit pas. Répondre sur le chemin absolu revenait à laisser
    le nom du dossier parent éteindre des contrôles.
    """
    try:
        relatif = chemin.relative_to(config.RACINE)
    except ValueError:
        return False
    return bool(set(relatif.parts) & config.IGNORES)


def _fichiers_du_projet() -> list[Path]:
    """Les fichiers du projet : suivis par git, ou nouveaux mais pas ignorés.

    `git ls-files` plutôt qu'un parcours du disque : il sait déjà ce que le
    `.gitignore` écarte, et il ne descend jamais dans node_modules. Sans dépôt,
    un parcours qui ne descend pas dans les dossiers de IGNORES.
    """
    if config.SOUS_GIT:
        try:
            sortie = config.git("ls-files", "-z", "--cached", "--others", "--exclude-standard",
                         timeout=30)
        except (OSError, subprocess.SubprocessError):
            sortie = None
        if sortie is not None and sortie.returncode == 0:
            noms = sortie.stdout.split("\0")
            return [config.RACINE / nom for nom in noms if nom]
    trouves = []
    for dossier, sous_dossiers, fichiers in os.walk(config.RACINE):
        sous_dossiers[:] = [nom for nom in sous_dossiers if nom not in config.IGNORES]
        trouves += [Path(dossier) / nom for nom in fichiers]
    return trouves


def suivi_par_git(chemin: Path) -> bool:
    """`chemin` est-il SUIVI par git (commité ou indexé) ?

    ⚠️ LE GARDE-FOU DU PREMIER CONTACT. Un vrai venv, un vrai `node_modules`,
    ne sont JAMAIS commités : ils sont toujours gitignorés. Un interpréteur ou
    un outil que git suit n'est donc pas un environnement, c'est une charge
    utile livrée par le dépôt — et qui descend avec le `git clone` d'un projet
    inconnu. Lintorn refuse de la lancer avant tout accord.

    Hors dépôt (`SOUS_GIT` faux), on ne peut pas trancher : on ne refuse pas,
    faute de savoir. Le vecteur réel — cloner un dépôt inconnu — passe par des
    fichiers suivis, et c'est ceux-là qu'on arrête.
    """
    if not config.SOUS_GIT:
        return False
    try:
        relatif = chemin.resolve().relative_to(config.RACINE.resolve()).as_posix()
    except (ValueError, OSError):
        return False
    try:
        sortie = config.git("ls-files", "--error-unmatch", "--", relatif)
    except (OSError, subprocess.SubprocessError):
        return False
    return sortie.returncode == 0


def _sommet_git() -> Path | None:
    """La racine du DÉPÔT — au-dessus du projet audité, sur un monorepo."""
    if not config.SOUS_GIT:
        return None
    try:
        sortie = config.git("rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError):
        return None
    sommet = sortie.stdout.strip()
    return Path(sommet) if sommet else None


def _hooks_pour_git() -> str:
    """`core.hooksPath` tel que GIT le comprendra.

    ⚠️ git résout un chemin relatif depuis le SOMMET du dépôt, pas depuis le
    projet audité. Sur un monorepo (`LINTORN_RACINE=.../api`), poser
    `.lintorn/hooks` faisait chercher `<depot>/.lintorn/hooks`, qui n'existe
    pas : git ne lançait aucun hook, sans un mot, et le contrôle affichait
    « branche et executable » puisque la chaîne posée était bien celle
    attendue. Le garde-fou était mort et se déclarait vivant.
    """
    if config.SOMMET_GIT is None:
        return config.HOOKS_ATTENDU
    relatif = os.path.relpath(config.HOOKS, config.SOMMET_GIT).replace("\\", "/")
    # Hors du dépôt (racine forcée ailleurs) : un chemin absolu, que git
    # accepte aussi, plutôt qu'un `../..` qu'il résoudrait autrement.
    return relatif if not relatif.startswith("..") else str(config.HOOKS)


# Un fichier écarté par `.gitignore` ne part pas sur le dépôt : brouillon,
# note personnelle, sortie d'outil. L'auditer revient à reprocher à quelqu'un
# le contenu de ses papiers de bureau — et ça ARRIVE : une note de reprise
# citant un fichier « à créer un jour » a suffi à rendre l'audit rouge, donc
# à bloquer un push.
#
# ⚠️ `git check-ignore` consulte l'index PAR DÉFAUT, et c'est exactement ce
# qu'on veut : un fichier déjà SUIVI reste dans le périmètre, même si une
# règle `.gitignore` le vise. C'est la subtilité de git elle-même — une règle
# n'a aucun effet sur un fichier déjà commité. On hérite de la bonne
# sémantique au lieu de la réimplémenter de travers.
def _ignores_par_git(chemins: list[Path]) -> set[str]:
    """Ceux de `chemins` que git ignore. Ensemble vide si git ne répond pas.

    Hors dépôt, rien n'est exclu : c'est le sens le moins dangereux (on audite
    plus, pas moins). `controle_hook_git()` annonce que ce filtre est inactif.
    """
    if not chemins or not config.SOUS_GIT:
        return set()
    try:
        sortie = config.git("check-ignore", "-z", "--stdin", timeout=15,
                     entree="\0".join(str(chemin) for chemin in chemins))
    except (OSError, subprocess.SubprocessError):
        return set()

    # 0 = au moins un ignoré · 1 = aucun · 128 = pas un dépôt git.
    # Sur tout le reste on n'exclut RIEN : un contrôle de trop se voit et se
    # corrige, un fichier qui sort de l'audit en silence ne se voit jamais.
    if sortie.returncode not in (0, 1):
        return set()

    trouves = sortie.stdout.split("\0")
    return {chemin for chemin in trouves if chemin}


def hors_gitignore(chemins: list[Path]) -> list[Path]:
    """`chemins`, privé de ce que git ignore. L'ordre d'entrée est conservé."""
    ignores = config._ignores_par_git(chemins)
    return [chemin for chemin in chemins if str(chemin) not in ignores]


def motifs_gitignore(chemins: list[str]) -> dict[str, str]:
    """{chemin: motif qui l'ignore} pour ceux de `chemins` que git ignore.

    Les chemins sont relatifs à RACINE et n'ont pas besoin d'exister : c'est
    ce qui permet de dire qu'un fichier CITÉ par la doc est local par
    construction. Même sens d'échec que `_ignores_par_git` : si git ne
    répond pas, rien n'est déclaré ignoré — le chemin reste vérifié.
    """
    if not chemins or not config.SOUS_GIT:
        return {}
    try:
        sortie = config.git("check-ignore", "-v", "-z", "--stdin", timeout=30,
                     entree="\0".join(chemins))
    except (OSError, subprocess.SubprocessError):
        return {}
    if sortie.returncode not in (0, 1):
        return {}
    # Par quatre : source, ligne, motif, chemin. Un motif en `!` a été
    # rencontré mais il RÉ-INCLUT le chemin : ce n'est pas un ignoré.
    champs = sortie.stdout.split("\0")
    return {champs[i + 3]: champs[i + 2] for i in range(0, len(champs) - 3, 4)
            if not champs[i + 2].startswith("!")}
