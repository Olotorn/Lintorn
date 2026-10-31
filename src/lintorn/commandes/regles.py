# Lintorn
"""`lintorn regles` : un brouillon de règle par règle de la doc."""

from __future__ import annotations

import json
import re

from .. import base, chemins, config
from ..base import MARQUEUR
from ..controles.projet import regles_enoncees, regles_maison
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
# Ni guillemet ni barre oblique inverse : l'ancre s'écrit telle quelle dans
# une chaîne TOML. Le `_` reste, il fait partie des noms cités.
_RX_HORS_ANCRE = re.compile(r'[`*"\\|]')
_RX_SOURCE_ECRITE = re.compile(r"""source\s*=\s*(["'])(.+?)\1""")


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


def _source(chemin: str, numero: int, phrase: str, enoncees) -> str:
    """La `source` d'une esquisse : le plus court début de phrase qui ne
    désigne que cette règle.

    Dans un tableau, le sujet (la première cellule) passe d'abord : « Zéro
    dépendance » se relit mieux que dix mots de phrase. Deux lignes
    identiques n'ont pas d'ancre possible : on retombe sur le numéro.
    """
    mots = _RX_HORS_ANCRE.sub(" ", phrase).split()
    candidats = [" ".join(mots[:n]) for n in range(min(3, len(mots)), len(mots) + 1)]
    if "|" in phrase:
        candidats.insert(0, " ".join(_RX_HORS_ANCRE.sub(" ", phrase.partition("|")[0]).split()))
    for candidat in candidats:
        source = f"{chemin}#{candidat}"
        if regles_enoncees.ligne_designee(source, enoncees)[0] == f"{chemin}:{numero}":
            return source
    return f"{chemin}:{numero}"


def esquisses_regles(deja_ecrit: str = "") -> list[str]:
    """Un bloc `[[regles]]` commente par regle enoncee mais non controlee.

    `deja_ecrit` : le contenu actuel du regles.toml. Une regle qu'une
    `source` y designe deja est sautee, sans quoi deux passages
    empileraient deux fois les memes brouillons.
    """
    enoncees = regles_enoncees.regles_enoncees()
    deja = {regles_enoncees.ligne_designee(source, enoncees)[0]
            for _, source in _RX_SOURCE_ECRITE.findall(deja_ecrit)}
    manquantes = [
        (chemin, numero, phrase, jetons)
        for chemin, numero, phrase, jetons in regles_enoncees.regles_sans_controle()
        if f"{chemin}:{numero}" not in deja
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
        "# Une regle qu'aucun motif ne peut exprimer (« une seule session a la",
        "# fois ») : remplis `hors_portee` a la place, avec ta raison. Une seule",
        "# des deux lignes, l'autre reste vide.",
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
            f'# source   = "{_source(chemin, numero, phrase, enoncees)}"',
            # Échappé comme une chaîne TOML : le `\` d'un `C:\Users` cité rendait
            # regles.toml illisible une fois décommenté, et TOUTES les règles tombaient.
            f"# nom      = {json.dumps(_nom_de_regle(phrase), ensure_ascii=False)}",
            '# racine   = "."          # <- restreins au dossier concerne',
            f"# suffixes = [{rendu}]{indice}",
            "# motif    = ''            # <- A ECRIRE : ce qui repere une VIOLATION",
            "# hors_portee = ''         # <- OU : pourquoi aucun motif ne peut l'exprimer",
            "# bloquant = false         # true quand la regle est deja tenue partout",
        ]
    return lignes


def contenu_regles_toml(esquisses: list[str]) -> str:
    """L'en-tete de `regles.toml`, suivi des esquisses ou d'un exemple."""
    lignes = [
        "# Les regles maison de ce projet.",
        "#   https://gitlab.com/olotorn/lintorn",
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
    # Corriger n'est pas son métier : il ajoute des brouillons, `lintorn corrige`
    # répare. Mais un `[[regle]]` mal écrit ne compte pour rien : le dire d'abord.
    mal_nommees = config.tables_mal_nommees(deja)
    if mal_nommees:
        print(f"{cible.name} : {len(mal_nommees)} table(s) que Lintorn ne lit pas "
              f"(ligne {', '.join(str(numero) for numero, *_ in mal_nommees)}) : lintorn corrige")
        print()

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
    # Une `source` qui ne désigne plus rien ne dit pas quelle règle elle visait :
    # son brouillon revient, en double de la règle qui existe déjà.
    recaler = regles_enoncees.sources_a_recaler(regles_enoncees.regles_enoncees())
    if recaler:
        print()
        print(f"ATTENTION : {len(recaler)} regle(s) deja ecrite(s) ont une `source` qui ne "
              "designe plus rien.")
        print("Si l'une d'elles couvrait une des phrases ci-dessus, recale sa `source`")
        print("et jette le brouillon au lieu d'ecrire la regle deux fois :")
        for nom, source, pourquoi in recaler:
            print(f"    - {nom} ({source}) : {pourquoi}")
    return 0


def tester() -> int:
    """`lintorn regles --test` : chaque règle, une par une, et ses `exemple`.

    Le contrôle « Regles maison » juge le PROJET ; ceci juge les RÈGLES. Une
    règle qui ne lit rien, ne finit pas, ou ne trouve pas son propre exemple
    ne protège rien, et rend le code 1. Une règle qui trouve des fautes
    MARCHE : ce qu'elle trouve est dit, c'est au projet de le corriger.
    """
    regles = config.REGLES_MAISON
    # L'exemple raté d'une règle chargée est dit sous elle, pas une seconde fois ici.
    deja_dits = tuple(f"{regle['nom']} : son exemple" for regle in regles)
    soucis = [souci for souci in config.SOUCIS_CONFIG if not souci.startswith(deja_dits)]
    if not regles and not config.HORS_PORTEE and not soucis:
        print("Aucune regle a tester : regles.toml n'en declare aucune (lintorn regles en prepare).")
        return 0

    cassees = 0
    index: dict = {}
    illisibles: set[str] = set()
    for regle in regles:
        statut, notes = _tester_une(regle, regles_maison.juger(regle, index, illisibles, set()))
        cassees += statut == "ALERTE"
        fichier, ligne = regle["ou"]
        print(f"{MARQUEUR[statut]} {regle['nom']}" + (f"  ({fichier}:{ligne})" if fichier else ""))
        for note in notes:
            print(f"       {note}")
    for decl in config.HORS_PORTEE:
        print(f"{MARQUEUR['INDISPONIBLE']} {decl['nom']}  hors_portee : aucun motif a tester")

    if soucis:
        print()
        print(f"Ce que Lintorn n'a pas pu charger ({len(soucis)}) :")
        for souci in soucis:
            print(f"    - {souci}")
    print()
    if cassees or soucis:
        print(f"{cassees + len(soucis)} probleme(s) : ces regles ne protegent pas ce que tu crois.")
        return 1
    sans_exemple = sum(1 for regle in regles if not regle["exemples"])
    if sans_exemple:
        print(f"Les {len(regles)} regle(s) a motif tournent, mais {sans_exemple} sans `exemple` :")
        print("rien ne prouve qu'elles savent trouver une faute. Donne a chacune un texte fautif.")
        return 0
    print(f"Les {len(regles)} regle(s) a motif marchent : chacune trouve son exemple.")
    return 0


def _tester_une(regle: dict, jugement) -> tuple[str, list[str]]:
    """(statut, ce qu'il faut en dire) d'une règle qui vient de tourner."""
    notes = []
    statut = "OK"
    if jugement.abandon:
        statut = "ALERTE"
        notes.append(jugement.abandon)
    elif not jugement.lus:
        statut = "ALERTE"
        suffixes = ", ".join(regle["suffixes"]) or "(aucun suffixe declare)"
        ou = chemins.relatif(regle["racine"])
        notes.append(f"{jugement.illisibles_ici} fichier(s) en {suffixes} sous {ou}/ ILLISIBLE(S)"
                     if jugement.illisibles_ici else
                     f"ne lit aucun fichier : rien en {suffixes} sous {ou}/ qui ne soit exclu")
    elif regle["si"] is not None and not jugement.applicables:
        statut = "VERIF"
        notes.append(f"lit {jugement.lus} fichier(s), mais son `si` n'apparait dans aucun")
    elif jugement.par_fichier:
        trouves = sorted(jugement.par_fichier)
        quoi = ("manque dans" if regle["requis"]
                else f"{sum(jugement.par_fichier.values())} occurrence(s) dans")
        notes.append(f"lit {jugement.lus} fichier(s), {quoi} {len(trouves)} : "
                     + ", ".join(trouves[:3]) + (" ..." if len(trouves) > 3 else ""))
    else:
        notes.append(f"lit {jugement.lus} fichier(s) : rien trouve")

    rates = [config.rate_son_exemple(regle, exemple) for exemple in regle["exemples"]]
    if not regle["exemples"]:
        if statut == "OK":
            statut = "VERIF"
        notes.append("sans `exemple` : rien ne prouve qu'elle sait trouver une faute")
    elif any(rates):
        statut = "ALERTE"
        notes += [f"son exemple {numero if len(rates) > 1 else ''}".rstrip() + f" {raison}"
                  for numero, raison in enumerate(rates, 1) if raison]
    else:
        notes.append("son exemple est attrape" if len(rates) == 1
                     else f"ses {len(rates)} exemples sont attrapes")
    return statut, notes
