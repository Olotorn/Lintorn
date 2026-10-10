#!/usr/bin/env python3
# Lintorn
"""Le sommaire de Lintorn : ce que l'on tape, et le fichier qui s'en charge.

La table `COMMANDES`, plus bas, est la seule chose à lire pour savoir ce que
Lintorn sait faire. Sans aucune de ses options, `lintorn` lance l'audit.

OÙ TOUCHER QUOI
    commandes/               une commande = un fichier (audit, init, hook…)
    rapport/                 le verdict : terminal, rapport.md, focus d'un push
    config.py                ce que Lintorn a détecté, les outils à lancer
    noyau.py                 qui tourne, dans quel ordre
    base.py                  la fiche Resultat, le lanceur, les traductions
    controles/projet/        ce qui juge LE PROJET : doc, mémoire, règles
    controles/outillage/     ce qui juge LINTORN : son hook, sa fraîcheur

Aucune dépendance : stdlib uniquement.
"""

from __future__ import annotations

import difflib
import sys

from . import config
from .commandes import aide, audit, confiance, hook, init, outils, regles, securite


# ─────────────────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────────────────────────────────────────
def _console_sure() -> None:
    """Empeche une console etroite de faire PLANTER Lintorn.

    Sous Git Bash ou cmd.exe, `sys.stdout` herite du codepage de la console —
    cp1252 en France. Y ecrire un caractere absent de cette table (une fleche,
    un trait de tableau, un emoji) leve une UnicodeEncodeError : le hook
    pre-push echoue alors sans message exploitable, et l'utilisateur croit son
    depot casse.

    ⚠️ Ce que cp1252 contient est plus large qu'on ne croit : accents,
    guillemets francais et tiret cadratin y sont. Ce qui manque, ce sont les
    symboles et le dessin de boites — exactement ce qu'on utilise pour rendre
    une sortie agreable.

    `errors="replace"` transforme donc le pire cas — un plantage — en un
    simple « ? » a l'ecran. On perd un glyphe, jamais le rapport.
    """
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            # Flux redirige, remplace (pytest) ou deja ferme : rien a garantir,
            # et surtout rien qui justifie d'interrompre un audit.
            pass

# ─────────────────────────────────────────────────────────────────────────────
# LE SOMMAIRE — ce que l'on tape → ce que ça lance
# ─────────────────────────────────────────────────────────────────────────────
# Pour AJOUTER ou RENOMMER une commande : sa ligne ici, et sa ligne dans le
# texte d'aide (`commandes/aide.py`).
#
# ⚠️ L'ORDRE COMPTE : la première option reconnue gagne. L'aide et la version
# passent avant tout — `--help` est le premier réflexe de quiconque découvre
# une commande, et il déclenchait un audit complet du dépôt courant.
COMMANDES = [
    (("-h", "--help", "--aide"), lambda args: aide.afficher_aide()),
    (("-V", "--version"), lambda args: aide.afficher_version()),
    (("--confiance",), lambda args: confiance.accorder(sans_demander="--oui" in args)),
    (("--installer-hook",), lambda args: hook.installer_hook()),
    (("--installer-outils",), lambda args: outils.installer_outils(sans_demander="--oui" in args)),
    (("--guide",), lambda args: aide.afficher_guide()),
    (("--init",), lambda args: init.init(ecraser="--force" in args)),
    (("--esquisser-regles",), lambda args: regles.esquisser_regles()),
    (("--maj-securite",), lambda args: securite.maj_securite(appliquer="--appliquer" in args)),
]

# ─────────────────────────────────────────────────────────────────────────────
# LES NOMS COURTS — `lintorn rapide` au lieu de `lintorn --rapide`
# ─────────────────────────────────────────────────────────────────────────────
# Seul le PREMIER mot est traduit : après `--fichiers`, un fichier nommé
# `rapide` reste un fichier. Les formes avec `--` restent comprises, car les
# hooks déjà installés tapent `--rapide`.
NOMS_COURTS = {
    "rapide": ["--rapide"],
    "doc": ["--doc"],
    "init": ["--init"],
    "regles": ["--esquisser-regles"],
    "confiance": ["--confiance"],
    "hook": ["--installer-hook"],
    "outils": ["--installer-outils"],
    "pip-audit": ["--maj-securite"],       # + `--appliquer` pour installer vraiment
    "guide": ["--guide"],
    "help": ["--help"],
    "aide": ["--help"],
    "version": ["--version"],
}


def _traduire_nom_court(args: list[str]) -> list[str]:
    """`rapide --fichiers a.py` → `--rapide --fichiers a.py`. Le reste ne bouge pas."""
    if args and args[0] in NOMS_COURTS:
        return NOMS_COURTS[args[0]] + args[1:]
    return args


# ─────────────────────────────────────────────────────────────────────────────
# LES OPTIONS COMPRISES
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️ UNE OPTION INCONNUE N'EST PAS UN AUDIT. `lintorn --vresion` lançait un
# audit complet : l'option mal tapée était ignorée en silence, et l'outil
# faisait autre chose que ce qu'on lui demandait, sans le dire. Tout ce qui
# n'est pas reconnu arrête donc Lintorn, avec l'option la plus proche.
# La liste se DÉDUIT du sommaire : une commande ajoutée là est comprise ici,
# sans seconde liste à tenir à jour.
_OPTIONS_AUDIT = {"--rapide", "--doc", "--fichiers", "--fichiers-stdin"}
_PRECISIONS = {"--force", "--oui", "--appliquer"}     # lues par une commande
OPTIONS = ({option for options, _ in COMMANDES for option in options}
           | _OPTIONS_AUDIT | _PRECISIONS)


def _separer(args: list[str]) -> tuple[list[str], list[str]]:
    """(options, fichiers désignés comme tels). Après `--`, TOUT est un fichier.

    ⚠️ Sans séparateur, un fichier poussé nommé `--help` était lu comme
    l'option : l'aide s'affichait, Lintorn sortait en 0, et le push passait
    SANS audit. Le hook pre-push passe donc `--fichiers -- <fichiers>`.

    ⚠️ Mais les hooks DÉJÀ installés chez les utilisateurs passent encore
    `--fichiers <fichiers>`, sans séparateur. Pour eux : après `--fichiers`,
    un nom qui désigne un fichier EXISTANT reste un fichier, même s'il a la
    forme d'une option.
    """
    if "--" in args:
        coupure = args.index("--")
        return args[:coupure], args[coupure + 1:]
    if "--fichiers" not in args:
        return args, []
    debut = args.index("--fichiers") + 1
    options, fichiers = args[:debut], []
    for arg in args[debut:]:
        if arg.startswith("-") and (config.RACINE / arg).exists():
            fichiers.append(arg)
        else:
            options.append(arg)
    return options, fichiers


def _arguments_inconnus(args: list[str]) -> list[str]:
    """Ce que Lintorn ne comprend pas. Après `--fichiers`, un mot nu est un fichier."""
    options, _ = _separer(args)
    inconnus = []
    apres_fichiers = False
    for arg in options:
        if arg == "--fichiers":
            apres_fichiers = True
        elif arg in OPTIONS or (apres_fichiers and not arg.startswith("-")):
            continue
        else:
            inconnus.append(arg)
    return inconnus

# ─────────────────────────────────────────────────────────────────────────────
# UNE FAUTE DE FRAPPE — proposer, JAMAIS deviner
# ─────────────────────────────────────────────────────────────────────────────
# Comme git : « voulais-tu dire : lintorn rapide ». Mais la commande proposée
# n'est JAMAIS lancée d'office : une faute sur `pip-audit --appliquer`
# installerait des paquets que personne n'a demandés.
def _proposer(arg: str) -> str | None:
    """Ce que l'on voulait sans doute taper, prêt à copier — ou None."""
    proche = difflib.get_close_matches(arg, sorted(OPTIONS | set(NOMS_COURTS)),
                                       n=1, cutoff=0.6)
    if not proche:
        return None
    # Une forme longue qui a un nom court est proposée sous ce nom :
    # `--rapdie` → `lintorn rapide`, la forme que montre l'aide.
    courts: dict[str, str] = {}
    for nom, options in NOMS_COURTS.items():
        courts.setdefault(options[0], nom)
    trouve = courts.get(proche[0], proche[0])
    # `--force`, `--oui`… précisent une commande : seuls, ils ne lancent rien.
    return f"lintorn {trouve}" if trouve in NOMS_COURTS else trouve


def _signaler_inconnus(inconnus: list[str]) -> int:
    """Dit ce qui n'a pas été compris, propose le plus proche, ne lance rien."""
    sans_piste = False
    for arg in inconnus:
        genre = "Option" if arg.startswith("-") else "Commande"
        print(f"{genre} inconnue : {arg}")
        proposition = _proposer(arg)
        if proposition:
            print(f"Voulais-tu dire :  {proposition}")
        else:
            sans_piste = True
    if not sans_piste:
        print("Rien n'a ete lance.")
        return 2
    # Rien d'approchant : la liste COURTE des commandes, pas l'aide entière —
    # ses quarante lignes noieraient le message d'erreur, surtout dans un hook.
    print("Rien n'a ete lance. Les commandes :")
    for ligne in aide.liste_courte():
        print(ligne)
    print("Tout le detail : lintorn help")
    return 2


def main() -> int:
    _console_sure()
    # Traduit AVANT tout le reste : sinon `rapide` serait refusé comme option inconnue.
    args = _traduire_nom_court(sys.argv[1:])

    inconnus = _arguments_inconnus(args)
    if inconnus:
        return _signaler_inconnus(inconnus)

    # Les fichiers passés après `--` ne sont JAMAIS des options.
    args, apres_separateur = _separer(args)

    for options, commande in COMMANDES:
        if set(options) & set(args):
            return commande(args)
    return audit.lancer(args, apres_separateur)


if __name__ == "__main__":
    raise SystemExit(main())
