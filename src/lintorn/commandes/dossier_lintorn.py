# Lintorn
"""Préparer `.lintorn/` : son `.gitignore` garde la config et jette les sorties."""

from __future__ import annotations

from .. import base

# Le `.gitignore` que `--init` pose DANS `.lintorn/`.
#
# POURQUOI LA, ET PAS DANS CELUI DU PROJET. Editer le `.gitignore` de
# quelqu'un est intrusif, et pose une question insoluble a la relance : que
# faire si l'utilisateur a modifie les lignes ? Un fichier a nous, dans un
# dossier a nous, se supprime avec le dossier et ne touche a rien d'autre.
#
# Et surtout : l'etape « ajoute ces deux lignes a ton .gitignore » se recopiait
# mal. Un utilisateur a copie la ligne de PROSE, backticks compris, et oublie
# la negation — sa configuration s'est retrouvee ignoree, sans aucun message.
# Une etape qu'on supprime est une etape qu'on ne peut plus rater.
#
# ⚠️ Ce fichier ne peut RIEN si une regle parente exclut le dossier entier
#    (`.lintorn/` avec la barre finale) : git n'y descend meme pas. C'est le
#    seul cas d'echec, et `--init` le detecte pour le dire.
_GITIGNORE_INTERNE = """\
# Ecrit par `lintorn --init`.
#
# Les sorties de Lintorn se regenerent a chaque audit : elles n'ont rien a
# faire dans un depot. La CONFIG, elle, se versionne — c'est une decision
# d'equipe, pas un artefact de ta machine.
*
!.gitignore
!config.toml
!regles.toml
"""


# La ligne qui prouve que ce `.gitignore` est le NOTRE. Sans elle, on
# risquerait de modifier celui qu'un dev a ecrit a la main.
_SIGNATURE_GITIGNORE = "# Ecrit par `lintorn --init`."

# Les fichiers que Lintorn veut voir VERSIONNES dans `.lintorn/`.
_A_VERSIONNER = ("!.gitignore", "!config.toml", "!regles.toml")


def poser_gitignore_interne(dossier) -> str:
    """Pose `.lintorn/.gitignore`, ou complete celui qu'on a deja pose.

    N'ecrase JAMAIS celui d'un humain : on ne touche qu'a un fichier portant
    notre propre signature.

    ⚠️ Le COMPLETER n'est pas un luxe. `regles.toml` est arrive apres. Sans
    cette mise a jour, tout projet configure avant lui verrait son fichier de
    regles ignore par git, donc absent du depot — silencieusement, ce qui est
    la panne que Lintorn combat partout ailleurs.
    """
    fichier = dossier / ".gitignore"
    # ⚠️ AVANT `exists()` : un lien PENDANT (vers un fichier absent) répond
    # « n'existe pas », et l'écriture aurait créé sa cible hors du projet.
    if fichier.is_symlink():
        return "lien symbolique, laisse tel quel"
    if not fichier.exists():
        try:
            base.ecrire_fichier_du_projet(fichier, _GITIGNORE_INTERNE)
        except OSError as erreur:
            return f"NON ecrit ({erreur})"
        return "ecrit - les sorties restent hors du depot, la config s'y versionne"

    try:
        contenu = fichier.read_text(encoding="utf-8")
    except OSError as erreur:
        return f"illisible ({erreur})"

    if _SIGNATURE_GITIGNORE not in contenu:
        return "ecrit a la main, laisse tel quel"

    manquants = [ligne for ligne in _A_VERSIONNER if ligne not in contenu]
    if not manquants:
        return "deja a jour"
    try:
        with fichier.open("a", encoding="utf-8") as flux:
            flux.write("\n".join(manquants) + "\n")
    except OSError as erreur:
        return f"NON complete ({erreur})"
    return f"complete : {', '.join(manquants)}"
