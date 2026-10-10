# Lintorn
"""Mémoire IA vs code : ce que lit l'assistant IA dit-il encore la vérité ?"""

from __future__ import annotations

import os
from pathlib import Path

from ... import config
from ...base import Resultat
from . import doc_vs_code


def _fiches_memoire() -> list[Path] | None:
    """Les fiches `.md` du dossier mémoire — None si le dossier est ILLISIBLE.

    ⚠️ `glob` rend une liste VIDE sur un dossier qu'on n'a pas le droit de
    lister : le contrôle annonçait « aucun fichier memoire » alors que des
    fiches s'y trouvaient, jamais lues. Deux causes, deux messages.
    """
    try:
        with os.scandir(config.MEMOIRE_IA) as entrees:
            return sorted(Path(entree.path) for entree in entrees
                          if entree.name.endswith(".md") and entree.is_file())
    except OSError:
        return None


def _annoncer_ressemblance(resultat: Resultat) -> Resultat:
    """Dit, sur la ligne même, qu'une mémoire n'a été reconnue qu'à son nom.

    ⚠️ Un nom de dossier qui finit comme celui du projet peut appartenir à un
    AUTRE projet : le verdict porterait alors sur la mémoire d'un voisin.
    L'annoncer dans le seul détail ne suffit pas — un vert en jette le
    détail. C'est le résumé qui le porte.
    """
    if not config.MEMOIRE_PAR_RESSEMBLANCE:
        return resultat
    avis = (f"Memoire {config.MEMOIRE_IA_ORIGINE}. Le dossier exact de ce projet est "
            "introuvable : celui-ci a ete retenu parce que son nom finit comme celui du "
            "projet. Ce peut etre la memoire d'un AUTRE projet du meme nom. Si c'est bien "
            "la sienne, confirme-le dans .lintorn/.env : LINTORN_MEMOIRE=chemin/de/ce/dossier/memory")
    resultat.resume = f"{config.MEMOIRE_IA_ORIGINE} - {resultat.resume}"
    resultat.detail = f"{avis}\n\n{resultat.detail}" if resultat.detail else avis
    resultat.detail_meme_au_vert = True
    return resultat


def controle_memoire_ia() -> Resultat:
    """La mémoire de l'assistant — CONSULTATIF, ne bloque jamais.

    Pourquoi la surveiller quand même : elle vit HORS du dépôt, donc elle n'est
    pas versionnée, personne ne la relit, et rien ne la confronte au code. Un
    chemin périmé y survit donc indéfiniment — et l'assistant continue de le
    citer avec assurance, longtemps après la disparition du fichier.
    """
    return _annoncer_ressemblance(_controle_memoire_ia())


def _controle_memoire_ia() -> Resultat:
    if config.MEMOIRE_IA is None:
        # On dit POURQUOI on ne trouve rien, et comment reprendre la main :
        # un « INDISPONIBLE » sans explication se confond avec un « rien à
        # signaler » au bout de trois lectures.
        return Resultat(
            "Memoire IA vs code", "INDISPONIBLE",
            f"dossier memoire introuvable ({config.MEMOIRE_IA_ORIGINE})"
            " - voir LINTORN_MEMOIRE dans .lintorn/.env",
            bloquant=False,
        )

    fichiers = _fiches_memoire()
    if fichiers is None:
        return Resultat("Memoire IA vs code", "INDISPONIBLE",
                        "dossier memoire ILLISIBLE (droits) - rien n'a ete lu", bloquant=False)
    if not fichiers:
        return Resultat("Memoire IA vs code", "INDISPONIBLE", "aucun fichier memoire", bloquant=False)

    return doc_vs_code._verifier_documents("Memoire IA vs code", fichiers, bloquant_possible=False)
