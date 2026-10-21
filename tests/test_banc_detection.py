# Lintorn
#
# La détection, éprouvée sur les cas que le banc d'essai a trouvés sur de vrais
# dépôts : chaque test rejoue la forme d'un projet réel en miniature.
#
# `config` calcule tout à l'IMPORT. Un défaut de détection ne se voit donc
# qu'en l'important pour de bon, dans un processus neuf pointé sur le faux
# projet — monkeypatcher un résultat déjà calculé ne prouverait rien.

import importlib.metadata
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import lintorn
import lintorn.commandes
from lintorn import config, dependances, noyau
from lintorn.outils import requirements

# Un faux outil est un script sh : sous Windows, il ne se lance pas.
_SANS_SH = pytest.mark.skipif(os.name == "nt", reason="le faux outil est un script sh")

# ⚠️ Le `src` de CE dépôt, en chemin ABSOLU. Hérité tel quel, un
# `PYTHONPATH=src` relatif ne désigne plus rien une fois le processus lancé
# dans le faux projet : Python retombe alors sur le Lintorn installé, et le
# test juge un autre code que celui qu'il croit juger.
_SRC = str(Path(lintorn.__file__).resolve().parents[1])

_LECTURE = """
import json
from lintorn import config

def rel(chemin):
    if chemin is None:
        return None
    try:
        return chemin.relative_to(config.RACINE).as_posix() or "."
    except ValueError:
        return str(chemin)

print(json.dumps({
    "cles": [c["cle"] for c in config.COMMANDES],
    "commandes": [{**{k: v for k, v in c.items() if k not in ("cmd", "cwd")},
                   "cmd": [str(m) for m in c["cmd"]], "cwd": rel(c["cwd"])}
                  for c in config.COMMANDES],
    "disponibles": [cle for cle, _ in config.CONTROLES_DISPONIBLES],
    "soucis": config.SOUCIS_CONFIG,
    "py_racine": rel(config.PY_RACINE),
    "py_sans_temoin": config.PY_SANS_TEMOIN,
    "frontend": rel(config.FRONTEND),
    "ecosystemes": sorted(config.ECOSYSTEMES_OSV),
    "docs_ia": [rel(chemin) for chemin in config.DOCS_IA],
    "prefixes": config.PREFIXES_PROJET,
}, default=str))
"""


def _ecrire(racine: Path, fichiers: dict) -> None:
    for chemin, contenu in fichiers.items():
        cible = racine / chemin
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(contenu, encoding="utf-8")


def _environnement(racine: Path) -> dict:
    environnement = {**os.environ, "LINTORN_RACINE": str(racine), "PYTHONPATH": _SRC,
                     # Jamais la vraie mémoire de la machine qui lance les tests.
                     "CLAUDE_CONFIG_DIR": str(racine / ".claude-absent")}
    environnement.pop("LINTORN_MEMOIRE", None)
    environnement.pop("VIRTUAL_ENV", None)
    return environnement


def _detecte(racine: Path, fichiers: dict) -> dict:
    """Ce que `config` déduit de ce faux projet, lu dans un processus neuf."""
    _ecrire(racine, fichiers)
    sortie = subprocess.run([sys.executable, "-c", _LECTURE], cwd=racine,
                            env=_environnement(racine), capture_output=True, text=True,
                            timeout=60, check=False)
    assert sortie.returncode == 0, f"la detection a fait tomber Lintorn :\n{sortie.stderr}"
    return json.loads(sortie.stdout)


def test_le_processus_neuf_juge_le_meme_code_que_ce_test(tmp_path):
    """Le garde-fou des garde-fous : sans lui, tous les tests ci-dessous
    pourraient juger le Lintorn installé plutôt que celui-ci."""
    sortie = subprocess.run([sys.executable, "-c", "import lintorn; print(lintorn.__file__)"],
                            cwd=tmp_path, env=_environnement(tmp_path), capture_output=True,
                            text=True, timeout=60, check=True)

    assert Path(sortie.stdout.strip()).resolve() == Path(lintorn.__file__).resolve()


# ─────────────────────────────────────────────────────────────────────────────
# B1 — un témoin Python sans code Python n'est pas un projet Python
# ─────────────────────────────────────────────────────────────────────────────
def test_un_pyproject_d_outillage_ne_fait_pas_un_projet_python(tmp_path):
    """Un dépôt Go/TS dont le pyproject.toml n'installe que des linters de
    templates recevait ruff, vulture et pip-audit — et ruff bloquait le push
    sur la fixture `.ipynb` d'un test Go."""
    lu = _detecte(tmp_path, {
        "pyproject.toml": '[project]\nname = "x"\n[dependency-groups]\ndev = ["djlint"]\n',
        "go.mod": "module x\n",
        "main.go": "package main\n",
        "modules/jupyter/fixture.ipynb": "{}",
    })

    assert lu["py_racine"] is None
    assert lu["py_sans_temoin"] is False
    assert "ruff" not in lu["cles"]
    assert not {"code_mort", "failles", "tests"} & set(lu["disponibles"])


def test_un_temoin_avec_du_code_reste_un_projet_python(tmp_path):
    lu = _detecte(tmp_path, {"pyproject.toml": '[project]\nname = "x"\n',
                             "src/paquet/__init__.py": ""})

    assert lu["py_racine"] == "."
    assert "ruff" in lu["cles"]


def test_un_temoin_vide_ne_masque_pas_le_vrai_projet_python(tmp_path):
    """Le premier `pyproject.toml` trouvé n'a pas de code : il faut regarder
    les suivants, pas conclure « aucun Python »."""
    # `docs-outils` se trie AVANT `ml` : c'est lui que l'ancienne recherche retenait.
    lu = _detecte(tmp_path, {
        "docs-outils/pyproject.toml": '[project]\nname = "outils"\n',
        "docs-outils/README.md": "rien de Python ici\n",
        "ml/pyproject.toml": '[project]\nname = "ml"\n',
        "ml/modele.py": "",
    })

    assert lu["py_racine"] == "ml"
    ruff = next(c for c in lu["commandes"] if c["cle"] == "ruff")
    assert ruff["cwd"] == "ml"


def _init(racine: Path) -> tuple[str, str]:
    """(ce que `--init` affiche, le config.toml qu'il écrit)."""
    sortie = subprocess.run([sys.executable, "-m", "lintorn", "--init"], cwd=racine,
                            env=_environnement(racine), capture_output=True, text=True,
                            timeout=60, check=True)
    return sortie.stdout, (racine / ".lintorn" / "config.toml").read_text(encoding="utf-8")


def _executer(racine: Path, fichiers: dict, chemin_extra: Path | None = None,
              claude: Path | None = None) -> dict:
    """{titre: (statut, resume, detail)} — le circuit COMPLET, `noyau.executer`."""
    _ecrire(racine, fichiers)
    environnement = _environnement(racine)
    if claude:
        environnement["CLAUDE_CONFIG_DIR"] = str(claude)
    if chemin_extra:
        environnement["PATH"] = f"{chemin_extra}{os.pathsep}{environnement['PATH']}"
    code = ("import json; from lintorn import noyau; print(json.dumps({r.titre: "
            "[r.statut, r.resume, r.detail] for r in noyau.executer()}))")
    sortie = subprocess.run([sys.executable, "-c", code], cwd=racine, env=environnement,
                            capture_output=True, text=True, timeout=120, check=False)
    assert sortie.returncode == 0, sortie.stderr
    return json.loads(sortie.stdout)


def _faux_outil(dossier: Path, nom: str, script: str) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    outil = dossier / nom
    outil.write_text(f"#!/bin/sh\n{script}\n", encoding="utf-8")
    outil.chmod(0o755)
    return dossier


def test_le_code_ignore_par_git_ne_fait_pas_un_projet_python(tmp_path):
    """La liste vient de git : un `.py` que le dépôt ignore n'est pas à lui."""
    _ecrire(tmp_path, {"pyproject.toml": '[project]\nname = "x"\n',
                       ".gitignore": "brouillon/\n", "brouillon/essai.py": ""})
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)

    lu = _detecte(tmp_path, {})

    assert lu["py_racine"] is None
    assert "ruff" not in lu["cles"]


# ─────────────────────────────────────────────────────────────────────────────
# B2 — OSV : les .csproj et les verrous Python
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("verrou", ["uv.lock", "poetry.lock", "Pipfile.lock", "pdm.lock"])
def test_un_verrou_python_fait_proposer_osv(tmp_path, verrou):
    """pip-audit lit un venv, jamais le verrou : sur un projet uv sans venv
    dans le dossier, les dépendances verrouillées n'étaient lues par personne."""
    lu = _detecte(tmp_path, {"pyproject.toml": '[project]\nname = "x"\n', "app.py": "",
                             verrou: ""})

    assert any(ecosysteme.startswith("Python") for ecosysteme in lu["ecosystemes"])
    assert "failles_osv" in lu["disponibles"]


def test_un_projet_dotnet_sans_packages_lock_fait_proposer_osv(tmp_path):
    """547 `.cs`, 28 `.csproj`, aucun packages.lock.json : les dépendances
    NuGet n'étaient auditées par rien, et le projet passait pour du JS."""
    lu = _detecte(tmp_path, {"src/Catalog.API/Catalog.API.csproj": "<Project />",
                             "src/Catalog.API/Program.cs": "",
                             "package.json": "{}", "package-lock.json": "{}"})

    assert lu["ecosystemes"] == [".NET"]
    assert "failles_osv" in lu["disponibles"]


def test_init_nomme_dotnet_et_ne_prend_plus_la_racine_pour_un_front(tmp_path):
    _ecrire(tmp_path, {"src/Web/Web.csproj": "<Project />", "package.json": "{}"})

    affiche, modele = _init(tmp_path)

    assert ".NET" in affiche
    assert f"JS ({tmp_path.name})" not in affiche, "la racine se lisait comme un dossier front"
    assert "\nfailles_osv" in modele, "failles_osv doit etre propose, decommente"


@_SANS_SH
def test_failles_osv_accorde_tourne_meme_sans_verrou_reconnu(tmp_path):
    """Forcé à la main, il était REFUSÉ avec un message faux (« pas de verrou
    d'un autre langage ») alors qu'OSV-Scanner savait lire le projet. Accordé,
    il tourne : et s'il ne trouve rien, c'est lui qui le dit."""
    faux = _faux_outil(tmp_path / "bin", "osv-scanner", "echo '{\"results\": []}'; exit 128")

    resultats = _executer(tmp_path / "projet", {
        "Directory.Packages.props": "<Project />",
        ".lintorn/config.toml": "[controles]\nfailles_osv = true\n",
    }, chemin_extra=faux)

    statut, resume, _ = resultats["Failles connues (OSV-Scanner)"]
    assert statut == "INDISPONIBLE"
    assert "aucun verrou lisible" in resume
    _, _, configuration = resultats["Configuration (Lintorn)"]
    assert "autre langage" not in (configuration or "")


# ─────────────────────────────────────────────────────────────────────────────
# B4 — les fichiers d'instructions IA
# ─────────────────────────────────────────────────────────────────────────────
def test_copilot_et_les_regles_claude_sont_des_fichiers_ia(tmp_path):
    """Claude Code charge `.claude/rules/*.md`, Copilot son fichier de
    `.github/` : leurs règles étaient lues comme de la doc ordinaire."""
    lu = _detecte(tmp_path, {
        "AGENTS.md": "x", ".github/copilot-instructions.md": "x",
        ".claude/rules/python.md": "x", ".claude/rules/frontend.md": "x",
        "web/.claude/rules/web.md": "x",
        ".github/ISSUE_TEMPLATE/bug.md": "x", "docs/rules/python.md": "x",
    })

    assert sorted(lu["docs_ia"]) == sorted([
        ".claude/rules/frontend.md", ".claude/rules/python.md",
        ".github/copilot-instructions.md", "AGENTS.md", "web/.claude/rules/web.md"])


def test_une_fixture_de_test_n_est_pas_un_fichier_ia(tmp_path):
    """Un `conventions.md` de tests Markdown était compté comme le fichier
    d'Aider : ses lignes seraient devenues des « règles énoncées »."""
    lu = _detecte(tmp_path, {
        "CLAUDE.md": "x",
        "crates/semantic/resources/mdtest/import/conventions.md": "x",
        "tests/fixtures/projet/CLAUDE.md": "x",
        "pkg/testdata/AGENTS.md": "x",
    })

    assert lu["docs_ia"] == ["CLAUDE.md"]


def test_une_skill_vendorisee_n_est_pas_un_fichier_ia(tmp_path):
    """Elle décrit un AUTRE dépôt : ses règles ne sont pas celles du projet."""
    lu = _detecte(tmp_path, {".github/skills/aspire/SKILL.md": "x"})

    assert lu["docs_ia"] == []


def test_un_chemin_declare_par_le_projet_est_reconnu(tmp_path):
    lu = _detecte(tmp_path, {
        "pyproject.toml": '[tool.lintorn]\nfichiers_ia = ["REGLES.md", "docs/ia/*.md"]\n',
        "REGLES.md": "x", "docs/ia/front.md": "x", "docs/autre.md": "x", "CLAUDE.md": "x",
    })

    assert sorted(lu["docs_ia"]) == ["REGLES.md", "docs/ia/front.md"]


# ─────────────────────────────────────────────────────────────────────────────
# B5 — une mémoire reconnue à son seul nom est annoncée, jamais prise en silence
# ─────────────────────────────────────────────────────────────────────────────
def _memoire(claude: Path, nom: str) -> Path:
    """Un dossier mémoire de Claude Code, avec une fiche qui cite un fichier."""
    dossier = claude / "projects" / nom / "memory"
    dossier.mkdir(parents=True)
    (dossier / "fiche.md").write_text("Le point d'entree est `app.py`.\n", encoding="utf-8")
    return dossier


_MEMOIRE = "Memoire IA vs code"


def test_une_memoire_prise_a_son_nom_est_annoncee(tmp_path):
    """Un clone nommé `ps2` recevait la mémoire de `Bios-PS1-PS2`, en
    « decouverte auto », sans que le rapport le dise."""
    claude = tmp_path / ".claude"
    _memoire(claude, "-home-quelquun-Documents-Bios-PS1-PS2")

    resultats = _executer(tmp_path / "clones" / "ps2", {"app.py": ""}, claude=claude)

    _, resume, detail = resultats[_MEMOIRE]
    assert "RESSEMBLANCE" in resume
    assert "Bios-PS1-PS2" in resume, "le dossier retenu doit etre nomme"
    assert "LINTORN_MEMOIRE" in detail
    assert "chemin(s) cite(s)" in resume, "la memoire est lue quand meme : elle n'est pas refusee"
    assert "RESSEMBLANCE" in resultats["Fraicheur memoire (git)"][1]


def test_plusieurs_memoires_ressemblantes_ne_se_departagent_pas(tmp_path):
    claude = tmp_path / ".claude"
    _memoire(claude, "-home-a-Bios-PS1-PS2")
    _memoire(claude, "-home-b-jeux-ps2")

    resultats = _executer(tmp_path / "clones" / "ps2", {"app.py": ""}, claude=claude)

    statut, resume, _ = resultats[_MEMOIRE]
    assert statut == "INDISPONIBLE"
    assert "Bios-PS1-PS2" in resume and "jeux-ps2" in resume
    assert "aucun n'est pris" in resume


def test_la_memoire_exacte_d_un_projet_reste_silencieuse(tmp_path):
    """Le cas ordinaire, celui de tous les projets restés à leur place."""
    projet = tmp_path / "clones" / "ps2"
    projet.mkdir(parents=True)
    claude = tmp_path / ".claude"
    _memoire(claude, re.sub(r"[^a-zA-Z0-9]", "-", str(projet.resolve())))
    _memoire(claude, "-home-a-Bios-PS1-PS2")

    resultats = _executer(projet, {"app.py": ""}, claude=claude)

    statut, resume, _ = resultats[_MEMOIRE]
    assert statut == "OK", resume
    assert "RESSEMBLANCE" not in resume


# ─────────────────────────────────────────────────────────────────────────────
# B6 — `verifier_donnees` est la commande d'UN projet, pas de Django
# ─────────────────────────────────────────────────────────────────────────────
_DJANGO = {"manage.py": "", "requirements.txt": "django==5.0\n", "boutique/models.py": ""}


def test_donnees_metier_n_est_pas_propose_a_un_projet_django_quelconque(tmp_path):
    """Activé, il aurait lancé une commande inconnue : un rouge bloquant."""
    lu = _detecte(tmp_path, _DJANGO)

    assert "django_check" in lu["disponibles"]
    assert "donnees_metier" not in lu["disponibles"]


def test_donnees_metier_reste_propose_au_projet_qui_a_la_commande(tmp_path):
    lu = _detecte(tmp_path, {
        **_DJANGO, "boutique/management/commands/verifier_donnees.py": "",
    })

    assert "donnees_metier" in lu["disponibles"]


def test_init_ecrit_donnees_metier_commente_sans_la_commande(tmp_path):
    _ecrire(tmp_path, _DJANGO)

    _, modele = _init(tmp_path)

    assert "# donnees_metier" in modele, "sans la commande, la cle est ecrite commentee"
    assert "\ndonnees_metier" not in modele


def test_installer_outils_ne_propose_verifier_donnees_qu_a_qui_l_a(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PY_RACINE", None)
    monkeypatch.setattr(config, "BACKEND", tmp_path)
    monkeypatch.setattr(config, "FRONTEND", None)
    monkeypatch.setattr(config, "ECOSYSTEMES_OSV", {})
    monkeypatch.setattr(config, "PROJET", {})

    monkeypatch.setattr(config, "DONNEES_METIER", False)
    sans = [outil["cle"] for outil in lintorn.commandes.outils._outillage_du_projet()]
    monkeypatch.setattr(config, "DONNEES_METIER", True)
    avec = [outil["cle"] for outil in lintorn.commandes.outils._outillage_du_projet()]

    assert "django_check" in sans and "donnees_metier" not in sans
    assert "donnees_metier" in avec


def test_donnees_metier_force_sans_commande_dit_ce_qui_manque(tmp_path):
    lu = _detecte(tmp_path, {**_DJANGO,
                             ".lintorn/config.toml": "[controles]\ndonnees_metier = true\n"})

    assert "donnees_metier" not in lu["cles"]
    assert any("verifier_donnees" in souci for souci in lu["soucis"])


# ─────────────────────────────────────────────────────────────────────────────
# B7 — une branche neuve : le hook liste ce que le distant n'a pas encore
# ─────────────────────────────────────────────────────────────────────────────
def _git(depot: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(depot), "-c", "user.email=t@t", "-c", "user.name=t",
                           *arguments], capture_output=True, text=True, timeout=30,
                          check=True).stdout.strip()


def _depot_pousse(tmp_path: Path, defaut: str, cloner: bool = True) -> Path:
    """Un dépôt dont le remote a `defaut` pour branche par défaut, et une
    branche neuve, pas encore poussée, qui modifie `nouveau.py`."""
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q", "-b", defaut)
    (source / "ancien.py").write_text("", encoding="utf-8")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "depart")
    distant = tmp_path / "distant.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(distant)],
                   check=True, timeout=30)
    local = tmp_path / "local"
    subprocess.run(["git", "clone", "-q", str(distant), str(local)], check=True, timeout=30)
    if not cloner:
        # Un dépôt créé sur place puis poussé n'a pas de `origin/HEAD`.
        _git(local, "remote", "set-head", "origin", "-d")
    _git(local, "checkout", "-q", "-b", "nouvelle")
    (local / "nouveau.py").write_text("", encoding="utf-8")
    _git(local, "add", "-A")
    _git(local, "commit", "-qm", "nouveau")
    return local


def _pousser(tmp_path: Path, local: Path) -> tuple[str, list[str]]:
    """(ce qu'affiche le hook, les fichiers qu'il confie à Lintorn)."""
    hook = local / ".lintorn" / "hooks" / "pre-push"
    hook.parent.mkdir(parents=True)
    hook.write_bytes((config.HOOKS_SOURCE / "pre-push").read_bytes())
    hook.chmod(0o755)
    entree = tmp_path / "entree"
    faux = _faux_outil(tmp_path / "bin", "lintorn", f"cat > '{entree}'")
    sha = _git(local, "rev-parse", "HEAD")
    sortie = subprocess.run(
        ["sh", str(hook), "origin", "url"], cwd=local, text=True, timeout=60, check=False,
        capture_output=True, input=f"refs/heads/nouvelle {sha} refs/heads/nouvelle {'0' * 40}\n",
        env={**os.environ, "PATH": f"{faux}{os.pathsep}{os.environ['PATH']}"})
    recus = entree.read_text(encoding="utf-8").split() if entree.is_file() else []
    return sortie.stdout, recus


@_SANS_SH
def test_le_hook_suit_la_branche_par_defaut_du_remote(tmp_path):
    """Sur un dépôt en `development`, `origin/main` n'existait pas : une
    branche neuve perdait le focus, sans un mot."""
    affiche, recus = _pousser(tmp_path, _depot_pousse(tmp_path, "development"))

    assert recus == ["nouveau.py"]
    assert "inconnue" not in affiche


@_SANS_SH
@pytest.mark.parametrize("defaut", ["master", "trunk"])
def test_sans_origin_head_la_branche_neuve_est_quand_meme_listee(tmp_path, defaut):
    """Un dépôt créé sur place n'a pas `origin/HEAD` : le hook supposait `main`
    ou `master`, et sur `trunk` ne listait rien. Ce que le distant n'a pas
    encore ne dépend pas de sa branche par défaut."""
    affiche, recus = _pousser(tmp_path, _depot_pousse(tmp_path, defaut, cloner=False))

    assert recus == ["nouveau.py"]
    assert "inconnue" not in affiche


# ─────────────────────────────────────────────────────────────────────────────
# B8 — le remède suit le gestionnaire de paquets, et --init ne réclame plus de
#      venv à un projet sans Python
# ─────────────────────────────────────────────────────────────────────────────
def _remede_tsc(lu: dict) -> str:
    return next(c for c in lu["commandes"] if c["cle"] == "typescript")["remede"]


@pytest.mark.parametrize("verrou, commande", [
    ("pnpm-lock.yaml", "pnpm install"), ("yarn.lock", "yarn install"),
    ("bun.lock", "bun install"), ("package-lock.json", "npm install"),
])
def test_le_remede_de_tsc_suit_le_verrou(tmp_path, verrou, commande):
    lu = _detecte(tmp_path, {"package.json": "{}", "tsconfig.json": "{}", verrou: ""})

    assert _remede_tsc(lu) == f"{commande} (dans .)"


def test_le_remede_se_lance_la_ou_vit_le_verrou(tmp_path):
    """Un front yarn rangé sous le dossier Django : `yarn install`, dans le
    front. Un sous-projet d'un workspace : l'installation se fait à sa racine."""
    front = _detecte(tmp_path / "a", {"netbox/manage.py": "",
                                      "netbox/project-static/package.json": "{}",
                                      "netbox/project-static/tsconfig.json": "{}",
                                      "netbox/project-static/yarn.lock": ""})
    workspace = _detecte(tmp_path / "b", {"pnpm-lock.yaml": "", "web/package.json": "{}",
                                          "web/tsconfig.json": "{}"})

    assert _remede_tsc(front) == "yarn install (dans netbox/project-static)"
    assert _remede_tsc(workspace) == "pnpm install (dans .)"


def test_sans_verrou_le_remede_est_npm_install_dans_le_front(tmp_path):
    lu = _detecte(tmp_path, {"front/package.json": "{}", "front/tsconfig.json": "{}"})

    assert _remede_tsc(lu) == "npm install (dans front)"


def test_installer_outils_ne_propose_plus_npm_a_un_projet_yarn(tmp_path, monkeypatch, capsys):
    """`npm install` sur un projet yarn ignore yarn.lock et crée un
    package-lock.json concurrent, qu'on conseillait même de versionner."""
    _ecrire(tmp_path, {"package.json": "{}", "tsconfig.json": "{}", "yarn.lock": ""})
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "PY_RACINE", None)
    monkeypatch.setattr(config, "BACKEND", None)
    monkeypatch.setattr(config, "FRONTEND", tmp_path)
    monkeypatch.setattr(config, "PROJETS_TS", [tmp_path])
    monkeypatch.setattr(config, "ECOSYSTEMES_OSV", {})
    monkeypatch.setattr(config, "PROJET", {})
    monkeypatch.setattr(lintorn.commandes.outils, "_oui", lambda question: False)

    lintorn.commandes.outils.installer_outils()

    affiche = capsys.readouterr().out
    assert "yarn install" in affiche
    assert "npm install" not in affiche


def test_init_ne_reclame_pas_de_venv_a_un_projet_sans_python(tmp_path):
    _ecrire(tmp_path, {"composer.lock": "{}", "package.json": "{}", "app/Kernel.php": ""})

    _, modele = _init(tmp_path)

    assert "AUCUN VENV" not in modele
    assert "Aucun code Python" in modele


def test_init_reclame_toujours_un_venv_a_un_projet_python_qui_n_en_a_pas(tmp_path):
    _ecrire(tmp_path, {"pyproject.toml": '[project]\nname = "x"\n', "app.py": ""})

    _, modele = _init(tmp_path)

    assert "AUCUN VENV TROUVE" in modele


# ─────────────────────────────────────────────────────────────────────────────
# B9 — pas de préfixe pour un dossier qui n'existe pas
# ─────────────────────────────────────────────────────────────────────────────
def test_un_front_sans_src_n_invente_pas_de_prefixe(tmp_path):
    """`src/` était ajouté d'office : sur un front qui range ses sources dans
    `web_src/` ou `ruff/src/`, le préfixe désignait un dossier absent."""
    lu = _detecte(tmp_path, {"playground/package.json": "{}",
                             "playground/ruff/src/Editor.tsx": ""})

    assert lu["prefixes"] == ["playground/"]


def test_un_front_avec_src_garde_son_prefixe(tmp_path):
    lu = _detecte(tmp_path, {"front/package.json": "{}", "front/src/main.ts": ""})

    assert lu["prefixes"] == ["front/src/", "front/"]


# ─────────────────────────────────────────────────────────────────────────────
# B12 — « Dependances vs venv » : le bon requirements.txt, et les extras
# ─────────────────────────────────────────────────────────────────────────────
def test_le_requirements_de_la_racine_sert_au_projet_django_range_plus_bas(tmp_path):
    """`manage.py` dans `netbox/`, `requirements.txt` à la racine : le contrôle
    cherchait à côté de manage.py, et disparaissait du rapport sans un mot."""
    lu = _detecte(tmp_path, {"netbox/manage.py": "", "requirements.txt": "django==5.0\n",
                             ".venv/bin/python": ""})

    dependances = next(c for c in lu["commandes"] if c["cle"] == "dependances")
    assert Path(dependances["cmd"][-1]) == tmp_path.resolve()


def test_le_requirements_voisin_du_code_passe_avant_celui_de_la_racine(tmp_path):
    lu = _detecte(tmp_path, {"api/manage.py": "", "api/requirements.txt": "django==5.0\n",
                             "requirements.txt": "mkdocs==1.0\n", ".venv/bin/python": ""})

    dependances = next(c for c in lu["commandes"] if c["cle"] == "dependances")
    assert Path(dependances["cmd"][-1]) == (tmp_path / "api").resolve()


def test_les_extras_ne_font_pas_un_paquet_absent(tmp_path):
    """`psycopg[c,pool]==3.3.5` était déclaré « PAS INSTALLE — ImportError
    garanti » alors que psycopg était installé : un rouge bloquant à tort."""
    version = importlib.metadata.version("pytest")
    (tmp_path / "requirements.txt").write_text(
        f"pytest[testing]=={version}\npytest=={version};python_version>'3'\n",
        encoding="utf-8")
    script = Path(lintorn.__file__).parent / "dependances.py"

    sortie = subprocess.run([sys.executable, str(script), str(tmp_path)],
                            capture_output=True, text=True, timeout=120, check=False)

    assert "PAS INSTALLES" not in sortie.stdout, sortie.stdout
    assert "DIVERGENTES" not in sortie.stdout, sortie.stdout


def _installes() -> list[str]:
    """Le `pip freeze` du python de ces tests, qui joue le venv du projet."""
    sortie = subprocess.run([sys.executable, "-m", "pip", "freeze", "--local"],
                            capture_output=True, text=True, timeout=120, check=True)
    return [ligne for ligne in sortie.stdout.splitlines()
            if "==" in ligne and not ligne.startswith(("#", "-"))]


def _nom(ligne: str) -> str:
    return re.sub(r"[-_.]+", "-", ligne.split("==", 1)[0]).lower()


def _comparer(tmp_path, lignes: list[str]) -> subprocess.CompletedProcess:
    (tmp_path / "requirements.txt").write_text("\n".join(lignes) + "\n", encoding="utf-8")
    script = Path(lintorn.__file__).parent / "dependances.py"
    return subprocess.run([sys.executable, str(script), str(tmp_path)],
                          capture_output=True, text=True, timeout=120, check=False)


def test_les_outils_d_audit_ne_sont_pas_des_dependances_oubliees(tmp_path):
    """`lintorn outils` les installe dans le venv : comptés « installés mais pas
    déclarés », avec ce qu'ils tirent, ils faisaient refuser le premier push."""
    for outil in ("ruff", "pytest", "vulture", "pip-audit"):
        pytest.importorskip(outil.replace("-", "_"))
    # Ni les outils, ni CacheControl et filelock, que pip-audit tire par
    # `CacheControl[filecache]` : une option entre crochets.
    retires = {"ruff", "pytest", "vulture", "pip-audit", "cachecontrol", "filelock"}

    sortie = _comparer(tmp_path, [ligne for ligne in _installes() if _nom(ligne) not in retires])

    assert sortie.returncode == 0, sortie.stdout
    assert "PAS DECLARES" not in sortie.stdout, sortie.stdout
    note = next(ligne for ligne in sortie.stdout.splitlines() if ligne.startswith("Non comptes"))
    for nom in ("ruff", "pytest", "pip-audit", "filelock"):
        assert nom in note, "ecarte, mais NOMME"


def test_une_ligne_sans_version_declare_son_paquet(tmp_path):
    """`certifi>=2020` était ignoré : certifi « installé mais pas déclaré », un
    rouge bloquant ; et un paquet absent ainsi déclaré passait inaperçu."""
    lignes = ["certifi>=2020" if _nom(ligne) == "certifi" else ligne for ligne in _installes()]
    if "certifi>=2020" not in lignes:
        pytest.skip("certifi absent du venv de test")

    sortie = _comparer(tmp_path, [*lignes, "absent-zz>=1.0"])

    assert sortie.returncode == 1
    assert "PAS DECLARES" not in sortie.stdout, sortie.stdout
    assert "PAS INSTALLES (1)" in sortie.stdout and "absent-zz>=1.0" in sortie.stdout


def test_la_liste_des_outils_d_audit_suit_celle_de_lintorn_outils():
    assert ({dependances.normaliser(o) for o in dependances.OUTILS_D_AUDIT}
            == {o.replace("_", "-") for o in config.OUTILS_INSTALLABLES})


def test_le_resume_des_dependances_dit_quel_ecart(tmp_path, monkeypatch):
    """« 33 ligne(s) de sortie » ne disait pas pourquoi le push était refusé."""
    (tmp_path / "requirements.txt").write_text(
        "\n".join([*_installes(), "absent-zz==1.0"]) + "\n", encoding="utf-8")
    for nom, valeur in (("RACINE", tmp_path), ("PYTHON", sys.executable),
                        ("VENV_PROJET", tmp_path / ".venv"),
                        ("REQUIREMENTS", tmp_path / "requirements.txt"),
                        ("CONTROLES_INTERNES", {})):
        monkeypatch.setattr(config, nom, valeur)
    monkeypatch.setattr(config, "COMMANDES", [requirements.commande()])

    resultat = noyau.executer()[0]

    assert resultat.statut == "ALERTE"
    assert resultat.resume == "1 declare(s) mais pas installe(s)"


def test_un_paquet_que_le_code_importe_n_est_pas_excuse_par_les_outils(tmp_path, monkeypatch):
    """`import pluggy` jamais déclaré : avant `lintorn outils`, « installe mais pas
    declare » ; après, pytest tirant pluggy, « rien a signaler ». Le projet
    plantait sur une machine neuve derrière un vert."""
    pytest.importorskip("pluggy")
    (tmp_path / "app.py").write_text("import os\nimport pluggy\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text(
        "\n".join(ligne for ligne in _installes()
                  if _nom(ligne) not in {"ruff", "pytest", "vulture", "pip-audit", "pluggy"})
        + "\n", encoding="utf-8")
    for nom, valeur in (("RACINE", tmp_path), ("PYTHON", sys.executable),
                        ("VENV_PROJET", tmp_path / ".venv"),
                        ("REQUIREMENTS", tmp_path / "requirements.txt"),
                        ("CONTROLES_INTERNES", {})):
        monkeypatch.setattr(config, nom, valeur)
    monkeypatch.setattr(config, "COMMANDES", [requirements.commande()])

    resultat = noyau.executer()[0]

    assert resultat.statut == "ALERTE", resultat.detail
    assert "- pluggy==" in resultat.detail and "(ton code l'importe)" in resultat.detail


_SOUS_DEPENDANCES_DE_REQUESTS = {"certifi", "idna", "urllib3", "charset-normalizer"}


def test_des_dependances_directes_seulement_ne_font_pas_signaler_leurs_sous_dependances(tmp_path):
    """`requests>=2` sans certifi, idna, urllib3 : « 4 installe(s) mais pas
    declare(s) », un rouge bloquant, alors que pip les installe partout."""
    pytest.importorskip("requests")
    retires = {"ruff", "pytest", "vulture", "pip-audit", *_SOUS_DEPENDANCES_DE_REQUESTS}

    sortie = _comparer(tmp_path, [ligne for ligne in _installes() if _nom(ligne) not in retires])

    assert sortie.returncode == 0, sortie.stdout
    assert "PAS DECLARES" not in sortie.stdout, sortie.stdout
    tires = next(ligne for ligne in sortie.stdout.splitlines() if ligne.startswith("Sans ligne"))
    assert all(nom in tires for nom in _SOUS_DEPENDANCES_DE_REQUESTS), "pas comptes, mais NOMMES"


def test_une_sous_dependance_que_le_code_importe_se_declare(tmp_path):
    pytest.importorskip("requests")
    (tmp_path / "app.py").write_text("import requests\nfrom urllib3 import util\n", encoding="utf-8")
    retires = {"ruff", "pytest", "vulture", "pip-audit", *_SOUS_DEPENDANCES_DE_REQUESTS}

    sortie = _comparer(tmp_path, [ligne for ligne in _installes() if _nom(ligne) not in retires])

    assert "PAS DECLARES (1)" in sortie.stdout, sortie.stdout
    assert "- urllib3==" in sortie.stdout and "(ton code l'importe)" in sortie.stdout


def test_une_option_entre_crochets_sur_une_ligne_epinglee_compte(tmp_path):
    """`CacheControl[filecache]==x` tire filelock ; `CacheControl==x` seul, non."""
    for module in ("cachecontrol", "filelock"):
        pytest.importorskip(module)
    lignes = [ligne for ligne in _installes()
              if _nom(ligne) not in {"ruff", "pytest", "vulture", "pip-audit", "filelock"}]
    avec = [ligne.replace("==", "[filecache]==", 1) if _nom(ligne) == "cachecontrol" else ligne
            for ligne in lignes]

    sans_option = _comparer(tmp_path, lignes).stdout
    avec_option = _comparer(tmp_path, avec).stdout

    tires = [ligne for ligne in avec_option.splitlines() if ligne.startswith("Sans ligne")]
    assert tires and "filelock" in tires[0], avec_option
    assert not any(ligne.startswith("Sans ligne") and "filelock" in ligne
                   for ligne in sans_option.splitlines()), sans_option


def test_un_module_du_projet_n_est_pas_un_paquet_importe(tmp_path):
    """`import tests` vise le dossier du projet ; `api/requests.py` ne cache pas `import requests`."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "requests.py").write_text("", encoding="utf-8")
    (tmp_path / "app.py").write_text("import tests, os.path as p\nimport requests\n"
                                     "from . import voisin\n", encoding="utf-8")

    assert dependances.importes(tmp_path) == {"os", "requests"}


def _dependances_par_le_noyau(tmp_path, monkeypatch, lignes: list[str]):
    (tmp_path / "requirements.txt").write_text("\n".join(lignes) + "\n", encoding="utf-8")
    for nom, valeur in (("RACINE", tmp_path), ("PYTHON", sys.executable),
                        ("VENV_PROJET", tmp_path / ".venv"),
                        ("REQUIREMENTS", tmp_path / "requirements.txt"),
                        ("CONTROLES_INTERNES", {})):
        monkeypatch.setattr(config, nom, valeur)
    monkeypatch.setattr(config, "COMMANDES", [requirements.commande()])
    return noyau.executer()[0]


def test_au_vert_les_paquets_sans_ligne_restent_nommes(tmp_path, monkeypatch):
    """« rien a signaler » seul : le rapport taisait les paquets laissés sans ligne."""
    pytest.importorskip("requests")
    retires = {"ruff", "pytest", "vulture", "pip-audit", *_SOUS_DEPENDANCES_DE_REQUESTS}

    resultat = _dependances_par_le_noyau(
        tmp_path, monkeypatch, [ligne for ligne in _installes() if _nom(ligne) not in retires])

    assert resultat.statut == "OK", resultat.detail
    assert "paquet(s) sans ligne, expliques dans le rapport" in resultat.resume
    assert resultat.detail_meme_au_vert and "certifi" in resultat.detail


def test_un_requirements_complet_reste_un_simple_vert(tmp_path, monkeypatch):
    resultat = _dependances_par_le_noyau(tmp_path, monkeypatch, _installes())

    assert resultat.statut == "OK", resultat.detail
    assert resultat.resume == "rien a signaler"
    assert not resultat.detail_meme_au_vert


def test_le_resume_de_vulture_compte_ses_candidats(tmp_path, monkeypatch):
    sortie = ("a.py:3: unused function 'f' (60% confidence)\n"
              "b.py:9: unused variable 'x' (100% confidence)")
    monkeypatch.setattr(config, "VENV_PROJET", tmp_path / ".venv")
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {})
    monkeypatch.setattr(config, "COMMANDES", [{
        "cle": "code_mort", "titre": "Code mort (vulture, consultatif)", "bloquant": False,
        "cmd": [sys.executable, "-c", f"print({sortie!r}); raise SystemExit(3)"],
        "cwd": tmp_path, "traduction": "vulture", "lent": False, "codes_alerte": (3,)}])

    resultat = noyau.executer()[0]

    assert resultat.resume == "2 candidat(s) de code mort - a confirmer a l'oeil"


# ─────────────────────────────────────────────────────────────────────────────
# A5 — monorepo : chaque projet TypeScript a sa ligne
# ─────────────────────────────────────────────────────────────────────────────
_MONOREPO = {"package.json": "{}", "pnpm-lock.yaml": "",
             "server/package.json": "{}", "server/tsconfig.json": "{}",
             "web/package.json": "{}", "web/tsconfig.json": "{}",
             "docs/tsconfig.json": "{}"}


def test_un_workspace_sans_tsconfig_ne_fait_plus_disparaitre_typescript(tmp_path):
    """La racine du workspace n'a pas de tsconfig : aucune ligne TypeScript,
    ni rouge ni INDISPONIBLE, alors que `server/` et `web/` en sont pleins."""
    resultats = _executer(tmp_path, _MONOREPO)

    for dossier in ("server", "web"):
        statut, resume, _ = resultats[f"TypeScript {dossier}/ (tsc --noEmit)"]
        assert statut == "INDISPONIBLE", resume
    assert not any("docs" in titre for titre in resultats), "sans package.json, pas un projet"


def test_chaque_projet_ts_a_sa_commande_et_son_remede(tmp_path):
    lu = _detecte(tmp_path, _MONOREPO)

    tsc = {c["cwd"]: c for c in lu["commandes"] if c["cle"] == "typescript"}
    assert sorted(tsc) == ["server", "web"]
    assert tsc["web"]["remede"] == "pnpm install (dans .)"
    assert "web/" in lu["prefixes"], "le focus doit reconnaitre les chemins de tsc lance dans web/"


def test_un_projet_ts_unique_a_la_racine_garde_son_titre(tmp_path):
    lu = _detecte(tmp_path, {"package.json": "{}", "tsconfig.json": "{}"})

    assert [c["titre"] for c in lu["commandes"] if c["cle"] == "typescript"] == [
        "TypeScript (tsc --noEmit)"]


def test_un_tsc_hisse_par_le_workspace_est_trouve(tmp_path):
    _ecrire(tmp_path, {**_MONOREPO, "node_modules/.bin/tsc": ""})

    lu = _detecte(tmp_path, {})

    tsc = next(c for c in lu["commandes"] if c["cwd"] == "web")
    assert Path(tsc["cmd"][0]) == tmp_path / "node_modules" / ".bin" / "tsc"
