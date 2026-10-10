# Lintorn
"""`lintorn confiance` : donner à Lintorn l'accord de lancer ses outils dans ce projet."""

from __future__ import annotations

from .. import confiance, noyau


def accorder(sans_demander: bool = False) -> int:
    """Pose l'accord depuis un terminal, sans attendre qu'un audit le réclame.

    C'est le seul chemin pour un hook git ou une CI, qui n'ont personne à qui
    poser la question. `--oui` note l'accord sans le demander : à réserver aux
    scripts qui maîtrisent le dépôt.
    """
    a_lancer = noyau.a_lancer(rapide=False)
    if not a_lancer:
        # Dire qu'il n'y avait rien à accorder, plutôt qu'un « c'est fait » creux.
        print("Rien a accorder : Lintorn n'a aucune commande a lancer dans ce projet.")
        return 0
    manquants = confiance.nouveaux(a_lancer)
    if not manquants:
        print("Tout ce que Lintorn lance dans ce projet est deja accorde.")
        print(f"(Notes dans {confiance.fichier()} - supprimer la ligne du projet pour retirer l'accord.)")
        return 0
    if not sans_demander:
        if not confiance.terminal():
            print("Aucun terminal pour poser la question : rien n'est accorde.")
            print("Lance `lintorn confiance` dans un terminal, ou avec --oui si tu maitrises ce depot.")
            return 1
        if not confiance.demander(manquants):
            print("Rien n'est accorde. Lintorn ne lancera pas ces commandes.")
            return 1
    souci = confiance.enregistrer(manquants)
    if souci:
        print(f"L'accord n'a PAS pu etre note : {souci}")
        return 1
    print(f"Accorde : {len(manquants)} commande(s), pour ce projet seulement.")
    return 0
