"""Rien n'est écrit hors de `.lintorn/` — et ce qui l'est ne se lit jamais à moitié."""

from __future__ import annotations

import os
import sys

import pytest

from lintorn import base, config
from lintorn.commandes import regles
from lintorn.outils import pytest as outil_pytest, tsc


def test_une_ecriture_ne_tronque_jamais_le_fichier_qu_un_lecteur_a_ouvert(tmp_path, monkeypatch):
    """Un lecteur (hook, éditeur, assistant IA) ne voit pas un fichier VIDE entre
    la troncature et l'écriture : l'ancien contenu reste lisible jusqu'au bout."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    fichier = tmp_path / ".lintorn" / "rapport.md"
    base.ecrire_sortie(fichier, "ancien")

    with fichier.open(encoding="utf-8") as lecteur:
        base.ecrire_sortie(fichier, "nouveau")
        assert lecteur.read() == "ancien"
    assert fichier.read_text(encoding="utf-8") == "nouveau"
    assert [p.name for p in fichier.parent.iterdir()] == ["rapport.md"], "un temporaire est reste"


@pytest.mark.skipif(os.name == "nt", reason="bits d'exécution POSIX")
def test_une_ecriture_garde_les_droits_du_fichier(tmp_path, monkeypatch):
    """Le hook réécrit reste exécutable : git ignore un hook qui ne l'est pas."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    hook = tmp_path / ".lintorn" / "hooks" / "pre-push"
    base.ecrire_sortie(hook, "a")
    hook.chmod(0o755)

    base.ecrire_sortie(hook, "b")

    assert hook.stat().st_mode & 0o777 == 0o755


def test_regles_sur_un_lintorn_qui_est_un_fichier_echoue_proprement(tmp_path, monkeypatch, capsys):
    """`.lintorn` posé comme fichier : un message et le code 1, pas un traceback."""
    (tmp_path / ".lintorn").write_text("je suis un fichier", encoding="utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "DOSSIER_LINTORN", tmp_path / ".lintorn")
    monkeypatch.setattr(config, "FICHIER_REGLES", tmp_path / ".lintorn" / "regles.toml")
    monkeypatch.setattr(regles, "esquisses_regles", lambda deja="": ["# [[regles]]", '# nom = "X"'])

    assert regles.esquisser_regles() == 1
    assert "Traceback" not in capsys.readouterr().out


def test_regles_illisible_est_annonce(tmp_path, monkeypatch, capsys):
    """Un `regles.toml` qui n'est pas de l'UTF-8 : refus annoncé, pas un traceback."""
    dossier = tmp_path / ".lintorn"
    dossier.mkdir()
    (dossier / "regles.toml").write_bytes(b"\xff\xfe\x00 pas de l'utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "DOSSIER_LINTORN", dossier)
    monkeypatch.setattr(config, "FICHIER_REGLES", dossier / "regles.toml")

    assert regles.esquisser_regles() == 1
    assert "illisible" in capsys.readouterr().out


def test_pytest_lance_par_lintorn_ne_laisse_aucun_cache_dans_le_projet(tmp_path, monkeypatch):
    """`.pytest_cache/` et `__pycache__/` sont des écritures DANS le projet audité."""
    projet = tmp_path / "projet"
    projet.mkdir()
    (projet / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(config, "PYTHON", sys.executable)
    monkeypatch.setattr(config, "PY_RACINE", projet)
    # Le bilan JUnit va dans `.lintorn/cache/` : sans ce dossier à part, il
    # s'écrivait dans le `.lintorn/` du dépôt qui lance ces tests.
    monkeypatch.setattr(config, "DOSSIER_LINTORN", tmp_path / ".lintorn")
    entree = outil_pytest.commande()

    resultat = base.lancer(entree["titre"], entree["cmd"], entree["cwd"])

    assert resultat.statut == "OK", resultat.resume
    assert sorted(p.name for p in projet.iterdir()) == ["test_x.py"]


def test_tsc_range_son_cache_dans_lintorn(tmp_path, monkeypatch):
    """`tsc --noEmit` pose un `.tsbuildinfo` à côté du tsconfig : on le détourne."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "DOSSIER_LINTORN", tmp_path / ".lintorn")

    cmd = tsc._cache_dans_lintorn("front/")

    assert cmd[:2] == ["--incremental", "--tsBuildInfoFile"]
    assert cmd[2] == str(tmp_path / ".lintorn" / "cache" / "tsc-front.tsbuildinfo")


@pytest.mark.skipif(os.name == "nt", reason="liens symboliques POSIX")
def test_tsc_ne_donne_pas_de_chemin_qui_mene_hors_du_projet(tmp_path, monkeypatch):
    """`.lintorn` lié vers l'extérieur : le cache n'y irait pas."""
    projet, dehors = tmp_path / "p", tmp_path / "dehors"
    projet.mkdir()
    dehors.mkdir()
    (projet / ".lintorn").symlink_to(dehors, target_is_directory=True)
    monkeypatch.setattr(config, "RACINE", projet)
    monkeypatch.setattr(config, "DOSSIER_LINTORN", projet / ".lintorn")

    assert tsc._cache_dans_lintorn("") == []
