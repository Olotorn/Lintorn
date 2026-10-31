# Lintorn
"""`lintorn init` : écrire `.lintorn/config.toml`, taillé pour CE projet."""

from __future__ import annotations

from pathlib import Path

from .. import base, chemins, config
from . import dossier_lintorn, regles


def _octets(fichier: Path) -> bytes | None:
    try:
        return fichier.read_bytes()
    except OSError:
        return None


def _controles_du_modele() -> list[tuple[str, str, bool]]:
    """Les contrôles opt-in que `--init` écrit dans `[controles]`.

    (clé, ce qu'il implique, s'applique-t-il à CE projet). Un contrôle qui ne
    s'applique pas est écrit commenté : il existe, mais rien à activer ici.

    ⚠️ Un test impose que TOUT contrôle `opt_in` de `config.py` figure ici.
    `django_check` et `migrations` sont devenus opt-in sans y être ajoutés :
    un projet Django recevait une config qui ne les nommait jamais.
    """
    return [
        ("tests", "pytest — EXECUTE le code du projet", bool(config.PY_RACINE)),
        ("django_check", "manage.py check — IMPORTE settings.py et les apps",
         bool(config.BACKEND)),
        ("migrations", "makemigrations --check — meme import", bool(config.BACKEND)),
        ("donnees_metier", "manage.py verifier_donnees — ouvre la BASE",
         config.DONNEES_METIER),
        ("deploy", "check --deploy — bruyant tant qu'on est en dev", bool(config.BACKEND)),
        ("code_mort", "vulture — consultatif, beaucoup de faux positifs", bool(config.PY_RACINE)),
        ("failles", "pip-audit — sort sur le RESEAU", bool(config.PY_RACINE)),
        ("failles_npm", "npm audit — sort sur le RESEAU",
         bool(config.FRONTEND and (config.FRONTEND / config.VERROU_NPM).is_file())),
        ("failles_osv", "osv-scanner, les autres langages — sort sur le RESEAU",
         bool(config.ECOSYSTEMES_OSV)),
    ]


def _modele_python() -> list[str]:
    """La section « Le python qui audite » du modèle, selon ce que CE projet a.

    ⚠️ Sans code Python, pas de venv à chercher : « AUCUN VENV TROUVE… Cree-en
    un » poussait un projet PHP ou C# à une action inutile, et contredisait
    le rapport, qui disait lui-même qu'il n'y avait rien à vérifier.
    """
    titre = "# ── Le python qui audite ─────────────────────────────────────────────"
    if config.PY_RACINE is None:
        raison = ("# Des fichiers .py, mais ni pyproject.toml ni equivalent : les outils"
                  if config.PY_SANS_TEMOIN else
                  "# Aucun code Python dans ce projet : ruff, pytest et pip-audit")
        return [titre, raison,
                "# ne tournent pas, il n'y a donc aucun venv a chercher. Rien a regler."]
    return [
        titre,
        "# ruff, pytest et pip-audit doivent tourner avec le venv DU PROJET :",
        "# lances avec un autre, ils repondent quand meme, mais sur le mauvais",
        "# environnement. Lintorn cherche `venv/`, `.venv/` et `env/` tout seul.",
        "#",
        "# Si ton venv vit ailleurs (poetry, pdm, conda, pipenv), dis-lui ou :",
        ("# AUCUN VENV TROUVE pour l'instant - Lintorn lancera donc les outils"
         if config.VENV_PROJET is None else
         f"# Trouve sans aide ici : {config.VENV_PROJET.name}/ - rien a regler."),
        ("# avec SON python, pas le tien. Cree-en un, ou pointe le tien ci-dessous."
         if config.VENV_PROJET is None else "#"),
        '# venv = "../.venvs/mon-projet"',
    ]


def init(ecraser: bool = False) -> int:
    """Écrit un `.lintorn/config.toml` taillé pour CE projet.

    POURQUOI GÉNÉRER PLUTÔT QUE FOURNIR UN EXEMPLE FIGÉ : Lintorn vient de
    détecter ce que le projet contient. Un modèle générique obligerait
    l'utilisateur à commenter les trois quarts des lignes avant de démarrer —
    et c'est exactement à ce moment-là qu'on referme un outil.

    Ce qu'il NE PEUT PAS deviner : les règles maison. « Importer axios depuis
    services/api.ts » n'est écrit nulle part dans le code, c'est une décision.
    D'où un exemple commenté, à remplir.
    """
    cible = config.DOSSIER_LINTORN / "config.toml"
    # ⚠️ Avec une section [tool.lintorn] dans pyproject.toml, c'est ELLE qui
    # compte : le config.toml écrit ici serait ignoré, et l'utilisateur y
    # activerait des contrôles qui ne tourneraient jamais.
    if "pyproject.toml" in config.FICHIERS_CONFIG_LUS:
        print("Ce projet se configure deja dans pyproject.toml, section [tool.lintorn] :")
        print("un .lintorn/config.toml y serait IGNORE. Regle Lintorn dans pyproject.toml,")
        print("ou retire-en la section [tool.lintorn] pour passer a config.toml.")
        return 1
    if cible.exists() and not ecraser:
        print(f"{cible.relative_to(config.RACINE)} existe deja.")
        print("Relance avec --force pour l'ecraser.")
        return 1

    # « racine » plutôt que le nom du dépôt : `JS (eshop)` se lisait comme un
    # dossier front nommé eshop, et un projet C# passait pour un projet JS.
    def ou(dossier) -> str:
        return "racine" if dossier == config.RACINE else chemins.relatif(dossier)

    detecte = []
    if config.PY_RACINE:
        detecte.append(f"Python ({ou(config.PY_RACINE)})")
    if config.BACKEND:
        detecte.append(f"Django ({ou(config.BACKEND)})")
    if config.FRONTEND:
        suffixe = " + TypeScript" if config.FRONTEND in config.PROJETS_TS else ""
        detecte.append(f"JS{suffixe} ({ou(config.FRONTEND)})")
    autres_ts = [ou(projet) for projet in config.PROJETS_TS if projet != config.FRONTEND]
    if autres_ts:
        detecte.append(f"TypeScript ({', '.join(autres_ts)})")
    detecte += sorted(config.ECOSYSTEMES_OSV)

    lignes = [
        "# Configuration de Lintorn pour ce projet.",
        "#   https://gitlab.com/olotorn/lintorn",
        "#",
        f"# Genere par `lintorn init`. Detecte : {', '.join(detecte) or 'rien de connu'}.",
        "",
        *([] if config.SOUS_GIT else [
            "# ⚠️ Ce dossier n'est PAS un depot git. Le perimetre .gitignore, la",
            "#    fraicheur des memoires et le hook pre-push sont donc sans objet :",
            "#    leurs controles se taisent faute de depot, pas parce que tout va",
            "#    bien. Les autres tournent normalement.",
            "",
        ]),
        "# ── Le perimetre ─────────────────────────────────────────────────────",
        "# Lintorn n'audite que ce qui appartient au depot : tout fichier ecarte",
        "# par ton .gitignore sort du perimetre — brouillons, notes personnelles,",
        "# sorties d'outils. Rien a regler ici, c'est ton .gitignore qui decide.",
        "#",
        "# ⚠️ Un fichier DEJA SUIVI par git reste audite, meme si une regle du",
        "#    .gitignore le vise : une regle n'agit que sur ce qui n'est PAS",
        "#    encore suivi. Pour le sortir vraiment, il faut le desindexer :",
        "#        git rm -r --cached <fichier>",
        "#",
        "# Pour ecarter en plus des documents VERSIONNES :",
        '#     docs_exclus = ["docs/*", "CHANGELOG.md"]',
        "",
        *_modele_python(),
        "",
        "# ── Les controles ────────────────────────────────────────────────────",
        "# Par defaut Lintorn n'execute pas ton code, n'ouvre pas ta base et ne",
        "# sort pas sur le reseau. Passe a `true` ce que tu veux activer.",
        "[controles]",
    ]

    for cle, role, pertinent in _controles_du_modele():
        prefixe = "" if pertinent else "# "
        lignes.append(f"{prefixe}{cle:<15}= false   # {role}")

    lignes += [
        "",
        "# ── Tes regles maison ────────────────────────────────────────────────",
        "# Elles vivent a cote, dans `regles.toml` : ce fichier-ci est un",
        "# reglage qu'on ecrit une fois, elles sont une liste qui grossit.",
        "# Les deux se versionnent.",
    ]

    lignes += [
        "",
        "# ── De la doc a NE PAS verifier ──────────────────────────────────────",
        "# Un tutoriel (« creez un fichier `myapp.py` ») et un changelog citent",
        "# des fichiers qui n'existent pas dans le projet : c'est normal, et les",
        "# verifier ne produit que du bruit. `*` traverse les dossiers.",
        "#",
        "# docs_exclus = [\"docs/*\", \"CHANGELOG.md\"]",
        "",
        "# ── Une doc qui cite des fichiers absents ────────────────────────────",
        "# Une roadmap ou une note de conception cite legitimement des fichiers",
        "# pas encore ecrits, ou supprimes. Mets ce marqueur n'importe ou dedans",
        "# et ses chemins morts seront LISTES au lieu de bloquer :",
        "#",
        "#     <!-- lintorn:prospectif -->",
        "",
        "# ── Tes propres outils ───────────────────────────────────────────────",
        "# Pour AJOUTER un outil que Lintorn ne connait pas : mypy, eslint,",
        "# go vet, un script a toi. Il n'y a pas d'interrupteur : le bloc lui-meme",
        "# est l'activation. ENLEVE LES # devant ses lignes, adapte-les, et une",
        "# ligne de plus apparait au rapport. Un bloc par outil.",
        "#",
        "# Lintorn juge l'outil a son code de sortie :",
        "#   0 = [ OK ]   1 = [ !! ] il a trouve quelque chose   autre = [ERR!] il a plante",
        "#",
        "# ⚠️ Ces commandes sont EXECUTEES : ne lance pas Lintorn dans un depot",
        "#    en qui tu n'as pas confiance.",
        "#",
        "# [[commandes]]",
        '# cle      = "mypy"                           # un nom court, unique',
        '# titre    = "Types (mypy)"                   # ce qu\'affiche le rapport',
        '# cmd      = ["{python}", "-m", "mypy", "."]  # MOT PAR MOT ; {python} = le',
        "#                                             # Python du projet (son venv)",
        '# cwd      = "."                              # le dossier d\'ou la lancer',
        "# bloquant = false                            # true = un probleme bloque le push",
        "# lent     = false                            # true = sautee par le hook",
        "",
    ]

    try:
        base.ecrire_fichier_du_projet(cible, "\n".join(lignes))
    except OSError as erreur:
        print(f"Echec : {erreur}")
        return 1

    # « Ecrit » seulement pour ce qui l'a été. Annoncé sur un fichier laissé tel
    # quel, il faisait croire que les règles de l'utilisateur avaient été
    # remplacées. Le verbe vient du disque, pas du message rendu.
    gitignore = cible.parent / ".gitignore"
    avant = _octets(gitignore)
    garde = dossier_lintorn.poser_gitignore_interne(cible.parent)
    verbe_gitignore = "Ecrit" if _octets(gitignore) != avant else "Garde"

    # `regles.toml` est ecrit MEME vide de regles : un fichier absent laisse
    # croire que la fonctionnalite n'existe pas. Present et commente, il
    # montre la forme a remplir.
    esquisses = regles.esquisses_regles()
    fichier_regles = config.FICHIER_REGLES
    regles_ecrites = not fichier_regles.exists()
    if regles_ecrites:
        try:
            base.ecrire_fichier_du_projet(fichier_regles, regles.contenu_regles_toml(esquisses))
        except OSError as erreur:
            print(f"Echec sur regles.toml : {erreur}")
            return 1

    relatif = cible.relative_to(config.RACINE)
    # Des esquisses qui n'ont pas été écrites ne se décommentent pas.
    nombre = sum(1 for ligne in esquisses if ligne == "# [[regles]]") if regles_ecrites else 0
    if not regles_ecrites:
        resume_regles = "deja present, rien n'y est ecrit"
    elif nombre:
        resume_regles = f"{nombre} regle(s) de ta doc, en esquisse a completer"
    else:
        resume_regles = "la forme a remplir, en commentaire"
    verbe_regles = "Ecrit" if regles_ecrites else "Garde"
    print(f"Projet detecte : {', '.join(detecte) or 'rien de connu'}")
    if config.PY_SANS_TEMOIN:
        print("                 (des fichiers .py, mais ni pyproject.toml ni equivalent :")
        print("                  les outils Python ne tourneront pas - voir le rapport)")
    print(f"Ecrit          : {relatif}")
    print(f"{verbe_regles:<15}: {fichier_regles.relative_to(config.RACINE)} - {resume_regles}")
    print(f"{verbe_gitignore:<15}: {relatif.parent / '.gitignore'} - {garde}")
    print()
    print("A FAIRE MAINTENANT :")
    print(f"    1. ouvre {relatif} et active les controles que tu veux")
    print("       (ou `lintorn outils` : il propose ceux qui s'appliquent)")
    if nombre:
        print(f"    2. ouvre {fichier_regles.relative_to(config.RACINE)} : garde ce qui compte,")
        print("       decommente, et ecris le `motif` de chaque regle gardee")
        print("    3. `lintorn` pour un premier rapport")
    else:
        print("    2. `lintorn` pour un premier rapport")

    if not config.SOUS_GIT:
        print()
        print("A SAVOIR : ce dossier n'est pas un depot git. Le hook pre-push,")
        print("la fraicheur des memoires et le perimetre .gitignore sont donc")
        print("sans objet - c'est ecrit en tete de ta config.")
        return 0

    # Contre-epreuve : on ne se contente pas d'avoir ECRIT le garde-fou, on
    # demande a git s'il produit l'effet voulu. Sans ca, un utilisateur dont
    # le .gitignore exclut le dossier entier croirait sa config versionnee.
    # Elle exige un depot : sans lui, `hors_gitignore` ne filtre rien et
    # repondrait « tout va bien » sans avoir regarde — d'ou le retour au-dessus.
    caches = [f.name for f in (cible, fichier_regles) if not config.hors_gitignore([f])]
    if caches:
        print()
        print(f"ATTENTION : git ignore {' et '.join(caches)}, ces fichiers ne")
        print("partiront pas sur le depot. Une regle de ton .gitignore exclut")
        print("le DOSSIER entier :")
        print()
        print("    .lintorn/     exclut le dossier : git n'y descend pas, et")
        print("                  aucune exception interne ne peut le rattraper")
        print("    .lintorn/*    exclut son CONTENU : les exceptions marchent")
        print()
        print("Remplace la premiere forme par la seconde, ou retire la regle :")
        print("le .gitignore pose dans .lintorn/ suffit desormais a lui seul.")
    return 0
