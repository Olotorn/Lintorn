# Lintorn : le guide détaillé

> Pour démarrer, le [README](README.md) suffit. Ce guide entre dans le détail : la
> configuration, les autres langages, les cas particuliers.

**Audite ton code et la mémoire que lit ton assistant IA et te dit quand les deux ont divergé.**


Les assistants de code lisent la documentation de ton projet : CLAUDE.md, notes
d'architecture, fichiers de mémoire persistante. Cette documentation s'écrit une fois, puis
pourrit en silence. L'assistant continue de la lire, de lui faire confiance, et d'appliquer
des règles qui ne correspondent plus au code.

Lintorn regarde les deux côtés. Il lance les outils de qualité habituels sur ton code, et il
vérifie que chaque chemin, chaque règle et chaque affirmation de ta documentation correspond
encore à quelque chose de réel. Quand les deux se contredisent, il le dit.

```console
$ pipx install lintorn
$ cd ton-projet
$ lintorn init
$ lintorn

=== Lintorn - RAPPORT AUDIT ===
[ OK ] Ruff (lint Python)          rien a signaler
[ OK ] TypeScript (tsc --noEmit)   rien a signaler
[ !! ] Doc vs code                 124 chemin(s) cite(s), 12 introuvable(s)
[ ?? ] Memoire IA vs code          46 chemin(s) cite(s), 3 a verifier
[ ?? ] Regles enoncees vs controlees  25 enoncee(s), 1 controlee(s), 24 SANS controle
[ OK ] Hook pre-push               branche et executable
```

## À lire avant d'installer

**Lintorn est un outil expérimental, en pleine croissance, et il n'est pas stable à 100 %.**

- il est **mis à jour souvent** ;
- il a été **éprouvé en conditions réelles sur peu de projets** (voir le README). Sur une
  arborescence qu'il ne connaît pas, sa détection peut se tromper ;
- le **format de configuration bouge encore**. Il ne sera figé qu'à la 1.0.

Je ne vends rien. C'est un outil écrit pour mon propre usage, publié parce qu'il peut servir à
des développeurs comme moi. Si la détection déraille chez toi, ouvre un ticket (*issue*) sur
[GitLab](https://gitlab.com/DamXs/lintorn/-/issues) : c'est ce qui fait avancer le projet.

Lintorn demande Python 3.11 ou plus récent.

## pipx ou pip ?

**pipx est recommandé, pip reste possible.**

- Avec **pipx**, Lintorn s'installe une seule fois pour tout ton compte, dans son propre
  environnement. La commande `lintorn` est trouvée de partout : ton terminal, le bouton Git
  de VS Code, n'importe lequel de tes projets. Il ne se mélange pas aux dépendances de tes
  projets.
- Avec **pip**, Lintorn s'installe dans l'environnement actif, souvent le venv du projet, et
  n'existe que là. Un push lancé d'ailleurs (un terminal où ce venv n'est pas activé, un
  éditeur qui n'a pas le même PATH que ton terminal) ne le trouve pas : le hook affiche
  « Lintorn introuvable » et laisse passer le push **sans vérification**. Le contrôle
  `Hook pre-push` te le rappelle ensuite. Avec pip, pousse donc depuis un terminal où ce venv
  est actif.

## Le principe

> **Un contrôle qui se tait est plus dangereux qu'un contrôle qui passe au rouge.**

Lintorn ne te laisse jamais croire qu'une chose a été vérifiée quand elle ne l'a pas été :

- un outil **non installé** est annoncé indisponible, jamais « 0 problème trouvé » ;
- une règle dont le dossier cible n'existe pas est **écartée**, pas rapportée comme tenue ;
- une règle qui n'a lu **aucun fichier** le dit, au lieu de compter comme respectée ;
- **aucune** règle déclarée est annoncé comme tel, au lieu de « toutes les règles sont tenues » ;
- son propre hook git est vérifié jusqu'au **bit exécutable** : git ignore un hook non
  exécutable sans aucun message.

## Ce qu'il vérifie

| Domaine | Contrôles |
|---|---|
| **Doc vs code** | chaque chemin cité dans ta documentation existe encore |
| **Mémoire IA vs code** | même traitement pour la mémoire persistante de ton assistant |
| **Fraîcheur des mémoires** | une mémoire qui cite du code modifié depuis sa dernière vérification |
| **Règles maison** | tes propres conventions, appliquées mécaniquement |
| **Énoncé vs contrôlé** | les règles écrites dans CLAUDE.md qu'aucun contrôle ne fait respecter |
| **Python** | ruff, `requirements.txt` vs venv, migrations manquantes, `manage.py check`, pytest, pip-audit, vulture |
| **JavaScript** | `tsc --noEmit`, `npm audit` |
| **Les autres langages** | les failles connues de leurs dépendances, par OSV-Scanner (Rust, Go, PHP, Ruby, Java, .NET, Dart…) |
| **L'outillage lui-même** | son hook pre-push est-il installé, exécutable *et* à jour |

Tout est détecté automatiquement : un contrôle qui ne concerne pas ton projet (les contrôles
Django sur un projet sans Django) n'apparaît pas.

## Avec un assistant IA, c'est beaucoup plus rapide

**Lintorn ne contient aucun LLM, et n'en appellera jamais.** Il est gratuit, tourne hors
ligne, sans clé d'API, dans un hook git, avec n'importe quel Python de la machine.

Mais il est *fait pour* la boucle où un assistant lit sa sortie. Pour l'installer sur un
projet, un agent IA fait gagner un temps considérable :

- il lit ton code et ton CLAUDE.md, en déduit les réglages, et écrit le `config.toml` ;
- il écrit les **motifs** de tes règles maison, la seule chose que Lintorn ne peut pas
  deviner : une règle maison est une décision, pas une propriété du code ;
- il lit le rapport et **se corrige lui-même** au fur et à mesure que les règles se mettent en
  place ;
- il repère les particularités de ton projet que la détection automatique ne couvre pas.

**Ce n'est pas obligatoire.** Sans assistant, Lintorn fonctionne exactement pareil : tu écris
la config toi-même, et `lintorn init` puis `lintorn regles` te préparent le terrain.

## Les règles que tu énonces, celles que tu fais respecter

Lintorn lit les règles de ton fichier d'instructions IA (CLAUDE.md, AGENTS.md…) et signale
celles qu'aucun contrôle ne fait respecter.

Il n'invente jamais le motif d'une règle. *« Ne jamais coder une couleur en dur »* ne dit pas
s'il faut chercher `#fff`, `rgba(` ou `hsl()`, ni si les commentaires sont exemptés : c'est à
toi (ou à ton assistant) de l'écrire. `lintorn regles` prépare un brouillon commenté par règle
non couverte, tout rempli sauf le motif :

```toml
# [[regles]]
# source   = "CLAUDE.md:23"   # la regle est ENONCEE la-bas, pas ici
# nom      = "Axios partage"
# racine   = "."
# suffixes = [".ts", ".tsx"]
# motif    = ''               # <- a toi de l'ecrire : a quoi ressemble une VIOLATION
# bloquant = false
```

`source` désigne la ligne où la règle est énoncée : la phrase reste écrite à un seul endroit.
Ce contrôle ne bloque jamais un push.

## Les documents qui citent ce qui n'existe pas

Une roadmap, une note de conception ou un compte rendu peut citer des fichiers qui n'existent
pas encore, ou plus. Marque le document, n'importe où dedans :

```markdown
<!-- lintorn:prospectif -->
```

Ses chemins morts sont alors **listés, pas bloquants** : tu les vois toujours, ils n'arrêtent
plus ton push.

Deux genres de documents reçoivent ce traitement sans aucun marqueur :

- **les tutoriels** : un document dont la plupart des chemins cités n'existent pas ici
  décrit le projet du lecteur, pas le tien. Une citation morte isolée, elle, reste bloquante ;
- **les journaux de versions** : un fichier dont le nom contient changelog, changes,
  release-notes, history ou news (CHANGELOG.md, HISTORY.md, NEWS.md…), ou rangé dans un
  dossier changelog/, release-notes/ ou releases/.

Le résumé du contrôle compte ces documents.

## Sans danger par défaut

Le premier lancement ne peut rien abîmer. Lintorn ne modifie pas tes fichiers, ne sort pas sur
le réseau, et n'exécute pas le code de ton projet sans que tu le demandes.

### L'accord avant de lancer

Lintorn **lit** sans rien demander : ta doc, ta mémoire IA, tes règles. Mais il ne **lance**
aucun programme dans ton projet (ruff, pytest, tsc, tes outils maison) sans ton accord. Au
premier lancement, il te montre ce qu'il veut lancer et te demande `[o/N]` : non par défaut.

Cet accord est noté **hors du projet**, dans ta configuration à toi (~/.config/lintorn/, ou
%APPDATA%\lintorn sous Windows) : chaque personne qui clone le projet donne le sien. Il ne se
redemande pas, sauf si quelque chose change : une nouvelle commande, ou le contenu d'un script
de ton projet qu'un outil maison lance. Lintorn te dit alors quel fichier a changé.

Sans terminal pour répondre (le hook lancé par VS Code, la CI), il ne lance rien et **le dit** :
le hook termine par « Push autorisé SANS vérification complète ». `lintorn confiance`, une fois
dans un terminal, donne l'accord. En CI, `LINTORN_CONFIANCE=oui` l'accorde d'office.

### Ce qui est opt-in

Ceux-là sont **opt-in** : `tests` (exécute ton code), `django_check` et `migrations`
(ils importent tes réglages et toutes tes apps, donc ton code), `failles`, `failles_npm` et
`failles_osv` (réseau), `donnees_metier` (ouvre ta base), `code_mort` et `deploy` (bruyants
pendant le développement). `lintorn outils` te les propose un par un.

Le contrôle `Configuration (Lintorn)` liste ceux qui s'appliquent à ton projet et que tu n'as
pas encore accordés. Il signale aussi une clé mal tapée, une clé activée sur un projet qui n'a
rien à lui faire contrôler (`failles_npm` sans package-lock.json), et une valeur du mauvais
type. Seuls `true` et `false` valent accord : `tests = "false"`, écrit entre guillemets,
n'active rien.

### Ce que Lintorn écrit

Sans que tu le demandes, Lintorn n'écrit que dans le `.lintorn/` de ton projet, et jamais à
travers un lien symbolique, fichier **ou dossier**. Les commandes qui écrivent ailleurs le
disent et te le demandent : `lintorn outils` (ta configuration, jusque dans `pyproject.toml`
si elle y vit), `lintorn pip-audit --appliquer` (`requirements.txt`) et `lintorn hook` (le
`core.hooksPath` de ce clone).

Il ne télécharge pas `tsc` : il utilise celui de ton projet, installé par `npm install`.

## Les rapports

Chaque lancement écrit son rapport deux fois : en Markdown (`.md`), et en page web (`.html`,
à ouvrir dans un navigateur, lisible sur un téléphone, sans réseau). Les deux disent la même
chose.

| Fichiers | Écrits par | Ils restent jusqu'à |
|---|---|---|
| `.lintorn/rapport.md` et `.lintorn/rapport.html` | tes commandes (`lintorn`, `lintorn rapide`, `lintorn doc`…) | ta prochaine commande |
| `.lintorn/rapport-push.md` et `.lintorn/rapport-push.html` | le hook, à chaque push | ton prochain push |

La première ligne de chaque rapport dit d'où il vient : « pendant un push » ou « hors push ».

## Configuration

`lintorn init` écrit deux fichiers :

| Fichier | Ce qu'il contient | Comment il vit |
|---|---|---|
| `.lintorn/config.toml` | les réglages : quels contrôles tournent, quels fichiers sont des instructions IA | écrit une fois, peu touché |
| `.lintorn/regles.toml` | tes règles maison | grossit, s'édite souvent, se relit à plusieurs |

Les réglages peuvent aussi vivre sous `[tool.lintorn]` dans ton `pyproject.toml`. Des règles
écrites dans ta configuration et dans `regles.toml` s'additionnent.

```toml
[controles]
tests = true

[[regles]]
nom      = "Couleurs en dur dans un CSS"
regle    = "uniquement des variables de theme, comme var(--bg)"
racine   = "front/src"
suffixes = [".css"]
motif    = '#[0-9a-fA-F]{3,8}\b'
bloquant = false          # true = empeche la regression, false = mesure la dette

[[commandes]]
cle   = "mypy"
titre = "Types (mypy)"
cmd   = ["{python}", "-m", "mypy", "."]   # {python} = le Python du projet, son venv compris
```

Une règle dit **une** des deux choses, jamais les deux. `motif` décrit à quoi ressemble une
**violation** ; `motif_requis` décrit ce qui **doit être présent**. Ajoute `si` et la règle ne
s'applique qu'aux fichiers qui le contiennent. C'est comme ça qu'on exprime *si X apparaît,
alors Y doit apparaître aussi* :

```toml
[[regles]]
nom          = "Un total cite sans sa source"
regle        = "citer le releve des qu'on cite le total"
racine       = "docs"
suffixes     = [".md"]
motif_requis = 'releve du \d{2}/\d{2}'
si           = '\btotal\b'
bloquant     = true
```

Une règle conditionnelle dont le `si` n'a jamais été trouvé n'a rien vérifié : elle n'est pas
comptée comme tenue, et le rapport dit combien sont restées inertes, avec un lien vers leur
ligne dans `regles.toml`.

### Quand aucun motif ne peut exprimer la règle

Certaines règles dépassent une expression régulière : comparer deux fichiers, vérifier une
propriété structurelle, ou distinguer un usage fautif d'un usage légitime identique.
Déclare-la **hors de portée**, avec sa raison :

```toml
[[regles]]
source      = "CLAUDE.md:50"
nom         = "Versions"
hors_portee = """
Comparer DEUX fichiers depasse un motif, qui lit un fichier a la fois.
Couverte par test_les_deux_numeros_de_version_sont_d_accord.
"""
```

Trois garde-fous l'accompagnent :

- **`source` est obligatoire** : sans lui, la déclaration ne désigne aucune ligne de doc, donc
  ne couvre rien ;
- **si la raison cite un `test_...`, Lintorn vérifie qu'il existe.** Test renommé ou supprimé :
  la règle redevient visible, et le rapport dit laquelle ;
- **le compte reste affiché** : `7 enoncee(s), 2 controlee(s), 5 hors de portee`.

Les commandes personnalisées sont **exécutées**, avec le même contrat que les scripts npm, les
hooks git ou un Makefile. Ne lance pas Lintorn dans un dépôt en qui tu n'as pas confiance.

## Les autres langages

Lintorn est *écrit* en Python ; il n'exige pas que ton projet le soit. Les quatre contrôles
qui font sa particularité (doc vs code, mémoire IA, règles maison, intégrité du hook)
fonctionnent sur n'importe quel dépôt.

Les **failles connues** des dépendances sont couvertes pour presque tous les écosystèmes :

| Écosystème | Audit | Clé |
|---|---|---|
| Python | pip-audit | `failles` |
| JavaScript (npm) | `npm audit`, dès qu'il y a un package-lock.json | `failles_npm` |
| Rust, Go, PHP, Ruby, Java, .NET, Dart, Elixir, R, Swift… | [OSV-Scanner](https://google.github.io/osv-scanner/), qui lit leurs fichiers de verrou | `failles_osv` |

OSV-Scanner lit aussi les verrous npm et Python : une faille déjà signalée par npm audit ou
pip-audit peut réapparaître sur sa ligne. Il ne s'installe pas par pip : `brew install
osv-scanner`, ou l'une des [autres méthodes](https://google.github.io/osv-scanner/installation/).
Lintorn désactive son analyse d'appels, qui compilerait ton projet.

Un audit qui n'a pas pu répondre (réseau coupé, verrou illisible) s'affiche `INDISPONIBLE`,
jamais « 0 faille ».

Tout le reste se branche par `[[commandes]]` : phpstan, eslint, `go vet`, `cargo clippy`.

## Les outils externes

Lintorn n'a **aucune dépendance** : il tourne avec n'importe quel Python 3.11+ de la machine.
Les outils qu'il lance sont ceux de ton projet : ruff applique *tes* règles, pytest voit *tes*
dépendances.

```console
$ lintorn outils
```

Il regarde ce que contient ton projet et ne propose que ce qui s'y applique : pas de
pip-audit sans Python, pas de npm audit sans verrou npm. Deux gestes, deux accords :

- **installer** les outils Python qui manquent (ruff, pytest, vulture, pip-audit) dans le
  venv de ton projet, en une seule question. Le contrôle `Dependances vs venv` ne les compte
  pas parmi tes dépendances, ni ce qui n'est là que pour eux : il les nomme à part dans le
  rapport. Un paquet qu'ils tirent mais que ton code importe, ou qu'une de tes dépendances
  tire aussi, reste le tien. Si une faille touche un paquet qui n'est là que pour eux
  (certifi, tiré par pip-audit), `lintorn pip-audit --appliquer` le met à jour sans l'ajouter
  à ton `requirements.txt` ;
- **activer** chaque contrôle opt-in, un par un, en disant ce qu'il implique (exécuter ton
  code, sortir sur le réseau). `--oui` ne répond qu'à la première question, jamais aux
  suivantes.

Ce qu'il ne sait pas installer lui-même, il le dit, avec la commande : `npm install` pour
`tsc`, Node.js pour npm audit, Homebrew ou le site d'OSV-Scanner pour ce dernier.

Le contrôle `Dependances vs venv` compare `requirements.txt` à ce qui est installé. Une ligne
avec une version exacte (`django==5.0`) est comparée à la version installée ; une ligne sans
(`django>=5`, `django`) dit seulement que le paquet doit être là. Le fichier peut être complet
(comme l'écrit `pip freeze`) ou ne lister que tes dépendances directes : un paquet sans ligne que
tire une de tes dépendances n'est pas signalé, pip l'installera partout. Sauf si ton code
l'importe lui-même : ce que tu importes se déclare.

### Quel Python les lance

Lintorn cherche le virtualenv de ton projet dans `venv/`, `.venv/` et `env/`, à la racine du
dépôt comme dans son dossier Python, et utilise l'interpréteur qu'il y trouve.

Quand il n'en trouve aucun, il se replie sur le sien, et la ligne `Python du projet (venv)`
le dit : pip-audit et la comparaison avec `requirements.txt` portent alors sur l'environnement
de Lintorn, pas sur celui de ton projet.

Si ton virtualenv vit hors du projet (poetry, pdm, conda, pipenv), indique-le :

```toml
[tool.lintorn]
venv = "../.venvs/mon-projet"
```

## Sans dépôt git

Lintorn fonctionne sur un dossier non versionné. Le hook pre-push et la fraîcheur des
mémoires n'y ont pas d'objet, et `.gitignore` n'écarte plus rien de l'audit : Lintorn le dit
dans son rapport.

Sans git, il parcourt le dossier lui-même. Au-delà de 50 000 fichiers, il s'arrête et ne lance
rien. Dans un dépôt git, cette limite n'existe pas. `lintorn version`, `lintorn help` et
`lintorn guide` répondent de partout, sans rien lire.

## Les commandes

```console
lintorn                      audit complet
lintorn rapide               saute les outils lents (ce que lance le hook pre-push)
lintorn doc                  le controle de documentation seul
lintorn init                 genere la config de ce projet
lintorn regles               esquisse un bloc [[regles]] par regle non couverte
lintorn hook                 installe le hook pre-push (sans faire taire tes hooks existants)
lintorn confiance            autorise Lintorn a lancer ses outils dans ce projet
lintorn outils               installe et active ce qui s'applique a ce projet, en demandant
lintorn pip-audit            ce que propose pip-audit (a blanc)
lintorn guide                la notice en une page : a quoi il sert, comment lire un rapport
lintorn version              la version installee
lintorn help                 l'aide
```

Une option mal tapée n'est jamais ignorée : Lintorn s'arrête, ne lance rien, et propose
l'option la plus proche.

## Un dépôt, plusieurs projets

Dans un monorepo, chaque sous-projet peut avoir son Lintorn. Désigne-lui son dossier avec
`LINTORN_RACINE`, depuis le sommet du dépôt (sans elle, Lintorn remonte jusqu'au `.git` et
audite tout le dépôt) :

```console
$ LINTORN_RACINE=api lintorn init
$ LINTORN_RACINE=api lintorn hook
$ LINTORN_RACINE=web lintorn init
$ LINTORN_RACINE=web lintorn hook
```

git ne lance qu'un seul hook : celui du premier sous-projet branché lance aussi celui des
autres, avec la liste de ce qui part. Il n'y a rien à ajouter nulle part. Chaque sous-projet
ne juge que ses propres fichiers, annonce son nom au moment du push
(« Lintorn controle avant push : web/ »), et écrit son rapport du push dans son `.lintorn/`.
Un refus de l'un annule le push.

Le hook trouve les autres sous-projets par leur `.lintorn/` versionné : garde la
configuration dans git, comme `lintorn init` la prépare. Le contrôle `Hook pre-push` de chaque
sous-projet dit par quel hook il est lancé, ou pourquoi il ne l'est pas.

## Le hook pre-push

`lintorn hook` installe le hook : à chaque `git push`, il lance `lintorn rapide` et bloque le
push si un contrôle **bloquant** est au rouge. Avec un terminal, il te demande d'abord si tu
veux pousser quand même.

### Si ton projet a déjà des hooks

git ne lit qu'un seul dossier de hooks. Si ton projet en a déjà (pre-commit, husky, ou écrits
à la main), `lintorn hook` ne les fait pas taire : il pose son script sans le brancher, et te
donne la ligne à ajouter à ton propre pre-push :

```bash
.lintorn/hooks/pre-push "$@" || exit 1
```

Copie celle qu'il t'affiche : dans un monorepo, elle commence par le dossier de ton
sous-projet. Mets-la **avant tout `exit`**. Avec husky, c'est dans .husky/pre-push, pas dans
.husky/_/ (ces fichiers-là sont régénérés).

Garde le `|| exit 1` : c'est lui qui annule le push quand Lintorn le refuse. Sans lui, le push
part quand même. Appelé par ton hook, Lintorn affiche « LINTORN REFUSE CE PUSH », jamais
« PUSH ANNULE ». Quand personne ne pouvait répondre à sa question (un push depuis VS Code), le
contrôle `Hook pre-push` signale ensuite le push parti malgré son refus.

Avec pre-commit, lefthook ou simple-git-hooks, pas de ligne : ces outils réécrivent leurs
scripts à chaque installation. `lintorn hook` te donne alors le bloc à mettre dans **leur**
config, et la commande à relancer. Copie-le en entier : `use_stdin: true` (lefthook) transmet
à Lintorn ce que tu pousses, et `verbose: true` (pre-commit) affiche ce qu'il dit même quand il
laisse passer. Le contrôle `Hook pre-push` te prévient si `verbose: true` manque.

Sous Windows, pre-commit ne laisse pas Lintorn accéder au terminal : il ne peut pas te
demander s'il faut pousser quand même, et refuse le push si un contrôle bloquant est au
rouge. Seul `git push --no-verify` passe alors outre.

`lintorn hook --force` branche Lintorn quand même : il te dit quels hooks ne tourneront plus,
et le contrôle `Hook pre-push` te le rappelle tant qu'ils sont là.

### Vérifier qu'il tourne

Après l'installation, **pousse une fois**. Le contrôle `Hook pre-push` passe au vert quand il
a **vu** Lintorn tourner pendant un push.

Sur un autre clone, relance `lintorn hook` : le script n'est pas versionné, et sans lui ton
push s'arrête sur « not found ». Pareil dans un **worktree** (ceux que Claude Code crée pour
ses agents, par exemple) : le contrôle `Hook pre-push` te le signale, et un `lintorn hook` dans
le worktree règle ça.

Une limite : Lintorn s'appuie sur le journal où git note chaque push. Un push qui n'y laisse
aucune trace lui échappe : un push vers une adresse plutôt que vers le nom d'un dépôt distant
(git push https://… au lieu de git push origin), ou le push de Gerrit vers refs/for/main. Le
contrôle affiche alors le dernier push qu'il a vu. Si git ne tient plus ce journal
(`core.logAllRefUpdates = false`), le contrôle le dit.

### Ce que le hook dit au push

Le détail de chaque push est dans `.lintorn/rapport-push.md` (voir
[Les rapports](#les-rapports)).

La dernière ligne du hook ne dit « Lintorn OK » que si ce que tu pousses a été vérifié.
Sinon, le push passe quand même (rien de bloquant n'a été trouvé), mais elle dit « Push
autorisé SANS vérification complète », avec la raison juste au-dessus :

- un outil n'a rien vérifié (accord non validé, outil absent, ou outil qui a planté) ;
- ta configuration n'est pas entièrement chargée : un guillemet oublié dans `regles.toml`
  suffit à retirer toutes tes règles maison, et Lintorn te dit quelle ligne ;
- aucun des fichiers que tu pousses n'est lu par un contrôle (une feuille de style, une image,
  poussées seules). Si une partie seulement n'est pas lue, le push garde son « Lintorn OK » :
  la ligne « Defauts dans les fichiers pousses » nomme ce que rien ne lit ;
- Lintorn ne sait pas ce que tu pousses : la copie du hook date d'une version précédente
  (relance `lintorn hook`), ou l'outil qui l'appelle ne lui transmet pas ce que git envoie ;
- ce que tu pousses n'est pas ce qu'il y a sur ton disque.

Ce dernier cas : Lintorn lit les fichiers **de ton disque**, git envoie des **commits**. Quand
les deux diffèrent (une correction pas encore commitée, le push d'une autre branche ou d'un
tag que celle où tu es), Lintorn nomme les fichiers concernés. Pour qu'il vérifie exactement
ce qui part, commite tes modifications (ou mets-les de côté avec `git stash`), ou pousse
depuis la branche concernée.

Quand rien de nouveau ne part de ton projet (une branche supprimée, des commits déjà sur le
serveur poussés sous un autre nom, un push qui ne touche qu'un autre sous-projet), Lintorn le
dit (« rien de nouveau ne part ») et laisse partir : il n'a rien à juger.

Si la version de Lintorn que lance le hook n'est pas celle qui l'a posé (le venv d'un autre
projet activé dans ton terminal, par exemple), le hook le signale en tête de son message.

Si la commande `lintorn` est introuvable au moment du push, le hook laisse passer, et le dit.
Le contrôle `Hook pre-push` le signale ensuite : « ton dernier push est parti SANS Lintorn ».
Voir [pipx ou pip ?](#pipx-ou-pip-).

## Mettre à jour Lintorn

```console
$ pipx upgrade lintorn        # ou : pip install --upgrade lintorn
$ lintorn hook                # dans chacun de tes projets
```

Le hook posé dans ton projet est une copie, que la mise à jour ne touche pas : relance
`lintorn hook` après chaque mise à jour. Le contrôle `Hook pre-push` te prévient quand la
copie est périmée.

Pour savoir quand une nouvelle version sort : le [flux RSS de
PyPI](https://pypi.org/rss/project/lintorn/releases.xml).

## Licence

[AGPL-3.0](LICENSE). Utilise-le, modifie-le et partage-le librement. Si tu le distribues, ou
si tu l'offres comme service en réseau, tu dois publier ta source sous la même licence.

C'est un choix délibéré : Lintorn est donné, et cette licence empêche que quelqu'un le
referme pour le revendre. Détenteur du copyright : **Olotorn**. Pour une licence commerciale
dispensant de l'obligation de publier la source, contacte-moi.

## Contribuer

Pas encore ouvert aux contributions de code extérieures. Les rapports de bug et les idées,
eux, sont les bienvenus, et c'est ce qui aide le plus à ce stade. Quand ça ouvrira, les
contributions demanderont un CLA, pour que la double licence reste possible. Détails dans
`CONTRIBUTING.md`.
