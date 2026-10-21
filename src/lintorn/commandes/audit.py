# Lintorn
"""L'audit : `lintorn`, `--rapide`, `--doc`, `--fichiers`."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from .. import base, config, noyau
from ..base import Resultat
from ..controles.outillage import audit_complet, hook_git
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
    # Une fois chacun : deux branches, ou deux commits d'une branche neuve,
    # touchent souvent le même fichier.
    return list(dict.fromkeys(ligne.rstrip("\r") for ligne in texte.split("\n")
                              if ligne.rstrip("\r")))


def _depuis_la_racine(fichiers: list[str]) -> list[str]:
    """Les noms tapés depuis un sous-dossier, dits depuis la racine du projet.

    Le focus les cherchait depuis la racine : `lintorn --fichiers f.js` lancé
    dans `sous/` disait « aucun defaut connu » d'un `sous/f.js` fautif.
    """
    try:
        ici = Path.cwd().resolve()
        racine = config.RACINE.resolve()
    except OSError:
        return fichiers
    noms = []
    for fichier in fichiers:
        chemin = Path(fichier)
        try:
            noms.append((chemin if chemin.is_absolute() else ici / chemin)
                        .resolve().relative_to(racine).as_posix())
        except (ValueError, OSError):
            noms.append(fichier)
    return noms


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
        fichiers = _depuis_la_racine(fichiers + apres_separateur)
    if "--fichiers-stdin" in args:
        fichiers += _fichiers_de_l_entree()

    hook = os.environ.get("LINTORN_HOOK") == "1"
    if hook:
        # La seule preuve que le pre-push d'un autre outil lance vraiment
        # Lintorn : lire son texte prenait un commentaire pour un appel.
        hook_git.noter_passage()
    if (hook and not fichiers and os.environ.get("LINTORN_LISTE") == "complete"
            and "LINTORN_POUSSE" in os.environ):
        # Le hook a dit tout ce qui part, et rien de nouveau ne part : rien à
        # juger. Une faute du disque refusait la suppression d'une branche, et
        # « Lintorn OK » tombait sur zéro fichier lu.
        # Sa propre conclusion : celle d'un audit dirait « AUCUN controle n'a pu
        # tourner », vrai, mais là où il n'y avait rien à contrôler.
        rien = focus.rien_ne_part()
        markdown.ecrire_rapport([rien], hook=True)
        print(f"\n{rien.resume[0].upper()}{rien.resume[1:]}.")
        hook_git.noter_verdict(0)
        return 0

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
                # Sa ligne a été jugée AVANT : elle disait « jamais lance » sous
                # l'audit complet qui venait de tourner.
                a_jour = audit_complet.controle_audit_complet()
                resultats = [a_jour if r.titre == a_jour.titre else r for r in resultats]

        if fichiers:
            resultats.append(focus.focus_sur(resultats, fichiers))
        if hook:
            resultats += focus.ecart_avec_le_disque(
                fichiers, os.environ.get("LINTORN_POUSSE", "").split(),
                os.environ.get("LINTORN_LISTE"), os.environ.get("LINTORN_DISTANT"))

        ligne.etape("ecriture du rapport")
        rapport_ecrit = markdown.ecrire_rapport(resultats, hook=hook)

    code = console.afficher(resultats, rapport_ecrit, manque_config, hook=hook)
    if hook:
        hook_git.noter_verdict(code)
    return code
