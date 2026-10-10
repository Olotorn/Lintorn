# Lintorn
"""Le verdict dans le terminal, et le code de sortie qui va avec."""

from __future__ import annotations

from .. import __version__, chemins, config
from ..base import MARQUEUR, Resultat
from ..controles import outillage


def signaler_non_bloquants(resultats: list[Resultat]) -> int:
    """Nomme les alertes NON BLOQUANTES avant de rendre la main. Rend leur nombre.

    ⚠️ LE VERDICT QUI DEMENTAIT SON PROPRE RAPPORT.

    `en_echec` ne retient que les alertes BLOQUANTES. Or les deux controles qui
    surveillent les garde-fous — le hook pre-push, et le python avec lequel les
    outils ont tourne — sont non bloquants par construction : quand le hook
    n'est pas branche, bloquer un push serait de toute facon impossible.

    Ils s'affichaient donc `[ !! ]` dans le rapport, et la derniere ligne
    annoncait trois lignes plus bas « rien a signaler ». Qui ne lit que le
    verdict — c'est-a-dire tout le monde, une fois l'outil devenu routine —
    repartait en croyant son push protege par un hook mort.

    Le rapport disait vrai, le resume le dementait. C'est la meme panne que
    partout ailleurs ici, au dernier etage.
    """
    signales = [r for r in resultats
                if r.statut in ("ALERTE", "ERREUR") and not r.bloquant]
    if not signales:
        return 0

    print(f"{len(signales)} controle(s) non bloquant(s) signalent quelque chose :")
    for r in signales:
        print(f"    - {r.titre} : {r.resume}")
    return len(signales)


def outils_muets(resultats: list[Resultat]) -> list[Resultat]:
    """Les OUTILS accordés qui n'ont pas répondu — donc rien vérifié.

    Pas des alertes : les lister une à une noierait les vraies sous le bruit
    des outils absents. Mais la conclusion n'a plus le droit de dire « tous
    les controles sont au vert » par-dessus : OSV tombé sur un délai réseau
    la laissait l'affirmer, la veille de trois failles critiques. Ce que
    `--rapide` saute exprès n'en fait pas partie.
    """
    outils = {entree["titre"] for entree in config.COMMANDES}
    return [r for r in resultats
            if r.statut == "INDISPONIBLE" and r.titre in outils
            and not r.resume.startswith("NON EXECUTE (mode --rapide)")]


# Pour le hook seulement : rien ne bloque, mais des outils n'ont rien vérifié.
# Sans ce code, le hook concluait « Lintorn OK » sous la liste des outils muets
# — et c'est la dernière ligne qu'on lit. Hors du hook, 0 : la CI ne doit pas
# échouer sur un outil absent.
NON_VERIFIE = 3


def afficher(resultats: list[Resultat], rapport_ecrit: bool, manque_config: bool,
             hook: bool = False) -> int:
    """Imprime le verdict dans le terminal. Rend le code de sortie de Lintorn."""
    echecs = [r for r in resultats if r.en_echec]
    # ⚠️ Sur un projet sans config, les messages renvoyaient vers
    # `.lintorn/config.toml` — un fichier qui n'existe PAS tant que `--init`
    # n'a pas tourne. On envoyait donc l'utilisateur vers un fichier fantome
    # sans jamais lui dire comment le creer.
    # Console volontairement en ASCII : le hook git tourne sous Git Bash, qui
    # n'affiche pas l'UTF-8 correctement. Le rapport, lui, garde les accents.
    print(f"\n=== Lintorn {__version__} - RAPPORT AUDIT ===")
    for r in resultats:
        print(f"{MARQUEUR[r.statut]} {r.titre:<34} {r.resume}")

    if rapport_ecrit:
        # `_relatif` et pas `relative_to` : une sortie rangee ailleurs que sous
        # la racine leve, et faisait tomber Lintorn APRES tous les controles.
        print(f"\nLe rapport de Lintorn : {chemins.relatif(config.RAPPORT)}"
              + (f"  ·  la meme chose en page web : "
                 f"{chemins.relatif(config.RAPPORT.with_suffix('.html'))}"
                 if config.RAPPORT.with_suffix(".html").is_file() else ""))

    if manque_config:
        print("\nCe projet n'a pas encore de configuration Lintorn.")
        print("    lintorn init        # la mettre en place")
        print("    lintorn guide       # comprendre ce que tu viens de lire")
    if echecs:
        print(f"Lintorn signale {len(echecs)} controle(s) bloquant(s) en alerte :")
        for r in echecs:
            print(f"    - {r.titre}")
        signaler_non_bloquants(resultats)
        return 1
    # ⚠️ LE FAUX VERT DU DERNIER ETAGE.
    #
    # « Tous les controles sont au vert » est techniquement exact quand aucun
    # n'est en alerte — y compris quand AUCUN n'a pu tourner. Sur un projet
    # dont Lintorn ne connait ni le langage ni la doc, il affichait donc un
    # feu vert triomphal apres n'avoir strictement rien verifie.
    #
    # Un verdict global doit refleter ce qui a ete CONTROLE, pas seulement
    # l'absence d'alerte.
    a_tourne = [
        r for r in resultats
        # VERIF compte : « 6 chemins verifies, 2 a confirmer » a bien tourne.
        if r.statut in ("OK", "ALERTE", "ERREUR", "VERIF")
        and r.titre not in outillage.TITRES_OUTILLAGE
    ]
    if not a_tourne:
        print("AUCUN controle n'a pu tourner sur ce projet.")
        print("Ce n'est PAS un feu vert : Lintorn n'a rien verifie du tout.")
        print("    lintorn init               # lui dire quoi surveiller ici")
        print("    lintorn outils             # ce qui s'applique a ce projet")
        signaler_non_bloquants(resultats)
        return NON_VERIFIE if hook else 0

    muets = outils_muets(resultats)
    if signaler_non_bloquants(resultats):
        print("Aucun ne bloque le push. Le rapport dit ce que chacun a trouve.")
    elif muets:
        print("Rien a signaler sur ce qui a tourne.")
    else:
        print("Lintorn n'a rien a signaler : tous les controles bloquants sont au vert.")
    if muets:
        print(f"{len(muets)} outil(s) n'ont rien verifie : "
              + ", ".join(r.titre for r in muets))
    return NON_VERIFIE if muets and hook else 0
