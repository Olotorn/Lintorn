# Lintorn — le guide détaillé

> Pour démarrer, le [README](README.md) suffit. Ce guide entre dans le détail : la
> configuration, les autres langages, les cas particuliers.

**Audite ton code et la mémoire que lit ton assistant IA et te dit quand les deux ont divergé.**


Les assistants de code lisent la documentation de ton projet : `CLAUDE.md`, notes
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

Ce n'est pas une formule de prudence, c'est l'état réel du projet :

- il est **mis à jour souvent**, pour corriger les défauts trouvés en cours de route — dont
  certains sont trouvés par Lintorn lui-même, qui s'audite ;
- il a été **éprouvé sur quelques projets seulement** (Django + React, FastAPI, un projet Go,
  un dossier sans code source). Sur une arborescence qu'il ne connaît pas, sa détection peut
  se tromper ;
- le **format de configuration bouge encore**. Il ne sera figé qu'à la 1.0.

Je ne vends rien. C'est un outil écrit pour mon propre usage, publié parce qu'il peut servir à
des développeurs comme moi. Si la détection déraille chez toi, c'est une information utile :
ouvre une issue, c'est exactement ce qui fait avancer le projet.

## L'idée sur laquelle il est bâti

> **Un contrôle qui se tait est plus dangereux qu'un contrôle qui passe au rouge.**

Un rouge se répare. Un contrôle qui cesse silencieusement de fonctionner te laisse croire que
tu es couvert alors que plus rien n'est surveillé. Lintorn traite ça comme la panne
principale, partout :

- un outil **non installé** est annoncé indisponible — jamais « 0 problème trouvé » ;
- une règle dont le dossier cible n'existe pas est **écartée**, pas rapportée comme tenue ;
- une règle qui n'a lu **aucun fichier** le dit, au lieu de compter comme respectée ;
- **aucune** règle déclarée est annoncé comme tel, au lieu de « toutes les règles sont tenues » ;
- son propre hook git est vérifié jusqu'au **bit exécutable** — git ignore un hook non
  exécutable dans le silence le plus complet, et c'est exactement comme ça que ce projet a
  perdu son garde-fou pendant quatre jours.

## Ce qu'il vérifie

| Domaine | Contrôles |
|---|---|
| **Doc vs code** | chaque chemin cité dans ta documentation existe encore |
| **Mémoire IA vs code** | même traitement pour la mémoire persistante de ton assistant |
| **Fraîcheur des mémoires** | une mémoire qui cite du code modifié depuis sa dernière vérification |
| **Règles maison** | tes propres conventions, appliquées mécaniquement |
| **Énoncé vs contrôlé** | les règles écrites dans `CLAUDE.md` qu'aucun contrôle ne fait respecter |
| **Python** | ruff, migrations manquantes, `manage.py check`, pytest, pip-audit, vulture |
| **JavaScript** | `tsc --noEmit`, `npm audit` |
| **Les autres langages** | les failles connues de leurs dépendances, par OSV-Scanner — Rust, Go, PHP, Ruby, Java, .NET, Dart… |
| **L'outillage lui-même** | son hook pre-push est-il installé, exécutable *et* à jour |

Tout est détecté automatiquement. Pas de Django ? Les contrôles Django n'apparaissent pas du
tout — plutôt que de rester en permanence « indisponibles », ce qui transforme un voyant
d'alerte en meuble.

## Avec un assistant IA, c'est beaucoup plus rapide

**Lintorn ne contient aucun LLM, et n'en appellera jamais.** C'est ce qui lui permet d'être
gratuit, de tourner hors ligne, sans clé d'API, dans un hook git, avec n'importe quel Python
de la machine.

Mais il est *fait pour* la boucle où un assistant lit sa sortie. Et pour l'installer sur un
projet, un agent IA fait gagner un temps considérable :

- il lit ton code et ton `CLAUDE.md`, en déduit les réglages, et écrit le `config.toml` ;
- il écrit les **motifs** de tes règles maison — la seule chose que Lintorn ne peut pas
  deviner, parce qu'une règle maison est une décision, pas une propriété du code ;
- il lit le rapport et **se corrige lui-même** au fur et à mesure que les règles se mettent en
  place : chaque règle ajoutée resserre ce que l'assistant a le droit de faire au coup
  suivant ;
- il repère les particularités de ton projet que la détection automatique ne couvre pas.

C'est mesuré, pas théorique : un assistant sans aucune connaissance préalable de Lintorn l'a
configuré de bout en bout sur un dossier **sans une ligne de code source**, et a remonté dans
la foulée de vraies lacunes de l'outil.

**Ce n'est pas obligatoire.** Sans assistant, Lintorn fonctionne exactement pareil — tu écris
la config toi-même, et `lintorn init` puis `lintorn regles` te préparent le
terrain. L'assistant fait gagner du temps, il n'ouvre aucune porte.

## Les règles que tu énonces, celles que tu fais respecter

Ton `CLAUDE.md` dit à un assistant quelles sont les règles du projet. Rien ne relie ces
phrases à quoi que ce soit qui les fasse respecter, donc l'écart entre ce qu'un projet
*déclare* et ce qu'il *vérifie* grandit en silence : personne ne relit une documentation en
cherchant ce qui manque ailleurs.

Lintorn lit les règles dans ton fichier d'instructions IA et signale celles qu'aucun contrôle
ne couvre. Il n'invente jamais la détection. *« Ne jamais coder une couleur en dur »* ne dit
pas s'il faut chercher `#fff`, `rgba(` ou `hsl()`, ni si les commentaires sont exemptés. C'est
une décision technique, et un motif deviné est une usine à faux positifs — c'est comme ça
qu'un rapport cesse d'être lu.

Alors il esquisse, et tu décides. Un bloc commenté par règle non couverte, tout rempli sauf le
motif :

```toml
# [[regles]]
# source   = "CLAUDE.md:23"   # la regle est ENONCEE la-bas, pas ici
# nom      = "Axios partage"
# racine   = "."
# suffixes = [".ts", ".tsx"]
# motif    = ''               # <- a toi de l'ecrire : a quoi ressemble une VIOLATION
# bloquant = false
```

`source` remplace la recopie de la phrase dans la config : la règle reste énoncée à un seul
endroit et ne peut pas dériver. Ce contrôle ne bloque jamais un push — documenter une
intention ne doit pas être puni.

## Les documents qui citent légitimement ce qui n'existe pas

Une roadmap, une note de conception ou un compte rendu cite des fichiers qui n'existent pas —
pas encore (un module à écrire), ou plus (un fichier supprimé, mentionné précisément pour ça).
Bloquer dessus te pousserait à écrire ces documents *hors* des dossiers scannés, ce qui
recrée l'angle mort que le contrôle existe pour supprimer.

Marque le document, n'importe où dedans :

```markdown
<!-- lintorn:prospectif -->
```

Ses chemins morts sont alors **listés, pas bloquants** — tu les vois toujours, ils cessent
juste d'arrêter ton push.

### Deux genres sont reconnus sans aucun marqueur

**Les tutoriels.** Un tutoriel apprend au lecteur à créer des fichiers *dans son propre
projet* : il cite donc légitimement des chemins qui n'existent pas ici. Le signal est net, et
il a été mesuré sur les 1693 documents de FastAPI : la distribution est bimodale — 146
documents n'ont **aucun** chemin manquant, 207 les ont **tous** manquants. D'où la règle, en
une phrase : *si la plupart de ce qu'un document cite n'existe pas ici, il ne décrit pas ce
projet*. Une citation isolée n'est jamais excusée — c'est exactement la forme d'une vraie
pourriture documentaire.

**Les journaux de version.** Un changelog cite ce qui existait *à l'époque*. Reconnu par son
nom :

```
CHANGELOG.md    release-notes.md    HISTORY.md    NEWS.md
```

Sur FastAPI, un seul de ces fichiers représentait 174 des 460 chemins bloquants.

Sans ça, FastAPI remontait **460 chemins bloquants au premier lancement** — un mur qui fait
fermer l'outil. Avec la seule échappatoire qui existait (`docs_exclus = ["docs/*"]`), 98 % de
la documentation cessait d'être lue, pour un feu vert sur 2 chemins : exactement le faux
« tout va bien » que cet outil existe pour empêcher. Les deux nombres apparaissent maintenant
dans la ligne de résumé, documents requalifiés compris — le silence n'est jamais une option.

## Ce à quoi ce contrôle ne sert *pas*

Le contrôle de documentation vise la documentation **descriptive** — « le module
*services/api.ts* fait ceci ». Deux familles en sortent par nature :

- les **tutoriels** : « crée un fichier *myapp.py* » cite un fichier que *le lecteur* créera ;
- les **changelogs** : ils citent les fichiers de toutes les versions passées, supprimés
  compris.

Pointé sur un gros projet de référence, Lintorn a signalé 460 chemins morts — tous issus de
ses tutoriels et de ses notes de version. À ce niveau de bruit, personne ne lit le contrôle,
donc il ne protège rien. Exclus-les :

```toml
docs_exclus = ["docs/*", "CHANGELOG.md"]
```

## Sans danger par défaut

Le premier lancement ne peut rien abîmer. Lintorn ne modifie pas tes fichiers, ne sort pas sur
le réseau, et n'exécute pas le code de ton projet sans que tu le demandes.

### L'accord avant de lancer

Lintorn **lit** sans rien demander : ta doc, ta mémoire IA, tes règles. Mais il ne **lance**
aucun programme dans ton projet (ruff, pytest, tsc, tes outils maison) sans ton accord. Au
premier lancement, il te montre ce qu'il veut lancer et te demande `[o/N]` : non par défaut.

Cet accord est noté **hors du projet**, dans ta configuration à toi (~/.config/lintorn/).
Un accord écrit dans le dépôt serait celui de son auteur : un dépôt piégé se l'accorderait
lui-même. Il ne se redemande pas, sauf si quelque chose change : une nouvelle commande, ou le
contenu d'un script de ton projet qu'un outil maison lance. Lintorn te dit alors quel fichier a
changé.

Sans terminal pour répondre (le hook lancé par VS Code, la CI), il ne lance rien et **le dit** :
le hook termine par « Push autorisé SANS vérification complète ». `lintorn confiance`, une fois
dans un terminal, donne l'accord. En CI, `LINTORN_CONFIANCE=oui` l'accorde d'office.

### Ce qui est opt-in

Ceux-là sont **opt-in** : `tests` (exécute ton code), `django_check` et `migrations`
(ils importent tes réglages et toutes tes apps, donc ton code), `failles`, `failles_npm` et
`failles_osv` (réseau), `donnees_metier` (ouvre ta base), `code_mort` et `deploy` (bruyants
pendant le développement). `lintorn outils` te les propose un par un.

Aucun ne s'éteint en silence : le contrôle `Configuration (Lintorn)` liste ceux qui
s'appliquent à ton projet et que tu n'as pas encore accordés. Un contrôle absent du rapport
sans explication laisserait croire qu'il a été fait.

Une clé mal tapée, ou activée sur un projet qui n'a rien à lui faire contrôler (`failles_npm`
sans package-lock.json), ne s'éteint plus en silence : le contrôle `Configuration (Lintorn)`
la signale. Même chose pour une valeur du mauvais type — seuls `true` et `false` valent
accord : `tests = "false"`, écrit entre guillemets, n'active rien.

Chaque audit écrit deux fois la même chose : `rapport.md`, la source, et `rapport.html`, la
même matière en page web — à ouvrir dans un navigateur, lisible sur un téléphone, sans
réseau ni feuille de style à télécharger. La page ne décide rien : elle rend le rapport.

Sans que tu le demandes, Lintorn n'écrit que dans le `.lintorn/` de ton projet — et jamais
à travers un lien symbolique, fichier **ou dossier** : un dépôt cloné ne peut pas lui faire
écraser autre chose. Les commandes qui écrivent ailleurs le disent et te le demandent :
`lintorn outils` (ta configuration, jusque dans `pyproject.toml` si elle y vit),
`lintorn pip-audit --appliquer` (`requirements.txt`) et `lintorn hook` (le `core.hooksPath`
de ce clone).
Il ne télécharge pas non plus `tsc` : il utilise celui de ton projet, installé par
`npm install`.

## Configuration

`lintorn init` écrit deux fichiers, parce qu'ils n'ont pas la même vie :

| Fichier | Ce qu'il contient | Comment il vit |
|---|---|---|
| `.lintorn/config.toml` | les réglages — quels contrôles tournent, quels fichiers sont des instructions IA | écrit une fois, peu touché |
| `.lintorn/regles.toml` | tes règles maison | grossit, s'édite souvent, se relit à plusieurs |

Les réglages peuvent aussi vivre sous `[tool.lintorn]` dans ton `pyproject.toml`. Le fichier
séparé compte pour les projets sans `pyproject.toml` à leur racine, c'est-à-dire la plupart
des projets non-Python. Les règles déclarées à l'un ou l'autre endroit fonctionnent toujours :
les deux sources sont fusionnées, donc rien ne casse pour les projets configurés avant que
`regles.toml` existe.

```toml
[controles]
tests = true

[[regles]]
nom      = "Couleurs en dur dans un CSS"
regle    = "uniquement des variables de theme — var(--bg)"
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
s'applique qu'aux fichiers qui le contiennent — c'est comme ça qu'on exprime *si X apparaît,
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

Une règle conditionnelle dont le `si` n'est jamais tombé n'a rien vérifié : elle n'est donc
pas comptée comme tenue, et le rapport dit combien sont restées inertes — avec un lien vers
leur ligne dans `regles.toml`.

### Quand aucun motif ne peut exprimer la règle

Certaines règles dépassent une expression régulière : comparer deux fichiers, vérifier une
propriété structurelle, ou distinguer un usage fautif d'un usage légitime identique. Écrire un
motif approximatif fabriquerait des faux positifs, et une règle qu'on apprend à ignorer ne
protège plus rien.

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

Ce n'est pas un bouton « silence », et trois choses l'en empêchent :

- **`source` est obligatoire** — sans lui la déclaration ne désigne aucune ligne de doc, donc
  ne couvre rien ;
- **si la raison cite un `test_...`, Lintorn vérifie qu'il existe.** Test renommé ou supprimé,
  la promesse est rompue : la règle redevient visible, et le rapport dit laquelle ;
- **le compte reste affiché à vie** — `7 enoncee(s), 2 controlee(s), 5 hors de portee`. Rien
  ne disparaît du rapport, et un ratio qui dérive se voit.

Les commandes personnalisées sont **exécutées** — le même contrat que les scripts npm, les
hooks git ou un Makefile. Ne lance pas Lintorn dans un dépôt en qui tu n'as pas confiance.

## Les autres langages

Lintorn est *écrit* en Python ; il n'exige pas que ton projet le soit. Les quatre contrôles
qui font sa particularité — doc vs code, mémoire IA, règles maison, intégrité du hook — sont
indépendants du langage et fonctionnent sur n'importe quel dépôt.

Les **failles connues** des dépendances sont couvertes pour presque tous les écosystèmes :

| Écosystème | Audit | Clé |
|---|---|---|
| Python | pip-audit | `failles` |
| JavaScript (npm) | `npm audit`, dès qu'il y a un package-lock.json | `failles_npm` |
| Rust, Go, PHP, Ruby, Java, .NET, Dart, Elixir, R, Swift… | [OSV-Scanner](https://google.github.io/osv-scanner/), qui lit leurs fichiers de verrou | `failles_osv` |

OSV-Scanner lit aussi les verrous npm et Python : une faille déjà signalée par npm audit ou
pip-audit peut réapparaître sur sa ligne. C'est voulu — un doublon plutôt qu'un oubli, car
pip-audit lit le venv et non les fichiers de dépendances, et un audit en panne ne couvre
rien. Il ne s'installe pas par pip : `brew install osv-scanner`, ou l'une des
[autres méthodes](https://google.github.io/osv-scanner/installation/). Lintorn coupe son
analyse d'appels, qui compilerait ton projet : l'accord donné porte sur le réseau, pas sur
l'exécution de ton code.

Un audit qui n'a pas pu répondre — réseau coupé, verrou illisible — s'affiche
`INDISPONIBLE`, jamais « 0 faille ». C'est le piège de ces outils : npm sort avec le même
code pour une faille trouvée et pour une panne, et OSV-Scanner rend une liste de failles
*vide* quand le réseau tombe.

Tout le reste se branche par `[[commandes]]` : phpstan, eslint, `go vet`, `cargo clippy`.

## Les outils externes

Lintorn lui-même a **zéro dépendance** — délibérément, pour pouvoir tourner dans un hook git
avec n'importe quel Python de la machine. Les outils qu'il appelle appartiennent au projet
audité, pour que ruff applique *tes* règles et que pytest voie *tes* dépendances.

```console
$ lintorn outils
```

Il regarde ce que contient ton projet et ne propose que ce qui s'y applique — pas de
pip-audit sans Python, pas de npm audit sans verrou npm. Deux gestes, deux accords :

- **installer** les outils Python qui manquent (ruff, pytest, vulture, pip-audit) dans le
  venv de ton projet — une seule question ;
- **activer** chaque contrôle opt-in, un par un, en disant ce qu'il implique — exécuter ton
  code, sortir sur le réseau. `--oui` ne répond qu'à la première question, jamais aux
  secondes.

Ce qu'il ne sait pas installer lui-même, il le dit, avec la commande : `npm install` pour
`tsc`, Node.js pour npm audit, Homebrew ou le site d'OSV-Scanner pour ce dernier.

### Quel Python les lance

Lintorn cherche le virtualenv de ton projet dans `venv/`, `.venv/` et `env/` — à la racine du
dépôt comme dans son dossier Python — et utilise l'interpréteur qu'il y trouve.

Quand il n'en trouve aucun, il se replie sur le sien et **le dit**, parce que ce repli n'est
pas anodin : `pip-audit` remonterait alors les failles de cet environnement-là plutôt que
celles de ton projet, et `requirements.txt` serait comparé aux mauvais site-packages. Les deux
répondent quand même — de façon plausible, sur le mauvais environnement. C'est la panne que
Lintorn existe pour supprimer, donc il l'annonce comme `Python du projet (venv)` au lieu de se
taire.

Si ton virtualenv vit hors du projet — poetry, pdm, conda, pipenv — aucune convention de nom ne peut
le trouver. Indique-le :

```toml
[tool.lintorn]
venv = "../.venvs/mon-projet"
```

Ça compte surtout quand Lintorn est installé sur la machine plutôt que par projet. `pip` ne
peut pas t'avertir à l'installation : un wheel est décompressé, jamais exécuté, donc il n'y a
pas de hook d'installation à lancer ni moyen de poser une question. Préfère
`pipx install lintorn`, et laisse le contrôle ci-dessus te dire quel interpréteur a réellement
fait l'audit.

## Sans dépôt git

Lintorn fonctionne sur un dossier non versionné. Trois contrôles n'ont alors pas d'objet — le
hook pre-push, la fraîcheur des mémoires, le périmètre `.gitignore` — et il **dit lequel**
plutôt que de rendre un verdict sur ce qu'il n'a pas pu regarder.

## Les commandes

```console
lintorn                      audit complet
lintorn rapide               saute les outils lents (ce que lance le hook pre-push)
lintorn doc                  le controle de documentation seul
lintorn init                 genere la config de ce projet
lintorn regles               esquisse un bloc [[regles]] par regle non couverte
lintorn hook                 installe le hook pre-push
lintorn confiance            autorise Lintorn a lancer ses outils dans ce projet
lintorn outils               installe et active ce qui s'applique a ce projet, en demandant
lintorn pip-audit            ce que propose pip-audit (a blanc)
lintorn guide                la notice en une page : a quoi il sert, comment lire un rapport
```

Une option mal tapée n'est jamais ignorée : Lintorn s'arrête, ne lance rien, et propose
l'option la plus proche.

Après chaque mise à jour de Lintorn, relance `lintorn hook` : le hook posé dans
ton projet est une copie, que `pipx upgrade lintorn` ne touche pas. Le contrôle
`Hook pre-push` te prévient quand elle est périmée.

Python 3.11+.

## Licence

[AGPL-3.0](LICENSE). Utilise-le, modifie-le et partage-le librement. Si tu le distribues — ou
si tu l'offres comme service en réseau — tu dois publier ta source sous la même licence.

C'est un choix délibéré : Lintorn est donné, et cette licence empêche que quelqu'un le
referme pour le revendre. Détenteur du copyright : **Olotorn**. Pour une licence commerciale
dispensant de l'obligation de publier la source, contacte-moi.

## Contribuer

Pas encore ouvert aux contributions de code extérieures — les rapports de bug et les idées,
eux, sont les bienvenus, et c'est ce qui aide le plus à ce stade. Quand ça ouvrira, les
contributions demanderont un CLA, pour que la double licence reste possible. Détails dans
`CONTRIBUTING.md`.
