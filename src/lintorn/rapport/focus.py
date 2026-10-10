# Lintorn
"""Le focus d'un push : ne garder que ce qui touche les fichiers poussés."""

from __future__ import annotations

import re
from pathlib import Path

from .. import config
from ..base import Resultat


# ─────────────────────────────────────────────────────────────────────────────
# FOCUS SUR LES FICHIERS D'UN PUSH
# ─────────────────────────────────────────────────────────────────────────────
def _alias(chemin_git: str) -> list[str]:
    """Toutes les façons dont un même fichier peut apparaître dans un rapport.

    git parle en chemins depuis la racine du dépôt :
        api/comptes/vues.py
    mais ruff tourne DANS le backend et écrit :
        comptes/vues.py
    On compare donc sur plusieurs formes du même chemin.

    ⚠️ Les préfixes viennent de la DÉTECTION (`config.PREFIXES_PROJET`), ils
    ne sont plus écrits en dur. Avec des préfixes figés, le focus ne
    reconnaissait aucun fichier sur un autre projet — et annonçait « aucun
    defaut connu dedans » sans avoir rien pu comparer, juste avant le push.
    """
    chemin = chemin_git.replace("\\", "/")
    formes = [chemin]
    for prefixe in config.PREFIXES_PROJET:
        if chemin.startswith(prefixe):
            formes.append(chemin[len(prefixe):])
    return formes


# Ce que lit chaque outil livré, par suffixe. Les audits de failles et les
# contrôles Django lisent des verrous ou des réglages, pas les fichiers du push.
_SUFFIXES_LUS = {
    "ruff": (".py", ".pyi", ".ipynb"),
    "code_mort": (".py",),
    "tests": (".py",),
    "typescript": (".ts", ".tsx", ".mts", ".cts"),
}
_OUTILS_LIVRES = {"ruff", "dependances", "tests", "code_mort", "failles", "django_check",
                  "migrations", "donnees_metier", "deploy", "typescript",
                  "failles_npm", "failles_osv"}


def _sous(fichier: str, dossier: Path) -> bool:
    return any((base / fichier).resolve().is_relative_to(Path(dossier).resolve())
               for base in filter(None, (config.RACINE, config.SOMMET_GIT)))


def _lus_par_un_controle(resultats: list[Resultat], fichiers: list[str]) -> set[str]:
    """Les fichiers poussés qu'au moins un contrôle AYANT TOURNÉ a vraiment lus.

    « Aucun defaut connu dedans » s'affichait sur des `.cs`, `.rb`, `.go`
    qu'aucun contrôle ne sait lire : un vert au moment du push, sur des
    fichiers que personne n'avait regardés.

    Une commande ajoutée par le projet (`[[commandes]]`) est créditée de tout
    ce qui est sous son dossier : c'est le projet qui l'a branchée là.
    """
    ont_tourne = {r.titre for r in resultats if r.statut in ("OK", "ALERTE", "VERIF")}
    lus: set[str] = set()
    for entree in config.COMMANDES:
        if entree["titre"] not in ont_tourne:
            continue
        if entree["cle"] in _OUTILS_LIVRES:
            suffixes = _SUFFIXES_LUS.get(entree["cle"], ())
            lus |= {f for f in fichiers
                    if Path(f).suffix in suffixes and _sous(f, entree["cwd"])}
        else:
            lus |= {f for f in fichiers if _sous(f, entree["cwd"])}

    docs = set()
    if "Doc vs code" in ont_tourne:
        docs |= set(config.DOCS_A_VERIFIER)
    if ont_tourne & {"Memoire IA vs code", "Regles enoncees vs controlees"}:
        docs |= set(config.DOCS_IA)
    relatifs = set()
    for doc in docs:
        try:
            relatifs.add(Path(doc).resolve().relative_to(config.RACINE.resolve()).as_posix())
        except (ValueError, OSError):
            continue
    lus |= {f for f in fichiers if f in relatifs}

    if "Regles maison" in ont_tourne:
        for regle in config.REGLES_MAISON:
            lus |= {f for f in fichiers
                    if Path(f).suffix in regle["suffixes"] and _sous(f, regle["racine"])
                    and not any(exclu in f for exclu in regle["exclure"])}
    return lus


def _existe(fichier: str) -> bool:
    """Un fichier SUPPRIMÉ par le push n'a plus de défaut à avoir."""
    return any((base / fichier).exists()
               for base in filter(None, (config.RACINE, config.SOMMET_GIT)))


def focus_sur(resultats: list[Resultat], fichiers: list[str]) -> Resultat:
    """Ne garde, dans tous les rapports, que ce qui touche CES fichiers.

    C'est ce qui transforme « 638 couleurs en dur dans le projet » en
    « 3 couleurs en dur dans ce que tu viens de pousser ». Sans ça, un rapport
    global est illisible : on ne sait pas si le défaut vient de ce push ou
    traîne depuis six mois.
    """
    fichiers = [fichier.replace("\\", "/") for fichier in fichiers]
    lus = _lus_par_un_controle(resultats, fichiers)
    non_lus = [fichier for fichier in fichiers if fichier not in lus and _existe(fichier)]
    formes = [forme for fichier in fichiers for forme in _alias(fichier)]
    # ⚠️ UN CHEMIN ENTIER, pas une sous-chaîne : `app/vues.py` était reconnu
    # dans `monapp/vues.py` — un défaut du voisin imputé au push.
    reperes = [re.compile(rf"(?<![\w./-]){re.escape(forme)}(?!\.?[\w/-])")
               for forme in formes if forme]
    pousses = {fichier.replace("\\", "/") for fichier in fichiers}
    touches: list[str] = []

    # Le statut le plus GRAVE parmi ce qui a reellement matche. Rendre
    # « ALERTE » en dur transformait deux `[ ?? ]` — « a confirmer a l'oeil,
    # pas un defaut » — en un `[ !! ]` juste avant le push. Un rouge qu'aucune
    # correction ne peut eteindre apprend a ignorer les rouges.
    gravite = ""

    for resultat in resultats:
        # INDISPONIBLE n'a rien trouve : l'outil n'a pas tourne. Son detail
        # (« No module named ruff »…) n'est pas une trouvaille sur tes fichiers.
        if resultat.statut in ("OK", "INDISPONIBLE"):
            continue
        # ⚠️ LA LISTE COMPLÈTE quand le contrôle la fournit : son détail ne
        # montre que les huit fichiers les plus touchés. Un fichier poussé
        # au-delà du huitième y manquait — le focus le disait propre.
        if resultat.fichiers:
            for fichier, quoi in resultat.fichiers.items():
                if fichier in pousses:
                    touches.append(f"[{resultat.titre}] {fichier} : {quoi}")
                    if resultat.statut != "VERIF" or not gravite:
                        gravite = resultat.statut
            continue
        if not resultat.detail:
            continue
        for ligne in resultat.detail.splitlines():
            propre = ligne.strip()

            # Dans les details que Lintorn ecrit lui-meme, `>` cite la regle et
            # `#` titre la section : c'est de la PROSE. Une citation qui nomme
            # un fichier pousse etait comptee comme un defaut de plus — la
            # regle apparaissait deux fois. Reserve au markdown maison : la
            # sortie brute de pytest utilise `>` pour marquer l'assertion.
            if resultat.detail_markdown and propre[:1] in (">", "#"):
                continue
            # ⚠️ Les outils écrivent les chemins avec le séparateur de l'OS :
            # sous Windows, ruff sort `api\outils\noyau.py`. Les formes
            # calculées par `_alias`, elles, sont en slashs — git ne parle que
            # cette langue. Sans normaliser AVANT de comparer, plus rien ne
            # correspond sous Windows : le focus annonce « aucun defaut connu
            # dedans » au moment précis où l'on pousse. Un faux vert.
            compare = propre.replace("\\", "/")
            if propre and any(repere.search(compare) for repere in reperes):
                touches.append(f"[{resultat.titre}] {propre}")
                if resultat.statut != "VERIF" or not gravite:
                    gravite = resultat.statut

    titre = "Defauts dans les fichiers pousses"
    apercu = ", ".join(non_lus[:3]) + (" ..." if len(non_lus) > 3 else "")
    jamais_lus = ("\n\nAucun contrôle de Lintorn ne lit ces fichiers : l'absence de "
                  "défaut n'y prouve rien.\n" + "\n".join(f"- {f}" for f in non_lus)
                  if non_lus else "")

    if not touches:
        if not non_lus:
            return Resultat(
                titre, "OK",
                f"{len(fichiers)} fichier(s) pousse(s), aucun defaut connu dedans",
                bloquant=False,
            )
        if len(non_lus) == len(fichiers):
            return Resultat(titre, "INDISPONIBLE",
                            f"aucun controle ne lit ces fichiers : {apercu}",
                            jamais_lus.strip(), bloquant=False)
        return Resultat(
            titre, "VERIF",
            f"aucun defaut connu dans {len(fichiers) - len(non_lus)} fichier(s),"
            f" {len(non_lus)} que rien ne lit : {apercu}",
            jamais_lus.strip(), bloquant=False,
        )

    # « defaut » serait faux quand tout vient de VERIF : rien n'est casse,
    # il y a des points a regarder.
    quoi = "point(s) a verifier" if gravite == "VERIF" else "defaut(s)"
    return Resultat(
        titre, gravite,
        f"{len(touches)} {quoi} dans {len(fichiers)} fichier(s) pousse(s)"
        + (f", {len(non_lus)} que rien ne lit" if non_lus else ""),
        "\n".join(f"- {t}" for t in touches) + jamais_lus,
        bloquant=False,   # informatif : le blocage reste décidé par les contrôles eux-mêmes
    )
