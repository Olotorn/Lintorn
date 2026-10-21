# Lintorn
"""Écrire `.lintorn/rapport.md`, et sa page web à côté.

PRINCIPE — le rapport est un FAIT SUR LE CODE, pas une mémoire : il est ÉCRASÉ
à chaque exécution, jamais fusionné, jamais trié. Un fait sur le code périme dès
que le code change et se recalcule en quelques secondes.
"""

from __future__ import annotations

import re
from datetime import datetime

from .. import __version__, base, config
from ..base import MARQUEUR, Resultat
from . import html


# ─────────────────────────────────────────────────────────────────────────────
# RAPPORT
# ─────────────────────────────────────────────────────────────────────────────
def _cellule_du_tableau(texte: str) -> str:
    """Une cellule du tableau récapitulatif : sur UNE ligne, sans `|` nu.

    Un résumé qui contient ` | ` (plusieurs règles en alerte) décalait les
    colonnes, et la fin du résumé disparaissait au rendu.
    """
    return " ".join(str(texte).split()).replace("|", "\\|")


def _cloture(texte: str) -> str:
    """Une clôture de bloc plus longue que toute suite de backticks du texte.

    Une sortie brute qui contient ``` fermait le bloc : la suite s'affichait
    comme du Markdown — de quoi y glisser une fausse section.
    """
    plus_longue = max((len(suite) for suite in re.findall(r"`+", texte)), default=0)
    return "`" * max(3, plus_longue + 1)


def ecrire_rapport(resultats: list[Resultat], hook: bool = False) -> bool:
    """Écrit le rapport, celui du push à part. Rend False, et le dit, s'il n'a pas pu l'être.

    Un dossier en lecture seule (CI, image montée) faisait planter Lintorn
    APRÈS que tous les contrôles avaient tourné : le verdict était perdu.
    """
    # UN SEUL moment pour les deux rendus : deux horloges lues à quelques
    # millisecondes d'écart pouvaient tomber de part et d'autre d'une minute,
    # et le même audit semblait en être deux.
    moment = datetime.now()
    rapport = config.rapport_du(hook)
    lignes = [
        f"# Le rapport de Lintorn — {config.RACINE.name}",
        "",
        # La VERSION : un hook peut lancer un autre Lintorn que celui du
        # projet (celui du système, plus vieux). Sans elle, rien ne le montrait.
        f"> Généré le {moment:%d/%m/%Y %H:%M} par `lintorn {__version__}`, "
        + ("**pendant un push**. Tes commandes (`lintorn`, `lintorn rapide`…) écrivent "
           f"`{config.rapport_du(False).name}`." if hook else
           f"**hors push**. Le dernier push a le sien : `{config.rapport_du(True).name}`."),
        "> **Fichier régénéré à chaque exécution : ne rien y écrire à la main.**",
        "",
        "| Contrôle | Statut | Résumé |",
        "|---|---|---|",
    ]
    lignes += [f"| {_cellule_du_tableau(r.titre)} | {MARQUEUR[r.statut]} "
               f"| {_cellule_du_tableau(r.resume)} |" for r in resultats]

    for r in resultats:
        if not r.detail or (r.statut == "OK" and not r.detail_meme_au_vert):
            continue
        detail = base.detail_du_rapport(r)

        lignes +=["", f"## {MARQUEUR[r.statut]} {r.titre}", ""]
        if r.detail_markdown:
            # Détail déjà en Markdown (liens cliquables) : surtout PAS de bloc
            # ``` , qui afficherait le code source des liens au lieu des liens.
            lignes.append(detail)
        else:
            cloture = _cloture(detail)
            lignes += [cloture, detail, cloture]

    try:
        base.ecrire_sortie(rapport, "\n".join(lignes) + "\n")
    except OSError as erreur:
        print(f"Rapport NON ecrit ({erreur}) - le verdict ci-dessous reste valable.")
        return False

    # ⚠️ La page est un CONFORT : si elle échoue, le rapport Markdown reste
    # écrit et le verdict reste vrai. On le dit, et on continue — perdre un
    # audit entier pour une vue serait absurde.
    # À CÔTÉ du Markdown, par construction : deux chemins réglés séparément
    # finissent par diverger (c'est arrivé dans les tests, qui redirigeaient
    # l'un et pas l'autre).
    page = rapport.with_suffix(".html")
    try:
        base.ecrire_sortie(page, html.page(resultats, moment, hook))
    except OSError as erreur:
        # ⚠️ La page d'un audit PRÉCÉDENT, laissée à côté d'un rapport neuf,
        # le contredirait : deux verdicts pour un même projet. Si on ne peut
        # pas la réécrire, on la retire — et si même ça échoue, on le DIT.
        try:
            base.retirer_sortie(page)
            print(f"Page HTML NON ecrite ({erreur}) - le rapport Markdown, lui, est a jour.")
        except OSError:
            print(f"Page HTML NON ecrite ({erreur}) - l'ANCIENNE page est encore la : "
                  "perimee, ne pas s'y fier.")
    return True
