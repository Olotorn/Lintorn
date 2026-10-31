# Lintorn
"""`lintorn rapport` et `lintorn rapport-push` : ouvrir le dernier rapport, sans rien relancer."""

from __future__ import annotations

import webbrowser

from .. import chemins, config


def ouvrir(push: bool) -> int:
    """La page web du dernier rapport, dans le navigateur ; le Markdown s'il n'y a qu'elle.

    ⚠️ Seulement un rapport ÉCRIT ICI : versionné ou lien symbolique, il vient
    d'ailleurs. Une page posée par un dépôt piégé s'ouvrirait dans le
    navigateur de l'utilisateur, et un faux rapport tout vert y serait cru.
    """
    rapport = config.rapport_du(push)
    page = rapport.with_suffix(".html")
    cible = page if page.is_file() else rapport
    if not cible.is_file():
        if push:
            print("Pas encore de rapport de push : il s'ecrit au premier `git push` avec le hook.")
        else:
            print("Pas encore de rapport : lance `lintorn` (ou `lintorn rapide`).")
        return 1
    if cible.is_symlink() or config.suivi_par_git(cible):
        print(f"{chemins.relatif(cible)} est versionne ou est un lien : il n'a pas ete ecrit")
        print("par Lintorn sur cette machine. Il n'est pas ouvert. Relance `lintorn` pour le tien.")
        return 1
    print(chemins.relatif(cible))
    try:
        ouvert = webbrowser.open(cible.resolve().as_uri())
    except (OSError, webbrowser.Error):
        ouvert = False
    if not ouvert:
        print("Pas de navigateur ici : ouvre ce fichier toi-meme.")
    return 0
