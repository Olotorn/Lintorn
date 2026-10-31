# Lintorn
"""Fraîcheur de la mémoire : le code qu'une fiche cite a-t-il bougé depuis qu'elle a été vérifiée ?"""

from __future__ import annotations

import datetime
import os
import re
import subprocess

from ... import config
from ...base import Resultat
from . import chemins_cites, memoire_ia

# « Memoire IA vs code » répond à : les chemins cités existent-ils ?
# Celui-ci répond à : ce que la mémoire raconte de ces fichiers est-il encore
# d'actualité ? Les deux sont indépendants — une mémoire peut n'avoir aucun
# chemin casse et affirmer malgré tout le contraire du code.
#
# LE PRINCIPE : une date saisie à la main ment dès qu'on oublie de la changer.
# Git, lui, n'oublie rien. On ne demande donc à l'humain qu'UNE chose — la date
# de sa dernière vérification — et c'est git qui dit si elle a péri.
#
# L'heure est facultative : `verifie_le: 2026-10-02 14:30`. ⚠️ Une date seule
# vaut le DÉBUT de la journée. git, lui, lisait `--since=2026-10-02` comme « ce
# jour à l'heure qu'il est » : la même fiche était suspecte le matin et
# fraîche le soir. Toute la journée compte : un doute de trop plutôt qu'un
# commit manqué, et l'heure écrite le lève.
_RX_VERIFIE_LE = re.compile(
    r"^\s*verifie_le\s*:\s*(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2})?))?\s*$", re.M)


def _pathspecs_cites(texte: str) -> list[str]:
    """Les chemins cités par un document, traduits en **pathspecs git**.



    ⚠️ Le nom nu est le cas **majoritaire** en mémoire : on y écrit « le
     `NOM DU FICHIER` », jamais son chemin complet. Une première
    version ne résolvait que les chemins complets — elle trouvait 0 fichier
    sur `nom_du_fichier.md`, donc 0 commit, donc un contrôle qui
    serait resté VERT à jamais. Trouvé par son propre test :
    le pire des bugs, celui qui ne fait rien de visible.
    """
    texte = re.sub(r"```.*?```", "", texte, flags=re.DOTALL)
    specs: set[str] = set()

    for token in re.findall(r"`([^`\n]+)`", texte):
        token = token.strip().rstrip("/").removeprefix("./")
        if not chemins_cites.est_un_chemin(token):
            continue
        token = re.sub(r":\d+(-\d+)?$", "", token)

        if "/" in token:
            for racine in config.RACINES_RESOLUTION:
                cible = racine / token
                if cible.exists():
                    try:
                        specs.add(cible.resolve().relative_to(config.RACINE).as_posix())
                    except ValueError:
                        pass      # hors dépôt : git n'a rien à en dire
                    break
        elif token.endswith(config.EXTENSIONS):
            # git retrouvera le fichier où qu'il soit rangé dans le dépôt
            specs.add(f":(glob)**/{token}")

    return sorted(specs)


# Séparateur de commits dans la sortie de `git log`.
#
# ⚠️ DEUX pièges, tous deux silencieux :
#   1. PAS un caractère nul : Windows refuse un octet 0 dans un argument de
#      processus (`ValueError: embedded null character`).
#   2. Le préfixe `format:` est OBLIGATOIRE. `--format=<chaîne libre>` est
#      refusé par git (« invalid --pretty format ») : il n'accepte qu'un nom
#      de format connu (oneline, short…) ou `format:` / `tformat:`. Sans le
#      préfixe, git sortait en 128, la fonction avalait l'échec et renvoyait
#      « 0 commit » — donc un contrôle VERT sur une mémoire périmée.
_SENTINELLE = "@@Lintorn-COMMIT@@"


def _commits_depuis(depuis: str, pathspecs: list[str]) -> tuple[int, list[str] | None]:
    """(nombre de commits, fichiers touchés) depuis cette date.

    `--name-only` combiné à un pathspec ne liste QUE les fichiers concernés :
    c'est git qui filtre, on n'a aucun recoupement à faire nous-mêmes.

    Renvoie `(0, None)` — et non `(0, [])` — quand git est en panne. L'appelant
    DOIT distinguer « rien n'a bougé » de « je n'ai pas pu regarder » : c'est
    précisément la confusion qui a rendu ce contrôle faussement vert.
    """
    # `--relative` : les noms depuis la racine du projet, comme ceux de
    # `git diff --relative` auxquels `_deja_relus` les compare.
    try:
        sortie = config.git("log", f"--since={depuis}", f"--format=format:{_SENTINELLE}",
                            "--name-only", "--relative", "--", *pathspecs, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 0, None

    if sortie.returncode != 0:
        return 0, None

    nb = 0
    touches: set[str] = set()
    for ligne in sortie.stdout.splitlines():
        ligne = ligne.strip()
        if ligne == _SENTINELLE:
            nb += 1
        elif ligne:
            touches.add(ligne)
    return nb, sorted(touches)


def _non_commites(pathspecs: list[str]) -> set[str] | None:
    """Les fichiers cités qui diffèrent du dernier commit, index compris ; None si git se tait."""
    modifies: set[str] = set()
    for indexe in ((), ("--cached",)):
        try:
            sortie = config.git("diff", "--name-only", "--relative", "-z", *indexe,
                                "--", *pathspecs, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if sortie.returncode != 0:
            return None
        modifies.update(nom for nom in sortie.stdout.split("\0") if nom)
    return modifies


def _ecrit_apres(nom: str, moment: datetime.datetime) -> bool:
    """Ce fichier a-t-il été écrit après `moment` ? Supprimé, il n'a plus d'heure : oui.

    ⚠️ L'heure de modification se règle : `cp -p`, `rsync -a`, `tar x` posent
    celle de la source, et un fichier remplacé par une vieille copie passait
    pour écrit avant la relecture. L'heure de changement (`st_ctime`) ne se
    règle pas : elle dit quand le fichier a changé sur CE disque. Sous
    Windows, `st_ctime` est l'heure de création : l'heure de modification seule.
    """
    try:
        etat = (config.RACINE / nom).stat()
    except OSError:
        return True
    ecrit = etat.st_mtime if os.name == "nt" else max(etat.st_mtime, etat.st_ctime)
    return ecrit >= moment.timestamp()


def _head_au_moment(moment: datetime.datetime) -> str | None:
    """Le commit de HEAD au moment de la relecture, d'après le journal de git (reflog).

    None quand le journal ne remonte pas jusque-là : clone plus récent que
    la relecture, journal coupé ou purgé. Le journal note à la seconde : ce
    qui est noté dans la seconde même de la relecture compte comme après.
    """
    try:
        sortie = config.git("reflog", "show", "--date=unix", "--format=%H%x09%gd", "HEAD",
                            "--", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if sortie.returncode != 0:
        return None
    limite = moment.timestamp()
    for ligne in sortie.stdout.splitlines():          # du plus récent au plus ancien
        commit, _, reference = ligne.partition("\t")
        try:
            heure = int(reference[reference.rindex("@{") + 2:].rstrip("}"))
        except ValueError:
            continue
        if heure < limite:
            return commit
    return None


def _changes_depuis(avant: str, pathspecs: list[str]) -> set[str] | None:
    """Les fichiers cités dont le contenu commité diffère entre `avant` et HEAD.

    Un fichier seulement déplacé (`R100`) n'a pas changé. None si git se tait
    (commit d'avant purgé, par exemple).
    """
    try:
        sortie = config.git("diff", "--name-status", "-z", "-M", "--relative", avant, "HEAD",
                            "--", *pathspecs, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if sortie.returncode != 0:
        return None
    changes: set[str] = set()
    champs = iter(sortie.stdout.split("\0"))
    for statut in champs:
        if not statut:
            break
        # Un déplacement ou une copie nomme deux chemins : l'ancien, puis le nouveau.
        chemin = next(champs, "")
        if statut[:1] in ("R", "C"):
            chemin = next(champs, "")
        if chemin and statut != "R100":
            changes.add(chemin)
    return changes


def _modifies_depuis(moment: datetime.datetime, non_commites: set[str]) -> list[str]:
    """Les fichiers cités modifiés APRÈS `moment` et pas encore commités.

    `git log` ne voit que les commits : du code cité réécrit sans être commité
    laissait la fiche « fraîche ». L'heure de modification départage ce qui a
    changé avant la relecture de ce qui a changé après.
    """
    return [nom for nom in sorted(non_commites) if _ecrit_apres(nom, moment)]


def _deja_relus(touches: list[str], moment: datetime.datetime,
                non_commites: set[str]) -> set[str]:
    """Les fichiers commités depuis `moment` que la relecture a vus tels qu'ils sont.

    Une fiche relue, puis commitée avec le code qu'elle décrit, devenait
    suspecte juste après ce commit : il est postérieur à sa date, mais il
    enregistre ce qui était déjà sur le disque. Un fichier identique au
    dernier commit, et écrit avant `moment`, n'a pas changé depuis la
    relecture. Ce que git change (pull, checkout, revert), il le réécrit :
    l'heure du fichier le dit.
    """
    return {nom for nom in touches
            if nom not in non_commites and not _ecrit_apres(nom, moment)}


def _liste(fichiers: list[str]) -> str:
    lignes = "\n".join(f"    - `{f}`" for f in fichiers[:6])
    if len(fichiers) > 6:
        lignes += f"\n    - *… et {len(fichiers) - 6} autre(s)*"
    return lignes


def controle_fraicheur_memoire() -> Resultat:
    """Une mémoire dont le code cité a bougé depuis sa dernière vérification.

    CONSULTATIF, jamais bloquant : « suspect » ne veut pas dire « faux ». Le
    code peut avoir changé sans invalider ce que la mémoire en dit. Le contrôle
    ne juge pas, il DÉSIGNE quoi relire — et c'est déjà énorme sur un projet
    où l'on n'ouvre jamais spontanément un fichier mémoire vieux de trois
    semaines.
    """
    return memoire_ia._annoncer_ressemblance(_controle_fraicheur_memoire())


def _controle_fraicheur_memoire() -> Resultat:
    titre = "Fraicheur memoire (git)"

    if config.MEMOIRE_IA is None:
        return Resultat(titre, "INDISPONIBLE",
                        f"dossier memoire introuvable ({config.MEMOIRE_IA_ORIGINE})",
                        bloquant=False)

    fichiers = memoire_ia._fiches_memoire()
    if fichiers is None:
        return Resultat(titre, "INDISPONIBLE",
                        "dossier memoire ILLISIBLE (droits) - rien n'a ete lu", bloquant=False)
    if not fichiers:
        return Resultat(titre, "INDISPONIBLE", "aucun fichier memoire", bloquant=False)

    # Sans dépôt, la fraîcheur ne se mesure pas : elle se compte en commits.
    # Le contrôle annonçait « NON VERIFIABLE (git muet) » — git n'était pas
    # muet, il répondait qu'il n'y a pas de dépôt. Deux causes, un message.
    if config.SOUS_GIT is None:
        return Resultat(titre, "INDISPONIBLE",
                        "git introuvable sur cette machine", bloquant=False)
    if not config.SOUS_GIT:
        return Resultat(titre, "INDISPONIBLE",
                        "pas de depot git - la fraicheur se compte en commits",
                        bloquant=False)

    suspectes: list[str] = []
    jamais: list[str] = []
    injoignables: list[str] = []
    illisibles: list[str] = []
    fraiches = 0
    hors_perimetre = 0
    index_epargne = False

    for doc in fichiers:
        # ⚠️ L'INDEX n'est pas une fiche. Sa forme est une ligne par fiche,
        # SANS en-tête — donc sans `verifie_le`. Le lui réclamer revenait à
        # exiger qu'il viole sa propre forme, et le contrôle restait `[ ?? ]`
        # à vie. Ce sont ses FICHES qui portent une date ; lui les résume.
        if doc.name == config.INDEX_MEMOIRE:
            index_epargne = True
            continue

        # Illisible (droits) : on ne SAIT pas, comme quand git se tait. La
        # compter fraîche serait affirmer sans avoir lu.
        try:
            texte = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            illisibles.append(doc.name)
            continue

        # ⚠️ On regarde les chemins AVANT la date. Une mémoire qui ne cite aucun
        # fichier — un profil, des préférences de travail — ne peut pas périmer
        # à cause du code : git n'a rien à en dire. Lui réclamer une date de
        # vérification serait du bruit permanent, et un contrôle bruyant finit
        # par ne plus être lu. Elle est HORS PÉRIMÈTRE, pas « en retard ».
        pathspecs = _pathspecs_cites(texte)
        if not pathspecs:
            hors_perimetre += 1
            continue

        trouve = _RX_VERIFIE_LE.search(texte)
        if not trouve:
            jamais.append(doc.name)
            continue

        jour, heure = trouve.group(1), trouve.group(2)
        try:
            moment = datetime.datetime.fromisoformat(f"{jour}T{heure or '00:00'}")
        except ValueError:
            jamais.append(doc.name)       # `2026-02-31` : pas une date, donc pas datée
            continue

        depuis = moment.strftime("%Y-%m-%d %H:%M:%S")
        nb, touches = _commits_depuis(depuis, pathspecs)
        non_commites = _non_commites(pathspecs)
        if touches is None or non_commites is None:
            # git n'a pas répondu : on ne SAIT pas. Surtout ne pas compter
            # cette mémoire comme fraîche — ce serait affirmer sans avoir vu.
            injoignables.append(doc.name)
            continue
        # Ce qui a changé dans les commits depuis la relecture. `git log
        # --since` lit la date des commits : celui d'un collègue, fait avant
        # la relecture et tiré après, ne comptait jamais. Le journal de git
        # dit où était HEAD à ce moment-là ; il sait aussi qu'un fichier
        # déplacé, ou revenu à l'identique, n'a pas changé. Sans lui (clone
        # plus récent que la relecture), les dates des commits.
        avant = _head_au_moment(moment)
        changes = _changes_depuis(avant, pathspecs) if avant else None
        candidats = sorted(changes) if changes is not None else touches
        relus = _deja_relus(candidats, moment, non_commites)
        suspects = [nom for nom in candidats if nom not in relus]
        # Recomptés sur ce qui reste : un commit qui n'a touché que du
        # contenu déjà relu ne compte plus.
        restants = [f":(literal){nom}" for nom in touches if nom in suspects]
        nb, touches = _commits_depuis(depuis, restants) if restants else (0, [])
        if touches is None:
            injoignables.append(doc.name)
            continue
        tires = [nom for nom in suspects if nom not in touches]
        modifies = _modifies_depuis(moment, non_commites)
        if nb == 0 and not tires and not modifies:
            fraiches += 1
            continue

        quand = f"{jour} {heure}" if heure else f"{jour} (sans heure : toute la journee compte)"
        raisons = []
        if nb:
            raisons.append(f"**{nb} commit(s) depuis** sur :\n{_liste(touches)}")
        if tires:
            raisons.append(f"**{len(tires)} fichier(s) change(s) par git depuis** (un pull, une "
                           f"fusion, un changement de branche) :\n{_liste(tires)}")
        if modifies:
            raisons.append(f"**{len(modifies)} fichier(s) modifie(s) depuis, pas encore "
                           f"commite(s)** :\n{_liste(modifies)}")
        suspectes.append(f"- **`{doc.name}`** — vérifiée le {quand}, "
                         + "\n  et ".join(raisons))

    resume = f"{fraiches} fraiche(s), {len(suspectes)} suspecte(s)"
    if jamais:
        resume += f", {len(jamais)} sans date"
    if hors_perimetre:
        resume += f", {hors_perimetre} sans code cite"
    if injoignables:
        resume += f", {len(injoignables)} NON VERIFIABLE(S) (git muet)"
    if illisibles:
        resume += f", {len(illisibles)} ILLISIBLE(S)"
    # Annoncé, jamais escamoté : un fichier qui sort du contrôle en silence
    # passerait pour vérifié.
    if index_epargne:
        resume += ", index epargne (ses fiches sont datees)"

    if not suspectes and not jamais and not injoignables and not illisibles:
        return Resultat(titre, "OK", resume, bloquant=False)

    detail = ""
    if suspectes:
        detail += ("**À RELIRE** — du code cité a changé depuis la dernière "
                   "vérification. Ce n'est pas une erreur : c'est un doute.\n\n")
        detail += "\n".join(suspectes)
    if jamais:
        if suspectes:
            detail += "\n\n"
        detail += (
            "**SANS DATE** — ces mémoires n'ont jamais été confrontées au code. "
            "Ajouter `verifie_le: AAAA-MM-JJ` (ou `AAAA-MM-JJ HH:MM`) dans leur "
            "frontmatter après les avoir relues :\n\n"
        )
        detail += "\n".join(f"- `{n}`" for n in jamais)
    if injoignables:
        if detail:
            detail += "\n\n"
        detail += (
            "**NON VÉRIFIABLES** — git n'a pas répondu pour ces mémoires. Le "
            "contrôle ne dit rien sur elles : ce n'est **pas** un feu vert.\n\n"
        )
        detail += "\n".join(f"- `{n}`" for n in injoignables)
    if illisibles:
        if detail:
            detail += "\n\n"
        detail += (
            "**ILLISIBLES** — Lintorn n'a pas pu ouvrir ces mémoires (droits ?). "
            "Le contrôle ne dit rien sur elles : ce n'est **pas** un feu vert.\n\n"
        )
        detail += "\n".join(f"- `{n}`" for n in illisibles)

    # VERIF et pas ALERTE : rien n'est cassé, il y a des choses à regarder.
    return Resultat(titre, "VERIF", resume, detail, bloquant=False, detail_markdown=True)
