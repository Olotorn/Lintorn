# Lintorn
"""Règles maison : les [[regles]] de regles.toml sont-elles tenues, et sur combien de fichiers ?"""

from __future__ import annotations

import os
import signal
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from ... import config
from ...base import Resultat, lien


def _ou_est_ecrite(regle: dict) -> str:
    """« **Nom de la regle** — .lintorn/regles.toml:42 », en lien cliquable.

    Le numero de ligne est recalcule a chaque execution, dans un rapport
    lui-meme regenere : il ne peut pas perimer.
    """
    fichier, ligne = regle["ou"]
    if not fichier:
        return f"- **{regle['nom']}**"
    return f"- **{regle['nom']}** — {lien(fichier, ligne)}"


# ⚠️ Un motif vient d'un fichier de config — donc, sur un dépôt cloné, de
# n'importe qui. `(a+)+$` face à une ligne de quarante `a` ne rend jamais la
# main (retour arrière exponentiel) : Lintorn gelait, et le `git push` avec.
# Au-delà de ce temps sur UN fichier, la règle est abandonnée — et le rapport
# le dit. Sous Windows, pas de minuterie de signal : pas de borne.
SECONDES_PAR_FICHIER = 5.0
# Et pour TOUS les fichiers d'une règle : un motif lent mais pas infini, sur
# des milliers de fichiers, gelait le push aussi sûrement qu'un motif infini.
SECONDES_PAR_REGLE = 20.0


class _MotifTropLent(Exception):
    """Un motif de règle qui ne rend pas la main."""


@contextmanager
def _chrono(secondes: float):
    """Interrompt le bloc au-delà de `secondes`, là où le système le permet."""
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        yield
        return

    def _trop_long(_numero, _cadre):
        raise _MotifTropLent

    ancien = signal.signal(signal.SIGALRM, _trop_long)
    signal.setitimer(signal.ITIMER_REAL, secondes)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, ancien)


def _fichiers_sous(racine: Path, index: dict, illisibles: set[str]) -> list[Path]:
    """Les fichiers RÉGULIERS sous `racine` — parcourus une seule fois par audit.

    ⚠️ On ne DESCEND PAS dans IGNORES : l'ancien `rglob("*")` parcourait tout
    node_modules avant de le filtrer, et recommençait pour CHAQUE règle —
    13 s pour 20 règles sur un node_modules de 60 000 fichiers.
    ⚠️ Les SORTIES de Lintorn sont écartées — le rapport cite le code fautif,
    et une règle y comptait ses propres citations, un peu plus à chaque
    passage. Mais PAS le reste de `.lintorn/` : config.toml et regles.toml se
    versionnent, une règle doit pouvoir les lire.

    ⚠️ `os.walk` saute EN SILENCE un dossier qu'il ne peut pas lister : ses
    fichiers échappaient à toutes les règles, sans un mot. `onerror` les
    range dans `illisibles`, que le contrôle affiche.
    """
    def _dossier_illisible(erreur: OSError) -> None:
        chemin = Path(erreur.filename)
        illisibles.add(chemin.relative_to(config.RACINE).as_posix() + "/"
                       if chemin.is_relative_to(config.RACINE) else str(chemin))

    if racine not in index:
        sorties = config.sorties_de_lintorn()
        trouves = []
        for dossier, sous_dossiers, noms in os.walk(racine, onerror=_dossier_illisible):
            sous_dossiers[:] = [nom for nom in sous_dossiers if nom not in config.IGNORES]
            trouves += [chemin for chemin in (Path(dossier) / nom for nom in noms)
                        if chemin not in sorties and chemin.is_file()]
        index[racine] = trouves
    return index[racine]


def controle_regles_maison() -> Resultat:
    """Les règles maison sont-elles tenues — et sur COMBIEN de fichiers ?

    « Toutes les regles sont tenues » ne disait ni combien de règles ni sur
    quoi : le même vert couvrait trois règles réelles et trois règles qui
    scannaient le vide — `racine` écarté par la config, `suffixes` qui ne
    correspondent plus à rien, `exclure` trop large. D'où le dénominateur.
    """
    # Aucune règle déclarée → on le DIT au lieu d'afficher « toutes les regles
    # sont tenues ». Un vert sur zéro règle est un mensonge par omission :
    # l'utilisateur croit couvert quelque chose qu'il n'a jamais défini.
    if not config.REGLES_MAISON:
        return Resultat(
            "Regles maison", "INDISPONIBLE",
            "aucune regle declaree - voir .lintorn/regles.toml",
            bloquant=False,
        )

    infractions: list[str] = []
    bloquant_touche = False
    lignes_detail: list[str] = []
    # Les règles qui n'ont ouvert AUCUN fichier, et l'ensemble de ceux qui
    # l'ont été : le dénominateur du verdict.
    a_vide: list[str] = []
    jamais_declenchees: list[str] = []
    abandonnees: list[str] = []
    fichiers_lus: set[str] = set()
    # Fichiers (et dossiers) qu'aucune règle n'a pu ouvrir. Ni lus, ni tus.
    illisibles: set[str] = set()
    # {fichier: ce que chaque règle y a trouvé} — la liste COMPLÈTE, pour le
    # focus du push ; le détail, lui, ne montre que les huit pires.
    en_defaut: dict[str, list[str]] = {}
    index: dict = {}

    for regle in config.REGLES_MAISON:
        par_fichier: dict[str, int] = {}
        lus = 0
        # Fichiers auxquels la règle s'APPLIQUE vraiment. Sans `si`, c'est
        # tous ceux qu'elle a lus ; avec, seulement ceux qui le contiennent.
        applicables = 0

        # On rassemble d'abord, on filtre ensuite : `hors_gitignore` interroge
        # git UNE fois pour toute la liste, au lieu d'un processus par fichier.
        candidats = [chemin for chemin in _fichiers_sous(regle["racine"], index, illisibles)
                     if chemin.suffix in regle["suffixes"]]
        trop_lent = False
        illisibles_ici = 0
        debut = time.monotonic()

        for chemin in config.hors_gitignore(candidats):
            relatif = chemin.relative_to(config.RACINE).as_posix()
            if any(exclu in relatif for exclu in regle["exclure"]):
                continue

            if time.monotonic() - debut > SECONDES_PAR_REGLE:
                abandonnees.append(
                    f"{_ou_est_ecrite(regle)}<br>son motif est trop lent : plus de "
                    f"{SECONDES_PAR_REGLE:g} s sur {lus} fichier(s) : regle abandonnee")
                trop_lent = True
                break

            # `errors="replace"` couvre un contenu mal encodé, pas un fichier
            # qu'on n'OUVRE pas (droits, fichier d'un autre utilisateur) : il
            # faisait tomber tout le rapport. Il n'est donc PAS compté parmi
            # les lus — et il est nommé plus bas.
            try:
                texte = chemin.read_text(encoding="utf-8", errors="replace")
            except OSError:
                illisibles.add(relatif)
                illisibles_ici += 1
                continue

            # Compté ICI et pas sur `candidats` : un fichier écarté par
            # `exclure` ou par git n'a jamais été ouvert.
            lus += 1
            fichiers_lus.add(relatif)

            try:
                with _chrono(SECONDES_PAR_FICHIER):
                    # `si` absent → la règle vaut pour tout fichier lu. Présent,
                    # elle ne juge que ceux qui le contiennent : les autres ne
                    # sont pas « conformes », elle ne les concerne pas.
                    concerne = regle["si"] is None or bool(regle["si"].search(texte))
                    if not concerne:
                        nb = 0
                    elif regle["requis"]:
                        # Un manque ne se compte pas en occurrences : c'est
                        # présent ou absent. Un fichier fautif pèse 1.
                        nb = 0 if regle["motif"].search(texte) else 1
                    else:
                        nb = len(regle["motif"].findall(texte))
            except _MotifTropLent:
                abandonnees.append(
                    f"{_ou_est_ecrite(regle)}<br>son motif ne rend pas la main sur "
                    f"`{relatif}` (plus de {SECONDES_PAR_FICHIER:g} s) : regle abandonnee")
                trop_lent = True
                break
            if concerne:
                applicables += 1
            if nb:
                par_fichier[relatif] = nb

        # Une règle abandonnée n'a PAS de verdict : ni tenue, ni en infraction.
        if trop_lent:
            continue

        if not lus:
            suffixes = ", ".join(regle["suffixes"]) or "(aucun suffixe declare)"
            racine = regle["racine"].name
            if illisibles_ici:
                a_vide.append(f"{_ou_est_ecrite(regle)}<br>ses {illisibles_ici} "
                              f"fichier(s) en {suffixes} sous `{racine}/` sont ILLISIBLES")
            else:
                a_vide.append(f"{_ou_est_ecrite(regle)}<br>`{racine}/` ne contient "
                              f"aucun fichier en {suffixes} qui ne soit pas exclu")
        elif regle["si"] is not None and not applicables:
            # Elle a bien lu des fichiers, mais sa condition n'est jamais
            # tombée : elle n'a donc rien verifie. Ce n'est pas une faute —
            # personne n'a mentionné X — mais ça ne vaut pas non plus
            # « regle tenue ».
            jamais_declenchees.append(
                f"{_ou_est_ecrite(regle)}<br>son `si` n'apparait dans aucun "
                f"des {lus} fichier(s) lus"
            )

        total = sum(par_fichier.values())
        if not total:
            continue

        if regle["bloquant"]:
            bloquant_touche = True
        marque = "BLOQUANT" if regle["bloquant"] else "consultatif"

        if regle["requis"]:
            infractions.append(f"{regle['nom']} : manque dans {len(par_fichier)}")
            entete = f"{len(par_fichier)} fichier(s) ou il MANQUE"
        else:
            infractions.append(f"{regle['nom']} : {total}")
            entete = f"{total} occurrence(s)"
        for fichier, nb in par_fichier.items():
            en_defaut.setdefault(fichier, []).append(
                f"{regle['nom']} (manque)" if regle["requis"] else f"{regle['nom']} : {nb}")

        lignes_detail += [
            "",
            f"### {regle['nom']} — {entete} *[{marque}]*",
            "",
            f"> {regle['regle']}",
            "",
        ]
        # Les 8 fichiers les plus concernés suffisent à savoir par où commencer.
        # Chemins en LIENS : un clic ouvre le fichier dans l'éditeur.
        pires = sorted(par_fichier.items(), key=lambda x: -x[1])[:8]
        lignes_detail += [
            f"- {lien(fichier)}" if regle["requis"] else f"- **{nb}** × {lien(fichier)}"
            for fichier, nb in pires
        ]
        if len(par_fichier) > 8:
            lignes_detail.append(f"- *… et {len(par_fichier) - 8} autre(s) fichier(s)*")

    # AUX DEUX sorties : une infraction ailleurs ne dispense pas de dire
    # qu'une règle a scanné le néant.
    if a_vide:
        lignes_detail += [
            "",
            "### Regles qui n'ont lu AUCUN fichier",
            "",
            "Elles ne protegent plus rien. Verifie le `racine`, les "
            "`suffixes` et le `exclure` de chacune dans `.lintorn/regles.toml` :",
            "",
            *a_vide,
        ]

    if illisibles:
        lignes_detail += [
            "",
            "### Fichiers illisibles",
            "",
            "Lintorn n'a pas pu les ouvrir (droits ?) : aucune regle ne les a "
            "lus, ils n'ont **pas** ete verifies :",
            "",
            *[f"- `{nom}`" for nom in sorted(illisibles)[:20]],
        ]
        if len(illisibles) > 20:
            lignes_detail.append(f"- *… et {len(illisibles) - 20} autre(s)*")

    if abandonnees:
        lignes_detail += [
            "",
            "### Regles abandonnees : motif trop lent",
            "",
            "Leur motif ne rend pas la main (retour arriere catastrophique, du "
            "type `(a+)+`) : elles n'ont PAS de verdict. Simplifie le motif :",
            "",
            *abandonnees,
        ]

    if jamais_declenchees:
        lignes_detail += [
            "",
            "### Regles conditionnelles jamais declenchees",
            "",
            "Leur `si` n'apparait dans aucun fichier lu : elles n'ont donc "
            "rien verifie. Normal si le cas ne s'est pas presente — a "
            "regarder si tu t'attendais a ce qu'il se presente :",
            "",
            *jamais_declenchees,
        ]

    # Une règle à vide n'est PAS « tenue » : elle est INVÉRIFIÉE. Les deux
    # ensembles sont disjoints — sans fichier lu, pas d'infraction possible.
    denominateur = f"{len(fichiers_lus)} fichier(s) lu(s)"
    tenues = (len(config.REGLES_MAISON) - len(infractions)
              - len(a_vide) - len(jamais_declenchees) - len(abandonnees))
    if jamais_declenchees:
        denominateur += f", {len(jamais_declenchees)} jamais declenchee(s)"
    fichiers = {fichier: " ; ".join(trouve) for fichier, trouve in en_defaut.items()}
    sans_verdict = []
    if a_vide:
        sans_verdict.append(f"{len(a_vide)} regle(s) n'ont lu AUCUN fichier")
    if abandonnees:
        sans_verdict.append(f"{len(abandonnees)} regle(s) abandonnee(s), motif trop lent")
    if illisibles:
        sans_verdict.append(f"{len(illisibles)} fichier(s) ou dossier(s) ILLISIBLE(S)")

    if not infractions:
        if sans_verdict:
            return Resultat(
                "Regles maison", "VERIF",
                f"{' ; '.join(sans_verdict)} - {tenues} tenue(s) sur {denominateur}",
                "\n".join(lignes_detail), bloquant=False, detail_markdown=True,
            )
        # Le detail passe MEME au vert quand des regles n'ont rien verifie :
        # le resume n'en donne que le nombre, et « lesquelles » ne se devine
        # pas. Sans ce drapeau, le rapport jetait la seule reponse utile.
        return Resultat(
            "Regles maison", "OK",
            f"{tenues} regle(s) tenue(s) sur {denominateur}",
            "\n".join(lignes_detail) if jamais_declenchees else "",
            detail_markdown=True, detail_meme_au_vert=True,
        )

    if abandonnees:
        denominateur += f", {len(abandonnees)} abandonnee(s) (motif trop lent)"
    if illisibles:
        denominateur += f", {len(illisibles)} ILLISIBLE(S)"
    return Resultat(
        "Regles maison", "ALERTE",
        f"{' | '.join(infractions)} (sur {denominateur})",
        "\n".join(lignes_detail),
        bloquant=bloquant_touche,
        detail_markdown=True,
        fichiers=fichiers,
    )
