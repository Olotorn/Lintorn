# Lintorn
"""Règles énoncées vs contrôlées : chaque règle écrite pour l'IA a-t-elle un contrôle ?"""

from __future__ import annotations

import re
import unicodedata

from ... import config
from ...base import Resultat, lien

# « Regles maison » répond à : les règles que j'ai CONFIGURÉES sont-elles tenues ?
# Celui-ci répond à la question d'avant : les règles que j'ai ÉCRITES dans ma
# doc ont-elles seulement un contrôle en face ?
#
# LE PROBLÈME QU'IL RÈGLE. Une règle vit dans CLAUDE.md parce qu'on l'y a
# écrite pour l'assistant. Rien ne la relie au `regles.toml`. L'écart entre
# « ce que je déclare à l'IA » et « ce que je fais respecter » grandit donc en
# silence : personne ne relit une doc pour y chercher ce qui MANQUE ailleurs.
#
# CE QU'IL NE FAIT PAS, ET POURQUOI. Il ne fabrique aucune regex à partir des
# phrases trouvées. « jamais de couleur en dur » ne dit pas s'il faut traquer
# `#fff`, `rgba(`, `hsl()`, ni s'il faut épargner les commentaires : c'est une
# décision technique, pas une traduction. Une regex devinée produirait des faux
# positifs — et un faux positif est ce qui tue la confiance dans l'outil. On
# SIGNALE le trou ; on laisse l'humain écrire la détection.
_RX_BACKTICK = re.compile(r"`([^`\n]{2,80})`")


# Une règle DIT quelque chose d'impératif. Sans ce filtre, toute ligne citant
# un fichier passerait pour une règle.
_RX_IMPERATIF = re.compile(
    r"\b(jamais|uniquement|toujours|doit|doivent|interdit|interdite|obligatoire"
    r"|unique|seule?|impérativement|imperativement|ne pas|proscrit"
    r"|never|always|must|mustn't|do not|don't|should not|shouldn't|avoid|only"
    r"|required|forbidden|mandatory|instead of|prefer)\b",
    re.I,
)


# Un fichier d'instructions IA énonce ses règles en LISTES et en prose
# (« - Never use `x` », « Do not use `--skip` »), en anglais le plus souvent.
# Ce qui sépare la consigne du récit : l'impératif OUVRE la proposition.
# « Never use `var` » prescrit ; « un devis `VALIDE` n'expire jamais »
# raconte, et reste dehors. Les modaux anglais (must, should not) prescrivent
# où qu'ils soient.
_DEBUT_DE_PROPOSITION = (r"(?:^\s*(?:(?:[-*+]|\d+[.)])\s+)?(?:\*\*[^*]+\*\*\s*[:—–-]?\s*)?"
                         r"|[.;:!?,—–]\s+)")


_RX_CONSIGNE = re.compile(
    _DEBUT_DE_PROPOSITION
    + r"(?:never|always|do not|don't|avoid|prefer|only|ne jamais|ne pas|jamais"
      r"|toujours|uniquement)\b"
    r"|^\s*(?:[-*+]|\d+[.)])\s+(?:\*\*)?no\b"
    r"|\b(?:must|mustn't|should not|shouldn't)\b"
    r"|\buse\b.*?\binstead of\b",
    re.I,
)


# La FORME sépare ce qui prescrit de ce qui décrit. Mesuré sur un vrai projet :
# sans ce filtre, 92 lignes remontaient — notes d'architecture et comptes rendus
# d'audit compris, qui *racontent* le système au passé. Avec, 25 lignes, toutes
# de vraies règles. Un projet énonce ses règles dans un TABLEAU de conventions
# ou derrière un marqueur explicite ; il raconte le reste en prose.
_RX_TABLEAU = re.compile(r"^\s*\|.*\|\s*$")


_RX_PUCE = re.compile(r"^(?:[-*+]|\d+[.)])\s+")


_RX_MARQUEUR_REGLE = re.compile(
    r"\*\*\s*(r[eè]gle|convention|interdit|obligatoire|rule)", re.I)


def _signe(texte: str) -> str:
    r"""Réduit un texte à ses lettres et chiffres, en minuscules.

    Permet de rapprocher `axios.create()` (dans la doc) de `axios\.create\(`
    (une regex du regles.toml) sans se battre avec les échappements : les deux
    donnent « axioscreate ».
    """
    return re.sub(r"[^0-9a-zà-ÿ]+", "", texte.lower())


def regles_enoncees() -> list[tuple[str, int, str, list[str]]]:
    """Les règles ÉNONCÉES dans les fichiers d'instructions IA.

    Rendu : (document, ligne, phrase, identifiants entre backticks).

    ⚠️ UNE SEULE implémentation, partagée par le contrôle et par l'esquisse
    de `--init`. Deux lecteurs séparés finiraient par diverger, et `--init`
    proposerait des brouillons pour des règles que le contrôle ne compte
    pas : l'outil se contredirait tout seul.
    """
    trouvees: list[tuple[str, int, str, list[str]]] = []

    for document in config.DOCS_IA:
        try:
            lignes = document.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        relatif = document.relative_to(config.RACINE).as_posix()

        dans_un_bloc = False
        for numero, ligne in enumerate(lignes, start=1):
            # Un bloc ``` montre du code ou une commande : ses lignes ne
            # prescrivent rien, même quand un commentaire y dit « never ».
            if ligne.lstrip().startswith("```"):
                dans_un_bloc = not dans_un_bloc
                continue
            jetons = _RX_BACKTICK.findall(ligne)
            if dans_un_bloc or not jetons:
                continue
            forme = ((_RX_TABLEAU.match(ligne) or _RX_MARQUEUR_REGLE.search(ligne))
                     and _RX_IMPERATIF.search(ligne))
            if not (forme or _RX_CONSIGNE.search(ligne)):
                continue
            # Sans sa puce : la phrase nomme aussi l'esquisse de `lintorn regles`.
            phrase = " ".join(_RX_PUCE.sub("", ligne.strip()).strip("|").split())
            trouvees.append((relatif, numero, phrase, jetons))

    return trouvees


_RX_NUMERO = re.compile(r"^(.+):(\d+)$")


def _mots(texte: str) -> str:
    """Les mots d'un texte, en minuscules, sans balisage ni ponctuation.

    `**Zéro dépendance** |` et « zéro dépendance » donnent les mêmes mots :
    une ancre se compare au texte, pas à sa mise en forme. Recomposé (NFC)
    d'abord : un « é » écrit e + accent (ce que produit macOS) coupait le
    mot en deux, et l'ancre ne désignait plus rien.
    """
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFC", texte).casefold()))


def ligne_designee(source: str, enoncees) -> tuple[str | None, str]:
    """(« doc:ligne » de la règle énoncée que vise `source`, pourquoi sinon).

    Deux écritures. `CLAUDE.md#Zéro dépendance` vise la règle de CLAUDE.md
    dont la phrase contient ces mots : écrire au-dessus ne la décale pas, et
    elle ne casse que si la règle elle-même change, quand il faut la relire.
    `CLAUDE.md:38` vise une ligne, et se périme dès qu'on ajoute une ligne
    plus haut.

    Un texte trouvé dans plusieurs règles ne désigne rien : en choisir une
    reviendrait à la déclarer couverte sur un pari.
    """
    if "#" in source:
        doc, texte = source.split("#", 1)
        cherche = f" {_mots(texte)} "
        trouvees = [f"{chemin}:{numero}" for chemin, numero, phrase, _ in enoncees
                    if chemin == doc and cherche.strip() and cherche in f" {_mots(phrase)} "]
        if len(trouvees) == 1:
            return trouvees[0], ""
        if trouvees:
            return None, (f"ce texte est dans {len(trouvees)} regles de {doc} : "
                          "allonge-le pour n'en designer qu'une")
        return None, (f"aucune regle de {doc} ne contient ce texte : "
                      "la regle a change, ou la `source` est fausse")

    if _RX_NUMERO.match(source) and source in {f"{c}:{n}" for c, n, _, _ in enoncees}:
        return source, ""
    doc = _RX_NUMERO.sub(r"\1", source)
    return None, ("cette ligne n'enonce aucune regle : la doc a bouge, ou la `source` est "
                  f'fausse. Le debut de sa phrase, `source = "{doc}#..."`, ne bouge pas avec la doc')


def sources_a_recaler(enoncees) -> list[tuple[str, str, str]]:
    """(nom, source, pourquoi) des règles dont la `source` ne désigne plus aucune règle énoncée.

    Les `[[regles]]` à motif comme les `hors_portee` : une règle renommée dans
    la doc redevenait « sans contrôle » sans que rien ne dise qu'une règle de
    `regles.toml` la visait encore.
    """
    recaler = []
    for regle in [*config.REGLES_MAISON, *config.HORS_PORTEE]:
        if not regle.get("source"):
            continue
        ligne, pourquoi = ligne_designee(str(regle["source"]), enoncees)
        if ligne is None:
            recaler.append((regle["nom"], str(regle["source"]), pourquoi))
    return recaler


def regles_sans_controle() -> list[tuple[str, int, str, list[str]]]:
    """Celles qu'aucun `[[regles]]` ne fait respecter.

    Deux façons d'être couverte, de la plus sûre à la plus souple :

    1. `source = "CLAUDE.md#debut de la phrase"` dans le regles.toml : un
       lien EXPLICITE, posé par `lintorn regles` ou à la main (voir
       `ligne_designee`). Aucune ambiguïté possible.
    2. sinon, un identifiant de la ligne se retrouve dans le nom ou le motif
       d'une règle configurée. Heuristique, volontairement indulgente : mieux
       vaut taire une règle déjà surveillée que crier au trou sur une règle
       qui l'est — un contrôle qui crie trop est un contrôle qu'on n'ouvre
       plus.

    ⚠️ Un `source` qui ne désigne plus rien (la phrase a changé, ou la doc a
    bougé d'une ligne sous un `CLAUDE.md:23`) fait RÉAPPARAÎTRE la règle
    comme non couverte. C'est le bon sens d'échec : on ré-alerte au lieu de
    masquer en silence.
    """
    enoncees = regles_enoncees()
    sources = {
        ligne_designee(str(regle["source"]), enoncees)[0]
        for regle in config.REGLES_MAISON if regle.get("source")
    }

    # La « signature » de ce qui DÉTECTE : le nom et le motif, rien d'autre.
    #
    # ⚠️ Le champ `regle` en est volontairement ABSENT. C'est de la prose, et
    # elle cite souvent la doc (« CLAUDE.md : … ») : une règle parlant de
    # `.claude/` s'y appariait par simple coïncidence de sous-chaîne
    # (« claude » ⊂ « claudemd ») et passait pour couverte. Un faux
    # « couvert » est pire qu'un faux trou : il fait disparaître du rapport
    # une règle que rien ne surveille.
    signature = _signe(" ".join(
        f"{regle['nom']} {regle['motif'].pattern}" for regle in config.REGLES_MAISON
    ))

    restantes = []
    for relatif, numero, phrase, jetons in enoncees:
        if f"{relatif}:{numero}" in sources:
            continue
        signes = [_signe(jeton) for jeton in jetons]
        if any(len(signe) >= 4 and signe in signature for signe in signes):
            continue
        restantes.append((relatif, numero, phrase, jetons))

    return restantes


# `async def` compris : une suite asynchrone declare ses tests comme les autres.
_RX_DEF_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)", re.MULTILINE)


_RX_TEST_CITE = re.compile(r"\btest_\w+")


def _tests_du_projet() -> set[str]:
    """Les noms de fonctions de test declarees dans le projet."""
    noms: set[str] = set()
    # `tests.py` : la convention DJANGO, que le seul `test_*.py` ignorait —
    # un `hors_portee` qui citait un de ces tests etait declare « promesse
    # rompue » alors que le test existait.
    for glob in ("test_*.py", "*_test.py", "tests.py", "test.py"):
        for chemin in config.RACINE.rglob(glob):
            if config.sous_ignores(chemin):
                continue
            try:
                noms.update(_RX_DEF_TEST.findall(
                    chemin.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return noms


def _hors_portee_tenables() -> tuple[dict[str, str], list[str]]:
    """({source: raison} des declarations valides, list des promesses rompues).

    ⚠️ C'EST CE QUI EMPECHE `hors_portee` D'ETRE UN BOUTON « SILENCE ». Une
    declaration qui dit « couverte par test_machin » est une PROMESSE : si
    le test a ete renomme ou supprime, la regle n'est plus couverte par rien
    et doit redevenir visible. Sans cette verification, il suffirait d'ecrire
    une phrase pour faire taire le controle a jamais.
    """
    tenables: dict[str, str] = {}
    rompues: list[str] = []
    connus = _tests_du_projet() if config.HORS_PORTEE else set()

    for decl in config.HORS_PORTEE:
        manquants = [nom for nom in _RX_TEST_CITE.findall(decl["raison"])
                     if nom not in connus]
        if manquants:
            rompues.append(f"- **{decl['nom']}** ({decl['source']}) — annonce "
                           f"`{'`, `'.join(manquants)}`, introuvable(s) dans les tests")
            continue
        tenables[decl["source"]] = decl["raison"]
    return tenables, rompues


def controle_regles_declarees() -> Resultat:
    # On ne lit QUE les fichiers d'instructions IA. La doc générale décrit le
    # système ; seul le fichier d'instructions engage le projet sur des règles.
    if not config.DOCS_IA:
        return Resultat(
            "Regles enoncees vs controlees", "INDISPONIBLE",
            f"aucun fichier d'instructions IA ({', '.join(config.FICHIERS_IA)})"
            " - voir fichiers_ia dans .lintorn/config.toml",
            bloquant=False,
        )

    enoncees = regles_enoncees()
    if not enoncees:
        return Resultat(
            "Regles enoncees vs controlees", "INDISPONIBLE",
            "aucune regle reperee (une regle = une ligne de tableau, ou marquee"
            " **Regle**, qui impose quelque chose en citant du code entre `backticks`)",
            bloquant=False,
        )

    raisons, rompues = _hors_portee_tenables()
    # ⚠️ Un `hors_portee` ne compte que s'il désigne une règle ÉNONCÉE. Sa
    # `source` peut viser une ligne qui a bougé, ou qui n'a jamais énoncé de
    # règle : compté quand même, il faisait descendre les « controlees » sous
    # zéro — et il ne couvrait rien.
    tenables: dict[str, str] = {}
    for decl in config.HORS_PORTEE:
        ligne, _ = ligne_designee(decl["source"], enoncees)
        if ligne is not None and decl["source"] in raisons:
            tenables[ligne] = raisons[decl["source"]]
    fantomes = [f"- **{nom}** ({source}) : {pourquoi}"
                for nom, source, pourquoi in sources_a_recaler(enoncees)]
    sans_controle = [r for r in regles_sans_controle()
                     if f"{r[0]}:{r[1]}" not in tenables]

    total = len(enoncees)
    trou = len(sans_controle)
    motivees = len(tenables)
    # Le compte des `hors_portee` reste AFFICHE a vie : c'est lui qui rend
    # l'abus visible. Les faire disparaitre du resume rendrait la declaration
    # gratuite, et le controle aveugle a sa propre mise en sourdine.
    resume = f"{total} enoncee(s), {total - trou - motivees} controlee(s)"
    if motivees:
        resume += f", {motivees} hors de portee"

    if not trou and not rompues and not fantomes:
        return Resultat("Regles enoncees vs controlees", "OK",
                        f"{resume} - aucune sans reponse")

    detail = [] if not trou else [
        f"**{trou} regle(s) sur {total}** sont ecrites dans la doc sans qu'aucun",
        "`[[regles]]` du `.lintorn/regles.toml` ne les fasse respecter.",
        "",
        "Ce n'est pas une infraction : c'est un ecart entre ce que le projet",
        "**declare** et ce qu'il **verifie**. A chaque ligne, trois issues — ecrire",
        "la regle dans `regles.toml`, la declarer `hors_portee` avec sa raison, ou",
        "retirer la phrase de la doc si elle a vieilli.",
        "",
        "`lintorn regles` prepare les blocs `[[regles]]` a completer : un `motif`,",
        "ou la raison d'un `hors_portee`, une ligne par regle.",
        "",
    ]
    if fantomes:
        detail = [
            "**SANS OBJET** — la `source` de ces regles ne designe aucune regle enoncee :",
            "elles ne couvrent donc aucune ligne de la doc. Recale leur `source` :",
            "",
            *fantomes,
            "",
            *detail,
        ]
    if rompues:
        detail = [
            "**PROMESSES ROMPUES** — ces regles se declarent `hors_portee` en",
            "citant un test qui n'existe plus. Elles ne sont donc couvertes par",
            "rien, et redeviennent visibles :",
            "",
            *rompues,
            "",
            *detail,
        ]
    for chemin, numero, phrase, _ in sans_controle[:12]:
        court = phrase if len(phrase) <= 110 else phrase[:107] + "…"
        detail += [f"- {lien(chemin, numero)}", f"  > {court}", ""]
    if trou > 12:
        detail.append(f"*… et {trou - 12} autre(s).*")

    # VERIF, jamais ALERTE : rien n'est cassé, c'est un point à trancher à l'œil.
    # Bloquer un push la-dessus punirait quelqu'un qui a simplement DOCUMENTÉ
    # une intention — l'inverse du comportement qu'on veut encourager.
    suite = [f"{trou} SANS controle"] if trou else []
    if rompues:
        suite.append(f"{len(rompues)} hors_portee a recaler")
    if fantomes:
        suite.append(f"{len(fantomes)} source(s) a recaler")
    return Resultat(
        "Regles enoncees vs controlees", "VERIF",
        f"{resume}, {', '.join(suite)}",
        "\n".join(detail), bloquant=False, detail_markdown=True,
    )
