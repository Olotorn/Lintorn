# Lintorn

[![Soutenir sur Liberapay](https://img.shields.io/badge/Liberapay-Soutenir-F6C915?logo=liberapay&logoColor=black)](https://liberapay.com/Olotorn/donate)
[![Faire un don avec PayPal](https://img.shields.io/badge/PayPal-Faire%20un%20don-00457C?logo=paypal&logoColor=white)](https://www.paypal.com/donate/?hosted_button_id=XTWSHH5DD3A2C)

Ton LLM te génère du code foireux ?  
Normal, sa mémoire pourrit avec le temps !  
**Lintorn le remet sur le droit chemin.**

## En 10 secondes

Lintorn vérifie que la **mémoire de ton agent IA** et tes fichiers de règles  
(CLAUDE.md, AGENTS.md, GEMINI.md, CONVENTIONS.md, .cursorrules…)  
disent encore la vérité sur ton code et ta documentation.

Il te le signale clairement, génère un rapport, et peut bloquer un `git push`  
si un contrôle bloquant est au rouge.

Il n'est pas invasif : il ne lance rien sans ton accord.

![Un git push bloqué, qu'on peut forcer en confirmant](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/gifs/git-push-refuse.gif)

### À quoi ressemble un rapport

```text
=== Lintorn 0.7.0 - RAPPORT AUDIT ===
[ OK ] Ruff (lint Python)                 rien a signaler
[ OK ] Tests (pytest)                     643 test(s) passe(s), 2 ignore(s)
[ -- ] Code mort (vulture, consultatif)   NON EXECUTE (mode --rapide) - relancer sans --rapide
[ -- ] Failles connues (pip-audit)        NON EXECUTE (mode --rapide) - relancer sans --rapide
[ OK ] Configuration (Lintorn)            config.toml + regles.toml lu(s), 4 regle(s) maison chargee(s)
[ OK ] Doc vs code                        35 chemin(s) cite(s), 4 fonction(s) citee(s), 0 introuvable(s)
[ OK ] Memoire IA vs code                 55 chemin(s) cite(s), 23 fonction(s) citee(s), 0 introuvable(s)
[ OK ] Fraicheur memoire (git)            8 fraiche(s), 0 suspecte(s), 12 sans code cite, index epargne (ses fiches sont datees)
[ OK ] Regles maison                      4 regle(s) tenue(s) sur 64 fichier(s) lu(s)
[ OK ] Regles enoncees vs controlees      16 enoncee(s), 3 controlee(s), 13 hors de portee - aucune sans reponse
[ OK ] Hook pre-push (Lintorn)            branche et executable - Lintorn tournera avant chaque push
[ OK ] Python du projet (venv)            venv du projet : .venv
[ OK ] Audit complet (outils lents)       lance il y a 3 jour(s)
[ OK ] Defauts dans les fichiers pousses  2 fichier(s) pousse(s), aucun defaut connu dedans
```

### **Pour l'anecdote : le projet Lintorn est surveillé par Lintorn lui-même.**

---

**Sommaire**

- [Démarrage rapide](#démarrage-rapide)
- [Guide Rapide](#guide-rapide)
- [C'est quoi ?](#cest-quoi-)
- [À quoi ça sert ?](#à-quoi-ça-sert-)
- [Pour quel projet ?](#pour-quel-projet-)
- [Conseils d'utilisation](#conseils-dutilisation)
- [Comment l'installer ?](#comment-linstaller-)
- [Comment s'en servir ?](#comment-sen-servir-)
- [Le hook, sans risque](#le-hook-sans-risque)
- [Les règles](#les-règles-le-cœur-de-lintorn)
- [Ajouter ses outils](#ajouter-ses-outils)
- [Les commandes](#les-commandes)
- [Soutenir](#soutenir-lintorn)

---

## Démarrage rapide

```bash
pipx install lintorn          # recommandé
cd ton-projet
lintorn init
lintorn                       # premier scan
lintorn hook                  # active le contrôle au push
lintorn status                # où en est Lintorn dans ton projet
```

Sans configuration, `lintorn` fonctionne déjà et te propose de faire `init`.

> **pipx est recommandé.**  
> Avec un simple `pip install`, Lintorn n'existe que dans l'environnement où tu l'as installé.  
> Un push lancé depuis VS Code ou un autre terminal peut alors partir sans vérification.  
> Pas encore pipx ? Voir [Comment l'installer ?](#comment-linstaller-)

Lis ce README (ou demande à ton LLM de te l’expliquer pour ton projet).

Les retours seront les bienvenus et ils me permettront d'avancer sur ce projet.
Pour me les donner :
- un ticket (*issue*) sur [GitLab](https://gitlab.com/olotorn/lintorn/-/issues).


## C'est quoi ?
Lintorn n'est pas qu'un linter, il est bien plus que ça : il **surveille la mémoire de ton agent IA**.

Les LLM écrivent leur mémoire sur ta machine et lui font confiance à 100 %.

Le problème : cette mémoire pourrit avec le temps, et personne ne le voit… sauf Lintorn.

Il compare :
- les fichiers d’instructions de ton agent (CLAUDE.md, AGENTS.md, GEMINI.md, etc.)
- la mémoire que l’IA garde localement

avec le code et la documentation réels de ton projet.

Résultat : ton agent se fait rattraper, souvent avant de répéter les mêmes erreurs.

Chaque IA (ou presque) a un correcteur de mémoire, mais il n'est pas automatique  
et tu n'y penses pas forcément : Lintorn est là pour ça.

Utilise-le, vérifie les mises à jour (`pipx upgrade lintorn` ou `pip install --upgrade lintorn`, puis `lintorn hook`), et dis-moi ce que tu en penses.

Avec ton accord, il installe aussi les outils d'audit utiles à ton projet (`lintorn outils`).

`lintorn hook` est un hook à installer : il lance un scan rapide à chaque `git push`, et bloque le push si un contrôle **bloquant** est au rouge.

Il écrit deux rapports, chacun en Markdown et en HTML (le même contenu, mais le HTML est plus agréable à lire) :
- `rapport.md` et `rapport.html` : ceux de tes commandes (`lintorn`, `lintorn rapide`...).
- `rapport-push.md` et `rapport-push.html` : ceux du hook, écrits à chaque `git push`. Une commande lancée juste après ne les écrase pas, et tu peux toujours relire pourquoi ton push a été bloqué.

```bash
lintorn rapport          # Ouvre le rapport directement dans ton navigateur
lintorn rapport-push     # Ouvre celui de ton dernier push
```
Je ne connais aucun outil similaire à Lintorn. Je l'ai créé pour mes besoins dans un premier temps, maintenant je le partage pour que tout le monde puisse vibe coder sans accroc.

L'ère du vibe coding est bien là, cet outil sera, je l'espère, une source de tranquillité pour les nouveaux projets.

**Il est pensé pour travailler avec une IA : c'est avec un LLM que Lintorn est le plus simple à utiliser.**

>**ATTENTION : Lintorn n'est pas encore stable à 100 % : il est jeune et n'a pas pu être testé sur tous les projets.**
>
>Un **bug** trouvé ? Signale-le-moi sur [GitLab](https://gitlab.com/olotorn/lintorn/-/issues).

## À quoi ça sert ?
Sur un gros projet, Lintorn te fait gagner du temps de deux façons :
- **Avec IA** : ton agent voit tout de suite qu’il part d’une mémoire obsolète et corrige. 
  Tu liras souvent : **« Lintorn m’a rattrapé… donc je corrige… »**
- **Sans IA** : tu gardes ta documentation cohérente avec le code, sans tout revérifier à la main.
  Le rapport te dit précisément où regarder (avec les liens).

**Le vrai danger**, c’est le `git push` : c’est là que Lintorn sert de garde-fou.

## Pour quel projet ?

Lintorn a été testé en conditions réelles sur :

- **Python / Django**
- **TypeScript / React / Vite**

Des tests ont été faits sur d'autres langages, mais pas en conditions réelles :

- Rust, Go, Ruby, Elixir, Java, JavaScript, PHP, C# / .NET

À toi de jouer ! Tous les retours sont bons à prendre, sur [GitLab](https://gitlab.com/olotorn/lintorn/-/issues).

## Conseils d'utilisation
Les bons conseils que j'ai à te donner.

- **Utilise une IA** (vibe coding). C'est avec un LLM que Lintorn révèle tout son potentiel :
  il saura mettre en place toutes les règles et améliorer ce que `lintorn regles` a préparé.
- `lintorn regles` prépare un brouillon de chaque règle déjà écrite dans les instructions de ton agent, mais cette commande est encore au stade expérimental et peut avoir des défauts. Je l'ai créée uniquement pour les nouveaux utilisateurs, pour te faciliter la tâche et donner des exemples.
Le LLM saura mieux faire toutes ces règles que nous et en trouvera sûrement plus.
- **Un LLM est une machine**, alors on lui donne des tâches inhumaines.
  Écrire les règles à la main est long. Un LLM te le fera en quelques minutes.

## Comment l'installer ?
1) `pipx install lintorn` **(pipx est recommandé !)**

   **Pas encore pipx ?**
   - Windows : `py -m pip install --user pipx`
   - Linux Ubuntu : `sudo apt install pipx`
   - Avec Homebrew : `brew install pipx`
   - Fedora : `sudo dnf install pipx`
   - puis `pipx ensurepath`, puis ouvre un nouveau terminal.

Plus d'info sur l'installation : https://pipx.pypa.io/stable/how-to/install-pipx.html

**Et avec pip ?** `pip install lintorn` marche aussi, mais Lintorn n'existe alors que dans l'environnement où tu l'as installé (ton venv, par exemple). Un push lancé d'ailleurs (le bouton Git de VS Code, un terminal sans ce venv) ne le trouve pas, et part sans vérification.

Lintorn te le signale, mais pipx évite le problème : il l'installe une seule fois pour tout ton profil utilisateur, à l'écart des dépendances de tes projets.

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

`lintorn rapide` : lance un scan sans les outils lents (vulture, pip-audit, npm audit, OSV-Scanner), mais lance pytest s'il est activé, qui peut être lent suivant le nombre de tests. C'est lui que le hook lance à chaque `git push`.

`lintorn` : lance tous les outils. Ça peut prendre un peu de temps, mais il est recommandé de le lancer de temps en temps. Le rapport de `lintorn rapide` t'indique depuis combien de temps le scan complet n'a pas été fait.

`lintorn status` : te dit en un écran où tu en es (le hook, l'accord, la config, ce qui est contrôlé, tes derniers rapports), sans rien lancer. Chaque ligne qui n'est pas au vert te donne la commande qui la règle.

## Le hook, sans risque
Un hook git qui tourne à chaque `git push`, ça peut faire peur. Voilà ce qu'il fait, et ce qu'il ne fait jamais :

- **Il ne modifie jamais ton code.** Il lit, il lance tes contrôles, il te dit ce qu'il trouve.
- **Il ne bloque pas en douce.** Quand un contrôle bloquant est au rouge, il te demande 
  d'abord : « Pousser quand même ? [o/N] ».
- **Tu peux toujours passer outre**, une fois : `git push --no-verify`.
- **Il respecte tes hooks existants** (pre-commit, husky…). S'il en trouve, `lintorn hook` ne les écrase pas : il te donne la ligne à ajouter à ton propre `pre-push`.
- **Tu peux le retirer à tout moment** : `lintorn hook --rm`. Si `lintorn hook --force` avait remplacé tes anciens hooks, il les remet.
- **Pour vérifier qu'il tourne**, sans rien toucher : `lintorn hook --status`.

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
exemple = 'print("debug")'
bloquant = true
```

`exemple` est un texte **fautif** que ta règle doit attraper. Il paraît inutile, mais c'est lui qui te protège : une règle dont le motif est mal écrit ne trouve jamais rien, et elle ressemble alors à une règle respectée. Avec un exemple, Lintorn le voit à chaque lancement et te le dit.

- `lintorn regles --test` essaie chaque règle, une par une : ce qu'elle lit, ce qu'elle trouve, et si elle attrape son exemple.
- `lintorn corrige` répare les fautes de frappe de `regles.toml` et `config.toml` (`[[regle]]` au lieu de `[[regles]]`, `bloquan` au lieu de `bloquant`...). Il te montre chaque correction et ne touche à rien sans ton accord « o ».

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


## Les commandes

```
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
    lintorn help                 toutes les commandes
```

## Guide Rapide
Chaque étape en animation. Clique sur celle qui t'intéresse dans le texte, ou regarde-les dans l'ordre.

### 0. Lintorn avant `lintorn init`
Tape `lintorn` : il lance son audit même sans configuration, et te propose de lancer `lintorn init`.

![lintorn sans configuration : il audite quand même et propose lintorn init](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/gifs/lintorn-sans-init.gif)

### 1. Installer
`lintorn init` crée le dossier `.lintorn/`.

![lintorn init crée le dossier .lintorn/](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/gifs/installer.gif)

### 2. Le dossier .lintorn/
Ce que `lintorn init` a créé, dans VS Code.

![Ce que lintorn init a créé, dans VS Code](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/png/dossier-lintorn.png)

### 3. Activer un contrôle
Passer un contrôle de `false` à `true` dans `config.toml`, puis relancer.

![Exemple de contrôles à activer](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/png/controles-lintorn.png)

### 4. Installer les outils selon le langage
`lintorn outils` scanne ton projet et installe les bons outils d'audit selon ses langages.

![lintorn outils : l'accord, les outils manquants, l'installation](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/gifs/installer-outils.gif)

### 5. Ajouter ton outil (optionnel)
Un bloc `[[commandes]]`, et ton outil apparaît dans le rapport.

![Ton outil maison](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/png/outils-maison.png)

### 6. Écrire une règle (le cœur)
Une règle dans `regles.toml`, et Lintorn trouve ce qui l'enfreint. L'IA est parfaite pour écrire les règles.

![Exemple d'une règle à écrire](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/png/regles-nouvelle.png)

### 7. Un git push vérifié
Un push propre passe, un push qui enfreint une règle est arrêté.

#### 7.1 Un git push validé
![Un git push validé sans accroc](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/gifs/git-push-ok.gif)

#### 7.2 Un git push bloqué
![Un git push bloqué, qu'on peut forcer en confirmant](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/gifs/git-push-refuse.gif)

### 8. Premier lancement
Tape `lintorn` pour la première fois : il te demande ton accord avant de lancer ses outils.

![lintorn, premier lancement : la question d'accord](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/gifs/premier-lancement.gif)

### 9. Les rapports (.md et .html)

#### 9.1 `.lintorn/rapport.md` : le rapport en Markdown, identique au HTML
![rapport.md](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/png/rapport-md-preview.png)

#### 9.2 `.lintorn/rapport.html` : à ouvrir dans le navigateur, plus agréable à lire
![rapport.html](https://gitlab.com/olotorn/lintorn/-/raw/main/docs/png/rapport-html.png)

#### 9.3 `.lintorn/rapport-push.md` et `.lintorn/rapport-push.html` : ton dernier push
Les mêmes rapports, écrits seulement par le hook. Ils restent là jusqu'au push suivant, quoi que tu lances entre-temps. L'en-tête de chaque rapport dit d'où il vient : « pendant un push » ou « hors push ».

---

## C'est la fin !
J'espère que ce guide est assez clair, si tu veux plus de détails [GUIDE.md](https://gitlab.com/olotorn/lintorn/-/blob/main/GUIDE.md)

Une question, un bug ? Ouvre un ticket (*issue*) sur [GitLab](https://gitlab.com/olotorn/lintorn/-/issues).

- Pour être prévenu à chaque nouvelle version, abonne-toi au [flux RSS de PyPI](https://pypi.org/rss/project/lintorn/releases.xml).
- Ce qui change à chaque version est expliqué dans les [notes de version](https://gitlab.com/olotorn/lintorn/-/releases).


**Tu ne seras plus jamais pris de court sur ton projet. Lintorn est une aide précieuse, mais attention : il peut avoir des bugs ! Sois attentif.**

**Je suis seul sur ce projet. Sois indulgent.**

---

## Soutenir Lintorn

Ton don m'aide à continuer à améliorer le projet et à le maintenir.

Pas envie de donner, ça me va !

Installe Lintorn et utilise-le, c'est aussi fort qu'un don.

[![Soutenir sur Liberapay](https://img.shields.io/badge/Liberapay-Soutenir-F6C915?logo=liberapay&logoColor=black)](https://liberapay.com/Olotorn/donate)
[![Faire un don avec PayPal](https://img.shields.io/badge/PayPal-Faire%20un%20don-00457C?logo=paypal&logoColor=white)](https://www.paypal.com/donate/?hosted_button_id=XTWSHH5DD3A2C)

---

- Auteur : Olotorn
- Licence : AGPL-3.0-or-later
- Prérequis : Python ≥ 3.11
- PyPI : [lintorn](https://pypi.org/project/lintorn/)
- GitLab : [olotorn/lintorn](https://gitlab.com/olotorn/lintorn)
- Merci aux outils que Lintorn fait tourner : [ruff](https://github.com/astral-sh/ruff), [pytest](https://pytest.org), [vulture](https://github.com/jendrikseipp/vulture), [pip-audit](https://github.com/pypa/pip-audit), [OSV-Scanner](https://google.github.io/osv-scanner/) et npm audit.

