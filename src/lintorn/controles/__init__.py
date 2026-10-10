# Lintorn
"""Les contrôles internes de Lintorn — ceux qu'aucun outil externe ne fait.

    projet/     ils jugent LE PROJET : sa doc, la mémoire de son IA, ses règles
    outillage/  ils surveillent LINTORN : sa config, son hook, son python
"""

from . import outillage, projet

__all__ = ["outillage", "projet"]
