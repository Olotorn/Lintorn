"""Lintorn ne LANCE rien dans un projet sans l'accord de son utilisateur.

Promesse fondatrice : le premier lancement ne fait aucun dégât. Chaque test
passe par le circuit complet (`noyau.executer`, `cli.main`) avec un faux outil
qui note dans un témoin quand il a été exécuté.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from lintorn import cli, confiance, config, noyau

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="faux outils en script shell")


@pytest.fixture(autouse=True)
def _sans_accord_global(monkeypatch):
    monkeypatch.delenv(confiance.VARIABLE_CI, raising=False)


def _outil(dossier, nom, temoin):
    chemin = dossier / nom
    chemin.write_text(f'#!/bin/sh\necho "{nom}" >> "{temoin}"\n', encoding="utf-8")
    chemin.chmod(0o755)
    return chemin


def _entree(chemin, cle=None, **en_plus):
    return {"cle": cle or chemin.name, "titre": f"Outil {chemin.name}", "cmd": [str(chemin)],
            "cwd": chemin.parent, "bloquant": False, "traduction": None, "lent": False, **en_plus}


@pytest.fixture
def projet(tmp_path, monkeypatch):
    racine = tmp_path / "projet"
    racine.mkdir()
    monkeypatch.setattr(config, "RACINE", racine)
    monkeypatch.setattr(config, "SOUS_GIT", False)
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {})
    # Un venv du projet : sans lui, un outil lancé par `sys.executable` serait
    # refusé avant même la question, et le test dépendrait de la machine.
    monkeypatch.setattr(config, "VENV_PROJET", racine / ".venv")
    return racine


def _terminal(monkeypatch, *reponses):
    """Un utilisateur devant son terminal. Rend la liste des questions posées."""
    questions = []
    suite = iter(reponses)
    monkeypatch.setattr(confiance, "terminal", lambda: True)

    def repondre(question=""):
        questions.append(question)
        return next(suite)

    monkeypatch.setattr("builtins.input", repondre)
    return questions


def test_sans_terminal_rien_ne_part_et_le_refus_est_annonce(projet, monkeypatch):
    temoin = projet / "temoin"
    monkeypatch.setattr(config, "COMMANDES", [_entree(_outil(projet, "ruff", temoin))])

    [resultat] = noyau.executer()

    assert not temoin.exists(), "un outil est parti sans accord"
    assert resultat.statut == "INDISPONIBLE"
    assert "aucun terminal" in resultat.resume
    assert "lintorn confiance" in resultat.resume


@pytest.mark.parametrize("reponse", ["", "n", "N", "non", "yy", "ye", "oui-mais-non", " "])
def test_tout_ce_qui_n_est_pas_un_oui_franc_refuse(projet, monkeypatch, reponse):
    """`[o/N]` : le non est le défaut, une faute de frappe ne peut pas accorder."""
    temoin = projet / "temoin"
    monkeypatch.setattr(config, "COMMANDES", [_entree(_outil(projet, "ruff", temoin))])
    _terminal(monkeypatch, reponse)

    [resultat] = noyau.executer()

    assert not temoin.exists()
    assert resultat.statut == "INDISPONIBLE"
    assert "accord refuse" in resultat.resume


@pytest.mark.parametrize("reponse", ["y", "Y", "yes", "o", "oui", " OUI "])
def test_un_oui_franc_lance_et_ne_se_redemande_plus(projet, monkeypatch, reponse):
    temoin = projet / "temoin"
    monkeypatch.setattr(config, "COMMANDES", [_entree(_outil(projet, "ruff", temoin))])
    questions = _terminal(monkeypatch, reponse)

    [premier] = noyau.executer()
    [second] = noyau.executer()

    assert premier.statut == second.statut == "OK"
    assert temoin.read_text().splitlines() == ["ruff", "ruff"]
    assert len(questions) == 1, "l'accord doit etre note : une question par projet"


def test_un_refus_ne_s_enregistre_pas_mais_ne_coute_qu_une_question_par_lancement(
        projet, monkeypatch):
    monkeypatch.setattr(config, "COMMANDES", [_entree(_outil(projet, "ruff", projet / "t"))])
    questions = _terminal(monkeypatch, "n", "y")

    noyau.executer()
    [resultat] = noyau.executer()

    assert len(questions) == 2
    assert resultat.statut == "OK"


def test_une_seule_question_pour_tout_ce_qui_est_nouveau(projet, monkeypatch, capsys):
    temoin = projet / "temoin"
    monkeypatch.setattr(config, "COMMANDES", [
        _entree(_outil(projet, "ruff", temoin)), _entree(_outil(projet, "tsc", temoin))])
    questions = _terminal(monkeypatch, "y")

    noyau.executer()

    assert len(questions) == 1
    sortie = capsys.readouterr().out
    assert "Outil ruff" in sortie and "Outil tsc" in sortie


def test_une_chose_nouvelle_ne_redemande_que_cette_chose(projet, monkeypatch, capsys):
    temoin = projet / "temoin"
    ruff = _entree(_outil(projet, "ruff", temoin))
    monkeypatch.setattr(config, "COMMANDES", [ruff])
    _terminal(monkeypatch, "y")
    noyau.executer()
    capsys.readouterr()

    pytest_ = _entree(_outil(projet, "pytest", temoin))
    monkeypatch.setattr(config, "COMMANDES", [ruff, pytest_])
    questions = _terminal(monkeypatch, "y")
    resultats = noyau.executer()

    assert len(questions) == 1
    sortie = capsys.readouterr().out
    assert "Outil pytest" in sortie
    assert "Outil ruff" not in sortie, "ruff etait deja accorde : pas a redemander"
    assert [r.statut for r in resultats] == ["OK", "OK"]


def test_ce_qui_est_deja_accorde_tourne_meme_quand_le_nouveau_est_refuse(projet, monkeypatch):
    temoin = projet / "temoin"
    ruff = _entree(_outil(projet, "ruff", temoin))
    monkeypatch.setattr(config, "COMMANDES", [ruff])
    _terminal(monkeypatch, "y")
    noyau.executer()
    temoin.unlink()

    autre = _entree(_outil(projet, "pytest", temoin))
    monkeypatch.setattr(config, "COMMANDES", [ruff, autre])
    _terminal(monkeypatch, "n")
    accorde, refuse = noyau.executer()

    assert accorde.statut == "OK"
    assert refuse.statut == "INDISPONIBLE"
    assert temoin.read_text().splitlines() == ["ruff"]


def test_un_outil_du_projet_dont_le_contenu_change_est_redemande(projet, monkeypatch):
    """Le nom ne bouge pas, le code oui : c'est une chose nouvelle."""
    temoin = projet / "temoin"
    outil = _outil(projet, "ruff", temoin)
    monkeypatch.setattr(config, "COMMANDES", [_entree(outil)])
    _terminal(monkeypatch, "y")
    noyau.executer()
    outil.write_text(f'#!/bin/sh\necho "AUTRE" >> "{temoin}"\n', encoding="utf-8")
    questions = _terminal(monkeypatch, "n")

    [resultat] = noyau.executer()

    assert len(questions) == 1
    assert resultat.statut == "INDISPONIBLE"
    assert temoin.read_text().splitlines() == ["ruff"]


def test_une_commande_du_projet_reecrite_est_redemandee(projet, monkeypatch):
    temoin = projet / "temoin"
    outil = _outil(projet, "mon-script", temoin)

    def commande(*arguments):
        return _entree(outil, cle="maison", du_projet=True) | {"cmd": [str(outil), *arguments]}

    monkeypatch.setattr(config, "COMMANDES", [commande("--gentil")])
    _terminal(monkeypatch, "y")
    noyau.executer()
    monkeypatch.setattr(config, "COMMANDES", [commande("--gentil")])
    assert len(_terminal(monkeypatch)) == 0
    noyau.executer()

    monkeypatch.setattr(config, "COMMANDES", [commande("--autre-chose")])
    questions = _terminal(monkeypatch, "n")
    [resultat] = noyau.executer()

    assert len(questions) == 1
    assert resultat.statut == "INDISPONIBLE"


def test_l_accord_ne_se_lit_jamais_dans_le_depot(projet, monkeypatch):
    """Le dépôt piégé livre lui-même son « accord » : il ne vaut rien."""
    temoin = projet / "temoin"
    outil = _outil(projet, "ruff", temoin)
    entree = _entree(outil)
    monkeypatch.setattr(config, "COMMANDES", [entree])
    (projet / ".lintorn").mkdir()
    faux = json.dumps({str(projet.resolve()): [confiance.identite(entree)]})
    for nom in (".lintorn/confiance.json", "confiance.json"):
        (projet / nom).write_text(faux, encoding="utf-8")

    [resultat] = noyau.executer()

    assert not temoin.exists()
    assert resultat.statut == "INDISPONIBLE"
    assert projet not in confiance.fichier().parents


def test_le_fichier_d_accord_illisible_se_traite_comme_aucun_accord(projet, monkeypatch):
    temoin = projet / "temoin"
    monkeypatch.setattr(config, "COMMANDES", [_entree(_outil(projet, "ruff", temoin))])
    confiance.fichier().parent.mkdir(parents=True)
    confiance.fichier().write_text("{pas du json", encoding="utf-8")

    [resultat] = noyau.executer()

    assert resultat.statut == "INDISPONIBLE"
    assert not temoin.exists()


def test_la_variable_d_environnement_accorde_pour_les_postes_maitrises(projet, monkeypatch):
    temoin = projet / "temoin"
    monkeypatch.setattr(config, "COMMANDES", [_entree(_outil(projet, "ruff", temoin))])
    monkeypatch.setenv(confiance.VARIABLE_CI, "oui")

    [resultat] = noyau.executer()

    assert resultat.statut == "OK"


def test_le_mode_rapide_ne_demande_pas_pour_ce_qu_il_saute(projet, monkeypatch):
    temoin = projet / "temoin"
    monkeypatch.setattr(config, "COMMANDES", [_entree(_outil(projet, "pip-audit", temoin), lent=True)])
    questions = _terminal(monkeypatch)

    [resultat] = noyau.executer(rapide=True)

    assert questions == []
    assert "NON EXECUTE" in resultat.resume


def test_lintorn_confiance_sans_terminal_n_accorde_rien(projet, monkeypatch, capsys):
    temoin = projet / "temoin"
    monkeypatch.setattr(config, "COMMANDES", [_entree(_outil(projet, "ruff", temoin))])
    monkeypatch.setattr(sys, "argv", ["lintorn", "confiance"])

    assert cli.main() == 1

    assert "Aucun terminal" in capsys.readouterr().out
    assert noyau.executer()[0].statut == "INDISPONIBLE"


def test_lintorn_confiance_oui_accorde_pour_les_lancements_suivants(projet, monkeypatch):
    """Le hook et la CI n'ont personne à qui demander : c'est leur chemin."""
    temoin = projet / "temoin"
    monkeypatch.setattr(config, "COMMANDES", [_entree(_outil(projet, "ruff", temoin))])
    monkeypatch.setattr(sys, "argv", ["lintorn", "confiance", "--oui"])

    assert cli.main() == 0

    assert noyau.executer()[0].statut == "OK"


def test_lintorn_confiance_pose_la_question_au_terminal(projet, monkeypatch):
    monkeypatch.setattr(config, "COMMANDES", [_entree(_outil(projet, "ruff", projet / "t"))])
    monkeypatch.setattr(sys, "argv", ["lintorn", "confiance"])
    _terminal(monkeypatch, "")

    assert cli.main() == 1
    assert confiance.nouveaux(config.COMMANDES), "un non ne doit rien accorder"

    _terminal(monkeypatch, "y")
    assert cli.main() == 0
    assert not confiance.nouveaux(config.COMMANDES)
    assert noyau.executer()[0].statut == "OK"


def test_lintorn_confiance_dit_quand_il_n_y_a_rien_a_accorder(projet, monkeypatch, capsys):
    monkeypatch.setattr(config, "COMMANDES", [])
    monkeypatch.setattr(sys, "argv", ["lintorn", "confiance", "--oui"])

    assert cli.main() == 0
    assert "Rien a accorder" in capsys.readouterr().out


def test_un_git_piege_n_execute_pas_son_fsmonitor(tmp_path, monkeypatch):
    """`.git/config` fait partie d'une archive : `core.fsmonitor` y lance un script
    au premier `git ls-files`, avant même la première question."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    temoin = tmp_path / "temoin"
    piege = _outil(tmp_path, "piege", temoin)
    subprocess.run(["git", "config", "core.fsmonitor", str(piege)], cwd=tmp_path, check=True)
    monkeypatch.setattr(config, "RACINE", tmp_path)

    config.git("ls-files", "--cached", "--others", "--exclude-standard")
    config.git("ls-files", "--error-unmatch", "--", "rien")

    assert not temoin.exists(), "git a execute le fsmonitor du depot"


def _script_du_projet(projet, temoin, contenu="gentil"):
    """`python3 outils/todo.py` : le programme est python3, le vrai code est le script."""
    script = projet / "outils" / "todo.py"
    script.parent.mkdir(exist_ok=True)
    script.write_text(f"open({str(temoin)!r}, 'a').write({contenu!r} + '\\n')\n", encoding="utf-8")
    return {"cle": "todo", "titre": "TODO restants", "cmd": [sys.executable, "outils/todo.py"],
            "cwd": projet, "bloquant": False, "traduction": None, "lent": False, "du_projet": True}


def test_un_script_du_projet_reecrit_apres_l_accord_est_redemande(projet, monkeypatch, capsys):
    """Vu en vrai : `todo.py` modifié dans vim, l'outil tournait sans rien redemander."""
    temoin = projet / "temoin"
    monkeypatch.setattr(config, "COMMANDES", [_script_du_projet(projet, temoin)])
    _terminal(monkeypatch, "y")
    noyau.executer()
    monkeypatch.setattr(config, "COMMANDES", [_script_du_projet(projet, temoin, "PIEGE")])
    questions = _terminal(monkeypatch, "n")
    capsys.readouterr()

    [resultat] = noyau.executer()

    assert len(questions) == 1, "le script a change : la question doit revenir"
    assert "modifie depuis ton accord : outils/todo.py" in capsys.readouterr().out
    assert resultat.statut == "INDISPONIBLE"
    assert temoin.read_text().splitlines() == ["gentil"], "le script reecrit a tourne"


def test_sans_terminal_le_refus_dit_quel_script_a_change(projet, monkeypatch):
    """Dans le hook, personne pour répondre : le refus doit au moins dire pourquoi."""
    temoin = projet / "temoin"
    monkeypatch.setattr(config, "COMMANDES", [_script_du_projet(projet, temoin)])
    _terminal(monkeypatch, "y")
    noyau.executer()
    monkeypatch.setattr(config, "COMMANDES", [_script_du_projet(projet, temoin, "PIEGE")])
    monkeypatch.setattr(confiance, "terminal", lambda: False)

    [resultat] = noyau.executer()

    assert resultat.statut == "INDISPONIBLE"
    assert "outils/todo.py modifie depuis ton accord" in resultat.resume
    assert temoin.read_text().splitlines() == ["gentil"]


def test_un_script_inchange_ne_redemande_rien(projet, monkeypatch):
    temoin = projet / "temoin"
    monkeypatch.setattr(config, "COMMANDES", [_script_du_projet(projet, temoin)])
    _terminal(monkeypatch, "y")
    noyau.executer()

    assert len(_terminal(monkeypatch)) == 0
    noyau.executer()
    assert temoin.read_text().splitlines() == ["gentil", "gentil"]
