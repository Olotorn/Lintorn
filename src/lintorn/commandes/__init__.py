# Lintorn
"""Une commande de Lintorn = un fichier. Le sommaire qui les aiguille : `cli.py`."""

from importlib import import_module

__all__ = ["aide", "audit", "confiance", "corrige", "dossier_lintorn", "hook", "init", "outils",
           "rapport", "regles", "securite", "status"]


def __getattr__(nom: str):
    """Chaque commande n'est importée qu'au moment où l'on s'en sert (pourquoi : `cli.py`)."""
    if nom in __all__:
        return import_module(f".{nom}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {nom!r}")
