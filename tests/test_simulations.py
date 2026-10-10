"""Ce que les simulations d'attaque ont trouvé : un test par cassure."""

import json
import os
import re
import signal
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest
from aides import _ILLISIBLE_POSSIBLE, _config_de, _config_doc_ia, _config_lue, _regle, _sortie_npm, _sortie_osv

import lintorn.commandes
import lintorn.controles
import lintorn.outils
import lintorn.rapport
from lintorn import base, config, noyau
from lintorn.base import Resultat

# ─────────────────────────────────────────────────────────────────────────────
# La simulation d'attaque du 2026-09-22 — un test par cassure
# ─────────────────────────────────────────────────────────────────────────────


def test_c1_un_refus_ecrit_en_texte_n_est_pas_un_accord(tmp_path):
    """`tests = "false"` — un refus, pour qui l'écrit — ACTIVAIT les tests :
    une chaîne non vide est vraie pour Python. Le code du projet tournait."""
    lu = _config_de(tmp_path, {
        "pyproject.toml": '[project]\nname = "x"\n',
        "app.py": "",
        ".lintorn/config.toml": '[controles]\ntests = "false"\nfailles = "non"\n',
    })

    assert "tests" not in lu["cles"], "un refus ecrit en texte a execute le code du projet"
    assert "failles" not in lu["cles"], "un refus ecrit en texte est sorti sur le reseau"
    assert any("seuls true et false" in souci for souci in lu["soucis"])


def test_c2_un_rapport_en_lien_symbolique_n_ecrase_pas_sa_cible(tmp_path, monkeypatch):
    """Un dépôt peut committer `.lintorn/rapport.md` en lien vers n'importe quel
    fichier : Lintorn l'écrasait au premier audit."""
    victime = tmp_path / "ailleurs" / "victime.txt"
    victime.parent.mkdir()
    victime.write_text("intact", encoding="utf-8")
    projet = tmp_path / "projet"
    (projet / ".lintorn").mkdir(parents=True)
    (projet / ".lintorn" / "rapport.md").symlink_to(victime)
    monkeypatch.setattr(config, "RACINE", projet)
    monkeypatch.setattr(config, "RAPPORT", projet / ".lintorn" / "rapport.md")

    assert lintorn.rapport.markdown.ecrire_rapport([Resultat("x", "OK", "rien")]) is True

    assert victime.read_text(encoding="utf-8") == "intact"
    assert not (projet / ".lintorn" / "rapport.md").is_symlink()


def test_c2_un_dossier_lintorn_qui_mene_ailleurs_est_refuse(tmp_path, monkeypatch):
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    projet = tmp_path / "projet"
    projet.mkdir()
    (projet / ".lintorn").symlink_to(ailleurs, target_is_directory=True)
    monkeypatch.setattr(config, "RACINE", projet)
    monkeypatch.setattr(config, "RAPPORT", projet / ".lintorn" / "rapport.md")

    assert lintorn.rapport.markdown.ecrire_rapport([Resultat("x", "OK", "rien")]) is False
    assert list(ailleurs.iterdir()) == []


def test_c2_une_config_en_lien_symbolique_n_est_pas_ecrite_a_travers(tmp_path, monkeypatch):
    """Un lien sur la config est la décision de l'utilisateur : on refuse."""
    cible = tmp_path / "partagee.toml"
    cible.write_text("[controles]\n", encoding="utf-8")
    fichier = _config_lue(tmp_path, monkeypatch, "")
    fichier.unlink()
    fichier.symlink_to(cible)

    assert lintorn.commandes.outils._activer(["failles_npm"]) is None
    assert cible.read_text(encoding="utf-8") == "[controles]\n"


def test_c2_le_hook_ne_s_ecrit_pas_a_travers_un_lien(tmp_path, monkeypatch):
    victime = tmp_path / "victime.sh"
    victime.write_text("intact", encoding="utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    lien = tmp_path / ".lintorn" / "hooks" / "pre-push"
    lien.parent.mkdir(parents=True)
    lien.symlink_to(victime)

    base.ecrire_sortie(lien, b"#!/bin/sh\n")

    assert victime.read_text(encoding="utf-8") == "intact"
    assert lien.read_bytes() == b"#!/bin/sh\n"


def test_c4_une_config_toml_ignoree_est_annoncee(tmp_path):
    """Avec [tool.lintorn] dans pyproject.toml, config.toml était ignoré sans un mot."""
    lu = _config_de(tmp_path, {
        "pyproject.toml": '[project]\nname = "x"\n\n[tool.lintorn]\nfichiers_ia = ["CLAUDE.md"]\n',
        ".lintorn/config.toml": "[controles]\ntests = true\n",
    })

    assert any("config.toml IGNORE" in souci for souci in lu["soucis"])


def test_c4_init_refuse_d_ecrire_une_config_qui_serait_ignoree(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "FICHIERS_CONFIG_LUS", ["pyproject.toml"])
    monkeypatch.setattr(config, "DOSSIER_LINTORN", tmp_path / ".lintorn")

    assert lintorn.commandes.init.init() == 1
    assert not (tmp_path / ".lintorn" / "config.toml").exists()
    assert "IGNORE" in capsys.readouterr().out


@pytest.mark.parametrize("fichiers, signale", [
    ({".lintorn/config.toml": 'controles = "oui"\n'}, True),
    ({".lintorn/config.toml": 'regles = "abc"\n'}, True),
    ({".lintorn/regles.toml": '[regles]\nnom = "x"\n'}, True),
    ({".lintorn/config.toml": 'commandes = "x"\n'}, True),
    ({".lintorn/config.toml": '[[commandes]]\ncle = "x"\ncmd = ["true"]\ncodes_alerte = 5\n'}, True),
    # Sans section `lintorn`, un pyproject tordu ne concerne pas Lintorn :
    # le seul défaut était le plantage.
    ({"pyproject.toml": 'tool = "x"\n'}, False),
])
def test_h1_un_mauvais_type_de_config_ne_fait_plus_tomber_lintorn(tmp_path, fichiers, signale):
    """Un scalaire à la place d'une table faisait planter Lintorn À L'IMPORT :
    plus aucune commande ne répondait, pas même celle qui répare."""
    lu = _config_de(tmp_path, fichiers)

    if signale:
        assert lu["soucis"], "le mauvais type doit etre SIGNALE, pas ignore en silence"


def test_h2_une_config_qui_n_est_pas_en_utf8_est_signalee(tmp_path):
    lu = _config_de(tmp_path, {
        ".lintorn/config.toml": b"# R\xe9glages\n[controles]\ntests = false\n",
        ".lintorn/.env": b"# pr\xe9f\xe9rence\nLINTORN_MEMOIRE=x\n",
    })

    assert any("config.toml illisible" in souci for souci in lu["soucis"])
    assert any(".env illisible" in souci for souci in lu["soucis"])


@pytest.mark.parametrize("json_npm", [
    '{"error": "une chaine"}',
    '{"vulnerabilities": {"x": null}}',
    '{"vulnerabilities": {"x": {"severity": "high", "via": null}}}',
    '{"vulnerabilities": {"x": {"severity": ["high"], "via": [null, 3]}}}',
    '{"a":' * 100000 + "1" + "}" * 100000,       # VRAIMENT imbriqué : RecursionError
])
def test_h3_un_json_npm_tordu_ne_fait_pas_tomber_l_audit(json_npm):
    resultat = lintorn.outils.npm_audit.traduire(_sortie_npm(json_npm))

    assert resultat.statut in ("ALERTE", "INDISPONIBLE", "OK")


@pytest.mark.parametrize("json_osv", [
    '{"results": ["x"]}',
    '{"results": [{"source": null, "packages": null}]}',
    '{"results": [{"packages": [{"package": null, "vulnerabilities": null, "groups": null}]}]}',
    '{"results": [{"packages": [{"groups": [{"ids": null}], "vulnerabilities": [{"affected": null}]}]}]}',
])
def test_h3_un_json_osv_tordu_ne_fait_pas_tomber_l_audit(json_osv):
    resultat = lintorn.outils.osv.traduire(_sortie_osv(json_osv, 1))

    assert resultat.statut == "ALERTE", "une forme illisible ne doit jamais devenir un vert"


@pytest.mark.skipif(os.name == "nt", reason="faux npm en script shell")
@pytest.mark.parametrize("corps, attendu", [
    ('{"error": {"code": "ENOAUDIT"}}', "INDISPONIBLE"),
    ('{"vulnerabilities": {}}', "OK"),
])
def test_h4_le_code_0_de_npm_passe_bien_par_le_traducteur(tmp_path, monkeypatch, corps, attendu):
    """Par le VRAI circuit — `noyau.executer` — et non par le traducteur appelé
    à la main : le premier correctif ajoutait 0 aux codes à traduire, mais
    `lancer()` rendait le vert AVANT de les regarder. Un test qui appelait le
    traducteur directement était vert sur un câblage mort."""
    faux_npm = tmp_path / "npm"
    faux_npm.write_text(f"#!/bin/sh\necho '{corps}'\nexit 0\n", encoding="utf-8")
    faux_npm.chmod(0o755)
    (tmp_path / config.VERROU_NPM).write_text("{}", encoding="utf-8")
    commande = {**lintorn.outils.npm_audit.commande(tmp_path), "cmd": [str(faux_npm)]}
    monkeypatch.setattr(config, "COMMANDES", [commande])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {})

    resultats = noyau.executer()

    assert [resultat.statut for resultat in resultats] == [attendu]


def test_h4_npm_qui_sort_en_0_avec_une_erreur_n_est_pas_un_vert(tmp_path):
    """Un registre qui refuse l'audit peut sortir en 0 : « rien a signaler »
    alors que rien n'avait été vérifié."""
    (tmp_path / config.VERROU_NPM).write_text("{}", encoding="utf-8")
    assert 0 in lintorn.outils.npm_audit.commande(tmp_path)["codes_alerte"]
    refus = Resultat("npm", "ALERTE", "x", '{"error": {"code": "ENOAUDIT"}}', code_sortie=0)
    propre = Resultat("npm", "ALERTE", "x", '{"vulnerabilities": {}}', code_sortie=0)

    assert lintorn.outils.npm_audit.traduire(refus).statut == "INDISPONIBLE"
    assert lintorn.outils.npm_audit.traduire(propre).statut == "OK", "une vraie liste vide reste un vert"


def test_h5_un_import_casse_du_projet_n_est_pas_un_outil_absent(tmp_path):
    """Un module RENOMMÉ dans le projet s'affichait « outil non installé »."""
    (tmp_path / "outil_factice.py").write_text("import projet_renomme\n", encoding="utf-8")

    casse = base.lancer("x", [sys.executable, "-m", "outil_factice"], tmp_path)
    absent = base.lancer("x", [sys.executable, "-m", "outil_qui_n_existe_pas"], tmp_path)

    assert casse.statut == "ALERTE", "le defaut du projet a ete deguise en outil absent"
    assert absent.statut == "INDISPONIBLE"


def test_h6_dependances_interroge_le_python_qui_le_lance(tmp_path):
    """Il devinait `venv/` en dur : sur un projet en `.venv/`, un faux rouge
    bloquant qu'aucune config ne corrigeait."""
    (tmp_path / "requirements.txt").write_text("paquet-qui-n-existe-pas==1.0\n", encoding="utf-8")
    script = Path(base.__file__).parent / "dependances.py"

    sortie = subprocess.run([sys.executable, str(script), str(tmp_path)],
                            capture_output=True, text=True, timeout=120, check=False)

    assert sortie.returncode == 1, sortie.stdout + sortie.stderr
    assert "venv introuvable" not in sortie.stdout
    assert "paquet-qui-n-existe-pas" in sortie.stdout


def test_h6_sans_venv_de_projet_pas_de_comparaison(tmp_path):
    lu = _config_de(tmp_path, {"requirements.txt": "x==1\n", "app.py": ""})

    assert "dependances" not in lu["cles"]


def test_h7_le_focus_voit_un_fichier_au_dela_des_huit_affiches(monkeypatch):
    regles = Resultat("Regles maison", "ALERTE", "x", "- **3** x autre.py",
                      bloquant=False, fichiers={"src/nouveau.py": "print oublie : 1"})

    focus = lintorn.rapport.focus.focus_sur([regles], ["src/nouveau.py"])

    assert focus.statut == "ALERTE", "une violation hors du top-8 passait pour propre"


def test_h7_les_regles_maison_donnent_la_liste_complete(tmp_path, monkeypatch):
    for numero in range(12):
        (tmp_path / f"f{numero}.md").write_text("interdit", encoding="utf-8")
    _regle(tmp_path, monkeypatch)

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert len(resultat.fichiers) == 12


def test_h8_le_focus_ne_confond_pas_deux_chemins_voisins():
    """`app/vues.py` était reconnu dans `monapp/vues.py`."""
    voisin = Resultat("Ruff", "ALERTE", "x", "monapp/vues.py:3:1: F401 import inutile")
    exact = Resultat("Ruff", "ALERTE", "x", "app/vues.py:3:1: F401 import inutile")

    assert lintorn.rapport.focus.focus_sur([voisin], ["app/vues.py"]).statut == "OK"
    assert lintorn.rapport.focus.focus_sur([exact], ["app/vues.py"]).statut == "ALERTE"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="pas de tube nomme ici")
def test_h9_un_tube_nomme_ne_gele_plus_lintorn(tmp_path, monkeypatch):
    os.mkfifo(tmp_path / "docs.md")
    (tmp_path / "vrai.md").write_text("rien", encoding="utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "DOCS_EXCLUS", [])

    documents = config._documents_du_depot()

    assert [document.name for document in documents] == ["vrai.md"]


def test_h9_un_motif_qui_ne_rend_pas_la_main_est_abandonne(tmp_path, monkeypatch):
    """`(a+)+$` face à quarante `a` : retour arrière exponentiel, hang."""
    if not hasattr(signal, "setitimer"):
        pytest.skip("pas de minuterie de signal sur ce systeme")
    (tmp_path / "piege.md").write_text("a" * 40 + "!", encoding="utf-8")
    _regle(tmp_path, monkeypatch, motif="(a+)+$")
    monkeypatch.setattr(lintorn.controles.projet.regles_maison, "SECONDES_PAR_FICHIER", 0.3)

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.statut == "VERIF", "une regle sans verdict n'est pas tenue"
    assert "abandonnee" in resultat.resume


def test_un_motif_lent_sur_beaucoup_de_fichiers_est_abandonne_aussi(tmp_path, monkeypatch):
    """Cinq secondes par fichier sur des milliers de fichiers : le push gelait
    aussi sûrement qu'avec un motif infini."""
    for numero in range(3):
        (tmp_path / f"m{numero}.md").write_text("texte", encoding="utf-8")
    _regle(tmp_path, monkeypatch, motif="texte")
    monkeypatch.setattr(lintorn.controles.projet.regles_maison, "SECONDES_PAR_REGLE", 0.0)

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.statut == "VERIF", "une regle sans verdict n'est pas tenue"
    assert "abandonnee" in resultat.resume


def test_h10_maj_securite_ne_plante_pas_sans_projet_python(monkeypatch, capsys):
    monkeypatch.setattr(config, "BACKEND", None)
    monkeypatch.setattr(config, "PY_RACINE", None)

    assert lintorn.commandes.securite.maj_securite(appliquer=True) == 1
    assert "Aucun code Python" in capsys.readouterr().out


def test_h11_un_pip_muet_ne_fait_pas_planter_maj_securite(tmp_path, monkeypatch, capsys):
    rapport = json.dumps({"dependencies": [{"name": "requests", "version": "2.5.0",
                                            "vulns": [{"id": "X", "fix_versions": ["2.20.0"]}]}]})
    reponses = iter([subprocess.CompletedProcess([], 0, rapport, ""),
                     subprocess.CompletedProcess([], 1, "", "")])
    monkeypatch.setattr(subprocess, "run", lambda *_, **__: next(reponses))
    monkeypatch.setattr(config, "BACKEND", None)
    monkeypatch.setattr(config, "PY_RACINE", tmp_path)
    monkeypatch.setattr(config, "VENV_PROJET", tmp_path / ".venv")

    assert lintorn.commandes.securite.maj_securite(appliquer=True) == 1
    assert "ECHEC requests" in capsys.readouterr().out


def test_h12_le_repinglage_garde_les_commentaires_et_les_noms_souples(tmp_path, monkeypatch):
    """`requests==2.5.0  # client HTTP` n'était pas repinglé, mais annoncé."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    fichier = tmp_path / "requirements.txt"
    fichier.write_text("requests==2.5.0  # client HTTP\ntyping_extensions==4.0.0\n",
                       encoding="utf-8")

    changes = lintorn.commandes.securite._repingler(fichier, [("requests", "2.20.0"),
                                           ("typing-extensions", "4.12.0")])

    assert changes == 2
    assert fichier.read_text(encoding="utf-8") == (
        "requests==2.20.0  # client HTTP\ntyping_extensions==4.12.0\n")


def test_m1_un_titre_d_avis_ne_fabrique_pas_de_fausse_section():
    """Un saut de ligne + `## [ OK ]` dans un titre injectait une section verte."""
    sortie = json.dumps({"vulnerabilities": {"x": {
        "severity": "high", "via": [{"title": "vrai\n## [ OK ] Tout va bien", "url": "javascript:x"}]}}})

    resultat = lintorn.outils.npm_audit.traduire(_sortie_npm(sortie))

    assert not any(ligne.startswith("#") for ligne in resultat.detail.splitlines())
    assert "javascript:" not in resultat.detail.replace("vrai ## \\[ OK \\]", "")
    assert "](javascript" not in resultat.detail


def test_m2_un_resume_avec_des_barres_ne_casse_pas_le_tableau():
    assert lintorn.rapport.markdown._cellule_du_tableau("r1 : 3 | r2 : 4\nsuite") == "r1 : 3 \\| r2 : 4 suite"


def test_m3_un_hors_portee_fantome_ne_rend_pas_le_compte_negatif(tmp_path, monkeypatch):
    _config_doc_ia(tmp_path, monkeypatch, "| Regle | `x.py` doit exister |\n")
    monkeypatch.setattr(config, "HORS_PORTEE", [
        {"nom": "fantome", "source": "CLAUDE.md:99", "raison": "r"},
        {"nom": "fantome bis", "source": "CLAUDE.md:98", "raison": "r"}])

    resultat = lintorn.controles.projet.regles_enoncees.controle_regles_declarees()

    assert "-1" not in resultat.resume
    assert resultat.statut == "VERIF"
    assert "SANS OBJET" in resultat.detail


def test_m4_un_env_avec_bom_est_lu(tmp_path):
    fichier = tmp_path / ".env"
    fichier.write_bytes(b"\xef\xbb\xbfLINTORN_MEMOIRE=/quelque/part\n")

    assert config._lire_env(fichier) == {"LINTORN_MEMOIRE": "/quelque/part"}


def test_m5_une_racine_de_regle_ne_sort_pas_du_projet(tmp_path, monkeypatch):
    (tmp_path / "projet").mkdir()
    _regle(tmp_path / "projet", monkeypatch, racine="../")

    assert config.REGLES_MAISON == []
    assert any("hors du projet" in souci for souci in config.SOUCIS_CONFIG)


def test_m6_typescript_ne_passe_plus_par_npx(tmp_path):
    """`npx tsc` sans TypeScript installé le TÉLÉCHARGEAIT : réseau non
    accordé, ~70 s, et un faux rouge bloquant."""
    lu = _config_de(tmp_path, {"package.json": "{}", "tsconfig.json": "{}"})

    commande = lu["cmd"]["typescript"]
    assert "npx" not in Path(commande[0]).name
    assert Path(commande[0]).parent.name == ".bin"


@_ILLISIBLE_POSSIBLE
def test_m7_un_dossier_en_lecture_seule_ne_fait_pas_planter(tmp_path, monkeypatch, capsys):
    dossier = tmp_path / ".lintorn"
    dossier.mkdir()
    dossier.chmod(0o555)
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "RAPPORT", dossier / "rapport.md")
    try:
        assert lintorn.rapport.markdown.ecrire_rapport([Resultat("x", "OK", "rien")]) is False
    finally:
        dossier.chmod(0o755)
    assert "NON ecrit" in capsys.readouterr().out


def test_m8_une_regle_ne_compte_pas_ce_que_cite_le_rapport(tmp_path, monkeypatch):
    """Le rapport cite le code fautif : une règle y comptait ses propres
    citations. Mais la config de `.lintorn/` se versionne : elle reste lue."""
    (tmp_path / ".lintorn").mkdir()
    (tmp_path / ".lintorn" / "rapport.md").write_text("interdit interdit", encoding="utf-8")
    (tmp_path / ".lintorn" / "notes.md").write_text("interdit", encoding="utf-8")
    (tmp_path / "vrai.md").write_text("interdit", encoding="utf-8")
    monkeypatch.setattr(config, "RAPPORT", tmp_path / ".lintorn" / "rapport.md")
    _regle(tmp_path, monkeypatch)

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.fichiers == {"vrai.md": "interdit : 1", ".lintorn/notes.md": "interdit : 1"}


def test_m9_le_parcours_ne_descend_pas_dans_les_dossiers_ignores(tmp_path):
    (tmp_path / "node_modules" / "paquet").mkdir(parents=True)
    (tmp_path / "node_modules" / "paquet" / "x.md").write_text("", encoding="utf-8")
    (tmp_path / "a.md").write_text("", encoding="utf-8")
    index: dict = {}

    trouves = lintorn.controles.projet.regles_maison._fichiers_sous(tmp_path, index, set())

    assert [chemin.name for chemin in trouves] == ["a.md"]
    assert lintorn.controles.projet.regles_maison._fichiers_sous(tmp_path, index, set()) is trouves, (
        "un seul parcours par audit")


# ─────────────────────────────────────────────────────────────────────────────
# La 3e passe de la simulation — ce qui trainait depuis la 0.3.0
# ─────────────────────────────────────────────────────────────────────────────
def test_cf_un_projet_range_sous_un_dossier_build_reste_audite(tmp_path):
    """`IGNORES` etait teste sur le chemin ABSOLU : un projet sous `~/build/`,
    ou clone par une CI dans `/home/travis/build/…`, perdait ses controles
    Django et sa doc passait pour menteuse."""
    racine = tmp_path / "build" / "projet"
    (racine / "back").mkdir(parents=True)
    (racine / ".lintorn").mkdir()
    (racine / "back" / "manage.py").write_text("", encoding="utf-8")
    (racine / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    # `django_check` est opt-in : ici, l'accord est donne. Ce qu'on teste,
    # c'est qu'un dossier nomme `build` ne le fasse pas disparaitre.
    (racine / ".lintorn" / "config.toml").write_text(
        "[controles]\ndjango_check = true\n", encoding="utf-8")

    sortie = subprocess.run(
        [sys.executable, "-c", "import json; from lintorn import config;"
         " print(json.dumps([c['cle'] for c in config.COMMANDES]))"],
        cwd=racine, capture_output=True, text=True, timeout=60, check=False,
        env={**os.environ, "LINTORN_RACINE": str(racine)})

    assert sortie.returncode == 0, sortie.stderr
    assert "django_check" in json.loads(sortie.stdout), "les controles Django ont disparu"


def test_les_traducteurs_annonces_sont_ceux_qui_existent():
    """`config` valide la cle `traduction` sans pouvoir importer `base` — c'est
    `base` qui importe `config`. Les deux listes doivent rester d'accord, sinon
    une traduction valide serait refusee, ou une inconnue acceptee."""
    assert set(config.TRADUCTEURS_CONNUS) == set(lintorn.outils.TRADUCTEURS)


def test_une_traduction_inventee_ne_s_ignore_pas_en_silence(tmp_path):
    lu = _config_de(tmp_path, {
        "pyproject.toml": '[project]\nname = "x"\n',
        ".lintorn/config.toml": ('[[commandes]]\ncle = "verif"\n'
                                 'cmd = ["sh", "-c", "exit 0"]\ntraduction = "npm-audit"\n'),
    })

    assert "verif" not in lu["cles"]
    assert any("npm_audit" in souci for souci in lu["soucis"]), "la plus proche est proposee"


def test_ca_les_controles_django_attendent_un_accord(tmp_path):
    """`manage.py check` importe settings.py et toutes les apps : c'est du
    code du projet. Actifs d'office, ils contredisaient « rien d'invasif sans
    ton accord » sur TOUT projet Django."""
    lu = _config_de(tmp_path, {"manage.py": "", "pyproject.toml": '[project]\nname = "x"\n'})

    assert "django_check" not in lu["cles"]
    assert "migrations" not in lu["cles"]


def test_ca_le_premier_lancement_nomme_aussi_ce_qui_existe(tmp_path, monkeypatch):
    """Sans aucune config, le controle disait « aucun fichier de
    configuration » et taisait ce qui s'applique au projet — au moment ou
    l'information sert le plus."""
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])
    monkeypatch.setattr(config, "FICHIERS_CONFIG_LUS", [])
    monkeypatch.setattr(config, "CONTROLES_DISPONIBLES", [("tests", "Tests (pytest)")])

    resultat = lintorn.controles.outillage.configuration.controle_configuration()

    assert resultat.statut == "INDISPONIBLE"
    assert "NON actives" in resultat.resume
    assert "tests = true" in resultat.detail


def test_ca_un_controle_non_active_est_nomme_pas_escamote(tmp_path, monkeypatch):
    """Un controle opt-in absent du rapport ne se distingue pas d'un controle
    sans objet : il faut DIRE lequel attend un accord."""
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])
    monkeypatch.setattr(config, "FICHIERS_CONFIG_LUS", ["config.toml"])
    monkeypatch.setattr(config, "CONTROLES_DISPONIBLES", [("django_check", "Django check")])

    resultat = lintorn.controles.outillage.configuration.controle_configuration()

    assert resultat.statut == "OK", "ce n'est pas une panne : rien n'a ete demande"
    assert "django_check" in resultat.detail
    assert "NON actives" in resultat.resume
    assert "django_check = true" in resultat.detail
    assert resultat.detail_meme_au_vert is True, "sinon le rapport jette la liste"


def test_cb_une_cle_mal_tapee_dans_une_regle_ne_passe_plus_en_silence(tmp_path):
    """`bloquan = true` laissait la regle NON bloquante : la violation etait
    signalee, et le push partait quand meme."""
    lu = _config_de(tmp_path, {
        "pyproject.toml": '[project]\nname = "x"\n',
        ".lintorn/regles.toml": ('[[regles]]\nnom = "R"\nmotif = "interdit"\n'
                                 'suffixes = [".md"]\nbloquan = true\n'),
    })

    assert "R" in lu["regles"], "la regle continue de controler"
    assert any("bloquan" in souci and "bloquant" in souci for souci in lu["soucis"])


def test_err5_une_racine_forcee_qui_n_existe_pas_se_dit(tmp_path):
    """git lance dans un dossier absent echoue comme s'il n'etait pas
    installe : le rapport annoncait « git introuvable sur cette machine »."""
    sortie = subprocess.run(
        [sys.executable, "-c", "import json; from lintorn import config;"
         " print(json.dumps([config.SOUCIS_CONFIG, str(config.RACINE)]))"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False,
        env={**os.environ, "LINTORN_RACINE": str(tmp_path / "faute" / "projet")})

    assert sortie.returncode == 0, sortie.stderr
    soucis, racine = json.loads(sortie.stdout)
    assert any("LINTORN_RACINE" in souci for souci in soucis)
    assert racine != str(tmp_path / "faute" / "projet")
    assert not (tmp_path / "faute").exists(), "aucune arborescence creee au fond d'un chemin faux"


def test_err1_un_caractere_de_saut_unicode_n_active_rien_de_plus(tmp_path):
    """`splitlines()` coupe aussi sur U+2028 : un commentaire en contenant un
    devenait du TOML ACTIF, et pip-audit (reseau) s'activait sans accord."""
    texte = "[controles]\n# exemple a ne PAS activer :\u2028failles = true\n"

    ecrit = lintorn.commandes.outils._activer_dans(texte, "controles", "tests")

    assert tomllib.loads(ecrit)["controles"] == {"tests": True}
    assert "\u2028" in ecrit, "le commentaire de l'utilisateur est rendu tel quel"


def test_err2_un_script_non_executable_ne_fait_pas_tomber_l_audit(tmp_path):
    """Oublier un `chmod +x` sur une commande maison est banal ; ca rendait un
    traceback et aucun rapport."""
    script = tmp_path / "v.sh"
    script.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    script.chmod(0o644)

    resultat = base.lancer("Verif", [str(script)], tmp_path, bloquant=True)

    assert resultat.statut == "INDISPONIBLE"
    assert "impossible de lancer" in resultat.resume
    assert resultat.bloquant is False


def test_err3_un_outil_bloquant_qui_depasse_le_delai_bloque_encore(monkeypatch, tmp_path):
    """Une suite de tests partie en boucle — donc une vraie regression —
    laissait passer le push au bout de dix minutes."""
    monkeypatch.setattr(base, "DELAI_OUTIL", 1)

    resultat = base.lancer("Tests", [sys.executable, "-c", "import time; time.sleep(30)"],
                           tmp_path, bloquant=True)

    assert resultat.statut == "ERREUR"
    assert resultat.bloquant is True
    assert "delai depasse" in resultat.resume


@pytest.mark.skipif(os.name == "nt", reason="groupes de processus POSIX")
def test_un_outil_qui_laisse_un_enfant_ne_fait_pas_attendre_lintorn(tmp_path):
    """L'outil sort, son enfant garde la sortie ouverte : avec un tube, Lintorn
    attendait l'enfant (dix minutes) pour un outil déjà terminé."""
    code = ("import subprocess,sys;"
            "subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)']);"
            "print('fini')")
    debut = time.monotonic()

    resultat = base.lancer("Outil", [sys.executable, "-c", code], tmp_path)

    assert time.monotonic() - debut < 10, "Lintorn a attendu l'enfant de l'outil"
    assert resultat.statut == "OK"


@pytest.mark.skipif(os.name == "nt", reason="groupes de processus POSIX")
def test_un_delai_depasse_tue_aussi_les_enfants(monkeypatch, tmp_path):
    temoin = tmp_path / "temoin"
    code = ("import subprocess,sys,time;"
            f"subprocess.Popen([sys.executable,'-c',\"import time;time.sleep(3);open({str(temoin)!r},'w')\"]);"
            "time.sleep(30)")
    monkeypatch.setattr(base, "DELAI_OUTIL", 1)

    base.lancer("Outil", [sys.executable, "-c", code], tmp_path)
    time.sleep(3.5)

    assert not temoin.exists(), "l'enfant de l'outil a survecu au delai"


def test_un_outil_qui_lit_stdin_ne_gele_pas(tmp_path):
    """`input()` dans un test : le hook git aurait attendu pour toujours (ou
    lu les lignes que git lui envoie)."""
    resultat = base.lancer("Outil", [sys.executable, "-c", "input()"], tmp_path, codes_alerte=())

    assert resultat.statut == "ERREUR"
    assert "EOF" in resultat.detail


def test_une_sortie_gigantesque_est_bornee_et_annoncee(monkeypatch, tmp_path):
    """300 Mo de sortie tenaient 2 Go en memoire. La queue est gardee : c'est
    la que les outils ecrivent leur bilan."""
    monkeypatch.setattr(base, "LIMITE_SORTIE", 1 << 20)
    code = ("import sys\n"
            "for i in range(100000): sys.stdout.write('ligne %d ' % i + 'x' * 90 + '\\n')\n"
            "print('BILAN FINAL')")

    resultat = base.lancer("Outil", [sys.executable, "-c", code], tmp_path, codes_alerte=(0,))

    assert len(resultat.detail) < (2 << 20)
    assert "sortie tronquee" in resultat.detail
    assert "BILAN FINAL" in resultat.detail


def test_err4_la_memoire_d_un_projet_voisin_n_est_pas_auditee(tmp_path, monkeypatch):
    """Le dossier retenu etait le premier dont le nom CONTENAIT celui du
    projet : `app` est contenu dans `app-legacy`, qui se trie avant."""
    projet = tmp_path / "web" / "app"
    projet.mkdir(parents=True)
    projets_claude = tmp_path / ".claude" / "projects"
    bon = projets_claude / re.sub(r"[^a-zA-Z0-9]", "-", str(projet)) / "memory"
    # Trie AVANT le vrai dossier : c'est lui que l'ancienne recherche retenait.
    voisin = projets_claude / "-aaa-app-legacy" / "memory"
    bon.mkdir(parents=True)
    voisin.mkdir(parents=True)
    monkeypatch.setattr(config, "RACINE", projet)
    monkeypatch.setitem(config.ENV, "CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))

    memoire, origine = config._dossier_memoire()

    assert memoire == bon, f"memoire d'un autre projet auditee ({origine})"


def test_cc_un_pip_audit_sans_reseau_n_est_pas_une_faille():
    """pip-audit sort en 1 pour une faille ET pour un proxy mort : le rapport
    affichait « 78 ligne(s) de sortie », un rouge qui ressemble a des failles
    sur un audit qui n'a rien audite."""
    panne = Resultat("Failles connues (pip-audit)", "ALERTE", "78 ligne(s) de sortie",
                     "ERROR:pip_audit._cli:Caught exception: HTTPSConnectionPool(...): "
                     "Max retries exceeded: ProxyError", code_sortie=1)

    resultat = lintorn.outils.pip_audit.traduire(panne)

    assert resultat.statut == "INDISPONIBLE"
    assert "rien n'a ete verifie" in resultat.resume


def test_cc_les_failles_de_pip_audit_sont_lues():
    brut = json.dumps({"dependencies": [
        {"name": "requests", "version": "2.5.0",
         "vulns": [{"id": "PYSEC-2018-28", "aliases": ["CVE-2018-18074"],
                    "fix_versions": ["2.20.0"]}]},
        {"name": "sain", "version": "1.0", "vulns": []},
    ]})
    trouve = Resultat("Failles connues (pip-audit)", "ALERTE", "3 ligne(s)", brut, code_sortie=1)

    resultat = lintorn.outils.pip_audit.traduire(trouve)

    assert resultat.statut == "ALERTE"
    assert resultat.resume == "1 paquet(s) vulnerable(s)"
    assert "CVE-2018-18074" in resultat.detail
    assert "`2.20.0`" in resultat.detail
    assert "sain" not in resultat.detail


def test_cd_un_dossier_lie_dans_le_projet_ne_fait_pas_ecrire_ailleurs(tmp_path, monkeypatch):
    """`.lintorn/hooks -> ../outils` faisait ecraser le script `outils/pre-push`
    du projet par le hook. Le fichier n'est pas le seul a pouvoir etre un lien."""
    (tmp_path / "outils").mkdir()
    (tmp_path / "outils" / "pre-push").write_text("script du projet", encoding="utf-8")
    (tmp_path / ".lintorn").mkdir()
    (tmp_path / ".lintorn" / "hooks").symlink_to(tmp_path / "outils")
    monkeypatch.setattr(config, "RACINE", tmp_path)

    with pytest.raises(OSError, match="lien symbolique"):
        base.ecrire_sortie(tmp_path / ".lintorn" / "hooks" / "pre-push", b"le hook")

    assert (tmp_path / "outils" / "pre-push").read_text(encoding="utf-8") == "script du projet"


def test_err6_un_chemin_de_la_machine_cite_dans_la_doc_ne_bloque_pas(tmp_path, monkeypatch):
    """Une doc parle aussi de la machine du lecteur (`~/.config/…`). Ce n'est
    pas une affirmation sur le depot : ca ne peut pas bloquer un push."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    doc = tmp_path / "guide.md"
    doc.write_text("Les reglages vivent dans `~/.config/outil/reglages.toml`.", encoding="utf-8")

    resultat = lintorn.controles.projet.doc_vs_code._verifier_documents("t", [doc], bloquant_possible=True)

    assert resultat.statut == "VERIF"
    assert resultat.bloquant is False
    assert "hors du depot" in resultat.detail


def test_err6_les_tests_d_un_tests_py_django_existent_aussi(tmp_path, monkeypatch):
    """`hors_portee` verifie que le test cite existe. Ne chercher que dans
    `test_*.py` declarait « promesse rompue » sur la convention Django."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "tests.py").write_text(
        "def test_le_numero_est_unique():\n    pass\n"
        "async def test_la_tache_repond():\n    pass\n", encoding="utf-8")

    trouves = lintorn.controles.projet.regles_enoncees._tests_du_projet()

    assert trouves == {"test_le_numero_est_unique", "test_la_tache_repond"}


# ─────────────────────────────────────────────────────────────────────────────
# N2 — un fichier qu'on ne peut pas OUVRIR : nommé, jamais fatal, jamais tu
# ─────────────────────────────────────────────────────────────────────────────
# `is_file()` écartait les tubes et les dossiers nommés `.md`, mais un fichier
# régulier en `chmod 000` passait, et `read_text` levait : trois contrôles
# tombaient, le rapport avec. `errors="replace"` couvre un contenu mal encodé,
# pas un fichier qu'on n'ouvre pas.



@_ILLISIBLE_POSSIBLE
def test_n2_un_document_illisible_est_nomme_sans_faire_tomber_le_controle(tmp_path, monkeypatch, illisible):
    monkeypatch.setattr(config, "RACINE", tmp_path)
    (tmp_path / "vrai.py").write_text("", encoding="utf-8")
    lisible = tmp_path / "lisible.md"
    lisible.write_text("voir `vrai.py`", encoding="utf-8")
    ferme = tmp_path / "ferme.md"
    ferme.write_text("voir `absent.py`", encoding="utf-8")
    illisible(ferme)

    resultat = lintorn.controles.projet.doc_vs_code._verifier_documents("t", [lisible, ferme], bloquant_possible=True)

    assert resultat.statut == "VERIF", "un document non lu n'est pas un feu vert"
    assert resultat.bloquant is False
    assert "1 ILLISIBLE(S)" in resultat.resume
    assert "ferme.md" in resultat.detail


@_ILLISIBLE_POSSIBLE
def test_n2_des_documents_tous_illisibles_ne_verifient_rien(tmp_path, monkeypatch, illisible):
    monkeypatch.setattr(config, "RACINE", tmp_path)
    ferme = tmp_path / "ferme.md"
    ferme.write_text("voir `absent.py`", encoding="utf-8")
    illisible(ferme)

    resultat = lintorn.controles.projet.doc_vs_code._verifier_documents("t", [ferme], bloquant_possible=True)

    assert resultat.statut == "INDISPONIBLE"
    assert "tous ILLISIBLES" in resultat.resume


@_ILLISIBLE_POSSIBLE
def test_n2_une_memoire_illisible_n_est_pas_comptee_fraiche(tmp_path, monkeypatch, illisible):
    (tmp_path / "fiche.md").write_text("cite `README.md`\n", encoding="utf-8")
    illisible(tmp_path / "fiche.md")
    monkeypatch.setattr(config, "MEMOIRE_IA", tmp_path)
    monkeypatch.setattr(config, "SOUS_GIT", True)

    resultat = lintorn.controles.projet.fraicheur_memoire.controle_fraicheur_memoire()

    assert resultat.statut == "VERIF"
    assert "1 ILLISIBLE(S)" in resultat.resume
    assert "fiche.md" in resultat.detail


@_ILLISIBLE_POSSIBLE
def test_n2_un_fichier_illisible_n_arrete_pas_les_regles(tmp_path, monkeypatch, illisible):
    (tmp_path / "a.md").write_text("interdit", encoding="utf-8")
    (tmp_path / "b.md").write_text("interdit", encoding="utf-8")
    illisible(tmp_path / "b.md")
    _regle(tmp_path, monkeypatch)

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.statut == "ALERTE", "l'infraction du fichier lisible reste vue"
    assert resultat.fichiers == {"a.md": "interdit : 1"}
    assert "1 ILLISIBLE(S)" in resultat.resume
    assert "`b.md`" in resultat.detail


@_ILLISIBLE_POSSIBLE
def test_n2_une_regle_qui_n_a_que_des_illisibles_dit_pourquoi(tmp_path, monkeypatch, illisible):
    (tmp_path / "b.md").write_text("interdit", encoding="utf-8")
    illisible(tmp_path / "b.md")
    _regle(tmp_path, monkeypatch)

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.statut == "VERIF"
    assert "sont ILLISIBLES" in resultat.detail, "« aucun fichier » serait faux : il y en a un"


@_ILLISIBLE_POSSIBLE
def test_n2_un_dossier_illisible_n_echappe_plus_aux_regles_en_silence(tmp_path, monkeypatch, illisible):
    """`os.walk` saute sans un mot un dossier qu'il ne peut pas lister."""
    (tmp_path / "a.md").write_text("propre", encoding="utf-8")
    (tmp_path / "prive").mkdir()
    (tmp_path / "prive" / "c.md").write_text("interdit", encoding="utf-8")
    illisible(tmp_path / "prive")
    _regle(tmp_path, monkeypatch)

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.statut == "VERIF", "un vert ici affirmerait un dossier jamais lu"
    assert "`prive/`" in resultat.detail
