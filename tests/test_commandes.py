"""Les noms courts (`lintorn rapide`) : plus simples à taper, et ils ne cassent rien."""

import subprocess
import sys
from pathlib import Path

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


@pytest.mark.parametrize("precision, attendu", [
    ("--force", "lintorn init, lintorn hook"), ("--oui", "lintorn confiance, lintorn outils"),
    ("--appliquer", "lintorn pip-audit")])
def test_une_precision_seule_ne_lance_rien(monkeypatch, capsys, precision, attendu):
    """`lintorn --force` lançait un audit complet sans rien dire de l'option tapée."""
    monkeypatch.setattr(cli.commandes.audit, "lancer",
                        lambda *_: pytest.fail("un audit a ete lance"))

    code, sortie = _taper(monkeypatch, capsys, precision)

    assert code == 2
    assert f"{precision} ne va qu'avec : {attendu}" in sortie


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


# ─────────────────────────────────────────────────────────────────────────────
# Hors d'un projet : répondre tout de suite, ne pas parcourir le disque
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("commande", ["version", "help", "guide"])
def test_version_aide_et_guide_ne_lisent_pas_le_projet(tmp_path, commande):
    """`cli` importait `config` d'office, qui parcourt tout le dossier courant hors
    dépôt : `lintorn version` prenait 16 s depuis `/usr`, et plantait depuis `/`
    sous Python 3.11 (`PermissionError` sur `/proc`)."""
    script = ("import sys\nfrom lintorn import cli\n"
              f"sys.argv = ['lintorn', {commande!r}]\ncode = cli.main()\n"
              "print('CONFIG' if 'lintorn.config' in sys.modules else 'SANS CONFIG', code)")
    sortie = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, capture_output=True,
                            text=True, timeout=60, check=False)

    assert sortie.stdout.splitlines()[-1] == "SANS CONFIG 0", sortie.stdout + sortie.stderr


def test_hors_depot_le_parcours_s_arrete_a_la_limite(tmp_path, monkeypatch):
    for numero in range(12):
        (tmp_path / f"f{numero}.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "SOUS_GIT", False)
    monkeypatch.setattr(config, "LIMITE_HORS_GIT", 5)

    assert len(config._fichiers_du_projet()) == 5


def test_un_dossier_trop_gros_pour_un_projet_n_est_pas_audite(monkeypatch, capsys):
    """Depuis le dossier personnel, l'audit durait plusieurs minutes, sur une moitié de dossier."""
    monkeypatch.setattr(config, "PARCOURS_COUPE", True)

    code, sortie = _taper(monkeypatch, capsys, "rapide")

    assert code == 2
    assert "n'est pas un depot git" in sortie
    assert "Rien n'a ete lance" in sortie
    monkeypatch.setattr("sys.argv", ["lintorn", "version"])
    assert cli.main() == 0, "la version, elle, n'a besoin de rien savoir du projet"


def test_aucun_texte_ne_donne_un_ancien_nom_de_commande():
    """Le rapport conseillait encore `--maj-securite --appliquer`. Les anciennes
    formes marchent toujours, mais seule la table de `cli.py` doit les citer."""
    anciens = ("--maj-securite", "--installer-hook", "--installer-outils", "--esquisser-regles")
    paquet = Path(cli.__file__).parent
    fautifs = [f"{fichier.relative_to(paquet)} : {ancien}"
               for fichier in sorted(paquet.rglob("*")) if fichier.is_file()
               and fichier.name != "cli.py" and fichier.suffix != ".pyc"
               for ancien in anciens if ancien in fichier.read_text(encoding="utf-8")]

    assert not fautifs



def _outils_d_un_projet_rust(tmp_path, monkeypatch, controles):
    """Un projet Rust avec osv-scanner installé : seul OSV s'y applique."""
    (tmp_path / "Cargo.lock").write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "PY_RACINE", None)
    monkeypatch.setattr(config, "BACKEND", None)
    monkeypatch.setattr(config, "FRONTEND", None)
    monkeypatch.setattr(config, "PROJETS_TS", [])
    monkeypatch.setattr(config, "ECOSYSTEMES_OSV", {"Rust": [tmp_path / "Cargo.lock"]})
    monkeypatch.setattr(config, "PROJET", {"controles": controles})
    monkeypatch.setattr(outils.shutil, "which", lambda nom: f"/bin/{nom}")
    monkeypatch.setattr(outils, "_oui", lambda question: False)


def test_lintorn_outils_dit_comment_lancer_ce_qui_est_actif(tmp_path, monkeypatch, capsys):
    """Activer ne lance rien : sans la commande à taper, on croyait que seul
    pip-audit, qui a la sienne, pouvait tourner."""
    _outils_d_un_projet_rust(tmp_path, monkeypatch, {"failles_osv": True})

    assert outils.installer_outils() == 0

    assert "Pour les lancer : lintorn (l'audit complet)" in capsys.readouterr().out


def test_lintorn_outils_ne_dit_pas_comment_lancer_ce_qui_est_inactif(tmp_path, monkeypatch, capsys):
    _outils_d_un_projet_rust(tmp_path, monkeypatch, {})

    outils.installer_outils()

    assert "Pour les lancer" not in capsys.readouterr().out
