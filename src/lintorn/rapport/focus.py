# Lintorn
"""Le focus d'un push : ne garder que ce qui touche les fichiers poussés."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .. import config
from ..base import Resultat
from ..controles.outillage import configuration

TITRE ="Defauts dans les fichiers pousses"
TITRE_ECART = "Ce qui part vs ce qui est lu"
TITRE_LISTE = "Ce qui part"
TITRE_RIEN = "Ce que ce push envoie"


def rien_ne_part() -> Resultat:
    """Le hook a dit ce qui part, et rien de nouveau ne part de ce projet : rien à juger."""
    return Resultat(
        TITRE_RIEN, "INDISPONIBLE",
        "rien de nouveau ne part de ce projet - rien a verifier",
        "Ce push n'envoie aucun fichier nouveau de ce projet : une branche supprimée, des "
        "commits déjà sur le distant poussés sous un autre nom, ou un push qui ne touche "
        "qu'un autre sous-projet. Lintorn n'a rien à juger, il laisse partir.",
        bloquant=False, detail_markdown=True, detail_meme_au_vert=True,
    )


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
# Les réglages que ruff lit avant tout : un TOML cassé le fait échouer.
_NOMS_LUS = {"ruff": ("pyproject.toml", "ruff.toml", ".ruff.toml")}


def _fichiers_de_lintorn() -> set[Path]:
    """Ce que « Configuration (Lintorn) » a lu et validé, et le `.gitignore` que Lintorn écrit.

    Pousser une règle ajoutée faisait dire « aucun controle ne lit ces
    fichiers » sur `regles.toml`, que Lintorn venait de lire, et le push
    finissait « SANS verification complete ».
    """
    lus = {fichier for fichier in (config.RACINE / "pyproject.toml",
                                   config.DOSSIER_LINTORN / "config.toml", config.FICHIER_REGLES)
           if fichier.name in config.FICHIERS_CONFIG_LUS}
    return lus | {config.DOSSIER_LINTORN / ".gitignore"}


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
    exacts: set[Path] = set()
    for entree in config.COMMANDES:
        if entree["titre"] not in ont_tourne:
            continue
        if entree["cle"] in _OUTILS_LIVRES:
            suffixes = _SUFFIXES_LUS.get(entree["cle"], ())
            noms = _NOMS_LUS.get(entree["cle"], ())
            lus |= {f for f in fichiers
                    if (Path(f).suffix in suffixes or Path(f).name in noms)
                    and _sous(f, entree["cwd"])}
            if entree["cle"] == "dependances" and config.REQUIREMENTS is not None:
                exacts.add(config.REQUIREMENTS)
        else:
            lus |= {f for f in fichiers if _sous(f, entree["cwd"])}

    if configuration.TITRE in ont_tourne:
        exacts |= _fichiers_de_lintorn()
    if "Doc vs code" in ont_tourne:
        exacts |= {Path(doc) for doc in config.DOCS_A_VERIFIER}
    if ont_tourne & {"Memoire IA vs code", "Regles enoncees vs controlees"}:
        exacts |= {Path(doc) for doc in config.DOCS_IA}
    relatifs = set()
    for doc in exacts:
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

    titre = TITRE
    apercu = _apercu(non_lus)
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


def _apercu(fichiers: list[str]) -> str:
    return ", ".join(fichiers[:3]) + (" ..." if len(fichiers) > 3 else "")


def _differe_du_disque(commit: str) -> set[str] | None:
    """Les fichiers du projet que `commit` n'a pas tels que le disque les a. None : git a échoué.

    `--relative` et `-- .` parlent comme le hook, depuis le projet. `^{commit}` :
    un tag annoté y mène. `core.fileMode=false` : un `chmod +x` pas encore
    commité ne change rien à ce que les contrôles lisent, et suffisait à
    annoncer un écart.
    """
    try:
        sortie = config.git("-c", "core.fileMode=false", "diff", "--name-only", "-z", "--relative",
                            f"{commit}^{{commit}}", "--", ".", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return set(sortie.stdout.split("\0")) - {""} if sortie.returncode == 0 else None


def _caches_a_git() -> set[str] | None:
    """Les fichiers du projet que git ne compare plus au disque. None : git a échoué.

    `assume-unchanged` (lettre minuscule dans `git ls-files -v`) et `skip-worktree`
    (`S`, que pose aussi un sparse-checkout) : `git diff` les dit inchangés quoi
    qu'il y ait sur le disque, et une faute commitée mais corrigée, ou absente,
    du disque partait sur « Lintorn OK ».
    """
    try:
        sortie = config.git("ls-files", "-v", "-z", "--", ".", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if sortie.returncode != 0:
        return None
    return {entree[2:] for entree in sortie.stdout.split("\0")
            if len(entree) > 2 and (entree[0].islower() or entree[0] == "S")}


def _differe_en_vrai(commit: str, fichier: str) -> bool:
    """Ce fichier du disque est-il autre que dans `commit` ? Comparé par git lui-même
    (`hash-object` applique les mêmes filtres que l'index), sans son drapeau."""
    try:
        attendu = config.git("rev-parse", "--verify", "-q", f"{commit}^{{commit}}:./{fichier}",
                             timeout=30)
        if attendu.returncode != 0:
            return False      # absent du commit : ce commit ne l'envoie pas
        if not (config.RACINE / fichier).is_file():
            return True
        disque = config.git("hash-object", "--", fichier, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return True
    return disque.returncode != 0 or disque.stdout.strip() != attendu.stdout.strip()


def _envoyes_par(commit: str, distant: str | None) -> set[str] | None:
    """Les fichiers que touchent les commits menant à `commit` que le distant n'a pas encore.

    Le calcul du hook pour une branche neuve, fait pour CE commit seul : un tag
    posé avant les derniers commits n'envoie pas leurs fichiers. Comparé à tous
    les fichiers du push, il les disait « pas sur ton disque tels qu'ils
    partent ».
    """
    distants = f"--remotes={distant}" if distant else "--remotes"
    try:
        sortie = config.git("log", "--format=", "--name-only", "-z", "--cc", "--relative", commit,
                            "--not", distants, "--", ".", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return set(sortie.stdout.split("\0")) - {""} if sortie.returncode == 0 else None


def ecart_avec_le_disque(fichiers: list[str], commits: list[str], liste: str | None,
                         distant: str | None) -> list[Resultat]:
    """Ce que ce push envoie et que Lintorn n'a pas lu : les fichiers qui diffèrent du disque,
    et ce que le hook n'a pas su lister.

    ⚠️ Les contrôles lisent le DISQUE, git envoie des COMMITS. Une correction
    pas encore commitée, une autre branche que celle où l'on est, un tag :
    Lintorn jugeait un fichier, git en envoyait un autre, et le hook concluait
    « Lintorn OK » sur un code fautif parti au distant. Juger le contenu des
    commits eux-mêmes reste à faire ; d'ici là, l'écart se DIT.

    `liste` vient du hook : `complete`, `echec` (git n'a pas tout listé), `rien`
    (l'outil qui l'appelle ne lui a rien transmis), None (une copie du hook
    d'avant cette variable). Sans liste complète, il n'y a rien à quoi comparer :
    le hook concluait « Lintorn OK » sans avoir comparé.
    """
    if liste is None:
        return [_liste_inconnue(
            "ton hook ne dit pas a Lintorn ce qui part : relance `lintorn hook`",
            "Ta copie du hook vient d'une version précédente de Lintorn. Elle ne lui transmet "
            "pas ce que le push envoie : Lintorn ne peut pas comparer ce qui part à ce qu'il a "
            "lu sur ton disque.\n\nPour la mettre à jour : `lintorn hook`.")]
    if liste == "rien":
        return [_liste_inconnue(
            "l'outil qui appelle Lintorn ne lui a pas transmis ce qui part",
            "Ton outil de hooks garde pour lui la liste que git donne à un pre-push : "
            "Lintorn ne sait pas ce que ce push envoie, et ne peut pas le comparer à ce "
            "qu'il a lu sur ton disque.\n\nAvec lefthook, la commande de Lintorn doit "
            "avoir `use_stdin: true` (voir `lintorn hook`).")]

    complete = liste == "complete"
    pousses = {fichier.replace("\\", "/") for fichier in fichiers}
    commits = [commit for commit in dict.fromkeys(commits) if commit.strip("0")]
    if complete and not pousses:
        commits = []          # aucun fichier ne part : rien à comparer
    differents: set[str] = set()
    caches = _caches_a_git() if commits else set()
    for commit in commits:
        autres = _differe_du_disque(commit)
        if autres is not None and caches is not None:
            # Seuls ceux qui partent : un sparse-checkout en cache des milliers.
            suspects = caches & (pousses if complete else (_envoyes_par(commit, distant) or set()))
            autres |= {fichier for fichier in suspects if _differe_en_vrai(commit, fichier)}
        if autres is None or caches is None:
            return [Resultat(TITRE_ECART, "VERIF",
                             "impossible de comparer ce que tu pousses a ton disque",
                             "git n'a pas su comparer un commit poussé à ton disque : ce que "
                             "Lintorn a lu n'est peut-être pas ce qui part.", bloquant=False)]
        if complete:
            autres &= pousses
        # Plusieurs commits (une branche et un tag, deux branches) : chacun
        # n'envoie que ses propres fichiers. Sans liste, ils la remplacent.
        if autres and (len(commits) > 1 or not complete):
            envoyes = _envoyes_par(commit, distant)
            if envoyes is not None:
                autres &= envoyes
        differents |= autres

    resultats = []
    if not complete:
        resultats.append(_liste_inconnue(
            "git n'a pas su lister tous les fichiers qui partent",
            "Le hook n'a pas pu lister une partie des fichiers de ce push : le focus ne "
            "les couvre pas, et rien ne dit qu'un contrôle sait les lire."))
    if differents:
        ecarts = sorted(differents)
        resultats.append(Resultat(
            TITRE_ECART, "VERIF",
            f"{len(ecarts)} fichier(s) pousse(s) ne sont pas sur ton disque tels qu'ils partent : "
            f"{_apercu(ecarts)}",
            "Lintorn lit les fichiers de ton disque. Ceux-ci n'y sont pas ce que le push envoie : "
            "des modifications pas encore commitées, le push d'une autre branche (ou d'un "
            "tag) que celle où tu es, ou un fichier que git ne compare plus au disque "
            "(`assume-unchanged`, `skip-worktree`, sparse-checkout). Ce que Lintorn a jugé "
            "n'est donc pas ce qui part :\n\n"
            + "\n".join(f"- {fichier}" for fichier in ecarts)
            + "\n\nPour qu'il vérifie exactement ce qui part : commite tes modifications (ou "
            "mets-les de côté, `git stash`), ou pousse depuis la branche concernée.",
            bloquant=False, detail_markdown=True,
        ))
    return resultats


def _liste_inconnue(resume: str, detail: str) -> Resultat:
    return Resultat(TITRE_LISTE, "VERIF", resume, detail, bloquant=False, detail_markdown=True)
