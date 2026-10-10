# Lintorn
"""Ce que Lintorn lit pour juger la doc : les documents, les fichiers d'instructions IA, la mémoire de l'assistant."""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path

from .. import config

# Les dossiers de DONNÉES DE TEST, par convention d'outil et non de projet :
# pytest, Jest, Rails, Django (`fixtures`), Go (`testdata`), Jest encore
# (`__snapshots__`, `__mocks__`). Un `.md` rangé là est l'ENTRÉE d'un test,
# pas la doc du projet : ses chemins désignent des fichiers imaginaires.
DOSSIERS_FIXTURES = {"fixtures", "__fixtures__", "testdata", "test_data", "test-data",
                     "__snapshots__", "__mocks__"}


# Les formats de doc lus. `.mdx` : Markdown + JSX (Docusaurus, Starlight).
# `.rst` : reStructuredText, toute la doc Sphinx. Lire le seul `.md` laissait
# des centres d'aide entiers hors du contrôle, sans un mot.
FORMATS_DOC = ("*.md", "*.mdx", "*.rst")


def _documents_du_depot(ecartes: dict[str, list[str]] | None = None) -> list[Path]:
    """La doc à vérifier. `ecartes` reçoit, par raison, ce qui a été mis de côté.

    ⚠️ Un document du dépôt qu'on ne lit pas doit être COMPTÉ : une doc
    commitée sous `vendor/`, sautée sans un mot, passerait pour vérifiée.
    Ce qui vit sous un dossier de IGNORES sans être suivi (`node_modules`
    installé) n'appartient pas au dépôt : on ne le compte pas.
    """
    trouves = []
    mis_de_cote: dict[Path, str] = {}
    candidats = (fichier for motif in config.FORMATS_DOC for fichier in config.RACINE.rglob(motif))
    for fichier in candidats:
        relatif = fichier.relative_to(config.RACINE)
        if ".lintorn" in relatif.parts:
            continue
        dossiers_tiers = [partie for partie in relatif.parts[:-1] if partie in config.IGNORES]
        if dossiers_tiers:
            mis_de_cote[fichier] = f"sous {dossiers_tiers[0]}/"
            continue
        if any(partie.lower() in config.DOSSIERS_FIXTURES for partie in relatif.parts[:-1]):
            mis_de_cote[fichier] = "de fixtures de test"
            continue
        # ⚠️ `is_file()` = un fichier RÉGULIER. Un tube nommé (`mkfifo docs.md`)
        # se lit sans fin : sa lecture gelait Lintorn, et le `git push` avec.
        if not fichier.is_file():
            continue
        # fnmatch et non `Path.match` : ce dernier ne traite `**` comme un
        # glob récursif qu'à partir de Python 3.13, et Lintorn tourne dès 3.11
        # — les motifs étaient donc silencieusement ignorés. Avec fnmatch, `*`
        # traverse les dossiers : `docs/*` suffit à écarter tout `docs/`.
        chemin_posix = relatif.as_posix()
        if any(fnmatch(chemin_posix, motif) for motif in config.DOCS_EXCLUS):
            continue
        trouves.append(fichier)
    if ecartes is not None and mis_de_cote:
        for fichier in config.hors_gitignore(sorted(mis_de_cote)):
            if fichier.is_file():
                ecartes.setdefault(mis_de_cote[fichier], []).append(
                    fichier.relative_to(config.RACINE).as_posix())
    return sorted(config.hors_gitignore(trouves))


# Les fichiers d'INSTRUCTIONS pour un assistant IA — là où un projet ÉNONCE ses
# règles. À ne pas confondre avec DOCS_A_VERIFIER (toute la doc) : une note
# d'architecture *décrit* le système, un fichier d'instructions *prescrit*.
#
# ⚠️ Liste ouverte, et surchargeable : tout le monde n'utilise pas Claude.
# Un NOM se reconnaît partout ; un CHEMIN (il contient un `/`) se reconnaît
# depuis la racine ou depuis n'importe quel sous-projet, et accepte `*`.
#
#     [tool.lintorn]
#     fichiers_ia = ["CLAUDE.md", "AGENTS.md", "REGLES.md", "docs/ia/*.md"]
#
# ⚠️ PAS `SKILL.md` : un dépôt range dans ses skills des instructions
# VENDORISÉES, écrites pour d'autres dépôts. Leurs règles ne sont pas celles
# du projet, et les compter reviendrait à lui réclamer des contrôles pour des
# conventions qui ne sont pas les siennes.
_FICHIERS_IA_DEFAUT = [
    "CLAUDE.md",      # Claude Code
    "AGENTS.md",      # convention multi-outils
    "GEMINI.md",      # Gemini CLI
    "CONVENTIONS.md",  # Aider
    ".cursorrules",   # Cursor
    ".github/copilot-instructions.md",  # GitHub Copilot
    ".claude/rules/*.md",               # Claude Code, règles rangées par thème
]


# Les dossiers où un dépôt range des DONNÉES de test. Un `conventions.md` y est
# une entrée qu'un test lit, pas une consigne donnée à un assistant : compté
# comme fichier IA, chacune de ses lignes devenait une « règle énoncée ».
DOSSIERS_DE_FIXTURES = {"fixtures", "fixture", "__fixtures__", "testdata", "test_data",
                        "test-data", "mdtest", "snapshots", "__snapshots__"}


def _est_un_fichier_ia(relatif: str) -> bool:
    """`relatif` (depuis la racine, en `/`) est-il un fichier d'instructions IA ?"""
    parties = relatif.lower().split("/")
    if set(parties[:-1]) & config.DOSSIERS_DE_FIXTURES:
        return False
    if parties[-1] in config._NOMS_IA:
        return True
    chemin = "/".join(parties)
    return any(fnmatch(chemin, motif) or fnmatch(chemin, "*/" + motif)
               for motif in config._CHEMINS_IA)


def _instructions_ia() -> list[Path]:
    """Les fichiers d'instructions IA, où qu'ils soient dans le dépôt.

    On les cherche au lieu de les nommer : un monorepo en pose souvent un par
    sous-projet (`backend/CLAUDE.md`), et les nommer un par un condamnerait
    Lintorn à ne voir que celui de la racine.

    Dans la liste de git plutôt que sur le disque : elle écarte déjà ce que le
    `.gitignore` exclut, et ne descend ni dans node_modules ni dans un autre
    dépôt rangé à l'intérieur de celui-ci, dont les consignes ne sont pas les
    siennes.
    """
    trouves = []
    for fichier in config._FICHIERS:
        if config.sous_ignores(fichier) or not fichier.is_file():
            continue
        if config._est_un_fichier_ia(fichier.relative_to(config.RACINE).as_posix()):
            trouves.append(fichier)
    return sorted(trouves)


# Le début de l'origine d'une mémoire retenue sur la seule foi de son nom.
PAR_RESSEMBLANCE = "trouvee par RESSEMBLANCE de nom"


def _nom_lisible(dossier: Path) -> str:
    """Le nom d'un dossier de projet Claude, privé du chemin du dossier personnel.

    Claude le dérive du chemin ABSOLU : il commence par le nom d'utilisateur,
    qui n'a rien à faire dans un rapport qu'on partage.
    """
    maison = re.sub(r"[^a-zA-Z0-9]", "-", str(Path.home()))
    nom = dossier.name
    return "~" + nom[len(maison):] if nom.startswith(maison) else nom


def _dossier_memoire():
    """Retrouve le dossier mémoire de l'IA. Renvoie (chemin | None, origine).

    POURQUOI ON CHERCHE plutôt que d'écrire un chemin figé : le nom du dossier
    est dérivé du chemin absolu du projet, il contient donc le nom de session
    de l'utilisateur. L'écrire en dur reviendrait à (1) publier une information
    personnelle si l'outil est partagé, et (2) casser le contrôle sur toute
    autre machine.

    Trois pistes, dans l'ordre :
      1. `LINTORN_MEMOIRE` dans `.lintorn/.env` — la porte de sortie quand la
         découverte auto échoue (autre PC, dossier déplacé, chemin exotique).
         Le .env étant gitignoré, le chemin personnel ne part jamais au dépôt.
      2. `CLAUDE_CONFIG_DIR` — la variable par laquelle Claude Code lui-même
         déplace sa config ; sans elle, `~/.claude`.
      3. Le dossier du projet, cherché SANS TENIR COMPTE DE LA CASSE.
         ⚠️ Le glob est sensible à la casse sous Linux : un dossier dont le
         nom differe par une majuscule n'aurait jamais été trouvé, et le contrôle serait
         passé « INDISPONIBLE » en silence sur la machine Linux à venir.

    ⚠️ Le nom cherché est celui du DOSSIER RACINE du projet audité, et non
    plus un nom écrit en dur. Claude Code nomme ses dossiers d'après le
    chemin absolu du projet : le nom de la racine s'y retrouve donc toujours.

    Renvoie None si rien n'est trouvé → le contrôle est simplement ignoré.
    L'`origine` sert à dire à l'utilisateur QUELLE piste a servi (ou échoué),
    sans jamais afficher le chemin lui-même.
    """
    explicite = config.ENV.get("LINTORN_MEMOIRE", "").strip()
    if explicite:
        chemin = Path(explicite).expanduser()
        if chemin.is_dir():
            return chemin, "LINTORN_MEMOIRE (.env)"
        # Configuré MAIS faux : le pire cas silencieux. On le dit.
        return None, "LINTORN_MEMOIRE (.env) pointe sur un dossier inexistant"

    racine_claude = config.ENV.get("CLAUDE_CONFIG_DIR", "").strip()
    base = (Path(racine_claude).expanduser() if racine_claude
            else Path.home() / ".claude") / "projects"
    if not base.is_dir():
        return None, "aucun dossier Claude sur cette machine"

    # Claude nomme ses dossiers d'apres le CHEMIN ABSOLU du projet, chaque
    # caractere non alphanumerique devenant un tiret. On reconstruit ce nom.
    #
    # ⚠️ Retenir « le premier dossier dont le nom CONTIENT celui du projet »
    # auditait la memoire du voisin : `app` est contenu dans `app-legacy`, qui
    # se trie avant. Le rapport parlait alors d'un autre projet, et la vraie
    # memoire n'etait jamais lue — l'angle mort que ce controle existe pour
    # supprimer.
    exact = base / re.sub(r"[^a-zA-Z0-9]", "-", str(config.RACINE)) / "memory"
    if exact.is_dir():
        return exact, "decouverte auto"

    # Repli : le projet a bouge de place depuis. On n'accepte qu'une
    # correspondance SANS ambiguite, et on dit laquelle.
    #
    # ⚠️ CE N'EST QU'UNE RESSEMBLANCE, et elle se dit. Claude code `/`, `-`,
    # `_` et `.` par le même tiret : « finit par -ps2 » attrape aussi bien le
    # projet déplacé que `Bios-PS1-PS2`, qui n'a rien à voir. Prise en
    # silence, la mémoire d'un autre projet était auditée comme la sienne.
    nom_projet = "-" + re.sub(r"[^a-zA-Z0-9]", "-", config.RACINE.name).lower()
    candidats = [dossier / "memory" for dossier in sorted(base.iterdir())
                 if dossier.is_dir() and dossier.name.lower().endswith(nom_projet)
                 and (dossier / "memory").is_dir()]
    if len(candidats) == 1:
        return candidats[0], f"{config.PAR_RESSEMBLANCE} : {config._nom_lisible(candidats[0].parent)}"
    if candidats:
        noms = ", ".join(config._nom_lisible(candidat.parent) for candidat in candidats)
        return None, (f"{len(candidats)} dossiers memoire ressemblent a '{config.RACINE.name}' "
                      f"({noms}) - aucun n'est pris : precise LINTORN_MEMOIRE dans .lintorn/.env")

    return None, f"aucun dossier memoire trouve pour '{config.RACINE.name}'"


# L'INDEX de la mémoire : le nom que lui donne Claude Code, qui le relit à
# chaque session. Ce n'est pas une fiche : une ligne par fiche, sans en-tête.
INDEX_MEMOIRE = "MEMORY.md"


# Un nom cité SANS dossier n'est vérifié que s'il finit par l'une d'elles.
# Limitées à Python et au web, elles laissaient passer tout nom de source
# Ruby, PHP, Go, Rust, C#, Java, Elixir… : sur ces projets, un fichier
# renommé et cité par son seul nom ne pouvait jamais être signalé.
# ⚠️ Pas `.conf`, `.yml`, `.yaml`, `.txt` : cités SEULS, ces noms désignent
# le plus souvent un fichier de la machine du lecteur ou d'un autre outil
# (`nginx.conf`, `docker-compose.yml`, le `requirements.txt` du projet
# audité). Mesuré : que du bruit bloquant. Avec un dossier, ils restent
# vérifiés comme tout chemin.
EXTENSIONS = (".py", ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs",
              ".css", ".scss", ".sass", ".less", ".json", ".md", ".mdx", ".rst",
              ".toml", ".ini", ".cfg", ".xml", ".lock",
              ".html", ".vue", ".svelte", ".sql", ".sh",
              ".rb", ".rake", ".erb", ".php", ".java", ".kt", ".kts", ".gradle",
              ".go", ".tmpl", ".rs", ".cs", ".csproj", ".ex", ".exs", ".heex",
              ".dart", ".swift", ".c", ".h", ".cpp", ".hpp")
