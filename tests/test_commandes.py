"""Les noms courts (`lintorn rapide`) : plus simples à taper, et ils ne cassent rien."""

import pytest

from lintorn import cli, config, noyau
from lintorn.commandes import aide, outils, securite


def test_un_nom_court_lance_la_commande(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["lintorn", "version"])
    assert cli.main() == 0
    assert "lintorn" in capsys.readouterr().out


def test_la_forme_avec_tirets_marche_toujours(monkeypatch, capsys):
    """Les hooks déjà installés tapent `--rapide` : cette forme doit survivre."""
    monkeypatch.setattr("sys.argv", ["lintorn", "--version"])
    assert cli.main() == 0


def test_seul_le_premier_mot_est_traduit():
    """Un fichier poussé nommé `rapide` reste un fichier."""
    assert cli._traduire_nom_court(["--fichiers", "rapide"]) == ["--fichiers", "rapide"]
    assert cli._traduire_nom_court(["rapide", "--fichiers", "a.py"]) == [
        "--rapide", "--fichiers", "a.py"]


@pytest.mark.parametrize("nom", sorted(cli.NOMS_COURTS))
def test_chaque_nom_court_mene_a_une_option_qui_existe(nom):
    """`"pip-audit": ["--pip-audit"]` menait vers une option inconnue : Lintorn
    aurait refusé la commande même qu'il annonce dans son aide."""
    assert cli._arguments_inconnus(cli.NOMS_COURTS[nom]) == []


def test_chaque_nom_court_est_dans_l_aide():
    for nom in cli.NOMS_COURTS:
        if nom not in ("aide",):   # doublon français de `help`
            assert f"lintorn {nom}" in aide.AIDE, f"`lintorn {nom}` absent de --help"


def test_une_faute_de_frappe_propose_le_nom_court(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["lintorn", "rapdie"])
    assert cli.main() == 2
    assert "rapide" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────────────────────
# Une faute de frappe : proposer, JAMAIS deviner
# ─────────────────────────────────────────────────────────────────────────────
def _taper(monkeypatch, capsys, *mots):
    monkeypatch.setattr("sys.argv", ["lintorn", *mots])
    monkeypatch.setattr(noyau, "executer", lambda **_: pytest.fail("un audit a ete lance"))
    code = cli.main()
    return code, capsys.readouterr().out


def test_une_commande_mal_tapee_propose_la_ligne_a_copier(monkeypatch, capsys):
    code, sortie = _taper(monkeypatch, capsys, "rapdie")

    assert code == 2
    assert "Commande inconnue : rapdie" in sortie
    assert "Voulais-tu dire :  lintorn rapide" in sortie


def test_l_ancienne_forme_mal_tapee_propose_le_nom_court(monkeypatch, capsys):
    _, sortie = _taper(monkeypatch, capsys, "--rapdie")

    assert "Option inconnue : --rapdie" in sortie
    assert "lintorn rapide" in sortie


def test_une_precision_mal_tapee_n_est_pas_proposee_comme_commande(monkeypatch, capsys):
    """`lintorn --force` seul ne ferait rien : on propose `--force`, pas une commande."""
    _, sortie = _taper(monkeypatch, capsys, "rapide", "--forse")

    assert "Voulais-tu dire :  --force" in sortie
    assert "lintorn --force" not in sortie


def test_sans_rien_d_approchant_la_liste_courte_des_commandes(monkeypatch, capsys):
    code, sortie = _taper(monkeypatch, capsys, "blabla")

    assert code == 2
    assert "Voulais-tu dire" not in sortie
    for commande in ("lintorn init", "lintorn hook", "lintorn help"):
        assert commande in sortie
    assert "d'activer ses audits" in sortie, "une description coupee en deux ne veut rien dire"
    assert "USAGE" not in sortie, "pas l'aide entiere : elle noierait le message d'erreur"


def test_la_commande_devinee_n_est_jamais_lancee(monkeypatch, capsys):
    """Une faute sur `pip-audit --appliquer` n'installe rien : on propose, c'est tout."""
    monkeypatch.setattr(securite, "maj_securite",
                        lambda **_: pytest.fail("la commande devinee a ete lancee"))
    code, sortie = _taper(monkeypatch, capsys, "pip-audti", "--appliquer")

    assert code == 2
    assert "lintorn pip-audit" in sortie


def test_lintorn_outils_montre_le_venv_sans_le_chemin_de_la_machine(tmp_path, monkeypatch, capsys):
    """Le chemin complet portait le nom de l'utilisateur : il finissait dans les
    captures qu'on partage. Relatif au projet, `.venv/bin/python` suffit."""
    venv = tmp_path / ".venv"
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "VENV_PROJET", venv)
    monkeypatch.setattr(config, "PYTHON", str(venv / "bin" / "python"))
    monkeypatch.setattr(config, "REQUIREMENTS", None)
    monkeypatch.setattr(outils, "_oui", lambda _question: False)

    outils._installer_pip([{"pip": "vulture", "role": "code mort"}], sans_demander=False)

    affiche = capsys.readouterr().out
    assert "(.venv/bin/python)" in affiche
    assert str(tmp_path) not in affiche
