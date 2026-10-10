# Lintorn
"""LE TABLEAU DE BORD : ce que Lintorn a compris du projet, calculé dans l'ordre.

Lis ce fichier de haut en bas : la racine du projet, puis ses langages, puis
sa config, puis le python qui audite, puis les outils à lancer, les documents
à lire, les règles maison. Chaque valeur dépend de celles d'au-dessus.

Le COMMENT vit dans un fichier par métier :

    projet.py               la racine, git, ce qui est ignoré, les fichiers suivis
    ecosystemes.py          quels langages : Django, Python, front, TypeScript, verrous
    reglages.py             lire et valider config.toml, [tool.lintorn], .env
    python.py               le python du projet, jamais celui de Lintorn
    docs.py                 les documents, les fichiers IA, la mémoire de l'assistant
    regles_maison.py        les [[regles]] de regles.toml
    commandes_du_projet.py  les [[commandes]] que le projet branche lui-même

⚠️ Tout le reste du code lit `config.NOM` — et ces fichiers aussi. Les tests
   simulent un projet en remplaçant `config.RACINE`, `config.PROJET`… ;
   `tests/test_architecture.py` garantit que personne ne lit sa propre copie.
"""

import os
import sys
from pathlib import Path

from ..outils import django, npm_audit, osv, pip_audit, pytest, requirements, ruff, tsc, vulture
from .commandes_du_projet import (
    _CLES_COMMANDE as _CLES_COMMANDE,
    TRADUCTEURS_CONNUS as TRADUCTEURS_CONNUS,
    _commandes_du_projet as _commandes_du_projet,
)
from .docs import (
    _FICHIERS_IA_DEFAUT as _FICHIERS_IA_DEFAUT,
    DOSSIERS_DE_FIXTURES as DOSSIERS_DE_FIXTURES,
    DOSSIERS_FIXTURES as DOSSIERS_FIXTURES,
    EXTENSIONS as EXTENSIONS,
    FORMATS_DOC as FORMATS_DOC,
    INDEX_MEMOIRE as INDEX_MEMOIRE,
    PAR_RESSEMBLANCE as PAR_RESSEMBLANCE,
    _documents_du_depot as _documents_du_depot,
    _dossier_memoire as _dossier_memoire,
    _est_un_fichier_ia as _est_un_fichier_ia,
    _instructions_ia as _instructions_ia,
    _nom_lisible as _nom_lisible,
)
from .ecosystemes import (
    SUFFIXES_OSV as SUFFIXES_OSV,
    VERROUS_JS as VERROUS_JS,
    VERROUS_OSV as VERROUS_OSV,
    _candidats as _candidats,
    _ecosystemes_osv as _ecosystemes_osv,
    _prefixe as _prefixe,
    _racine_python as _racine_python,
    _requirements as _requirements,
    _trouver as _trouver,
    installation_js as installation_js,
    remede_js as remede_js,
    tsc_de as tsc_de,
)
from .projet import (
    IGNORES as IGNORES,
    _fichiers_du_projet as _fichiers_du_projet,
    _hooks_pour_git as _hooks_pour_git,
    _ignores_par_git as _ignores_par_git,
    _racine_projet as _racine_projet,
    _sommet_git as _sommet_git,
    _sous_git as _sous_git,
    git as git,
    hors_gitignore as hors_gitignore,
    motifs_gitignore as motifs_gitignore,
    sous_ignores as sous_ignores,
    suivi_par_git as suivi_par_git,
)
from .python import (
    _dans_le_projet as _dans_le_projet,
    _interpreteur as _interpreteur,
    _python_du_projet as _python_du_projet,
    _venv_declare as _venv_declare,
)
from .reglages import (
    _CONTROLES_DEFAUT as _CONTROLES_DEFAUT,
    _TYPES_CONFIG as _TYPES_CONFIG,
    OBJET_DES_CLES as OBJET_DES_CLES,
    _accorde as _accorde,
    _charger_toml as _charger_toml,
    _cles_inconnues as _cles_inconnues,
    _cles_sans_effet as _cles_sans_effet,
    _config_projet as _config_projet,
    _lire_env as _lire_env,
    _retenu as _retenu,
    _valider_config as _valider_config,
)
from .regles_maison import (
    _CLES_REGLE as _CLES_REGLE,
    _RX_NOM_DE_REGLE as _RX_NOM_DE_REGLE,
    _lignes_des_regles as _lignes_des_regles,
    _regles_brutes as _regles_brutes,
    _regles_du_projet as _regles_du_projet,
)

# ─────────────────────────────────────────────────────────────────────────────
# CHEMINS — le projet AUDITÉ, et non l'endroit où Lintorn est installé
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️ LE RENVERSEMENT LE PLUS IMPORTANT DU FICHIER.
#
# Tant que Lintorn vivait DANS le projet qu'il auditait, il déduisait la
# racine de sa propre position : `Path(__file__).parents[1]`. Installé par
# `pip`, il vit dans `site-packages/` — cette déduction pointerait vers les
# entrailles du venv et TOUS les contrôles s'effondreraient d'un coup, en
# analysant le code d'autrui tout en paraissant fonctionner.
#
# Désormais le paquet ne sait rien du projet : le projet, c'est LÀ OÙ
# L'UTILISATEUR A LANCÉ LA COMMANDE.


# Où vit Lintorn lui-même — uniquement pour lire SES ressources (hooks/…).
# `parents[1]` : ce fichier vit dans `config/`, le paquet est un cran au-dessus.
# `.parent` seul désignait `config/` — et les hooks livrés devenaient introuvables.
PAQUET = Path(__file__).resolve().parents[1]

# Les soucis relevés AVANT que `SOUCIS_CONFIG` n'existe (la racine se calcule
# en premier). Ils l'y rejoignent plus bas : aucun ne se perd en route.
_SOUCIS_PRECOCES: list[str] = []


RACINE = _racine_projet()


# Trois contrôles en dépendent entièrement — le hook pre-push, la fraîcheur
# des mémoires, et le périmètre `.gitignore`. Sans dépôt, ils ne peuvent rien
# vérifier : ils doivent le DIRE, pas rendre un verdict.
SOUS_GIT = _sous_git()


# Calculé une fois, AVANT la détection : savoir où vit le code est ce qui
# distingue un projet d'un simple fichier de configuration posé là.
_FICHIERS = _fichiers_du_projet()
_SOURCES_PY = [fichier for fichier in _FICHIERS
               if fichier.suffix in (".py", ".pyi") and not sous_ignores(fichier)]


BACKEND = _trouver("manage.py")        # None si le projet n'est pas Django
FRONTEND = _trouver("package.json")    # None s'il n'y a pas de front JS/TS

# CHAQUE projet TypeScript : un package.json ET un tsconfig.json, profondeur 2.
# ⚠️ Pas seulement FRONTEND : sur un monorepo, le premier package.json est
# souvent celui du workspace, sans tsconfig. Le contrôle TypeScript
# disparaissait alors sans un mot, et `server/`, `web/` n'étaient jamais typés.
PROJETS_TS = [dossier for dossier in _candidats("tsconfig.json")
              if (dossier / "package.json").is_file()]


PY_RACINE = _racine_python()

# Des `.py` dans un projet qu'aucun témoin ne désigne comme Python. On ne le
# DEVINE pas Python : un projet JS ou Go avec un petit script recevrait alors
# l'alerte « aucun venv trouvé », un faux positif déjà payé une fois. Mais on
# ne dit plus « aucun code Python » non plus : c'était faux.
PY_SANS_TEMOIN = PY_RACINE is None and bool(_SOURCES_PY)


REQUIREMENTS = _requirements()

# Tout ce que Lintorn ÉCRIT va dans ce seul dossier du projet audité — jamais
# dans le paquet installé, qui est en lecture seule et partagé entre projets.
#
# Un dossier unique plutôt que des fichiers éparpillés à la racine : ça ne
# salit pas le projet de l'utilisateur, et une seule ligne suffit dans son
# `.gitignore`. Ça règle aussi un serpent qui se mordait la queue — un
# `rapport.md` posé à la racine était ramassé par le scan de documentation,
# et Lintorn analysait alors son propre rapport.
DOSSIER_LINTORN = RACINE / ".lintorn"
RAPPORT = DOSSIER_LINTORN / "rapport.md"
# La MEME matiere, en page web : le Markdown reste la source, `rapport/html.py`
# le rend. Ecrite a cote, jamais a la place.
RAPPORT_HTML = RAPPORT.with_suffix(".html")


NPM = "npm.cmd" if sys.platform == "win32" else "npm"


# ⚠️ LES PRÉFIXES QUI RÉCONCILIENT DEUX FAÇONS DE NOMMER UN MÊME FICHIER.
#
# git parle depuis la racine du dépôt      : `api/comptes/vues.py`
# ruff, lui, tourne DANS le backend        : `comptes/vues.py`
#
# Il faut donc pouvoir passer de l'un à l'autre — pour préfixer les liens du
# rapport, et pour reconnaître un fichier poussé dans la sortie d'un outil.
#
# Ces préfixes ont longtemps été ÉCRITS EN DUR. Conséquence chez
# quiconque n'a pas la même arborescence : les liens du rapport pointent dans le
# vide, et surtout le focus du hook pre-push ne reconnaît plus AUCUN fichier —
# il annonce alors « rien de casse dans ce que tu pousses » sans avoir rien pu
# comparer. Un faux vert au moment précis du push.
#
# Tri du PLUS LONG au plus court : `front/src/` doit être essayé avant
# `front/`, sinon le second l'emporte et laisse un `src/` parasite.
#
# ⚠️ `src/` seulement s'il EXISTE. Deviné, il désignait un dossier absent sur
# un front qui range ses sources ailleurs (`web_src/`, `ruff/src/`), et le
# focus aurait amputé de ce préfixe tout chemin qui commence par lui.
PREFIXE_BACKEND = _prefixe(BACKEND) or ""
PREFIXES_PROJET = sorted(
    {p for p in (
        _prefixe(BACKEND),
        _prefixe(FRONTEND / "src") if FRONTEND and (FRONTEND / "src").is_dir() else None,
        _prefixe(FRONTEND),
        # tsc écrit ses chemins depuis le projet où il tourne.
        *(_prefixe(projet) for projet in PROJETS_TS),
    ) if p},
    key=len, reverse=True,
)

# Le hook livré DANS le paquet, et l'endroit où il s'installe dans le projet
# audité — à côté de sa config, jamais dans `.git/hooks/`, que rien ne relie
# au projet.
HOOKS_SOURCE = PAQUET / "hooks"
HOOKS_ATTENDU = ".lintorn/hooks"
HOOKS = RACINE / HOOKS_ATTENDU


SOMMET_GIT = _sommet_git()


HOOKS_POUR_GIT = _hooks_pour_git()


# ─────────────────────────────────────────────────────────────────────────────
# RÉGLAGES DE MACHINE — `.lintorn/.env` (gitignoré)
# ─────────────────────────────────────────────────────────────────────────────
# Ce qui dépend de LA MACHINE, pas du projet, se règle ici. Modèle fourni :
# `.env.example`. Aucune valeur n'est obligatoire — sans .env, Lintorn se
# débrouille tout seul comme avant.
#
# Lecteur volontairement écrit à la main : Lintorn promet « aucune dépendance,
# stdlib uniquement » (voir l'en-tête de Lintorn.py). Ajouter python-dotenv pour
# 10 lignes trahirait cette promesse — et le hook pre-push doit pouvoir tourner
# avec n'importe quel python, pas seulement celui du venv backend.
# Ce que Lintorn n'a PAS réussi à charger : TOML cassé, règle au motif
# invalide, dossier introuvable. Chaque entrée décrit un contrôle qui a cessé
# d'exister — d'où l'importance que `controle_configuration()` la lise.
SOUCIS_CONFIG: list[str] = list(_SOUCIS_PRECOCES)


# L'environnement réel PRIME sur le fichier : on peut toujours surcharger le
# temps d'une commande sans éditer le .env.
#
# Le fichier vit dans `.lintorn/` du projet audité, et non à sa racine : un
# `.env` de racine appartient déjà au projet (Django, Vite…) et le polluer
# avec des réglages d'outillage mélangerait deux choses sans rapport.
ENV = {**_lire_env(DOSSIER_LINTORN / ".env"), **os.environ}


# ─────────────────────────────────────────────────────────────────────────────
# LA CONFIG DU PROJET AUDITÉ — `[tool.lintorn]` de son pyproject.toml
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️ CE QUI APPARTIENT AU PROJET NE DOIT PAS VIVRE DANS L'OUTIL.
#
# Les règles maison, les contrôles activés, la liste blanche de vulture :
# tout cela décrit UN projet. Livré dans le paquet, ça imposait les conventions
# d'un seul projet à tous les autres, et produisait ailleurs des alertes qui ne
# voulaient rien dire.

# Les fichiers dont Lintorn a RETENU le contenu — le dénominateur du rapport :
# sans eux, un `[ OK ]` ne dit pas sur quoi il porte. « Retenu », pas
# « ouvert » : un `pyproject.toml` sans section `[tool.lintorn]` se parse très
# bien et n'apporte rien.
FICHIERS_CONFIG_LUS: list[str] = []


PROJET = _valider_config(_config_projet())


# ─────────────────────────────────────────────────────────────────────────────
# LE PYTHON QUI AUDITE — et non celui qui héberge Lintorn
# ─────────────────────────────────────────────────────────────────────────────


PYTHON, VENV_PROJET, VENV_SOUCI = _python_du_projet()

# Les modules que `lintorn outils` sait installer. Un autre module
# manquant appelle un autre conseil : renvoyer vers une commande qui ne le
# connaît pas, c'est pire qu'aucun conseil. Un test garde cette liste d'accord
# avec celle de `cli.OUTILS_PYTHON`.
OUTILS_INSTALLABLES = ("ruff", "pytest", "vulture", "pip_audit")


# ─────────────────────────────────────────────────────────────────────────────
# 1. LES OUTILS À LANCER
# ─────────────────────────────────────────────────────────────────────────────
# Chaque entrée = un programme externe.
#
#   titre       ce qui s'affiche dans le rapport
#   cmd         la commande, découpée en morceaux (pas une seule chaîne !)
#   cwd         depuis quel dossier la lancer
#   bloquant    True  = un problème ici annule le push
#               False = on informe, on ne bloque pas
#   traduction  None, ou une clé de outils.TRADUCTEURS
#   lent        True = ignoré avec l'option --rapide (et par le hook git)
#   codes_alerte  (optionnel) les codes de sortie qui veulent dire « j'ai TROUVÉ
#               des problèmes », par opposition à « je suis en panne ».
#               ⚠️ La convention « 1 = trouvé » n'est PAS universelle :
#               vulture répond 3. Sans cette précision, on croit l'outil
#               planté alors qu'il fait son travail.
#               Défaut : (1,)
#   produit     (optionnel) les fichiers que l'outil écrit pour dire son bilan :
#               effacés avant chaque lancement, pour ne jamais lire ceux d'hier.
#
# ── Liste blanche de vulture ─────────────────────────────────────────────────
# Noms que vulture déclare « inutilisés » alors qu'ils sont IMPOSÉS par une API :
# le framework appelle la fonction avec ces arguments, les retirer casse l'appel.
# Sur un projet Django, ces noms produisent 100 % de fausses alertes — et un
# contrôle qui n'a que des faux positifs finit par ne plus être lu, donc par ne
# plus rien protéger.
#
# ⚠️ N'ajoute ici QUE des noms imposés de l'extérieur. Tout ce qu'on y met
# devient invisible pour toujours — la liste blanche est un angle mort choisi.
#
# Sur un projet non-Django, vide cette liste : elle n'a rien d'universel.
# Défaut : les noms imposés par Django, et UNIQUEMENT si Django est détecté.
# Sur un projet qui n'en a pas, la liste est vide — un angle mort ne se
# distribue pas « au cas où ».
_VULTURE_DEFAUT = [
    "sender",        # récepteurs de signaux Django (@receiver)
    "app_configs",   # fonctions de check système (@register)
    "model_admin",   # actions, filtres et vues de l'admin Django
] if BACKEND else []

# Surcharge complète via `vulture_ignores = [...]` dans `[tool.lintorn]`.
VULTURE_IGNORES = PROJET.get("vulture_ignores", _VULTURE_DEFAUT)

# ── Fraîcheur de l'audit complet ─────────────────────────────────────────────
# Les outils LENTS (vulture, pip-audit) ne tournent PAS en `--rapide`, donc pas
# non plus dans le hook pre-push. Sans rappel, ils peuvent ne jamais tourner —
# et une faille de sécurité connue dort alors dans le projet sans que rien ne
# bouge, puisqu'elle apparaît sans qu'une ligne de code ait changé.
#
# On préfère un rappel DANS l'outil qu'une tâche planifiée : un planificateur
# qui meurt ne prévient personne (même leçon que `core.hooksPath`).
ETAT = DOSSIER_LINTORN / "etat.json"
JOURS_AUDIT_COMPLET = 30


# ─────────────────────────────────────────────────────────────────────────────
# LES OUTILS, MONTÉS SELON CE QUI EXISTE VRAIMENT
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️ La liste n'est plus figée : chaque entrée n'est ajoutée que si le dossier
# qu'elle vise a été DÉTECTÉ. Sur un projet sans Django, les contrôles Django
# ne s'affichent pas du tout — plutôt que d'apparaître en échec ou, pire, en
# « INDISPONIBLE » permanent que l'utilisateur apprendrait à ignorer.
#
# POUR AJOUTER UN OUTIL À TON PROJET, ce n'est PAS ici : déclare-le dans ton
# `.lintorn/config.toml` (ou `[tool.lintorn]` de ton pyproject.toml) —
#
#     [[commandes]]
#     cle   = "mypy"
#     titre = "Types (mypy)"
#     cmd   = ["{python}", "-m", "mypy", "."]   # {python} = celui du projet
#
# La liste ci-dessous n'est que le socle livré avec Lintorn. La modifier
# reviendrait à éditer un paquet installé, donc à tout perdre à la prochaine
# mise à jour. Elle ne concerne que qui développe Lintorn lui-même.
COMMANDES: list[dict] = []

# ── Python : ruff partout, dépendances seulement s'il y a un requirements ────
if PY_RACINE:
    COMMANDES.append(ruff.commande())
    # Proposé UNIQUEMENT s'il y a un requirements.txt à comparer : sans lui,
    # le contrôle resterait « INDISPONIBLE » à vie — un voyant mort qu'on
    # apprend à ignorer. Et sans venv DU PROJET, on comparerait requirements.txt
    # aux paquets de Lintorn : « Python du projet » dit déjà pourquoi.
    if REQUIREMENTS is not None and VENV_PROJET is not None:
        COMMANDES.append(requirements.commande())
    COMMANDES += [pytest.commande(), vulture.commande(), pip_audit.commande()]


# ── Django : seulement si `manage.py` a été trouvé ───────────────────────────
# ⚠️ `verifier_donnees` n'est PAS une commande de Django : c'est celle d'UN
# projet, rangée dans une de ses apps. Proposée à tout projet Django, elle
# finissait en « Unknown command » — un rouge bloquant sur un projet sain.
# Elle n'est donc proposée qu'au projet qui la déclare.
DONNEES_METIER = BACKEND is not None and any(
    fichier.name == "verifier_donnees.py" and fichier.parent.name == "commands"
    and fichier.parent.parent.name == "management" and fichier.is_relative_to(BACKEND)
    for fichier in _FICHIERS)

if BACKEND:
    COMMANDES += [commande for commande in django.commandes()
                  if commande["cle"] != "donnees_metier" or DONNEES_METIER]


# ── TypeScript : un `tsc` par projet TS ──────────────────────────────────────
# TypeScript n'est proposé que s'il y a vraiment du TypeScript : un front en
# JavaScript pur n'a pas de `tsc`, et le contrôle resterait éternellement
# « INDISPONIBLE » — un voyant qu'on apprend à ignorer, donc un voyant mort.
# ⚠️ Le `tsc` DU PROJET, pas `npx tsc` : sans TypeScript installé, npx
# partait le TÉLÉCHARGER — une sortie réseau que personne n'avait accordée,
# ~70 s d'attente, et un faux rouge bloquant fait d'erreurs réseau. Absent,
# il s'annonce maintenant « introuvable », avec son remède (`remede`).
TSC = "tsc.cmd" if sys.platform == "win32" else "tsc"

COMMANDES += tsc.commandes()


# ── Les failles des dépendances JavaScript ───────────────────────────────────
# `pip-audit` ne voit que les paquets PYTHON : les centaines de dépendances
# npm d'un front n'étaient auditées par rien, et leurs failles connues
# dormaient hors du rapport.
VERROU_NPM = "package-lock.json"

_npm_audit = npm_audit.commande(FRONTEND)
if _npm_audit:
    COMMANDES.append(_npm_audit)


# ── Les failles des AUTRES langages : OSV-Scanner ────────────────────────────
# Un seul outil pour une vingtaine d'écosystèmes : il lit leurs fichiers de
# verrou et interroge la base publique OSV. Il couvre ce que ni pip-audit ni
# npm audit ne voient — Rust, Go, PHP, Ruby, Java, .NET, Dart…
OSV = "osv-scanner"

ECOSYSTEMES_OSV = _ecosystemes_osv(_FICHIERS, FRONTEND)
_osv = osv.commande(ECOSYSTEMES_OSV,
                    demande=PROJET.get("controles", {}).get("failles_osv") is True)
if _osv:
    COMMANDES.append(_osv)

# ─────────────────────────────────────────────────────────────────────────────
# LE PRINCIPE DES DÉFAUTS : ne rien faire que l'utilisateur n'ait demandé
# ─────────────────────────────────────────────────────────────────────────────
# Par défaut, Lintorn NE MODIFIE RIEN, NE SORT PAS sur le réseau et N'EXÉCUTE
# PAS le code du projet. Tout ce qui franchit une de ces trois lignes porte
# `opt_in` et réclame un accord explicite.
#
# POURQUOI, alors que ces contrôles sont les plus utiles : quelqu'un qui
# découvre Lintorn le lance dans un dépôt qu'il connaît mal. Si ça déclenche
# sa suite de tests, ça peut créer des bases, écrire des fichiers, appeler des
# API. Le premier lancement doit être INCAPABLE de faire du dégât — c'est la
# condition pour qu'on ose l'essayer.
#
# Pour les activer, dans le `pyproject.toml` du projet :
#
#     [tool.lintorn.controles]
#     tests = true
#     failles = true
_actifs = PROJET.get("controles", {})


# ⚠️ Un controle opt-in non active DISPARAIT du rapport : rien ne distingue
# alors « ce projet n'a pas de front » de « tu n'as jamais accorde npm audit ».
# On garde donc la liste de ce qui s'applique a ce projet et qui attend un
# accord — le contrôle `Configuration (Lintorn)` la nomme.
CONTROLES_DISPONIBLES = [(commande["cle"], commande["titre"])
                         for commande in COMMANDES if not _accorde(commande)]
COMMANDES = [commande for commande in COMMANDES if _accorde(commande)]


# ─────────────────────────────────────────────────────────────────────────────
# LES COMMANDES AJOUTÉES PAR LE PROJET
# ─────────────────────────────────────────────────────────────────────────────


COMMANDES += _commandes_du_projet()


# ─────────────────────────────────────────────────────────────────────────────
# 2. LES CONTRÔLES MAISON (ceux qu'aucun outil du marché ne fait)
# ─────────────────────────────────────────────────────────────────────────────

_surcharges = PROJET.get("controles", {})
CONTROLES_INTERNES = {
    cle: bool(_surcharges.get(cle, defaut))
    for cle, defaut in _CONTROLES_DEFAUT.items()
}


# ── Une clé de [controles] qui ne pilote rien ────────────────────────────────


SOUCIS_CONFIG.extend(_cles_sans_effet(_surcharges, {c["cle"] for c in COMMANDES}))

# Les documents du DÉPÔT dont on vérifie qu'ils ne mentent pas.
#
# ⚠️ On les CHERCHE au lieu de les nommer un par un.
#
# Les emplacements sont des CONVENTIONS répandues, pas ceux d'un projet
# particulier : racine, puis les dossiers de documentation les plus courants.
# ⚠️ NE PAS se contenter d'une liste de dossiers nommes.
#
# Une premiere version ne cherchait qu'a la racine et dans quelques dossiers
# connus. Sur un projet dont la doc vivait dans `android/vessel/README.md`,
# ce fichier etait donc invisible — un angle mort parfaitement silencieux,
# alors que ce controle existe precisement pour les supprimer.
#
# On balaie donc TOUT le depot, en s'arretant net devant les dossiers de
# IGNORES (node_modules, venv, vendor…) qui contiennent la doc des AUTRES.
# `.lintorn/` en fait partie : sinon Lintorn analyserait son propre rapport.
# ⚠️ TOUTE DOCUMENTATION N'EST PAS VÉRIFIABLE — et c'est une limite assumée.
#
# Ce contrôle vise la doc DESCRIPTIVE : « le module `services/api.ts` fait
# ceci ». Elle décrit le projet, donc ses chemins doivent exister.
#
# Deux familles y échappent par nature :
#   - la doc PÉDAGOGIQUE : « créez un fichier `myapp.py` » cite un fichier que
#     le LECTEUR va créer, pas un fichier du projet ;
#   - la doc HISTORIQUE (changelog, release notes) : elle cite les fichiers de
#     toutes les versions passées, dont ceux qui ont disparu depuis.
#
# Mesuré sur un gros projet de référence : 460 « chemins morts » signalés,
# tous issus de ses tutoriels et de son changelog. À ce niveau de bruit, plus
# personne ne lit le contrôle — donc il ne protège plus rien.
#
#     [tool.lintorn]
#     docs_exclus = ["docs/**", "CHANGELOG.md"]
DOCS_EXCLUS = [str(motif) for motif in PROJET.get("docs_exclus", [])]


# ─────────────────────────────────────────────────────────────────────────────
# LE PÉRIMÈTRE : ce que git ignore n'appartient pas au projet
# ─────────────────────────────────────────────────────────────────────────────


# Les documents du dépôt mis de côté, par raison : annoncés dans le rapport.
DOCS_ECARTES: dict[str, list[str]] = {}
DOCS_A_VERIFIER = _documents_du_depot(DOCS_ECARTES)


FICHIERS_IA = [str(nom) for nom in PROJET.get("fichiers_ia", _FICHIERS_IA_DEFAUT)]
_NOMS_IA = {nom.lower() for nom in FICHIERS_IA if "/" not in nom}
_CHEMINS_IA = [nom.lower().strip("/") for nom in FICHIERS_IA if "/" in nom]


DOCS_IA = _instructions_ia()


MEMOIRE_IA, MEMOIRE_IA_ORIGINE = _dossier_memoire()
# Vrai quand la mémoire n'a été reconnue qu'à son nom : chaque contrôle qui la
# lit doit alors le dire, sur sa ligne même.
MEMOIRE_PAR_RESSEMBLANCE = (MEMOIRE_IA is not None
                            and MEMOIRE_IA_ORIGINE.startswith(PAR_RESSEMBLANCE))


# Racines depuis lesquelles un chemin cité dans la doc peut être relatif.
# `filter(None, ...)` est indispensable : BACKEND et FRONTEND valent None sur
# un projet qui n'en a pas, et un None ici ferait planter toute résolution.
RACINES_RESOLUTION = [
    chemin for chemin in (
        RACINE,
        BACKEND,
        FRONTEND,
        FRONTEND / "src" if FRONTEND else None,
        BACKEND.parent if BACKEND else None,
    ) if chemin is not None
]


# ─────────────────────────────────────────────────────────────────────────────
# 3. LES RÈGLES MAISON — celles écrites dans CLAUDE.md
# ─────────────────────────────────────────────────────────────────────────────
# Une règle qu'aucun outil ne mesure finit toujours par être contournée sans
# que personne ne s'en aperçoive.
#
#   motif     une expression régulière : ce qu'on cherche
#   exclure   des bouts de chemin où la règle ne s'applique pas
#   bloquant  True pour une règle DÉJÀ respectée (on empêche la régression)
#             False pour une dette existante (on mesure, on ne bloque pas)
#
# ⚠️ AUCUNE RÈGLE N'EST LIVRÉE AVEC L'OUTIL — et c'est délibéré.
#
# Une règle maison décrit LA maison : « importer axios depuis services/api.ts »
# n'a aucun sens ailleurs. Livrées dans le paquet, elles produisaient chez les
# autres des alertes incompréhensibles, ou pire, un vert rassurant sur une
# règle qui ne scannait aucun fichier.
#
# Elles se déclarent donc dans le `pyproject.toml` DU PROJET :
#
#     [[tool.lintorn.regles]]
#     nom      = "Couleurs en dur dans un CSS"
#     regle    = "uniquement des variables de theme (var(--bg)...)"
#     racine   = "front/src"          # relatif à la racine du dépôt
#     suffixes = [".css"]
#     motif    = "#[0-9a-fA-F]{3,8}\\b|\\brgba?\\("
#     exclure  = ["components/shared/plates/"]
#     bloquant = false                # true = interdire la régression
# Le fichier dedie aux regles maison.
#
# POURQUOI UN FICHIER A PART. `config.toml` et les regles n'ont pas la meme
# vie : le premier est un REGLAGE, ecrit une fois et presque jamais retouche ;
# les secondes sont une LISTE DE TRAVAIL qui grossit, qu'on edite chaque
# semaine et qu'on relit a plusieurs. Melangees, un vrai projet donnait un
# config.toml de 280 lignes ou les six reglages se noyaient dans vingt-quatre
# brouillons de regles.
FICHIER_REGLES = DOSSIER_LINTORN / "regles.toml"


# REGLES_MAISON : ce que Lintorn fait respecter lui-meme.
# HORS_PORTEE   : ce que le projet a decide de NE PAS exprimer en motif, avec
#                 sa raison. Deux listes, parce que ce sont deux choses.
REGLES_MAISON, HORS_PORTEE = _regles_du_projet()
