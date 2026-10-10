# Lintorn
"""`lintorn regles` : un brouillon de règle par règle de la doc."""

from __future__ import annotations

import re

from .. import base, chemins, config
from ..controles.projet import regles_enoncees
from . import dossier_lintorn

# ─────────────────────────────────────────────────────────────────────────────
# ESQUISSER LES RÈGLES DÉJÀ ÉCRITES DANS LA DOC
# ─────────────────────────────────────────────────────────────────────────────
# Le projet ENONCE ses regles dans son fichier d'instructions IA. Les
# RECOPIER a la main dans le config.toml est du travail bete, et c'est la
# que la plupart des gens abandonnent.
#
# ⚠️ LES ESQUISSES SONT COMMENTEES, JAMAIS ACTIVES. `re.compile("")` reussit,
#    et un motif vide matche partout : une esquisse active compterait des
#    milliers de fausses infractions des le premier audit. Un brouillon doit
#    etre inerte tant que l'humain n'y a pas mis la main.
_RX_MARKDOWN = re.compile(r"[`*_]+")
_RX_SUFFIXE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,4}$")


def _nom_de_regle(phrase: str) -> str:
    """Un nom court. Dans un tableau, la premiere cellule EST le sujet."""
    cellules = [c.strip() for c in phrase.split("|") if c.strip()]
    brut = cellules[0] if cellules else phrase
    propre = " ".join(_RX_MARKDOWN.sub("", brut).replace('"', "'").split())
    if not propre:
        return "regle sans nom"
    return propre[:57] + "..." if len(propre) > 60 else propre


def _suffixes_probables(jetons: list[str]) -> list[str]:
    """Les extensions citees par la regle. Vide plutot que devine de travers."""
    trouves = []
    for jeton in jetons:
        fin = _RX_SUFFIXE.search(jeton.split("/")[-1].strip())
        if fin and fin.group(0).lower() not in trouves:
            trouves.append(fin.group(0).lower())
    return sorted(trouves)


def esquisses_regles(deja_ecrit: str = "") -> list[str]:
    """Un bloc `[[regles]]` commente par regle enoncee mais non controlee.

    `deja_ecrit` : le contenu actuel du config.toml. Une regle dont le
    `source` y figure deja est sautee — sans quoi deux passages
    empileraient deux fois les memes brouillons.
    """
    manquantes = [
        (chemin, numero, phrase, jetons)
        for chemin, numero, phrase, jetons in regles_enoncees.regles_sans_controle()
        if f'"{chemin}:{numero}"' not in deja_ecrit
    ]
    if not manquantes:
        return []

    lignes = [
        "",
        "# ── Esquisses : tes regles de doc qui n'ont pas encore de controle ───",
        "# Lintorn les a reperees, mais il NE PEUT PAS deviner comment les",
        "# detecter : « jamais de couleur en dur » ne dit pas s'il faut traquer",
        "# #fff, rgba( ou hsl(, ni s'il faut epargner les commentaires. C'est une",
        "# decision technique, et une regex devinee ne produirait que des faux",
        "# positifs — de quoi cesser de faire confiance au rapport.",
        "#",
        "# Decommente celles qui comptent, ecris leur `motif`, jette les autres.",
        "#",
        "# `source` evite de RECOPIER la phrase ici : la regle reste enoncee a un",
        "# seul endroit, et Lintorn sait qu'elle a desormais un controle.",
    ]
    for chemin, numero, phrase, jetons in manquantes:
        suffixes = _suffixes_probables(jetons)
        rendu = ", ".join(f'"{suffixe}"' for suffixe in suffixes)
        indice = "" if suffixes else "   # <- a preciser : .py, .ts, .css..."
        lignes += [
            "",
            f"# {phrase[:100]}",
            "# [[regles]]",
            f'# source   = "{chemin}:{numero}"',
            f'# nom      = "{_nom_de_regle(phrase)}"',
            '# racine   = "."          # <- restreins au dossier concerne',
            f"# suffixes = [{rendu}]{indice}",
            "# motif    = ''            # <- A ECRIRE : ce qui repere une VIOLATION",
            "# bloquant = false         # true quand la regle est deja tenue partout",
        ]
    return lignes


def contenu_regles_toml(esquisses: list[str]) -> str:
    """L'en-tete de `regles.toml`, suivi des esquisses ou d'un exemple."""
    lignes = [
        "# Les regles maison de ce projet.",
        "#   https://gitlab.com/DamXs/lintorn",
        "#",
        "# Un fichier a part parce qu'il VIT : il grossit, on l'edite souvent,",
        "# on le relit a plusieurs. `config.toml`, a cote, est un reglage qu'on",
        "# ecrit une fois. Les deux se versionnent.",
        "#",
        "# Lintorn ne peut PAS deviner une regle maison : c'est une decision,",
        "# elle n'est ecrite nulle part dans le code.",
        "#",
        "# bloquant = true  -> regle DEJA respectee, on empeche la regression",
        "# bloquant = false -> dette existante, on mesure sans bloquer",
        "#",
        "# Une regle dit UN de ces trois, jamais deux :",
        "#   motif        = '...'   ce texte est INTERDIT",
        "#   motif_requis = '...'   ce texte DOIT etre present",
        "#   hors_portee  = '...'   aucun motif ne peut l'exprimer, et voici",
        "#                          pourquoi (exige `source`). Si la raison cite",
        "#                          un test_..., Lintorn verifie qu'il existe.",
        "#",
        "# Et `si` la restreint aux fichiers qui le contiennent, ce qui donne",
        "# « si X apparait, alors Y doit apparaitre aussi » :",
        "#",
        "#   [[regles]]",
        '#   nom          = "Un chiffre cite sans sa source"',
        '#   regle        = "citer le releve des qu\'on cite le total"',
        '#   racine       = "docs"',
        '#   suffixes     = [".md"]',
        "#   motif_requis = 'releve du \\d{2}/\\d{2}'",
        "#   si           = '\\btotal\\b'",
        "#   bloquant     = true",
    ]
    if esquisses:
        lignes += esquisses
    else:
        lignes += [
            "",
            "# Voici la forme, a remplir :",
            "#",
            "# [[regles]]",
            '# nom      = "Couleurs en dur dans un CSS"',
            '# regle    = "uniquement des variables de theme"',
            '# racine   = "src"',
            '# suffixes = [".css"]',
            "# motif    = '#[0-9a-fA-F]{3,8}\\b'   # ou motif_requis, voir ci-dessus",
            "# exclure  = []",
            "# bloquant = false",
        ]
    return "\n".join(lignes) + "\n"


def esquisser_regles() -> int:
    """Ajoute au config.toml un brouillon par regle non controlee.

    POURQUOI UNE COMMANDE A PART, et pas seulement dans `--init` : `--init`
    ne tourne QU'UNE FOIS, au debut, quand la doc du projet est souvent
    encore vide. Les regles s'ecrivent apres, au fil des mois. Reservee a
    `--init`, la fonctionnalite ne servirait qu'aux projets neufs — jamais a
    ceux qui en ont le plus besoin.
    """
    cible = config.FICHIER_REGLES
    try:
        deja = cible.read_text(encoding="utf-8") if cible.is_file() else ""
    except (OSError, UnicodeDecodeError) as erreur:
        print(f"Echec : {cible.name} illisible ({erreur})")
        return 1
    dossier_lintorn.poser_gitignore_interne(cible.parent)

    esquisses = esquisses_regles(deja)
    if not esquisses:
        # « Chaque regle a deja un controle » s'affichait aussi quand AUCUNE
        # regle n'avait ete lue : une assurance tiree de zero lecture.
        if not config.DOCS_IA:
            print("Rien a esquisser : aucun fichier d'instructions IA dans ce projet")
            print(f"({', '.join(config.FICHIERS_IA)}). Lintorn n'a aucune regle a lire.")
            return 0
        lues = len(regles_enoncees.regles_enoncees())
        if not lues:
            print("Rien a esquisser : aucune regle reperee dans "
                  + ", ".join(chemins.relatif(doc) for doc in config.DOCS_IA) + ".")
            print("Ce n'est pas un feu vert : Lintorn n'a peut-etre pas su les lire.")
            return 0
        print(f"Rien a esquisser. {lues} regle(s) lue(s) : chacune a deja un controle,")
        print("ou son brouillon est deja dans le fichier. Detail : lintorn")
        return 0

    try:
        if deja:
            base.ecrire_fichier_du_projet(cible, deja + "\n".join(esquisses) + "\n")
        else:
            base.ecrire_fichier_du_projet(cible, contenu_regles_toml(esquisses))
    except OSError as erreur:
        print(f"Echec : {erreur}")
        return 1

    nombre = sum(1 for ligne in esquisses if ligne == "# [[regles]]")
    print(f"Ajoute a {cible.relative_to(config.RACINE)} : {nombre} esquisse(s), commentee(s).")
    print()
    print("A FAIRE MAINTENANT :")
    print("    1. ouvre le fichier : garde ce qui compte, jette le reste")
    print("    2. pour chaque regle gardee : decommente, puis ecris le `motif`")
    print("    3. `lintorn` pour verifier")
    return 0
