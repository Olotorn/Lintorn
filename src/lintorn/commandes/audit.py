# Lintorn
"""L'audit : `lintorn`, `--rapide`, `--doc`, `--fichiers`."""

from __future__ import annotations

import os
import sys
from datetime import datetime

from .. import base, config, noyau
from ..base import Resultat
from ..controles.projet import doc_vs_code
from ..rapport import attente, console, focus, markdown
from . import aide


def _fichiers_de_l_entree() -> list[str]:
    """Les fichiers poussés, un par ligne, lus sur l'entrée standard.

    ⚠️ PAS EN ARGUMENTS : sous Windows, une ligne de commande tient en 32 767
    caractères. Un push de mille fichiers la dépassait — Lintorn ne démarrait
    même pas, et le hook refusait le push sans pouvoir dire pourquoi.

    Lue en OCTETS, décodée comme un chemin (voir `config.git`) : un nom
    accentué revient tel que git l'a écrit, pas selon la langue de la
    console. Coupée sur `\n` seulement — `splitlines()` coupe aussi sur
    U+2028, qu'un nom de fichier peut contenir.
    """
    try:
        brut = sys.stdin.buffer.read()
    except (AttributeError, OSError, ValueError):
        return []
    texte = brut.decode(sys.getfilesystemencoding(), errors="replace")
    return [ligne.rstrip("\r") for ligne in texte.split("\n") if ligne.rstrip("\r")]


def _audit_complet_fait(resultats: list[Resultat]) -> bool:
    """Chaque outil lent accordé a-t-il rendu un verdict ?

    Noter la date dès que `--rapide` était absent faisait passer « Audit
    complet » au vert après un audit où aucun outil lent n'avait tourné — ou
    dont l'audit de failles venait d'expirer sur le réseau.
    """
    lents = {entree["titre"] for entree in config.COMMANDES if entree["lent"]}
    repondu = {r.titre for r in resultats if r.statut in ("OK", "ALERTE")}
    return bool(lents) and lents <= repondu


def lancer(args: list[str], apres_separateur: list[str]) -> int:
    """`lintorn`, `--rapide`, `--doc`, `--fichiers` : auditer, écrire, conclure."""
    # ⚠️ Calcule et affiche AVANT l'audit. Un debutant doit savoir ce qu'il
    # regarde avant de voir defiler des resultats, pas apres.
    manque_config = not config.PROJET and not (config.DOSSIER_LINTORN / "config.toml").exists()
    if manque_config:
        aide.accueil()

    fichiers: list[str] = []
    if "--fichiers" in args:
        fichiers = [a for a in args[args.index("--fichiers") + 1:] if not a.startswith("--")]
        fichiers += apres_separateur
    if "--fichiers-stdin" in args:
        fichiers += _fichiers_de_l_entree()

    with attente.Attente() as ligne:
        if "--doc" in args:
            ligne.etape("doc vs code")
            resultats = [doc_vs_code.controle_doc()]
        else:
            complet = "--rapide" not in args
            resultats = noyau.executer(rapide=not complet, etape=ligne.etape)
            if complet and _audit_complet_fait(resultats):
                # Les outils lents ont tourné : on note la date pour que le contrôle
                # « Audit complet » cesse de réclamer. Écrit APRÈS coup — un audit
                # interrompu ne doit pas compter comme fait.
                base.ecrire_etat("dernier_audit_complet",
                                  datetime.now().isoformat(timespec="seconds"))

        if fichiers:
            resultats.append(focus.focus_sur(resultats, fichiers))

        ligne.etape("ecriture du rapport")
        rapport_ecrit = markdown.ecrire_rapport(resultats)

    return console.afficher(resultats, rapport_ecrit, manque_config,
                            hook=os.environ.get("LINTORN_HOOK") == "1")
