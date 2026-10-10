# Lintorn
"""Comment montrer un chemin à un humain : depuis la racine du projet."""

from __future__ import annotations

from . import config


def relatif(chemin, resoudre: bool = False) -> str:
    """Un chemin tel qu'on le lit depuis la racine du projet (`.` pour elle).

    Absolu s'il en sort — mais jamais quand on peut l'éviter : il porte le nom
    de l'utilisateur et celui de sa machine, or ce texte part dans un rapport
    que le projet versionne.

    `resoudre` suit d'abord les liens symboliques : un venv lié ailleurs
    s'affiche alors là où il vit vraiment.
    """
    try:
        return (chemin.resolve() if resoudre else chemin).relative_to(config.RACINE).as_posix()
    except (ValueError, OSError):
        return str(chemin)
