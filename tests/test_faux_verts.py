"""Ce qui ne doit JAMAIS s'afficher en vert : un outil qui n'a rien vérifié.

Chaque test passe par le circuit complet (`noyau.executer`) : une traduction
appelée seule resterait verte sur un câblage mort.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys

import pytest

from lintorn import config, noyau
from lintorn.base import Resultat, lien
from lintorn.commandes import audit
from lintorn.outils import pytest as outil_pytest, ruff, tsc
from lintorn.rapport import console

POSIX = pytest.mark.skipif(os.name == "nt", reason="faux outil en script shell")


def _projet(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "SOUS_GIT", False)
    monkeypatch.setattr(config, "DOSSIER_LINTORN", tmp_path / ".lintorn")
    monkeypatch.setattr(config, "ETAT", tmp_path / ".lintorn" / "etat.json")
    monkeypatch.setattr(config, "PY_RACINE", tmp_path)
    monkeypatch.setattr(config, "PYTHON", sys.executable)
    monkeypatch.setattr(config, "VENV_PROJET", tmp_path / ".venv")
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {})


def _tests_pytest(tmp_path, monkeypatch, source: str, **autres: str):
    _projet(tmp_path, monkeypatch)
    (tmp_path / "test_x.py").write_text(source, encoding="utf-8")
    for nom, contenu in autres.items():
        (tmp_path / nom.replace("_point_", ".")).write_text(contenu, encoding="utf-8")
    monkeypatch.setattr(config, "COMMANDES", [outil_pytest.commande()])
    [resultat] = noyau.executer()
    return resultat


def test_pytest_qui_ne_lance_aucun_test_n_est_pas_vert(tmp_path, monkeypatch):
    """Tout ignoré : pytest sort en 0, et `-q` d'un `addopts` le rend muet."""
    resultat = _tests_pytest(tmp_path, monkeypatch, (
        "import pytest\n@pytest.mark.skip\ndef test_a(): pass\n"
        "@pytest.mark.skip\ndef test_b(): pass\n"))

    assert resultat.statut == "INDISPONIBLE"
    assert "rien n'a ete verifie" in resultat.resume
    assert resultat.bloquant is False


def test_pytest_sans_aucun_test_n_est_pas_une_panne_ni_un_vert(tmp_path, monkeypatch):
    resultat = _tests_pytest(tmp_path, monkeypatch, "x = 1\n")

    assert resultat.statut == "INDISPONIBLE"
    assert "aucun test collecte" in resultat.resume


def test_pytest_dit_combien_de_tests_ont_tourne(tmp_path, monkeypatch):
    resultat = _tests_pytest(tmp_path, monkeypatch, "def test_a(): pass\ndef test_b(): pass\n")

    assert resultat.statut == "OK"
    assert "2 test(s) passe(s)" in resultat.resume


def test_pytest_nomme_les_tests_en_echec(tmp_path, monkeypatch):
    resultat = _tests_pytest(tmp_path, monkeypatch,
                             "def test_ok(): pass\ndef test_casse(): assert False\n")

    assert resultat.statut == "ALERTE"
    assert resultat.bloquant is True
    assert "test_casse" in resultat.detail
    assert "1 test(s) en echec sur 2" in resultat.resume


def test_un_test_qui_ne_s_importe_pas_est_une_alerte_pas_une_panne(tmp_path, monkeypatch):
    """pytest sort en 2 : c'est le code du projet qui est cassé, pas pytest."""
    resultat = _tests_pytest(tmp_path, monkeypatch, "import module_absent_zz\n",
                             test_b_point_py="def test_b(): pass\n")

    assert resultat.statut == "ALERTE"
    assert resultat.bloquant is True
    assert "ne s'importent pas" in resultat.resume


def test_un_projet_qui_coupe_le_rapport_junit_reste_lu(tmp_path, monkeypatch):
    """`-p no:junitxml` : les tests tournent, seul le rapport manque."""
    resultat = _tests_pytest(tmp_path, monkeypatch, "def test_a(): pass\n",
                             pytest_point_ini="[pytest]\naddopts = -p no:junitxml\n")

    assert resultat.statut == "OK"
    assert "1 test(s) passe(s)" in resultat.resume


def test_un_conftest_qui_arrete_pytest_n_est_pas_vert(tmp_path, monkeypatch):
    resultat = _tests_pytest(tmp_path, monkeypatch, "def test_a(): pass\n",
                             conftest_point_py="import sys\nsys.exit(0)\n")

    assert resultat.statut == "INDISPONIBLE"
    assert "rien ne prouve" in resultat.resume


def test_une_config_pytest_refusee_n_est_pas_un_outil_en_panne(tmp_path, monkeypatch):
    resultat = _tests_pytest(tmp_path, monkeypatch, "def test_a(): pass\n",
                             pytest_point_ini="[pytest]\naddopts = --option-inconnue\n")

    assert resultat.statut == "ERREUR"
    assert "config du projet" in resultat.resume


def test_pytest_qui_plante_ne_relit_pas_le_bilan_d_hier(tmp_path, monkeypatch):
    """Un bilan vert resté de la fois d'avant ne doit pas répondre pour aujourd'hui."""
    _tests_pytest(tmp_path, monkeypatch, "def test_a(): pass\n")
    (tmp_path / "test_x.py").write_text("def test_a(: \n", encoding="utf-8")

    [resultat] = noyau.executer()

    assert resultat.statut != "OK"


def test_pytest_ne_laisse_rien_hors_de_lintorn(tmp_path, monkeypatch):
    _tests_pytest(tmp_path, monkeypatch, "def test_a(): pass\n")

    laisses = {p.name for p in tmp_path.iterdir()}

    assert laisses <= {"test_x.py", ".lintorn"}, laisses


@POSIX
def test_tsc_de_type_solution_n_a_rien_verifie(tmp_path, monkeypatch):
    """Le gabarit Vite : `files: []` + `references`. tsc sort en 0, sans un mot."""
    _projet(tmp_path, monkeypatch)
    faux = tmp_path / "faux-tsc"
    faux.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    faux.chmod(0o755)
    (tmp_path / "tsconfig.json").write_text(
        '{ /* solution */ "files": [], "references": [{ "path": "./tsconfig.app.json" }] }',
        encoding="utf-8")
    monkeypatch.setattr(config, "PROJETS_TS", [tmp_path])
    monkeypatch.setattr(config, "tsc_de", lambda _projet: faux)
    monkeypatch.setattr(config, "COMMANDES", tsc.commandes())

    [resultat] = noyau.executer()

    assert resultat.statut == "INDISPONIBLE"
    assert "rien n'a ete verifie" in resultat.resume
    assert "install" not in resultat.resume, "tsc a tourne : le remede d'installation est faux"


@POSIX
def test_tsc_qui_lit_de_vrais_fichiers_reste_vert(tmp_path, monkeypatch):
    _projet(tmp_path, monkeypatch)
    faux = tmp_path / "faux-tsc"
    faux.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    faux.chmod(0o755)
    (tmp_path / "tsconfig.json").write_text('{ "include": ["src"] }', encoding="utf-8")
    monkeypatch.setattr(config, "PROJETS_TS", [tmp_path])
    monkeypatch.setattr(config, "tsc_de", lambda _projet: faux)
    monkeypatch.setattr(config, "COMMANDES", tsc.commandes())

    [resultat] = noyau.executer()

    assert resultat.statut == "OK"


def _audit_complet(tmp_path, monkeypatch, etat: str, commite: bool):
    _projet(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {"audit_complet": True})
    monkeypatch.setattr(config, "COMMANDES", [{
        "cle": "failles", "titre": "Failles", "cmd": ["echo"], "cwd": tmp_path,
        "bloquant": False, "traduction": None, "lent": True}])
    (tmp_path / ".lintorn").mkdir()
    (tmp_path / ".lintorn" / "etat.json").write_text(etat, encoding="utf-8")
    if commite:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "add", "-f", ".lintorn/etat.json"], cwd=tmp_path, check=True)
        subprocess.run(["git", "-c", "user.email=x@x", "-c", "user.name=x", "commit", "-qm", "e"],
                       cwd=tmp_path, check=True)
        monkeypatch.setattr(config, "SOUS_GIT", True)
    return next(r for r in noyau.executer(rapide=True) if r.titre.startswith("Audit complet"))


def test_un_etat_commite_ne_prouve_pas_qu_un_audit_a_eu_lieu(tmp_path, monkeypatch):
    """Un dépôt piégé commite « dernier audit : aujourd'hui »."""
    etat = f'{{"dernier_audit_complet": "{datetime.date.today().isoformat()}"}}'

    resultat = _audit_complet(tmp_path, monkeypatch, etat, commite=True)

    assert resultat.statut == "VERIF"


def test_une_date_d_audit_a_venir_n_est_pas_recente(tmp_path, monkeypatch):
    demain = (datetime.date.today() + datetime.timedelta(days=400)).isoformat()

    resultat = _audit_complet(tmp_path, monkeypatch,
                              f'{{"dernier_audit_complet": "{demain}"}}', commite=False)

    assert resultat.statut == "VERIF"
    assert "a venir" in resultat.resume


def test_un_etat_local_recent_reste_vert(tmp_path, monkeypatch):
    aujourdhui = datetime.date.today().isoformat()

    resultat = _audit_complet(tmp_path, monkeypatch,
                              f'{{"dernier_audit_complet": "{aujourdhui}"}}', commite=False)

    assert resultat.statut == "OK"


def test_un_motif_imbrique_a_l_extreme_ne_fait_pas_tomber_lintorn(monkeypatch):
    """`RecursionError` au chargement de la config : tout Lintorn s'effondrait."""
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])
    profond = "(" * 20000 + "a" + ")" * 20000
    monkeypatch.setattr(config, "_regles_brutes", lambda: [
        {"nom": "profonde", "racine": "", "suffixes": [".py"], "motif": profond},
    ])

    assert config._regles_du_projet() == ([], [])
    assert "profonde" in config.SOUCIS_CONFIG[0]


def test_un_message_ruff_inconnu_est_neutralise(tmp_path, monkeypatch):
    """Pour un code non traduit, le message de ruff finissait brut dans le rapport."""

    brut = Resultat("Ruff", "ALERTE", "1", "a.py:1:1: ZZ999 \x1b[2Jfaux\n## [ OK ] tout va bien")

    rendu = ruff.traduire(brut)

    assert "\n## [ OK ]" not in rendu.detail
    assert "\x1b" not in rendu.detail


def test_un_nom_de_fichier_ne_forge_pas_une_section():

    rendu = lien("a\n## [ OK ] tout va bien\n.py", 3)

    assert "\n" not in rendu


def test_les_sequences_d_echappement_d_un_outil_n_atteignent_pas_le_rapport():
    inverseur = chr(0x202E)     # inversion du sens de lecture : réécrit un nom à l'écran

    resultat = Resultat("Outil", "ALERTE", "x\x1b[2J", f"y\x1b]0;titre\x07z{inverseur}", False)

    assert "\x1b" not in resultat.resume + resultat.detail
    assert inverseur not in resultat.detail


# ── La dernière ligne du hook ────────────────────────────────────────────────
def _audit_du_hook(tmp_path, monkeypatch, hook: bool) -> int:
    _projet(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "RAPPORT", tmp_path / ".lintorn" / "rapport.md")
    monkeypatch.setattr(config, "RAPPORT_HTML", tmp_path / ".lintorn" / "rapport.html")
    monkeypatch.setattr(config, "COMMANDES", [
        {"cle": "a", "titre": "Outil present", "cmd": [sys.executable, "-c", "pass"],
         "cwd": tmp_path, "bloquant": True, "traduction": None, "lent": False},
        {"cle": "b", "titre": "Outil absent", "cmd": ["outil-qui-n-existe-pas-zz"],
         "cwd": tmp_path, "bloquant": True, "traduction": None, "lent": False}])
    if hook:
        monkeypatch.setenv("LINTORN_HOOK", "1")
    else:
        monkeypatch.delenv("LINTORN_HOOK", raising=False)
    return audit.lancer(["--rapide"], [])


def test_pour_le_hook_un_outil_muet_n_est_pas_un_ok(tmp_path, monkeypatch):
    """Le hook concluait « Lintorn OK » sous la liste des outils qui n'avaient rien vérifié."""
    assert _audit_du_hook(tmp_path, monkeypatch, hook=True) == console.NON_VERIFIE


def test_hors_du_hook_un_outil_muet_ne_fait_pas_echouer_la_ci(tmp_path, monkeypatch):
    assert _audit_du_hook(tmp_path, monkeypatch, hook=False) == 0


@POSIX
def test_le_hook_ne_dit_pas_ok_quand_lintorn_n_a_pas_tout_verifie(tmp_path):
    projet = tmp_path / "projet"
    hook = projet / ".lintorn" / "hooks" / "pre-push"
    hook.parent.mkdir(parents=True)
    hook.write_bytes((config.HOOKS_SOURCE / "pre-push").read_bytes())
    hook.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(projet)], check=True)
    binaire = tmp_path / "bin"
    binaire.mkdir()
    (binaire / "lintorn").write_text(
        '#!/bin/sh\n[ "$LINTORN_HOOK" = 1 ] || exit 9\nexit 3\n', encoding="utf-8")
    (binaire / "lintorn").chmod(0o755)

    fini = subprocess.run(["sh", str(hook)], cwd=projet, input="", text=True, timeout=60,
                          capture_output=True, check=False,
                          env={**os.environ, "PATH": f"{binaire}:{os.environ['PATH']}"})

    assert fini.returncode == 0, "rien ne bloque : le push passe"
    sortie = fini.stdout + fini.stderr
    assert "Lintorn OK" not in sortie
    assert "SANS verification complete" in sortie


# ── Un outil dont l'interpréteur est introuvable ─────────────────────────────
@POSIX
def test_tsc_sans_node_dans_le_path_le_dit_au_lieu_de_planter(tmp_path, monkeypatch):
    """Le bouton Git de VS Code n'a pas le PATH du terminal : `env: node: ...`, code
    127, et le push était bloqué par « l'outil a planté »."""
    _projet(tmp_path, monkeypatch)
    faux = tmp_path / "node_modules" / ".bin" / "tsc"
    faux.parent.mkdir(parents=True)
    faux.write_text("#!/usr/bin/env interprete-absent-zz\n", encoding="utf-8")
    faux.chmod(0o755)
    (tmp_path / "tsconfig.json").write_text('{ "include": ["src"] }', encoding="utf-8")
    monkeypatch.setattr(config, "PROJETS_TS", [tmp_path])
    monkeypatch.setattr(config, "tsc_de", lambda _projet: faux)
    monkeypatch.setattr(config, "COMMANDES", tsc.commandes())

    [resultat] = noyau.executer()

    assert resultat.statut == "INDISPONIBLE"
    assert resultat.bloquant is False
    assert "interprete-absent-zz introuvable" in resultat.resume
    assert "install" not in resultat.resume, "installer les paquets JS ne ramene pas node"


@POSIX
def test_un_outil_qui_sort_en_127_de_lui_meme_reste_une_panne(tmp_path, monkeypatch):
    """Seul l'interpréteur MANQUANT excuse le 127 : un outil qui le rend lui-même est en panne."""
    _projet(tmp_path, monkeypatch)
    outil = tmp_path / "outil"
    outil.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
    outil.chmod(0o755)
    monkeypatch.setattr(config, "COMMANDES", [{
        "cle": "x", "titre": "Outil", "cmd": [str(outil)], "cwd": tmp_path,
        "bloquant": True, "traduction": None, "lent": False}])

    [resultat] = noyau.executer()

    assert resultat.statut == "ERREUR"
    assert resultat.bloquant is True
