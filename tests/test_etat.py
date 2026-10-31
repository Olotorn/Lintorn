"""`lintorn status` et `lintorn rapport` : dire où on en est, sans rien lancer ni écrire.

Par `cli.main`, comme l'utilisateur les tape.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from lintorn import cli, config

POSIX = pytest.mark.skipif(os.name == "nt", reason="depot git jetable en shell")


@pytest.fixture
def projet(tmp_path, monkeypatch):
    """Un dépôt git neuf, et Lintorn qui le regarde : rien de la machine ni du vrai dépôt."""
    vide = tmp_path.parent / f"{tmp_path.name}-gitconfig"
    vide.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(vide))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    lintorn = tmp_path / ".lintorn"
    for nom, valeur in {
            "RACINE": tmp_path, "SOUS_GIT": True, "SOMMET_GIT": tmp_path,
            "DOSSIER_LINTORN": lintorn, "HOOKS": lintorn / "hooks",
            "HOOKS_POUR_GIT": config.HOOKS_ATTENDU, "ETAT": lintorn / "etat.json",
            "RAPPORT": lintorn / "rapport.md", "FICHIER_REGLES": lintorn / "regles.toml",
            "COMMANDES": [], "CONTROLES_DISPONIBLES": [], "REGLES_MAISON": [],
            "HORS_PORTEE": [], "SOUCIS_CONFIG": [], "DOCS_IA": [], "PARCOURS_COUPE": False,
            "MEMOIRE_IA": None, "MEMOIRE_IA_ORIGINE": "aucun dossier memoire"}.items():
        monkeypatch.setattr(config, nom, valeur)
    return tmp_path


def _taper(monkeypatch, capsys, *mots) -> tuple[int, str]:
    monkeypatch.setattr("sys.argv", ["lintorn", *mots])
    code = cli.main()
    return code, capsys.readouterr().out


_ENTETE = ("# Le rapport de Lintorn\n\n> Généré le 27/10/2026 14:05 par `lintorn 0.7.0`, "
           "**hors push**.\n\n| Contrôle | Statut | Résumé |\n|---|---|---|\n"
           "| Ruff | [ !! ] | 2 alertes |\n| Doc | [ ?? ] | 1 doute |\n| Tests | [ OK ] | 3 |\n")


@POSIX
@pytest.mark.parametrize("mots", [["status"], ["--status"]])
def test_status_dit_ou_on_en_est_sans_rien_ecrire(projet, monkeypatch, capsys, mots):
    """Le hook, l'accord, la config, ce qui est contrôlé, le dernier lancement : sur un écran."""
    code, sortie = _taper(monkeypatch, capsys, *mots)

    assert code == 0
    for rubrique in ("Hook", "Confiance", "Configuration", "Controles", "Dernier lancement",
                     "Dernier push", "Audit complet"):
        assert rubrique in sortie, rubrique
    assert "lintorn hook " in sortie.split("A faire :")[1], "le hook manque : dire quoi taper"
    assert not (projet / ".lintorn").exists(), "status n'ecrit rien"


@POSIX
def test_status_lit_la_date_et_ce_qu_a_trouve_le_dernier_rapport(projet, monkeypatch, capsys):
    (projet / ".lintorn").mkdir()
    (projet / ".lintorn" / "rapport.md").write_text(_ENTETE, encoding="utf-8")

    _, sortie = _taper(monkeypatch, capsys, "status")

    ligne = next(ligne for ligne in sortie.splitlines() if ligne.startswith("Dernier lancement"))
    assert "27/10/2026 14:05 (lintorn 0.7.0) : 1 alerte(s), 1 a verifier" in ligne


@POSIX
def test_un_rapport_versionne_ne_vient_pas_de_cette_machine(projet, monkeypatch, capsys):
    """Un dépôt piégé commite un rapport tout vert daté d'aujourd'hui : status le croyait,
    et `lintorn rapport` l'ouvrait dans le navigateur."""
    (projet / ".lintorn").mkdir()
    (projet / ".lintorn" / "rapport.md").write_text(_ENTETE, encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".lintorn/rapport.md"], cwd=projet, check=True)
    ouverts = []
    monkeypatch.setattr("webbrowser.open", lambda adresse: ouverts.append(adresse) or True)

    _, statut = _taper(monkeypatch, capsys, "status")
    code, rapport = _taper(monkeypatch, capsys, "rapport")

    assert "est versionne : il ne vient pas de cette machine" in statut
    assert code == 1 and "n'est pas ouvert" in rapport
    assert ouverts == []


@POSIX
@pytest.mark.parametrize("commande, fichier", [("rapport", "rapport"),
                                               ("rapport-push", "rapport-push")])
def test_lintorn_rapport_ouvre_la_page_du_dernier_rapport(projet, monkeypatch, capsys,
                                                          commande, fichier):
    (projet / ".lintorn").mkdir()
    (projet / ".lintorn" / f"{fichier}.md").write_text(_ENTETE, encoding="utf-8")
    (projet / ".lintorn" / f"{fichier}.html").write_text("<p>page</p>", encoding="utf-8")
    ouverts = []
    monkeypatch.setattr("webbrowser.open", lambda adresse: ouverts.append(adresse) or True)

    code, sortie = _taper(monkeypatch, capsys, commande)

    assert code == 0
    assert ouverts == [(projet / ".lintorn" / f"{fichier}.html").resolve().as_uri()]
    assert f".lintorn/{fichier}.html" in sortie


@POSIX
def test_sans_rapport_ni_navigateur_lintorn_rapport_le_dit(projet, monkeypatch, capsys):
    monkeypatch.setattr("webbrowser.open", lambda adresse: False)

    code, absent = _taper(monkeypatch, capsys, "rapport")
    (projet / ".lintorn").mkdir()
    (projet / ".lintorn" / "rapport.md").write_text(_ENTETE, encoding="utf-8")
    code_sans, sans_navigateur = _taper(monkeypatch, capsys, "rapport")

    assert code == 1 and "lance `lintorn`" in absent
    assert code_sans == 0 and "ouvre ce fichier toi-meme" in sans_navigateur
    assert ".lintorn/rapport.md" in sans_navigateur, "a defaut de page web, le Markdown"
