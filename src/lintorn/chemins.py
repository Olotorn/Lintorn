# Lintorn
"""Comment montrer un chemin à un humain : depuis la racine du projet."""

from __future__ import annotations

import os
from pathlib import Path

from . import config


def relatif(chemin, resoudre: bool = False) -> str:
    """Un chemin tel qu'on le lit depuis la racine du projet (`.` pour elle).

    Absolu s'il sort du dépôt — mais jamais quand on peut l'éviter : il porte
    le nom de l'utilisateur et celui de sa machine, or ce texte part dans un
    rapport que le projet versionne. Dans le dépôt d'un sous-projet de monorepo,
    `../.husky/pre-push` le dit sans eux.

    `resoudre` suit d'abord les liens symboliques : un venv lié ailleurs
    s'affiche alors là où il vit vraiment.
    """
    try:
        chemin = chemin.resolve() if resoudre else chemin
        return chemin.relative_to(config.RACINE).as_posix()
    except (ValueError, OSError):
        pass
    try:
        sommet = config.SOMMET_GIT
        if sommet is not None and Path(chemin).resolve().is_relative_to(Path(sommet).resolve()):
            return Path(os.path.relpath(Path(chemin).resolve(), Path(config.RACINE).resolve())).as_posix()
    except (ValueError, OSError):
        pass
    return str(chemin)
