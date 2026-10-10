# Lintorn
"""Le hook pre-push est-il branché, exécutable, et à jour ?"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ... import config
from ...base import Resultat


def controle_hook_git() -> Resultat:
    """Le hook pre-push est-il RÉELLEMENT branché sur ce clone ?

    LA FAILLE : `core.hooksPath` vit dans `.git/config`, un fichier que git ne
    versionne PAS — et la copie du hook, dans `.lintorn/hooks/`, est écartée
    par le `.gitignore` de Lintorn. Sur un clone frais (autre PC, Codespaces,
    collègue), git regarde dans `.git/hooks/`, n'y trouve rien, ne dit rien,
    et le push part sans le moindre contrôle.

    C'est exactement le scénario que Lintorn traite partout ailleurs comme le plus
    grave : un garde-fou qui ne garde plus rien tout en paraissant sain.

    NON BLOQUANT exprès : quand le réglage manque, le hook ne tourne pas —
    bloquer un push serait donc de toute façon impossible. Ce contrôle sert aux
    lancements À LA MAIN, le seul moment où l'on peut encore s'en apercevoir.
    """
    titre = "Hook pre-push (Lintorn)"

    # Hors dépôt, ce contrôle n'a pas d'objet : il n'y a pas de push. Il
    # affichait pourtant « NON BRANCHE - `git push` ne controle RIEN », un
    # ROUGE impossible à corriger — et la commande qu'il proposait échouait.
    # Un rouge qu'on ne peut pas éteindre apprend à ignorer les rouges.
    if config.SOUS_GIT is None:
        return Resultat(titre, "INDISPONIBLE",
                        "git introuvable sur cette machine", bloquant=False)

    if not config.SOUS_GIT:
        return Resultat(
            titre, "INDISPONIBLE",
            "pas de depot git ici - aucun push a controler",
            "Ce dossier n'est pas versionne. **Trois controles sont donc sans "
            "objet**, et leur silence ne veut pas dire que tout va bien :\n\n"
            "- le **hook pre-push** : il n'y a pas de `git push` a intercepter ;\n"
            "- la **fraicheur des memoires** : elle se mesure en commits ;\n"
            "- le **perimetre `.gitignore`** : rien n'est exclu de l'audit.\n\n"
            "Les autres controles, eux, tournent normalement.",
            bloquant=False, detail_markdown=True,
        )

    try:
        # `git config --get` sort en 1 quand la clé est absente — précisément
        # le cas qu'on cherche. `config.git` ne lève jamais sur un code.
        sortie = config.git("config", "--get", "core.hooksPath")
    except (OSError, subprocess.SubprocessError) as erreur:
        return Resultat(titre, "ERREUR", f"git injoignable : {erreur}", bloquant=False)

    actuel = sortie.stdout.strip().replace("\\", "/")
    branche = _meme_dossier(actuel, config.HOOKS_POUR_GIT)
    # ⚠️ L'ABSENCE DU FICHIER SE JUGE APRÈS le réglage git, jamais avant.
    # Testée en premier, elle rendait « hook pas encore installe » — un gris
    # rassurant, réservé au premier lancement — pour un hook INSTALLÉ PUIS
    # DISPARU. Or il est ignoré par git (`.lintorn/.gitignore`), donc un
    # `git clean -fdX` l'efface : le garde-fou meurt, git ne dit rien, et le
    # push part sans audit derrière un message qui dit « pas encore ».
    present = (config.HOOKS / "pre-push").is_file()

    if branche and present:
        return _controle_hook_executable(titre)

    if branche:
        return Resultat(
            titre, "ALERTE",
            "BRANCHE MAIS ABSENT - `git push` ne controle RIEN",
            "`core.hooksPath` pointe bien sur `" + config.HOOKS_POUR_GIT + "`, mais le "
            "fichier `pre-push` n'y est plus (ou n'est pas lisible). git cherche "
            "un hook, n'en trouve aucun, et laisse passer le push **sans un "
            "message**.\n\n"
            "Le hook est un fichier local, ignore par git : `git clean -fdX` "
            "(nettoyage des fichiers ignores) l'efface. Pour le reposer :\n\n"
            "```bash\nlintorn hook\n```",
            bloquant=False, detail_markdown=True,
        )

    if not present:
        # ⚠️ « a disparu » etait le PREMIER message vu par un nouvel
        # utilisateur, et il etait faux : le hook n'avait jamais ete installe.
        # Un outil qui accuse au premier lancement perd la confiance qu'il
        # lui faut pour etre cru la fois d'apres.
        return Resultat(
            titre, "INDISPONIBLE",
            "hook pas encore installe - `lintorn hook`",
            "Sans le hook, `git push` ne lance aucun controle — et sans le "
            "moindre message. Une seule commande, une fois par clone :\n\n"
            "```bash\nlintorn hook\n```",
            bloquant=False,
            detail_markdown=True,
        )

    etat = "non configure" if not actuel else f"pointe ailleurs ({actuel})"
    return Resultat(
        titre, "ALERTE",
        f"NON BRANCHE ({etat}) - `git push` ne controle RIEN",
        "`core.hooksPath` vit dans `.git/config`, un fichier que git **ne "
        "versionne pas** : il ne suit donc pas les clones. Tant qu'il n'est "
        "pas posé, `git push` n'exécute aucun contrôle — sans le moindre "
        "message d'avertissement.\n\n"
        "Pour le brancher (une seule fois par clone, depuis la racine) :\n\n"
        "```bash\n"
        f"git config core.hooksPath {config.HOOKS_POUR_GIT}\n"
        "```\n\n"
        "ou, strictement équivalent : `lintorn hook`",
        bloquant=False,
        detail_markdown=True,
    )


def _meme_dossier(configure: str, attendu: str) -> bool:
    """Deux ecritures du meme dossier de hooks designent-elles le meme endroit ?

    ⚠️ Comparer les CHAINES rendait un rouge permanent — « NON BRANCHE, git
    push ne controle RIEN » — a qui avait pose un chemin absolu, pourtant
    valide et parfaitement fonctionnel. Un rouge qu'aucune commande n'eteint
    apprend a ignorer les rouges.
    """
    if not configure:
        return False
    if configure == attendu:
        return True
    # git resout un chemin relatif depuis le sommet du depot.
    depuis = config.SOMMET_GIT or config.RACINE
    try:
        return (depuis / configure).resolve() == (depuis / attendu).resolve()
    except OSError:
        return False


def _controle_hook_executable(titre: str) -> Resultat:
    """`core.hooksPath` est bon — reste à savoir si git a le DROIT de lancer.

    LA PANNE : git refuse d'exécuter un hook qui n'a pas le bit exécutable,
    et il le fait EN SILENCE — pas de message, pas d'erreur, le
    push part simplement sans contrôle. Le hook avait été créé sous Windows, où
    ce bit n'existe pas (`core.filemode=false`, Git Bash lance tout) ; il est
    donc parti dans le dépôt en 100644. Tant que le projet est resté sous
    Windows, personne n'a rien vu. Au passage sous Linux, le hook est mort ce
    jour-là — et Lintorn affichait toujours `[ OK ] branche`.

    C'était donc le pire cas possible : pas un rouge, pas même un `[ERR!]`, mais
    un VERT sur un garde-fou mort. Plusieurs jours de push en confiance.

    DEUX vérifications, parce que ce sont deux pannes différentes :
      * le bit sur le DISQUE   -> décide si git lance le hook ICI, maintenant
      * le mode dans l'INDEX   -> décide s'il le lancera sur TOUS les clones
    Réparer l'un sans l'autre laisse la moitié du problème en place : un
    `chmod` seul se perd au prochain clone, un mode git seul ne débloque pas la
    machine courante tant que le fichier n'est pas ressorti du dépôt.
    """
    chemin = config.HOOKS / "pre-push"
    fautes: list[str] = []

    # 0. LE CONTENU. git doit LIRE le script pour l'exécuter, et l'interpréteur
    #    du shebang doit exister : `#!/bin/sh\r` (fins de ligne Windows) n'en
    #    est pas un. Les deux échouent sur un `fatal: cannot exec` que rien ne
    #    relie au hook, et le contrôle annonçait « branche et executable ».
    try:
        installe = chemin.read_bytes()
    except OSError:
        installe = None
        fautes.append("illisible (droits) : git ne peut pas lire le script")
    # N'IMPORTE OU dans le fichier, et pas seulement en fin de ligne : `sh`
    # lit le `\r` comme un caractere de la commande (`$'\r': commande
    # introuvable`). Ne regarder que le shebang laissait passer un fichier aux
    # fins de ligne melangees — annonce « PERIME » alors qu'il etait mort.
    if installe is not None and b"\r" in installe:
        fautes.append("retour chariot (CR) : `sh` ne sait pas lire ce script")

    # 1. LE DISQUE. Sauté sous Windows : NTFS n'a pas de bit exécutable, et
    #    `os.access(X_OK)` y répond n'importe quoi. Là-bas, Git Bash lance le
    #    hook quel que soit le mode — le seul vrai risque est le mode git.
    if os.name != "nt" and not os.access(chemin, os.X_OK):
        fautes.append("pas executable sur le disque")

    # 2. L'INDEX GIT. Le mode voyage avec le dépôt : c'est lui qui décide du
    #    sort de Codespaces et de toute machine future.
    mode = _mode_git(chemin)
    if mode is not None and not mode.endswith("755"):
        fautes.append(f"enregistre en {mode} dans git (attendu 100755)")

    if not fautes:
        return _controle_hook_a_jour(titre, installe)

    return Resultat(
        titre, "ALERTE",
        f"BRANCHE MAIS MUET - {' + '.join(fautes)}",
        "`core.hooksPath` est bien posé, mais **git n'exécutera pas** ce "
        "fichier : il refuse tout hook dépourvu du bit exécutable, et il le "
        "fait **sans le moindre message**. `git push` repart donc sans aucun "
        "contrôle, avec un voyant au vert.\n\n"
        "Les deux lignes de la réparation (les deux sont nécessaires) :\n\n"
        "```bash\n"
        f"chmod +x {config.HOOKS_ATTENDU}/pre-push\n"
        f"git add {config.HOOKS_ATTENDU}/pre-push\n"
        "```\n\n"
        "`chmod` débloque **cette machine**, `git add` enregistre le mode "
        "`100755` dans le dépôt pour **tous les clones à venir**. Sous Windows, "
        "où `chmod` n'a pas d'effet, la seconde ligne devient "
        f"`git update-index --chmod=+x {config.HOOKS_ATTENDU}/pre-push`.\n\n"
        "Si c'est le CONTENU qui est en cause (illisible, fins de ligne "
        "Windows), `lintorn hook` repose une copie saine.",
        bloquant=False,
        detail_markdown=True,
    )


def _controle_hook_a_jour(titre: str, installe: bytes) -> Resultat:
    """Branché, exécutable — mais est-ce le hook de CETTE version de Lintorn ?

    LA PANNE : le hook posé dans le projet est une COPIE, figée le jour de
    `--installer-hook`. `pip install -U lintorn` met à jour le paquet, jamais
    elle : un correctif du hook n'atteignait donc aucun projet déjà équipé.
    Vécu : l'ancien hook passait les fichiers poussés sans séparateur `--`.
    Un fichier SUPPRIMÉ nommé `--help` y redevenait l'option, l'aide
    s'affichait, et le push partait sans audit.

    VERIF et non ALERTE : un hook périmé contrôle encore presque tout. Mais
    le dire ici est le seul chemin par lequel le correctif arrive jusqu'au
    projet.
    """
    # ⚠️ Comparaison OCTET POUR OCTET. Neutraliser les CRLF « pour tolérer un
    # checkout Windows » rendait vert un hook que git ne peut pas exécuter ;
    # c'est `_controle_hook_executable` qui les refuse, juste avant.
    try:
        livre = (config.HOOKS_SOURCE / "pre-push").read_bytes()
    except OSError as erreur:
        return Resultat(titre, "VERIF",
                        f"hook livre illisible ({erreur.strerror}) - "
                        "impossible de dire si la copie est a jour",
                        bloquant=False)

    if installe == livre:
        return Resultat(titre, "OK", "branche et executable - Lintorn tournera avant chaque push")

    return Resultat(
        titre, "VERIF",
        "branche mais PERIME - `lintorn hook`",
        "Le hook posé dans ce projet n'est pas celui de la version de Lintorn "
        "installée. `pip install -U lintorn` met à jour le paquet, **jamais** "
        "la copie posée par `--installer-hook` : les correctifs du hook ne "
        "t'atteignent donc pas. Pour la remplacer :\n\n"
        "```bash\nlintorn hook\n```\n\n"
        "Un hook modifié à la main tombe aussi ici, et la commande écrasera "
        "tes modifications. Ce que tu veux lancer à chaque push a sa place "
        "dans `[[commandes]]` : le hook les exécute déjà, sauf celles marquées "
        "`lent`.",
        bloquant=False, detail_markdown=True,
    )


def _mode_git(chemin: Path) -> str | None:
    """Mode enregistré dans l'index git (`100644`, `100755`), ou None.

    None = question sans réponse fiable (git muet, fichier pas encore suivi) →
    l'appelant ne doit alors RIEN conclure. Un contrôle qui invente un verdict
    quand il n'a pas la donnée est exactement le défaut qu'on corrige ici.
    """
    try:
        # `relative_to` lève ValueError sur un chemin hors dépôt : c'est une
        # question sans réponse, pas une panne — donc None comme le reste.
        relatif = chemin.relative_to(config.RACINE).as_posix()
        sortie = config.git("ls-files", "-s", "--", relatif)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None

    premiere = sortie.stdout.strip().split("\n")[0] if sortie.stdout.strip() else ""
    return premiere.split()[0] if premiere else None
