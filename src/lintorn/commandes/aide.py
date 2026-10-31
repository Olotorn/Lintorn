# Lintorn
"""`--help`, `--version`, `--guide`, et l'accueil d'un projet sans config."""

from __future__ import annotations

from .. import __version__

AIDE = """lintorn : audite le code d'un projet ET la memoire que lit l'assistant IA.

USAGE
    lintorn                      audit complet : ta doc, et tous les outils
                                 actifs (ruff, osv-scanner...)
    lintorn rapide               sans les outils lents (ce que lance le hook)
    lintorn doc                  uniquement : la documentation ment-elle ?
    lintorn --fichiers a.py b.ts + un focus sur ces fichiers

OU EN EST-ON (rien n'est lance ni modifie)
    lintorn status               le hook, l'accord, la config, ce qui est
                                 controle, les derniers rapports
    lintorn rapport              ouvre le dernier rapport dans le navigateur
    lintorn rapport-push         ouvre celui du dernier push

MISE EN PLACE
    lintorn init                 genere .lintorn/config.toml pour ce projet
    lintorn regles               prepare un [[regles]] par regle de ta doc
                                 qui n'a pas encore de controle
    lintorn regles --test        essaie chaque regle, et son `exemple`
    lintorn corrige              repare les fautes de frappe de regles.toml
                                 et config.toml ([[regle]], bloquan...),
                                 apres t'avoir montre chaque correction
    lintorn hook                 installe le hook pre-push (sans faire taire
                                 les hooks que le projet a deja), ou le met
                                 a jour, et dit ce qu'il a change
    lintorn hook --status        dit si le hook tourne, sans rien toucher
    lintorn hook --rm            le debranche et le retire
    lintorn confiance            autorise Lintorn a lancer ses outils dans ce
                                 projet (il le demande de lui-meme, une fois)
    lintorn confiance --rm       retire cet accord, pour ce projet
    lintorn outils               regarde ce que contient le projet, installe
                                 les outils qui s'y appliquent et propose
                                 d'activer ses audits, un par un

SECURITE
    Les failles connues (pip-audit, npm audit, osv-scanner) sont cherchees
    par l'audit complet, une fois activees avec `lintorn outils`.
    lintorn pip-audit            repare : les paquets Python que pip-audit
                                 signale, a mettre a jour (simulation)
    lintorn pip-audit --appliquer        les met a jour et repingle vraiment

DIVERS
    lintorn guide                la notice : a quoi ca sert, comment lire
                                 un rapport, quels fichiers
    lintorn version              la version installee
    lintorn help                 ce message

CONFIGURATION
    .lintorn/config.toml, ou [tool.lintorn] dans pyproject.toml.
    Lintorn lit sans rien demander, mais ne LANCE aucun outil dans un projet
    sans ton accord (`lintorn confiance`), une fois par projet et par outil
    nouveau. Il n'execute pas ton code, n'ouvre pas ta base et ne sort pas
    sur le reseau tant que tu ne l'as pas active.

    https://gitlab.com/olotorn/lintorn"""


# ─────────────────────────────────────────────────────────────────────────────
# PREMIER DÉMARRAGE SUR UN PROJET
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# CE QUE VOIT QUELQU'UN QUI ARRIVE
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️ ASCII PUR, comme tout ce qui s'imprime ici. Une console Windows en cp1252
#    leve une exception sur le moindre emoji ou tiret cadratin — et ce texte
#    est justement celui que verra le plus souvent un debutant, donc celui qui
#    a le moins le droit de planter.
#
# POURQUOI UN ACCUEIL. Un outil qui verifie la doc d'un projet doit lui-meme
# etre comprehensible sans lire sa doc. Sinon il ne parle qu'a ceux qui n'en
# avaient pas besoin.
def accueil() -> None:
    """Sur un projet sans configuration : dire ce qu'on est, et quoi taper."""
    print()
    print("  Lintorn n'est pas encore configure pour ce projet.")
    print()
    print("  Ce qu'il fait : il verifie que ta documentation et la memoire de")
    print("  ton assistant IA disent encore la verite sur ton code et que")
    print("  les regles que tu ecris sont reellement controlees quelque part.")
    print()
    print("  POUR DEMARRER")
    print("      lintorn init        lit le projet, ecrit sa configuration")
    print("      lintorn             ton premier rapport")
    print()
    print("  POUR COMPRENDRE")
    print("      lintorn guide       la notice, en une page")
    print()
    print("  Rien d'invasif sans ton accord : par defaut Lintorn n'execute")
    print("  pas ton code, n'ouvre pas ta base et ne sort pas sur le reseau.")


GUIDE = """
=== Lintorn - NOTICE ===

1. CE QU'IL REGARDE

   Les outils habituels -- ruff, pytest, tsc -- regardent ton CODE.
   Personne ne regarde ce qui est ECRIT AUTOUR : la doc du depot, le
   fichier d'instructions de ton assistant IA, les regles que tu t'es
   fixees. Ces textes vieillissent en silence, et un assistant qui les
   lit repete leurs erreurs avec assurance.

   Lintorn compare les deux et signale les desaccords.

2. LES QUATRE ETATS D'UN CONTROLE

   [ OK ]   rien a signaler
   [ !! ]   defaut trouve -- ca bloque le push
   [ ?? ]   a confirmer a l'oeil -- ca ne bloque pas
   [ -- ]   outil absent, ou controle non lance

   Le dernier est le plus important. Un controle qui se tait est plus
   dangereux qu'un controle qui passe au rouge : le rouge, on le repare ;
   le silence laisse croire qu'on est couvert alors que plus rien n'est
   surveille.

3. LES TROIS COMMANDES QUI SERVENT

   lintorn init               met en place la configuration
   lintorn                    l'audit complet, outils actifs compris
   lintorn hook               Lintorn tourne avant chaque `git push`

4. LES DEUX FICHIERS

   .lintorn/config.toml   les reglages. Ecrits une fois, peu de retouches.
   .lintorn/regles.toml   tes regles maison. Ca vit, ca grossit.

   Et ce que Lintorn ecrit, a ne pas toucher :
   .lintorn/rapport.md        ton dernier lancement (lintorn, lintorn rapide...)
   .lintorn/rapport-push.md   ton dernier push : il reste la jusqu'au suivant


5. TES REGLES MAISON

   "Jamais de couleur en dur dans un CSS" n'est ecrit nulle part dans
   le code : c'est une DECISION. Lintorn ne peut pas la deviner, mais il
   sait la lire dans ton CLAUDE.md et te dire lesquelles ne sont
   controlees par rien :

       lintorn regles

   Il prepare un bloc par regle, tout rempli sauf le motif la seule
   chose qu'une machine ne peut pas decider a ta place.

6. RIEN D'INVASIF PAR DEFAUT

   Executer tes tests, ouvrir ta base, sortir sur le reseau : chacun
   s'active explicitement dans config.toml -- `lintorn outils`
   te les propose un par un. Et avant de lancer le moindre outil dans un
   projet, Lintorn te demande ton accord (une fois par projet, `[o/N]`,
   non par defaut). Sans terminal -- hook, CI -- il refuse et le dit :
   `lintorn confiance` donne l'accord depuis un terminal.

Toutes les commandes : lintorn help
"""


def afficher_aide() -> int:
    print(AIDE)
    return 0


def afficher_version() -> int:
    print(f"lintorn {__version__}")
    return 0


def afficher_guide() -> int:
    print(GUIDE.strip())
    return 0


def liste_courte() -> list[str]:
    """Les commandes, tirées de l'aide : une seule liste à tenir à jour.

    Une description qui continue sur la ligne suivante la garde : coupée,
    « regarde ce que contient le projet, installe » ne voulait plus rien dire.
    """
    lignes: list[str] = []
    dans_une_commande = False
    for ligne in AIDE.splitlines():
        if ligne.startswith("    lintorn"):
            lignes.append(ligne)
            dans_une_commande = True
        elif dans_une_commande and ligne.startswith(" " * 10):
            lignes.append(ligne)
        else:
            dans_une_commande = False
    return lignes
