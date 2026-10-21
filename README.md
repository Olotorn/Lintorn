# Lintorn

**Sommaire**

- [Guide Rapide](#guide-rapide)
- [C'est quoi ?](#cest-quoi-)
- [À quoi ça sert ?](#à-quoi-ça-sert-)
- [Pour quel projet ?](#pour-quel-projet-)
- [Comment l'installer ?](#comment-linstaller-)
- [Comment s'en servir ?](#comment-sen-servir-)
- [Conseils d'utilisation](#conseils-dutilisation)
- [Le hook, sans risque](#le-hook-sans-risque)
- [Les règles](#les-règles-le-cœur-de-lintorn)
- [Ajouter ses outils](#ajouter-ses-outils)
- [Les commandes](#les-commandes)

## C'est quoi ?
**ATTENTION : Lintorn n'est pas encore stable à 100 % : il est jeune et n'a pas pu être testé sur tous les projets.**

Lintorn n'est pas invasif : il ne lance rien dans ton projet sans **ton accord**.

La fonction première de Lintorn est d'aller vérifier la mémoire de ton LLM, je l'ai créé pour cette raison. D'après mon expérience, la mémoire des LLM est la cause n°1 des erreurs qui se répètent dans le code. Un LLM écrit sa mémoire sur ta machine et lui fait confiance à 100 %. Or cette mémoire a tendance à pourrir, et personne ne le voit, sauf Lintorn !
Je ne connais aucun outil similaire à Lintorn. Utilise-le, vérifie les mises à jour (`pipx upgrade lintorn` ou `pip install --upgrade lintorn`, puis `lintorn hook`), et dis-moi ce que tu en penses.
Pour être prévenu à chaque nouvelle version, abonne-toi au [flux RSS de PyPI](https://pypi.org/rss/project/lintorn/releases.xml).
Tes retours seront les bienvenus et ils me permettront d'avancer sur ce projet. Pour me les donner : un ticket (*issue*) sur [GitLab](https://gitlab.com/DamXs/lintorn/-/issues).
L'ère du vibe coding est bien là, cet outil sera, je l'espère, une source de tranquillité pour les nouveaux projets.

**Il est pensé pour travailler avec une IA (vibe coding) : c'est avec un LLM qu'il est le plus simple à utiliser.**

Lintorn n'est pas qu'un linter, il vérifie la mémoire de ton LLM. Avec ton accord, il installe aussi les outils d'audit utiles à ton projet (`lintorn outils`).

Il vérifie que la mémoire de ton agent IA dit encore la vérité sur ton code : les fichiers d'instructions à la racine du projet (CLAUDE.md, AGENTS.md, GEMINI.md, CONVENTIONS.md, .cursorrules… et tu peux en ajouter d'autres) et la mémoire que l'IA garde sur ta machine. Il les compare à la doc et au code du projet.

Un hook est à installer : il lance un scan rapide à chaque `git push`, et bloque le push si un contrôle **bloquant** est au rouge.

Il écrit son rapport en deux versions, `rapport.md` et `rapport.html` : le même contenu, mais le HTML est plus agréable à lire. Le push a le sien, `rapport-push.md` (et `rapport-push.html`) : une commande lancée juste après ne l'écrase pas, et tu peux toujours relire pourquoi ton push a été bloqué.


## À quoi ça sert ?
Il te fait gagner du temps sur un gros projet. Comment, tu vas me dire ?

Il vérifie que ton agent IA ne code pas à partir d'une mémoire obsolète. Ton agent voit tout de suite qu'il fait une erreur et peut rectifier le tir. Tu liras souvent de ton agent : « **Lintorn m'a rattrapé… donc je corrige…** »

Si tu ne bosses pas avec une IA, il t'évite de te perdre dans ton projet : tu peux tenir ta documentation à jour sans revérifier toutes tes notes à la main.

Le rapport de Lintorn te dit où regarder et te donne les liens. Au passage, il vérifie que ton code respecte ce que dit ta doc, pour éviter les contradictions : ton code reste cohérent partout.

Lintorn te sert de béquille et de garde-fou au moment des `git push`, c'est là que le danger est le plus grand. Mais rassure-toi, tu peux aussi lancer un scan complet quand tu veux avec `lintorn` (voir [Les commandes](#les-commandes)).

## Pour quel projet ?
Pour l'instant, Lintorn a été testé en conditions réelles sur un projet Python avec Django, et TypeScript avec React et Vite. Des tests ont été faits sur d'autres langages, mais pas en conditions réelles.

Langages testés en conditions réelles :
- Python / Django
- TypeScript / React / Vite

Langages testés hors conditions réelles :
- Rust
- Go
- Ruby
- Elixir
- Java
- JavaScript
- PHP
- C# / .NET

À vous de jouer ! Tous les retours sont bons à prendre.

## Comment l'installer ?
1) `pipx install lintorn` **(pipx est recommandé !)**

   **Pas encore pipx ?**
   - Windows : `py -m pip install --user pipx`
   - Linux Ubuntu : `sudo apt install pipx`
   - Avec Homebrew: `brew install pipx`
   - Fedora : `sudo dnf install pipx`
   - puis `pipx ensurepath`, puis ouvre un nouveau terminal.

Plus d'info sur l'installation : https://pipx.pypa.io/stable/installation/

**Et avec pip ?** `pip install lintorn` marche aussi, mais Lintorn n'existe alors que dans l'environnement où tu l'as installé (ton venv, par exemple). Un push lancé d'ailleurs (le bouton Git de VS Code, un terminal sans ce venv) ne le trouve pas, et part sans vérification. Lintorn te le signale, mais pipx évite le problème : il l'installe une seule fois pour tout ton compte, à l'écart des dépendances de tes projets.

2) `lintorn init`
▶ [Voir l'animation](#1-installer)

Lintorn scanne ton projet, détecte les langages utilisés et écrit sa configuration. `lintorn outils` installe ensuite les bons outils pour ces langages.
Et voilà : Lintorn est installé à la racine de ton projet, dans `.lintorn/`.
Maintenant, il faut l'activer ! [Comment s'en servir ?](#comment-sen-servir-)

## Comment s'en servir ?
`lintorn init` a créé un dossier `.lintorn/` (▶ [voir l'animation](#2-le-dossier-lintorn)).

1) `config.toml` : la configuration. Les contrôles qui lancent ton code, ouvrent ta base de données ou sortent sur internet sont sur `false` : à toi de les activer ou non (▶ [voir l'exemple](#3-activer-un-contrôle)).
2) Active les contrôles que tu veux en remplaçant `false` par **`true`**. Tu peux aussi ajouter tes propres outils (voir [Ajouter ses outils](#ajouter-ses-outils)).
3) `regles.toml` : c'est là que tu mets tes règles maison (aide-toi d'un LLM pour gagner du temps). C'est le cœur de Lintorn : c'est ce fichier qui t'empêche de reculer dans ton projet. Va voir [Les règles](#les-règles-le-cœur-de-lintorn) pour plus de détails.
4) Le hook : active-le avec `lintorn hook`. À chaque `git push`, il lancera `lintorn rapide`. Ton projet a déjà des hooks ? Lintorn ne les écrase pas, il te dit comment les faire cohabiter (voir [Le hook, sans risque](#le-hook-sans-risque)).
5) L'accord : lance `lintorn` une fois dans un terminal et réponds `o` à sa question (ou tape `lintorn confiance`). Sans cet accord, le hook ne lance aucun outil, et il te le dit : « Push autorisé SANS vérification complète ».

`lintorn rapide` : lance un scan sans les outils lents (vulture, pip-audit, npm audit, OSV-Scanner). C'est lui que le hook lance à chaque `git push`.

`lintorn` : lance tous les outils. Ça peut prendre un peu de temps, mais il est recommandé de le lancer de temps en temps. Le rapport de `lintorn rapide` t'indique depuis combien de temps le scan complet n'a pas été fait.

## Conseils d'utilisation
Les bons conseils que j'ai à te donner.

- Utilise une IA (vibe coding).
- Ton LLM va pouvoir mettre en place toutes les règles et améliorer ce que `lintorn regles` a préparé.
- `lintorn regles` prépare un brouillon de chaque règle déjà écrite dans les instructions de ton agent, mais cette commande est encore au stade expérimental et peut avoir des défauts. Je l'ai créée uniquement pour les nouveaux utilisateurs, pour te faciliter la tâche et donner des exemples.
Le LLM saura mieux faire toutes ces règles que nous et en trouvera sûrement plus.
- **Un LLM est inhumain**, alors on lui donne des tâches inhumaines.
- Chaque IA (ou presque) a un correcteur de mémoire, mais il n'est pas automatique et tu n'y penses pas forcément : Lintorn est là pour ça ! Il te dit à chaque push que ta mémoire vs code a bougé.


## Le hook, sans risque
Un hook git qui tourne à chaque `git push`, ça peut faire peur. Voilà ce qu'il fait, et ce qu'il ne fait jamais :

- **Il ne modifie jamais ton code.** Il lit, il lance tes contrôles, il te dit ce qu'il trouve.
- **Il ne bloque pas en douce.** Quand un contrôle bloquant est au rouge, il te demande d'abord : « Pousser quand même ? [o/N] ».
- **Tu peux toujours passer outre**, une fois : `git push --no-verify`.
- **Il respecte tes hooks existants** (pre-commit, husky…). S'il en trouve, `lintorn hook` ne les écrase pas : il te donne la ligne à ajouter à ton propre `pre-push`.
- **Tu peux le retirer à tout moment** : `git config --unset core.hooksPath`.

### **Pourquoi un contrôle au push et non au commit ?**
Le faire à chaque commit serait l'idéal, mais Lintorn peut être assez lourd. J'ai donc choisi le push : on le fait moins souvent, et c'est là que le risque est le plus grand. Pouvoir choisir entre les deux viendra peut-être dans une prochaine version.


## Les règles, le cœur de Lintorn
C'est ici que ça devient cool ! Tu y mets tes propres règles pour que Lintorn suive le bon chemin, car aucun outil n'est capable de deviner à ta place ce que tu veux. Je te recommande fortement l'aide d'une IA à ce moment-là : c'est assez long à écrire, et un LLM te le fera en quelques minutes. À toi de vérifier ensuite que ton LLM ne s'est pas trompé. Une fois tes règles en place, plus aucune erreur n'est muette : Lintorn te le dira au prochain `git push` ou au prochain `lintorn`.

Exemple de règle, dans `.lintorn/regles.toml` :
```toml
[[regles]]
nom = "Pas de print() oublie"
regle = "on n'imprime pas de debogage dans le code livre"
racine = "src"
suffixes = [".py"]
motif = '^\s*print\('
bloquant = true
```

## Ajouter ses outils
Dans `config.toml`, une section `[[commandes]]` te permet d'ajouter tes propres outils : un outil que ton projet utilise déjà (mypy, eslint…) ou un petit script à toi. Tu y écris la commande, le dossier d'où la lancer, et si le contrôle est bloquant ou non (▶ [voir l'animation](#5-ajouter-ton-outil-optionnel)). Tu enregistres, et au prochain `lintorn`, ton outil tourne avec les autres et affiche sa ligne dans le rapport.

La première fois, Lintorn te demande ton accord avant de le lancer. Et si le script de ton outil change ensuite, il te le redemande, en te disant quel fichier a été modifié.

Exemple dans `.lintorn/config.toml` :
```toml
[[commandes]]
cle      = "mypy"
titre    = "Types (mypy)"
cmd      = ["{python}", "-m", "mypy", "."]
cwd      = "."
bloquant = false
```

`{python}` désigne le Python de ton projet (son venv). Écris-le plutôt que `python` tout court : sinon, quand le hook est lancé depuis VS Code sans ton venv activé, l'outil serait introuvable. Et l'outil (ici mypy) doit être installé dans ce venv.

---

**Pour l'anecdote : le projet Lintorn est surveillé par Lintorn lui-même.**

---

## Les commandes

```
USAGE
    lintorn                      audit complet
    lintorn rapide               sans les outils lents (ce que lance le hook)
    lintorn doc                  uniquement : la documentation ment-elle ?
    lintorn --fichiers a.py b.ts + un focus sur ces fichiers

MISE EN PLACE
    lintorn init                 génère .lintorn/config.toml pour ce projet
    lintorn regles               prépare un [[regles]] par règle de ta doc
                                 qui n'a pas encore de contrôle
    lintorn hook                 installe le hook pre-push
    lintorn confiance            autorise Lintorn à lancer ses outils dans ce
                                 projet (il le demande de lui-même, une fois)
    lintorn outils               regarde ce que contient le projet, installe
                                 les outils qui s'y appliquent et propose
                                 d'activer ses audits, un par un

SÉCURITÉ
    lintorn pip-audit               ce que pip-audit propose (simulation)
    lintorn pip-audit --appliquer   installe et repingle vraiment

DIVERS
    lintorn guide                la notice : à quoi ça sert, comment lire
                                 un rapport, quels fichiers
    lintorn version              la version installée
    lintorn help                 cette aide, dans le terminal
```

## Guide Rapide
Chaque étape en animation. Clique sur celle qui t'intéresse dans le texte, ou regarde-les dans l'ordre.

### 0. Lintorn avant `lintorn init`
Tape `lintorn` : il lance son audit même sans configuration, et te propose de lancer `lintorn init`.

![lintorn sans configuration : il audite quand même et propose lintorn init](https://gitlab.com/DamXs/lintorn/-/raw/main/docs/gifs/lintorn-sans-init.gif)

### 1. Installer
`lintorn init` crée le dossier `.lintorn/`.

![lintorn init crée le dossier .lintorn/](https://gitlab.com/DamXs/lintorn/-/raw/main/docs/gifs/installer.gif)

### 2. Le dossier .lintorn/
Ce que `lintorn init` a créé, dans VS Code.

![Ce que lintorn init a créé, dans VS Code](https://gitlab.com/DamXs/lintorn/-/raw/main/docs/png/dossier-lintorn.png)

### 3. Activer un contrôle
Passer un contrôle de `false` à `true` dans `config.toml`, puis relancer.

![Exemple de contrôles à activer](https://gitlab.com/DamXs/lintorn/-/raw/main/docs/png/controles-lintorn.png)

### 4. Installer les outils selon le langage
`lintorn outils` scanne ton projet et installe les bons outils d'audit selon ses langages.

![lintorn outils : l'accord, les outils manquants, l'installation](https://gitlab.com/DamXs/lintorn/-/raw/main/docs/gifs/installer-outils.gif)

### 5. Ajouter ton outil (optionnel)
Un bloc `[[commandes]]`, et ton outil apparaît dans le rapport.

![Ton outil maison](https://gitlab.com/DamXs/lintorn/-/raw/main/docs/png/outils-maison.png)

### 6. Écrire une règle (le cœur)
Une règle dans `regles.toml`, et Lintorn trouve ce qui l'enfreint. L'IA est parfaite pour écrire les règles.

![Exemple d'une règle à écrire](https://gitlab.com/DamXs/lintorn/-/raw/main/docs/png/regle-exemple.png)

### 7. Un git push vérifié
Un push propre passe, un push qui enfreint une règle est arrêté.

#### 7.1 Un git push validé
![Un git push validé sans accroc](https://gitlab.com/DamXs/lintorn/-/raw/main/docs/gifs/git-push-ok.gif)

#### 7.2 Un git push bloqué
![Un git push bloqué, qu'on peut forcer en confirmant](https://gitlab.com/DamXs/lintorn/-/raw/main/docs/gifs/git-push-refuse.gif)

### 8. Premier lancement
Tape `lintorn` pour la première fois : il te demande ton accord avant de lancer ses outils.

![lintorn, premier lancement : la question d'accord](https://gitlab.com/DamXs/lintorn/-/raw/main/docs/gifs/premier-lancement.gif)

### 9. Les rapports (.md et .html)

#### 9.1 `.lintorn/rapport.md` : le rapport en Markdown, identique au HTML
![rapport.md](https://gitlab.com/DamXs/lintorn/-/raw/main/docs/png/rapport-md-preview.png)

#### 9.2 `.lintorn/rapport.html` : à ouvrir dans le navigateur, plus agréable à lire
![rapport.html](https://gitlab.com/DamXs/lintorn/-/raw/main/docs/png/rapport-html.png)

#### 9.3 `.lintorn/rapport-push.md` et `.lintorn/rapport-push.html` : ton dernier push
Les mêmes rapports, écrits seulement par le hook. Ils restent là jusqu'au push suivant, quoi que tu lances entre-temps. La première ligne de chaque rapport dit d'où il vient : « pendant un push » ou « hors push ».

---

## C'est la fin !
J'espère que ce guide est assez clair.

Une question, un bug ? Ouvre un ticket (*issue*) sur [GitLab](https://gitlab.com/DamXs/lintorn/-/issues).

**Tu ne seras plus jamais pris de court sur ton projet. Lintorn est une aide précieuse, mais attention : il peut avoir des bugs ! Sois attentif.**

**Je suis seul sur ce projet. Sois indulgent.**
