"""Ce qu'un dépôt PIÉGÉ ne doit jamais obtenir de Lintorn.

Promesse fondatrice : le premier `lintorn`, sans aucun accord, ne fait aucun
dégât. On la met à l'épreuve en fabriquant les pièges eux-mêmes.
"""

from __future__ import annotations

import subprocess

import pytest

from lintorn import confiance, config, noyau
from lintorn.commandes import outils, securite


def _depot(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "x@x"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=tmp_path, check=True)


def _committer(tmp_path, *chemins):
    subprocess.run(["git", "add", "-f", *chemins], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "piege"], cwd=tmp_path, check=True)


def _piege_executable(chemin, temoin):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(f'#!/bin/sh\necho execute >> "{temoin}"\n', encoding="utf-8")
    chemin.chmod(0o755)


@pytest.mark.skipif(subprocess.os.name == "nt", reason="faux binaire en script shell")
def test_un_python_de_venv_commite_n_est_jamais_lance(tmp_path, monkeypatch):
    """Un dépôt piégé commite `.venv/bin/python` : lancé, il exécuterait le
    code de l'attaquant au premier `lintorn`, sans aucun accord."""
    _depot(tmp_path)
    temoin = tmp_path / "temoin"
    faux = tmp_path / ".venv" / "bin" / "python"
    _piege_executable(faux, temoin)
    _committer(tmp_path, ".venv/bin/python")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "SOUS_GIT", True)
    monkeypatch.setattr(config, "COMMANDES", [{
        "cle": "ruff", "titre": "Ruff (lint Python)", "cmd": [str(faux), "-m", "ruff"],
        "cwd": tmp_path, "bloquant": True, "traduction": None, "lent": False}])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {})

    [resultat] = noyau.executer()

    assert not temoin.exists(), "un executable commite a ete lance"
    assert resultat.statut == "INDISPONIBLE"
    assert "suivi par git" in resultat.resume


@pytest.mark.skipif(subprocess.os.name == "nt", reason="faux binaire en script shell")
def test_un_tsc_commite_n_est_jamais_lance(tmp_path, monkeypatch):
    """Même piège par `node_modules/.bin/tsc`, que le contrôle TypeScript lance."""
    _depot(tmp_path)
    temoin = tmp_path / "temoin"
    faux = tmp_path / "node_modules" / ".bin" / "tsc"
    _piege_executable(faux, temoin)
    _committer(tmp_path, "node_modules/.bin/tsc")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "SOUS_GIT", True)
    monkeypatch.setattr(config, "COMMANDES", [{
        "cle": "typescript", "titre": "TypeScript (tsc --noEmit)", "cmd": [str(faux), "--noEmit"],
        "cwd": tmp_path, "bloquant": True, "traduction": None, "lent": False}])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {})

    [resultat] = noyau.executer()

    assert not temoin.exists(), "un tsc commite a ete lance"
    assert resultat.statut == "INDISPONIBLE"


@pytest.mark.skipif(subprocess.os.name == "nt", reason="faux binaire en script shell")
def test_un_vrai_venv_gitignore_tourne_toujours(tmp_path, monkeypatch):
    """Le garde-fou ne doit PAS toucher au cas normal : un venv que git ignore
    (le seul vrai venv possible) reste lancé."""
    _depot(tmp_path)
    (tmp_path / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _committer(tmp_path, ".gitignore")
    temoin = tmp_path / "temoin"
    vrai = tmp_path / ".venv" / "bin" / "python"   # présent, mais gitignoré
    _piege_executable(vrai, temoin)
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "SOUS_GIT", True)

    assert config.suivi_par_git(vrai) is False, "un venv gitignore n'est pas suivi"
    assert not noyau._executable_commite(
        {"cmd": [str(vrai)]}), "un venv gitignore ne doit pas etre refuse"


def _projet_python(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "BACKEND", None)
    monkeypatch.setattr(config, "PY_RACINE", tmp_path)
    lance = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, *_, **__: lance.append(cmd))
    return lance


def test_pip_audit_sans_venv_du_projet_ne_lance_rien(tmp_path, monkeypatch, capsys):
    """Sans venv du projet, `config.PYTHON` est celui de Lintorn : `lintorn pip-audit
    --appliquer` auditait PUIS installait dans l'environnement de Lintorn, en
    annonçant « Tout est OK » pour le projet."""
    lance = _projet_python(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "VENV_PROJET", None)

    assert securite.maj_securite(appliquer=True) == 1

    assert lance == [], "un pip-audit est parti sans venv du projet"
    assert "aucun venv du projet" in capsys.readouterr().out


def test_pip_audit_sans_accord_ne_lance_rien(tmp_path, monkeypatch, capsys):
    """Commande explicite ou non, ce qui tourne dans un projet inconnu demande l'accord."""
    lance = _projet_python(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "VENV_PROJET", tmp_path / ".venv")
    monkeypatch.delenv(confiance.VARIABLE_CI)
    monkeypatch.setattr(confiance, "terminal", lambda: False)

    assert securite.maj_securite(appliquer=False) == 1

    assert lance == [], "un pip-audit est parti sans accord"
    assert "aucun terminal" in capsys.readouterr().out


def test_outils_sans_venv_du_projet_ne_sonde_pas_l_environnement_de_lintorn(tmp_path, monkeypatch):
    """Sans venv du projet, `python -c "import ruff"` interrogeait Lintorn lui-même :
    le tableau annonçait « installe » pour un projet qui n'a aucun environnement."""
    lance = _projet_python(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "VENV_PROJET", None)

    assert outils._importable("ruff") is False

    assert lance == []


def test_outils_sans_accord_ne_lance_pas_le_python_du_projet(tmp_path, monkeypatch, capsys):
    """`lintorn outils` sondait le venv (donc lançait son python) avant toute question."""
    lance = _projet_python(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "VENV_PROJET", tmp_path / ".venv")
    monkeypatch.delenv(confiance.VARIABLE_CI)
    monkeypatch.setattr(confiance, "terminal", lambda: False)

    assert outils.installer_outils() == 1

    assert lance == [], "le python du projet a ete lance sans accord"
    assert "aucun terminal" in capsys.readouterr().out


@pytest.mark.skipif(subprocess.os.name == "nt", reason="faux binaire en script shell")
def test_outils_refuse_un_python_de_venv_commite(tmp_path, monkeypatch, capsys):
    """Le python commité d'un dépôt piégé n'est pas plus lancé par `lintorn outils` que par l'audit."""
    _depot(tmp_path)
    temoin = tmp_path / "temoin"
    faux = tmp_path / ".venv" / "bin" / "python"
    _piege_executable(faux, temoin)
    _committer(tmp_path, ".venv/bin/python")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "SOUS_GIT", True)
    monkeypatch.setattr(config, "PY_RACINE", tmp_path)
    monkeypatch.setattr(config, "VENV_PROJET", tmp_path / ".venv")
    monkeypatch.setattr(config, "PYTHON", faux)

    assert outils.installer_outils() == 1

    assert not temoin.exists(), "un python commite a ete lance par `lintorn outils`"
    assert "suivi par git" in capsys.readouterr().out
