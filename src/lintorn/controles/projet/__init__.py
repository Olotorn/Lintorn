# Lintorn
"""Les contrôles qui jugent LE PROJET : sa doc, la mémoire de son IA, ses règles.

Ce sont ceux qu'aucun outil du marché ne fait à ta place. Ceux qui surveillent
Lintorn LUI-MÊME vivent à côté, dans `controles/outillage/`.

    chemins_cites.py      qu'est-ce qu'un chemin cité, et existe-t-il ?
    doc_vs_code.py        la documentation ment-elle ?
    memoire_ia.py         la mémoire de l'assistant IA ment-elle ?
    fraicheur_memoire.py  la mémoire a-t-elle vieilli depuis sa vérification ?
    regles_maison.py      les [[regles]] de regles.toml sont-elles tenues ?
    regles_enoncees.py    les règles écrites pour l'IA sont-elles contrôlées ?
"""

from . import (
    chemins_cites,
    doc_vs_code,
    fraicheur_memoire,
    memoire_ia,
    regles_enoncees,
    regles_maison,
)

__all__ = ['chemins_cites', 'doc_vs_code', 'fraicheur_memoire', 'memoire_ia', 'regles_enoncees', 'regles_maison']
