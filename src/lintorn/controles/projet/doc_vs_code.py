# Lintorn
"""Doc vs code : chaque chemin cité par la documentation existe-t-il encore ?

Le code a ruff, tsc et les tests pour le surveiller. La documentation, elle,
n'a RIEN : personne ne vérifie qu'elle décrit encore le projet. Elle affirme
donc tranquillement qu'un fichier existe alors qu'il a été supprimé, ou qu'un
module est écrit dans un langage qu'il a quitté depuis longtemps.

C'est sans gravité tant qu'un humain la lit en diagonale. Ça ne l'est plus
quand un assistant IA la lit intégralement et agit dessus.
"""

from __future__ import annotations

import re
from pathlib import Path

from ... import config
from ...base import Resultat, lien
from . import chemins_cites

# Trois genres citent des fichiers absents sans mentir pour autant :
#
#   1. la note prospective — marquée à la main
#   2. le JOURNAL DE VERSIONS — il cite ce qui existait A L'EPOQUE
#   3. le TUTORIEL — il apprend au lecteur à créer des fichiers CHEZ LUI
#
# MESURÉ SUR FASTAPI, 1693 documents. Sans cette distinction : 460 chemins
# bloquants au premier lancement — un mur qui fait fermer l'outil. Avec la
# seule échappatoire existante (`docs_exclus = ["docs/*"]`) : 98 % de la
# documentation cessait d'être lue, pour un « OK » sur 2 chemins. Le remède
# était pire que le mal : c'est le faux vert que Lintorn combat partout.
#
# LE SIGNAL. La répartition est nette, et bimodale : 146 documents n'ont AUCUN
# chemin absent, 207 les ont TOUS absents. Un document décrit ce projet, ou il
# parle d'autre chose — rarement les deux. D'où la règle, énonçable en une
# phrase : **si la majorité de ce qu'un document cite n'existe pas ici, il ne
# décrit pas ce projet.**
#
# ⚠️ SEUIL DELIBEREMENT ROND. « Plus de la moitié » se justifie tout seul.
#    L'ajuster jusqu'à ce qu'un projet précis passe au vert reviendrait à
#    truquer la mesure — et à casser ailleurs. Vérifié sur Lintorn et sur un
#    vrai projet Django : ZERO document requalifié, aucune trouvaille perdue.
_RX_JOURNAL = re.compile(r"(change ?log|(?<![a-z])changes(?![a-z])|release[-_ ]notes?|history|news)", re.I)
# Un journal rangé en dossier : `docs/release-notes/version-3.7.md`. Le NOM
# entier du dossier, pas un morceau : `apps/news/` est une fonctionnalité.
_RX_DOSSIER_JOURNAL = re.compile(r"change[-_ ]?logs?|release[-_ ]?notes?|releases", re.I)


_SEUIL_AUTRE_GENRE = 0.5


def _genre_du_document(doc, texte: str, cites: int, absents: int) -> str:
    """Ce qui autorise ce document à citer des fichiers absents, ou "" sinon."""
    if "lintorn:prospectif" in texte:
        return "doc prospectif"
    if _RX_JOURNAL.search(doc.name) or any(
            _RX_DOSSIER_JOURNAL.fullmatch(dossier) for dossier in _dossiers_sous_la_racine(doc)):
        return "journal de versions"
    # `cites >= 2` : sur une seule citation, un taux de 100 % ne veut rien dire.
    # C'est précisément le cas d'un vrai pourrissement de doc — un fichier
    # renommé, cité une fois. On ne l'excuse pas.
    if cites >= 2 and absents / cites > _SEUIL_AUTRE_GENRE:
        return f"{absents}/{cites} absents : ne decrit pas ce projet"
    return ""


def _dossiers_sous_la_racine(doc: Path) -> tuple[str, ...]:
    try:
        return doc.parent.relative_to(config.RACINE).parts
    except ValueError:
        return ()


def _docs_ecartes(ecartes: dict[str, list[str]]) -> tuple[str, str]:
    """(fragment du résumé, section du détail) des documents qu'on n'a pas lus."""
    if not ecartes:
        return "", ""
    resume = "".join(f", {len(docs)} doc(s) {raison} non lu(s)"
                     for raison, docs in sorted(ecartes.items()))
    detail = ("**NON LUS** — ces documents du dépôt n'ont pas été vérifiés : ils "
              "décrivent autre chose que le projet. La raison est indiquée à chaque "
              "ligne.\n\n"
              + "\n".join(f"- `{doc}` *({raison})*"
                          for raison, docs in sorted(ecartes.items()) for doc in docs))
    return resume, detail


def _verifier_documents(titre: str, documents: list, bloquant_possible: bool,
                        ecartes: dict[str, list[str]] | None = None) -> Resultat:
    """Cœur du contrôle : les chemins cités dans ces documents existent-ils ?

    `bloquant_possible=False` → on rapporte sans jamais bloquer. C'est le cas
    de la mémoire de l'IA : elle contient des INTENTIONS (« on créera la
    commande purger_corbeille ») autant que des faits. Un fichier pas encore
    écrit n'est pas un mensonge, et la mémoire de l'assistant ne doit jamais
    empêcher un push du dev.

    `ecartes` : les documents mis de côté en amont, par raison. Ils sont
    COMPTÉS dans le résumé — une doc sautée sans un mot passerait pour lue.
    """
    ecartes_resume, ecartes_detail = _docs_ecartes(ecartes or {})
    # ⚠️ GARDE-FOU : aucun document à analyser = le contrôle est HORS SERVICE,
    # pas « au vert ». C'est arrivé le 30/07 (les .md avaient été déplacés) :
    # l'outil affichait « OK — 0 chemin vérifié » et ne surveillait plus rien.
    # Un contrôle muet est plus dangereux qu'un contrôle rouge.
    # `is_file()` et non `exists()` : un tube nommé `docs.md` existe, et sa
    # lecture ne rend jamais la main — le `git push` gelait avec.
    existants = [d for d in documents if d.is_file()]
    if not existants:
        return Resultat(
            titre, "INDISPONIBLE",
            "AUCUN document trouve - le controle ne verifie rien !" + ecartes_resume,
            ecartes_detail, bloquant=False, detail_markdown=bool(ecartes_detail),
        )

    index_noms = chemins_cites.indexer_fichiers()
    arbre = chemins_cites._arborescence()
    autre_genre = 0               # documents requalifiés : tutoriel, journal…
    certains: list[str] = []      # cité AVEC extension et absent → le doc ment
    incertains: list[str] = []    # sans extension → peut être une tournure de phrase
    non_verifies: list[tuple[str, str]] = []  # (ligne, raison) : ni juste ni faux
    verifies = 0
    fonctions = 0                 # fonctions citées `ainsi()`, comptées à part des chemins
    code: chemins_cites.Code | None = None   # lu au premier besoin : la plupart des docs n'en citent pas
    illisibles: list[str] = []    # impossibles à ouvrir : droits, autre propriétaire
    # (doc, texte, cités, chemins absents, fonctions absentes avec « qualifiée par le projet »)
    lus: list[tuple[Path, str, int, list[str], list[tuple[str, bool]]]] = []

    for doc in existants:
        # `errors="replace"` couvre un contenu mal encodé, pas un fichier qu'on
        # n'OUVRE pas (droits, fichier d'un autre utilisateur) : il faisait
        # tomber le contrôle, et le rapport avec. Mis de côté et DIT plus bas —
        # un document sauté en silence passerait pour vérifié.
        try:
            texte = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            illisibles.append(doc.relative_to(config.RACINE).as_posix()
                              if doc.is_relative_to(config.RACINE) else doc.name)
            continue
        texte, citations = chemins_cites._citations(texte, doc.suffix.lower())

        deja_vus: set[str] = set()
        cites = 0
        absents: list[str] = []
        fonctions_absentes: list[tuple[str, bool]] = []
        for token in citations:
            token = token.strip().rstrip("/").removeprefix("./")
            fonction = chemins_cites.fonction_citee(token)
            if fonction and token not in deja_vus:
                deja_vus.add(token)
                code = code or chemins_cites.indexer_code()
                fonctions += 1
                cites += 1
                qualificatif, nom = fonction
                if nom not in code.identifiants:
                    # `base.x()` : le qualificatif nomme un module DU projet, c'est
                    # une affirmation sur lui. `x()` seul peut venir d'ailleurs.
                    fonctions_absentes.append(
                        (token, qualificatif.split(".")[0] in code.modules))
                continue
            if not chemins_cites.est_un_chemin(token) or token in deja_vus:
                continue
            deja_vus.add(token)
            verifies += 1
            cites += 1
            if not chemins_cites.existe(token, index_noms, depuis=doc.parent):
                absents.append(token)
        lus.append((doc, texte, cites, absents, fonctions_absentes))

    # Une seule question à git pour tous les documents : il répond en bloc.
    locaux = chemins_cites._locaux_par_construction(
        [(doc.parent, token) for doc, _, _, absents, _ in lus for token in absents], arbre)

    for doc, texte, cites, absents, fonctions_absentes in lus:
        # ── Document PROSPECTIF ──────────────────────────────────────────────
        # Une note de conception, une roadmap, un ADR ou un post-mortem citent
        # LÉGITIMEMENT des fichiers qui n'existent pas : pas encore (module à
        # écrire) ou plus (fichier supprimé, cité justement parce qu'il a
        # disparu). Sans échappatoire, Lintorn bloque le push et pousse à écrire
        # ces documents AILLEURS que dans les dossiers scannés — il fabrique
        # alors l'angle mort qu'il prétend supprimer. Sans échappatoire, il
        # recale jusqu'à la note qui décrit sa propre correction.
        #
        #     <!-- lintorn:prospectif -->   en tête du document
        #
        # → ses chemins introuvables deviennent consultatifs (VERIF), jamais
        #   bloquants. Le contrôle continue de les LISTER : on informe, on
        #   n'interdit pas.
        # On collecte les trouvailles de CE document avant de trancher : le
        # genre ne se connait qu'une fois le document entierement lu.
        doc_certains: list[str] = []
        doc_incertains: list[str] = []
        doc_locaux = 0
        # La mémoire vit HORS du dépôt : pas de lien cliquable possible,
        # on se contente de son nom de fichier.
        if doc.is_relative_to(config.RACINE):
            source = lien(doc.relative_to(config.RACINE).as_posix())
        else:
            source = f"`{doc.name}`"

        for token in absents:
            ligne = f"{source} → `{token}`"
            # Un fichier que le `.gitignore` du projet déclare local
            # (`configuration.py` à copier, un secret, un journal) ne sera
            # JAMAIS dans le dépôt : la doc a raison de le citer, et bloquer
            # le push dessus serait faux. Ni juste ni faux : compté à part.
            if (doc.parent, token) in locaux:
                doc_locaux += 1
                non_verifies.append((f"{ligne} *(gitignore : fichier local)*",
                                     "gitignore(s)"))
            # ⚠️ `~/.config/outil.toml`, `/etc/nginx/nginx.conf` : une doc parle
            # AUSSI de la machine du lecteur. Ces chemins-là ne sont pas des
            # affirmations sur le dépôt, et Lintorn bloquait le push dessus.
            # On les LISTE quand même — consultatif : rien n'en garantit la
            # justesse non plus.
            elif token.startswith(("~", "/")) or re.match(r"^[A-Za-z]:[\\/]", token):
                doc_incertains.append(f"{ligne} *(hors du depot)*")
            # Une extension explicite = une affirmation vérifiable. Sans extension,
            # ça peut être du texte → consultatif, on ne bloque pas dessus.
            elif (re.search(r"\.\w{2,4}(:\d|$)", token)
                  or re.sub(r":\d+(-\d+)?$", "", token).endswith(config.EXTENSIONS)):
                doc_certains.append(ligne)
            else:
                doc_incertains.append(ligne)
        for token, du_projet in fonctions_absentes:
            ligne = f"{source} → `{token}` *(nom absent du code)*"
            (doc_certains if du_projet else doc_incertains).append(ligne)

        # Un fichier local reste ABSENT du dépôt pour juger le genre. Le
        # compter présent faisait basculer des documents excusés jusque-là,
        # et remontait leurs exemples en introuvables bloquants.
        genre = _genre_du_document(doc, texte, cites,
                                   len(doc_certains) + len(doc_incertains) + doc_locaux)
        if genre:
            # Requalifie : on LISTE toujours, on ne bloque plus.
            autre_genre += 1
            incertains += [f"{ligne} *({genre})*"
                           for ligne in doc_certains + doc_incertains]
        else:
            certains += doc_certains
            incertains += doc_incertains

    # ⚠️ SECOND GARDE-FOU, jumeau de celui du haut. Les documents existent,
    # mais aucun ne cite le moindre chemin : il n'y a rien eu a verifier, et
    # afficher « OK » laisserait croire que la documentation a ete controlee.
    #
    # C'est le meme mensonge que « 0 document trouve » traite plus haut, sauf
    # qu'il survient un cran plus loin — une doc qui parle sans jamais citer
    # de fichier entre backticks. Vu sur un projet Go dont le README n'en
    # contenait aucun : le controle affichait OK sans avoir rien lu.
    illisibles_md = ("**ILLISIBLES** — Lintorn n'a pas pu les ouvrir (droits ?). Ils "
                     "n'ont **pas** été vérifiés : ce n'est pas un feu vert.\n\n"
                     + "\n".join(f"- `{nom}`" for nom in sorted(illisibles)))

    # Le premier garde-fou, un cran plus loin : des documents existent, mais
    # aucun n'a pu être ouvert. Rien n'a été lu, rien n'a été vérifié.
    if len(illisibles) == len(existants):
        return Resultat(
            titre, "INDISPONIBLE",
            f"{len(existants)} document(s), tous ILLISIBLES - le controle ne verifie rien !",
            illisibles_md, bloquant=False, detail_markdown=True,
        )

    if verifies == 0 and fonctions == 0:
        lus = len(existants) - len(illisibles)
        return Resultat(
            titre, "INDISPONIBLE",
            f"{lus} document(s) lu(s), AUCUN chemin cite - rien a verifier"
            + (f", {len(illisibles)} ILLISIBLE(S)" if illisibles else "")
            + ecartes_resume,
            (illisibles_md + "\n\n" if illisibles else "") +
            (ecartes_detail + "\n\n" if ecartes_detail else "") +
            "Lintorn ne verifie que les chemins ecrits comme du code : "
            "`services/api.ts` en Markdown (`.md`, `.mdx`), ``services/api.ts`` "
            "ou :file:`services/api.ts` en reStructuredText (`.rst`). Le meme "
            "nom en pleine phrase n'est qu'un mot.\n\n"
            "Si ta documentation cite des fichiers en pleine phrase, ecris-les "
            "ainsi et ce controle prendra vie. Une doc dans un autre format "
            "(`.txt`, `.adoc`) n'est pas lue du tout.",
            bloquant=False,
            detail_markdown=True,
        )

    resume = f"{verifies} chemin(s) cite(s)"
    if fonctions:
        resume += f", {fonctions} fonction(s) citee(s)"
    resume += f", {len(certains)} introuvable(s)"
    if incertains:
        resume += f", {len(incertains)} a verifier"
    # ⚠️ ANNONCE OBLIGATOIRE. Requalifier 170 documents sans le dire serait
    # exactement le silence que Lintorn combat : l'utilisateur croirait sa doc
    # entierement controlee. On chiffre ce qu'on a mis de cote.
    if autre_genre:
        resume += f", {autre_genre} doc(s) d'un autre genre"
    if illisibles:
        resume += f", {len(illisibles)} ILLISIBLE(S)"
    # Ce qui n'a pas pu être vérifié est COMPTÉ, par raison : sans ce
    # compte, un chemin écarté passerait pour un chemin juste.
    if non_verifies:
        par_raison: dict[str, int] = {}
        for _, raison in non_verifies:
            par_raison[raison] = par_raison.get(raison, 0) + 1
        resume += (f", {len(non_verifies)} non verifie(s) : "
                   + ", ".join(f"{n} {raison}" for raison, n in sorted(par_raison.items())))
    resume += ecartes_resume

    sections = []
    if certains:
        sections.append("**INTROUVABLES — le document ment :**\n\n"
                        + "\n".join(f"- {x}" for x in sorted(set(certains))))
    if incertains:
        sections.append("**À VÉRIFIER** — cité sans extension (peut-être une tournure de "
                        "phrase, ou un fichier à créer), une fonction que le code ne "
                        "nomme nulle part sans dire de quel module, ou cité par un document qui ne "
                        "décrit pas ce projet : tutoriel, journal de versions, note "
                        "prospective. La raison est indiquée à chaque ligne.\n\n"
                        + "\n".join(f"- {x}" for x in sorted(set(incertains))))
    if non_verifies:
        sections.append("**NON VÉRIFIÉS** — Lintorn ne peut pas trancher sur ces "
                        "chemins : ils ne comptent ni comme justes, ni comme faux. "
                        "La raison est indiquée à chaque ligne.\n\n"
                        + "\n".join(f"- {x}" for x in sorted({x for x, _ in non_verifies})))
    if illisibles:
        sections.append(illisibles_md)
    if ecartes_detail:
        sections.append(ecartes_detail)
    detail = "\n\n".join(sections)

    if not certains and not incertains and not illisibles:
        # Vert, mais ce qui a été mis de côté reste NOMMÉ dans le rapport.
        return Resultat(titre, "OK", resume, detail, detail_markdown=True,
                        detail_meme_au_vert=bool(detail))

    # ALERTE si un chemin est faux · VERIF s'il n'y a que des « à vérifier ».
    # Avant, ce cas retombait sur OK — et `ecrire_rapport` n'écrit pas le
    # détail d'un OK : le résumé annonçait « 1 a verifier » sans jamais dire
    # LEQUEL. L'information était produite puis jetée (trouvé par le dev).
    statut = "ALERTE" if certains else "VERIF"

    return Resultat(
        titre, statut, resume, detail,
        bloquant=bool(certains) and bloquant_possible,
        detail_markdown=True,
    )


def controle_doc() -> Resultat:
    """La doc du dépôt (CLAUDE.md, ARCHITECTURE.md…) — peut bloquer un push."""
    return _verifier_documents("Doc vs code", config.DOCS_A_VERIFIER, bloquant_possible=True,
                               ecartes=config.DOCS_ECARTES)
