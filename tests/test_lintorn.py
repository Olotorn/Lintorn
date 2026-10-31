"""La config et le cœur de l'outil : ce qui reste quand les autres familles ont leur fichier."""

import ast
import json
import os
import re
import subprocess
import sys
import tomllib
from datetime import date, timedelta
from fnmatch import fnmatch
from pathlib import Path

import pytest
from aides import _config_lue, _projet_detecte, _regle

import lintorn.commandes
import lintorn.controles
import lintorn.outils
import lintorn.rapport
from lintorn import __version__, base, cli as Lintorn, config, noyau
from lintorn.base import Resultat


# ─────────────────────────────────────────────────────────────────────────────
# Hors dépôt git — dire pourquoi, au lieu d'un rouge impossible à éteindre
# ─────────────────────────────────────────────────────────────────────────────
def test_le_hook_ne_passe_pas_au_rouge_sans_depot(monkeypatch):
    """Sans dépôt, il n'y a pas de push : ce contrôle n'a pas d'objet.

    Il affichait « NON BRANCHE - `git push` ne controle RIEN », un rouge
    qu'aucune commande ne pouvait éteindre. Un rouge inextinguible apprend à
    ignorer les rouges.
    """
    monkeypatch.setattr(config, "SOUS_GIT", False)

    resultat = lintorn.controles.outillage.hook_git.controle_hook_git()

    assert resultat.statut == "INDISPONIBLE"
    assert resultat.bloquant is False
    assert "pas de depot git" in resultat.resume


def test_git_absent_ne_se_confond_pas_avec_l_absence_de_depot(monkeypatch):
    """Deux causes distinctes, deux messages : sinon on annonce « pas de
    depot git » à quelqu'un qui en a un mais n'a pas installé git."""
    monkeypatch.setattr(config, "SOUS_GIT", None)

    resultat = lintorn.controles.outillage.hook_git.controle_hook_git()

    assert resultat.statut == "INDISPONIBLE"
    assert "git introuvable" in resultat.resume


def test_la_fraicheur_nomme_l_absence_de_depot(tmp_path, monkeypatch):
    """« NON VERIFIABLE (git muet) » était faux : git répondait très bien
    qu'il n'y a pas de dépôt."""
    (tmp_path / "memo.md").write_text("cite `src/x.py`", encoding="utf-8")
    monkeypatch.setattr(config, "MEMOIRE_IA", tmp_path)
    monkeypatch.setattr(config, "SOUS_GIT", False)

    resultat = lintorn.controles.projet.fraicheur_memoire.controle_fraicheur_memoire()

    assert resultat.statut == "INDISPONIBLE"
    assert "pas de depot git" in resultat.resume
    assert "muet" not in resultat.resume


def test_installer_le_hook_hors_depot_ne_laisse_rien_derriere(tmp_path, monkeypatch, capsys):
    """La copie se faisait AVANT le test de git : `git config` échouait, et il
    restait un hook orphelin que le contrôle suivant prenait pour mal branché.
    """
    monkeypatch.setattr(config, "SOUS_GIT", False)
    monkeypatch.setattr(config, "HOOKS", tmp_path / ".lintorn" / "hooks")

    assert lintorn.commandes.hook.installer_hook() == 1
    assert not (tmp_path / ".lintorn").exists(), "un hook orphelin a ete cree"
    assert "pas un depot git" in capsys.readouterr().out


def test_hors_depot_le_perimetre_n_exclut_rien(tmp_path, monkeypatch):
    """Sans dépôt, `.gitignore` n'a pas de sens : on audite tout plutôt que
    de laisser des fichiers sortir de l'audit en silence."""
    monkeypatch.setattr(config, "SOUS_GIT", False)
    fichier = tmp_path / "brouillon.md"

    assert config.hors_gitignore([fichier]) == [fichier]


def test_lecture_du_env_ignore_commentaires_guillemets_et_lignes_vides(tmp_path):
    fichier = tmp_path / ".env"
    fichier.write_text(
        "# un commentaire\n"
        "A=1\n"
        'B = "deux"\n'
        "\n"
        "C='trois'\n"
        "ligne_sans_signe_egal\n",
        encoding="utf-8",
    )

    assert config._lire_env(fichier) == {"A": "1", "B": "deux", "C": "trois"}


def test_un_env_absent_ne_plante_pas(tmp_path):
    """Le .env est FACULTATIF : sans lui, Lintorn doit se comporter comme avant."""
    assert config._lire_env(tmp_path / "aucun.env") == {}


# ─────────────────────────────────────────────────────────────────────────────
# La liste blanche de vulture
# ─────────────────────────────────────────────────────────────────────────────
def test_la_liste_blanche_vulture_est_bien_branchee():
    """Si `VULTURE_IGNORES` cesse d'être passé à l'outil, les 8 faux positifs
    du 12/08/2026 reviennent — et un contrôle qui n'a QUE des faux positifs
    finit par ne plus être lu, donc par ne plus rien protéger.

    Vulture est opt-in : quand le projet ne l'a pas demandé, la commande
    n'existe pas et il n'y a rien à prouver ici.
    """
    entrees = [c for c in config.COMMANDES if c["cle"] == "code_mort"]
    if not entrees:
        pytest.skip("vulture n'est pas active sur ce projet")
    entree = entrees[0]

    assert "--ignore-names" in entree["cmd"]
    passe = entree["cmd"][entree["cmd"].index("--ignore-names") + 1]
    for nom in config.VULTURE_IGNORES:
        assert nom in passe, f"{nom} n'est plus transmis a vulture"


# ─────────────────────────────────────────────────────────────────────────────
# La fraîcheur de l'audit complet
# ─────────────────────────────────────────────────────────────────────────────
def _etat(tmp_path, monkeypatch, contenu):
    fichier = tmp_path / "etat.json"
    if contenu is not None:
        fichier.write_text(contenu, encoding="utf-8")
    monkeypatch.setattr(config, "ETAT", fichier)
    # Un outil lent accordé : sans lui, le contrôle n'a rien à rafraîchir. Pris
    # dans la config du dépôt, le test dépendait de ce que CE dépôt active.
    monkeypatch.setattr(config, "COMMANDES", [{
        "cle": "failles", "titre": "Failles", "cmd": ["x"], "cwd": tmp_path,
        "bloquant": False, "traduction": None, "lent": True}])
    return fichier


def test_audit_complet_jamais_lance_le_signale(tmp_path, monkeypatch):
    _etat(tmp_path, monkeypatch, None)

    resultat = lintorn.controles.outillage.audit_complet.controle_audit_complet()

    assert resultat.statut == "VERIF"
    assert "jamais" in resultat.resume
    assert resultat.bloquant is False


def test_audit_complet_recent_est_vert(tmp_path, monkeypatch):
    _etat(tmp_path, monkeypatch,
          json.dumps({"dernier_audit_complet": date.today().isoformat()}))

    assert lintorn.controles.outillage.audit_complet.controle_audit_complet().statut == "OK"


def test_audit_complet_perime_reclame_une_relance(tmp_path, monkeypatch):
    """C'est ce silence-là qui a laissé dormir 3 failles de securite : ni
    `--rapide` ni le hook pre-push ne lancent pip-audit."""
    vieux = date.today() - timedelta(days=config.JOURS_AUDIT_COMPLET + 1)
    _etat(tmp_path, monkeypatch,
          json.dumps({"dernier_audit_complet": vieux.isoformat()}))

    resultat = lintorn.controles.outillage.audit_complet.controle_audit_complet()

    assert resultat.statut == "VERIF"
    assert "pip-audit" in resultat.detail
    assert resultat.bloquant is False, "un rappel ne doit jamais bloquer un push"


def test_un_etat_illisible_ne_plante_pas(tmp_path, monkeypatch):
    """Fichier tronqué par un Ctrl-C : Lintorn repart de zéro, il ne casse pas."""
    _etat(tmp_path, monkeypatch, "{ceci n'est pas du json")

    assert base.lire_etat() == {}


# ─────────────────────────────────────────────────────────────────────────────
# La mise à jour des paquets vulnérables
# ─────────────────────────────────────────────────────────────────────────────
def test_les_versions_se_comparent_en_nombres_pas_en_texte():
    """Comparées comme des CHAÎNES, "6.9.0" passe pour plus récent que
    "6.15.0" — et Lintorn proposerait de REVENIR en arrière sur un correctif."""
    assert lintorn.commandes.securite._version_tuple("6.15.0") > lintorn.commandes.securite._version_tuple("6.9.0")
    assert max(["6.9.0", "6.15.0"], key=lintorn.commandes.securite._version_tuple) == "6.15.0"
    assert lintorn.commandes.securite._version_tuple("50.0.0") > lintorn.commandes.securite._version_tuple("49.0.0")


# ─────────────────────────────────────────────────────────────────────────────
# Les défauts non invasifs
# ─────────────────────────────────────────────────────────────────────────────
def test_aucune_regle_maison_n_est_livree_avec_l_outil():
    """Une règle maison décrit UN projet : le paquet ne doit en imposer aucune.

    Livrées dans l'outil, les règles d'un projet produisaient chez les autres
    des alertes incompréhensibles — ou un vert rassurant sur un contrôle qui
    ne scannait aucun fichier. Elles viennent désormais TOUTES de la config du
    projet audité : sans config, la liste est vide.

    ⚠️ La question « ce dépôt déclare-t-il des règles ? » se pose aux DEUX
    sources. Posée au seul `config.toml`, elle est devenue fausse le jour où
    `regles.toml` est apparu — et ce test a echoue en le disant.
    """
    if config._regles_brutes():
        return      # ce dépôt-ci en déclare : rien à prouver ici
    assert config.REGLES_MAISON == []


def test_les_liens_du_readme_sont_absolus():
    """`README.md` EST la description PyPI, servie sans le depot autour.

    Un lien relatif y pointe dans le vide. `[AGPL-3.0](LICENSE)` etait casse
    sur la page PyPI depuis le debut sans que personne le voie.
    """
    readme = config.RACINE / "README.md"
    if not readme.is_file():
        pytest.skip("pas de README.md a la racine")

    cibles = re.findall(r"\]\(([^)]+)\)", readme.read_text(encoding="utf-8"))
    relatifs = [c for c in cibles if not c.startswith(("http://", "https://", "#"))]

    assert not relatifs, f"liens relatifs sur la page PyPI : {relatifs}"


def test_les_controles_invasifs_sont_desactives_par_defaut():
    """Le premier lancement doit être INCAPABLE de faire du dégât.

    pytest exécute le code du projet, pip-audit sort sur le réseau,
    `verifier_donnees` ouvre la base. Quelqu'un qui découvre Lintorn le lance
    dans un dépôt qu'il connaît mal : rien de tout ça ne doit partir sans un
    accord explicite. C'est la condition pour qu'on ose l'essayer.
    """
    actifs = config.PROJET.get("controles", {})
    for cle in ("tests", "failles", "failles_npm", "failles_osv", "donnees_metier",
                "code_mort", "deploy"):
        if actifs.get(cle):
            continue    # activé explicitement par ce projet : c'est son droit
        assert not any(c["cle"] == cle for c in config.COMMANDES), (
            f"'{cle}' tourne alors que personne ne l'a demande"
        )


def test_zero_chemin_cite_n_est_pas_un_succes(tmp_path):
    """Des documents lus mais aucun chemin cité = rien n'a été vérifié.

    Trouvé en pointant Lintorn sur un projet Go dont le README ne contenait
    aucun backtick : le contrôle affichait « OK — 0 chemin cité », donc un
    feu vert sur une documentation qu'il n'avait pas pu contrôler. C'est le
    jumeau exact du garde-fou « aucun document trouvé ».
    """
    doc = tmp_path / "README.md"
    doc.write_text("Un projet tres bien, sans le moindre backtick.", encoding="utf-8")

    resultat = lintorn.controles.projet.doc_vs_code._verifier_documents("t", [doc], bloquant_possible=True)

    assert resultat.statut == "INDISPONIBLE"
    assert resultat.bloquant is False
    assert "AUCUN chemin" in resultat.resume


def test_les_controles_d_outillage_ne_valent_pas_un_audit():
    """Le hook et la fraîcheur parlent de Lintorn, pas du projet.

    Ils peuvent être verts sur un dépôt où aucun autre contrôle n'a tourné.
    Les compter comme « un audit a eu lieu » redonnerait un feu vert à un
    projet dont rien n'a été vérifié.
    """
    for titre in lintorn.controles.outillage.TITRES_OUTILLAGE:
        assert titre not in ("Doc vs code", "Regles maison"), (
            "un controle du PROJET a ete classe comme outillage"
        )

    # Comparé aux titres RÉELLEMENT émis : un titre mal orthographié ici
    # classe le contrôle du côté PROJET, et un compteur ne verrait rien.
    emis = {
        lintorn.controles.outillage.configuration.controle_configuration().titre,
        lintorn.controles.outillage.hook_git.controle_hook_git().titre,
        lintorn.controles.outillage.audit_complet.controle_audit_complet().titre,
        lintorn.controles.outillage.python_projet.controle_python_projet().titre,
    }
    assert emis == set(lintorn.controles.outillage.TITRES_OUTILLAGE)


# ─────────────────────────────────────────────────────────────────────────────
# `hors_portee` — une decision assumee, jamais un bouton « silence »
# ─────────────────────────────────────────────────────────────────────────────
def _hors_portee(monkeypatch, raison, source="CLAUDE.md:50", tests=()):
    monkeypatch.setattr(config, "HORS_PORTEE",
                        [{"nom": "Versions", "source": source, "raison": raison}])
    monkeypatch.setattr(lintorn.controles.projet.regles_enoncees, "_tests_du_projet", lambda: set(tests))
    return lintorn.controles.projet.regles_enoncees._hors_portee_tenables()


def test_une_declaration_sans_test_cite_est_tenable(monkeypatch):
    """Un jugement (« un motif crierait sur du code correct ») n'a rien a
    prouver : il se lit, il se conteste. Il n'y a pas de promesse dedans."""
    tenables, rompues = _hors_portee(monkeypatch, "un motif crierait sur du code correct")

    assert tenables == {"CLAUDE.md:50": "un motif crierait sur du code correct"}
    assert rompues == []


def test_un_test_cite_qui_existe_couvre_la_regle(monkeypatch):
    tenables, rompues = _hors_portee(monkeypatch, "couverte par test_deux_versions",
                                     tests=["test_deux_versions"])

    assert "CLAUDE.md:50" in tenables
    assert rompues == []


def test_un_test_cite_qui_a_disparu_rouvre_la_regle(monkeypatch):
    """C'EST le garde-fou. Sans lui, une phrase suffirait a faire taire le
    controle pour toujours : il suffirait d'annoncer un test imaginaire."""
    tenables, rompues = _hors_portee(monkeypatch, "couverte par test_envole",
                                     tests=["test_un_autre"])

    assert tenables == {}
    assert len(rompues) == 1
    assert "test_envole" in rompues[0]


def test_hors_portee_sans_source_est_refuse(monkeypatch):
    """Sans `source`, la declaration ne designe aucune ligne de doc : elle ne
    peut donc couvrir personne."""
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])
    monkeypatch.setattr(config, "_regles_brutes", lambda: [
        {"nom": "orpheline", "racine": "", "hors_portee": "parce que"},
    ])

    assert config._regles_du_projet() == ([], [])
    assert "`source`" in config.SOUCIS_CONFIG[0]


def test_un_motif_et_un_hors_portee_ensemble_sont_refuses(monkeypatch):
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])
    monkeypatch.setattr(config, "_regles_brutes", lambda: [
        {"nom": "ambigue", "racine": "", "suffixes": [".md"],
         "source": "CLAUDE.md:1", "motif": "a", "hors_portee": "parce que"},
    ])

    assert config._regles_du_projet() == ([], [])
    assert "UN seul" in config.SOUCIS_CONFIG[0]


def test_le_compte_des_hors_portee_reste_affiche(monkeypatch):
    """Les faire disparaitre du resume rendrait la declaration gratuite. Le
    ratio visible est ce qui rend un abus reperable."""
    monkeypatch.setattr(config, "DOCS_IA", [config.RACINE / "CLAUDE.md"])
    # Les règles du VRAI regles.toml visent les vraies lignes de CLAUDE.md, pas la 50.
    monkeypatch.setattr(config, "REGLES_MAISON", [])
    monkeypatch.setattr(lintorn.controles.projet.regles_enoncees, "regles_enoncees",
                        lambda: [("CLAUDE.md", 50, "Versions | ...", ["versions"])])
    monkeypatch.setattr(lintorn.controles.projet.regles_enoncees, "regles_sans_controle",
                        lambda: [("CLAUDE.md", 50, "Versions | ...", ["versions"])])
    _hors_portee(monkeypatch, "couverte par test_deux", tests=["test_deux"])

    resultat = lintorn.controles.projet.regles_enoncees.controle_regles_declarees()

    assert resultat.statut == "OK"
    assert "1 hors de portee" in resultat.resume


# ─────────────────────────────────────────────────────────────────────────────
# `motif_requis` et `si` — dire « ce texte DOIT etre la », et sous condition
# ─────────────────────────────────────────────────────────────────────────────
def test_un_motif_requis_present_ne_declenche_rien(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("la mention obligatoire est la", encoding="utf-8")
    _regle(tmp_path, monkeypatch, motif_requis="obligatoire")

    assert lintorn.controles.projet.regles_maison.controle_regles_maison().statut == "OK"


def test_un_motif_requis_absent_est_une_infraction(tmp_path, monkeypatch):
    """L'inverse d'un motif interdit : c'est le SILENCE qui est fautif.

    Une règle ne savait dire que « ce texte est interdit ». « Toute LRAR doit
    citer le relevé » n'était donc pas exprimable.
    """
    (tmp_path / "a.md").write_text("rien de la mention attendue", encoding="utf-8")
    _regle(tmp_path, monkeypatch, motif_requis="obligatoire", bloquant=True)

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.statut == "ALERTE"
    assert resultat.bloquant is True
    assert "manque dans 1" in resultat.resume


def test_si_restreint_la_regle_aux_fichiers_concernes(tmp_path, monkeypatch):
    """« Si 110 apparait, alors 69 doit apparaitre aussi » : le fichier qui ne
    parle pas de 110 n'est pas fautif, la regle ne le concerne pas."""
    (tmp_path / "concerne.md").write_text("le total de 110 et le 69 declare", encoding="utf-8")
    (tmp_path / "hors_sujet.md").write_text("un texte sans aucun chiffre", encoding="utf-8")
    _regle(tmp_path, monkeypatch, motif_requis=r"\b69\b", si=r"\b110\b")

    assert lintorn.controles.projet.regles_maison.controle_regles_maison().statut == "OK"


def test_si_rempli_sans_le_motif_requis_declenche(tmp_path, monkeypatch):
    (tmp_path / "fautif.md").write_text("le total de 110, sans sa source", encoding="utf-8")
    _regle(tmp_path, monkeypatch, motif_requis=r"\b69\b", si=r"\b110\b", bloquant=True)

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.statut == "ALERTE"
    assert "manque dans 1" in resultat.resume


def test_une_conditionnelle_jamais_declenchee_n_est_pas_tenue(tmp_path, monkeypatch):
    """Sa condition n'est jamais tombée : elle n'a rien vérifié. Ce n'est pas
    une faute, mais la compter « tenue » gonflerait le verdict."""
    (tmp_path / "a.md").write_text("un texte sans aucun chiffre", encoding="utf-8")
    _regle(tmp_path, monkeypatch, motif_requis=r"\b69\b", si=r"\b110\b")

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert "0 regle(s) tenue(s)" in resultat.resume
    assert "1 jamais declenchee(s)" in resultat.resume


def test_declarer_les_deux_sens_est_refuse(monkeypatch):
    """`motif` ET `motif_requis` : Lintorn devrait deviner lequel appliquer.
    Deviner, c'est appliquer une regle que personne n'a ecrite."""
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])
    monkeypatch.setattr(config, "_regles_brutes", lambda: [
        {"nom": "ambigue", "racine": "", "suffixes": [".md"],
         "motif": "a", "motif_requis": "b"},
    ])

    assert config._regles_du_projet() == ([], [])
    assert "UN seul" in config.SOUCIS_CONFIG[0]


def test_une_regle_sans_aucun_motif_est_refusee(monkeypatch):
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])
    monkeypatch.setattr(config, "_regles_brutes", lambda: [
        {"nom": "vide", "racine": "", "suffixes": [".md"]},
    ])

    assert config._regles_du_projet() == ([], [])
    assert len(config.SOUCIS_CONFIG) == 1


# ─────────────────────────────────────────────────────────────────────────────
# La config qu'on n'a pas pu lire — elle doit PARLER
# ─────────────────────────────────────────────────────────────────────────────
def test_une_regle_au_motif_invalide_est_signalee(monkeypatch):
    """Une regex cassée écarte la règle : encore faut-il le dire.

    Écartée en silence, « Regles maison » annonçait « toutes les regles sont
    tenues » sur les survivantes.
    """
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])
    monkeypatch.setattr(config, "_regles_brutes", lambda: [
        {"nom": "motif casse", "racine": "", "suffixes": [".py"], "motif": "((("},
    ])

    assert config._regles_du_projet() == ([], [])
    assert len(config.SOUCIS_CONFIG) == 1
    assert "motif casse" in config.SOUCIS_CONFIG[0]


def test_un_toml_illisible_ne_repart_pas_sur_les_defauts_en_silence(tmp_path, monkeypatch):
    """Repartir sur les défauts est le bon choix. Le taire ne l'est pas.

    Avec un `config.toml` mal formé, `docs_exclus`, les contrôles coupés et
    les règles maison étaient ignorés — sans un mot dans le rapport.
    """
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])
    casse = tmp_path / "config.toml"
    casse.write_text('docs_exclus = [ "oups"', encoding="utf-8")

    assert config._charger_toml(casse) is None
    assert "config.toml illisible" in config.SOUCIS_CONFIG[0]

    resultat = lintorn.controles.outillage.configuration.controle_configuration()
    assert resultat.statut == "ALERTE"
    assert resultat.bloquant is False, "une virgule de TOML ne bloque pas un push"
    assert "NON CHARGEE" in resultat.resume


def test_sans_souci_la_config_dit_ce_qu_elle_a_lu(monkeypatch):
    """Le vert doit porter son DÉNOMINATEUR : sans lui, on ne distingue pas
    « tout va bien » de « je n'ai rien ouvert »."""
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])
    monkeypatch.setattr(config, "FICHIERS_CONFIG_LUS", ["config.toml"])
    monkeypatch.setattr(config, "REGLES_MAISON", [{"nom": "x"}])

    resultat = lintorn.controles.outillage.configuration.controle_configuration()

    assert resultat.statut == "OK"
    assert "config.toml" in resultat.resume
    assert "1 regle(s)" in resultat.resume


def test_un_fichier_de_config_n_est_compte_qu_une_fois(monkeypatch):
    """`_regles_brutes()` est appelable plusieurs fois : le dénominateur ne
    doit pas gonfler à chaque appel."""
    monkeypatch.setattr(config, "FICHIERS_CONFIG_LUS", [])
    config._regles_brutes()
    config._regles_brutes()

    assert config.FICHIERS_CONFIG_LUS.count("regles.toml") <= 1


def test_aucun_fichier_de_config_n_est_pas_un_feu_vert(monkeypatch):
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])
    monkeypatch.setattr(config, "FICHIERS_CONFIG_LUS", [])

    assert lintorn.controles.outillage.configuration.controle_configuration().statut == "INDISPONIBLE"


# ─────────────────────────────────────────────────────────────────────────────
# Une règle maison qui scanne le VIDE
# ─────────────────────────────────────────────────────────────────────────────


def test_une_regle_qui_ne_lit_aucun_fichier_n_est_pas_verte(tmp_path, monkeypatch):
    """Zéro fichier lu = zéro protection, et ça s'affichait « tenue ».

    Des `suffixes` qui ne correspondent plus, un dossier vidé, un `exclure`
    trop large : la règle scanne le néant et passait pour respectée.
    """
    (tmp_path / "note.md").write_text("interdit", encoding="utf-8")
    _regle(tmp_path, monkeypatch, suffixes=[".html"])   # aucun .html ici

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.statut == "VERIF", "un vert sur zero fichier lu"
    assert "AUCUN fichier" in resultat.resume
    assert "0 tenue(s)" in resultat.resume, "une regle a vide n'est pas « tenue »"
    assert resultat.bloquant is False


def test_une_regle_tenue_annonce_combien_de_fichiers_elle_a_lus(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("rien a signaler", encoding="utf-8")
    (tmp_path / "b.md").write_text("rien non plus", encoding="utf-8")
    _regle(tmp_path, monkeypatch, suffixes=[".md"])

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.statut == "OK"
    assert "2 fichier(s) lu(s)" in resultat.resume
    assert "toutes" not in resultat.resume, (
        "« toutes les regles sont tenues » ne dit ni combien ni sur quoi"
    )


def test_un_fichier_exclu_ne_gonfle_pas_le_denominateur(tmp_path, monkeypatch):
    """`exclure` retire le fichier de la lecture : le compter mentirait sur
    l'étendue réelle du contrôle."""
    (tmp_path / "a.md").write_text("rien", encoding="utf-8")
    (tmp_path / "archive.md").write_text("interdit", encoding="utf-8")
    _regle(tmp_path, monkeypatch, suffixes=[".md"], exclure=["archive.md"])

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.statut == "OK", "le fichier exclu ne doit pas declencher"
    assert "1 fichier(s) lu(s)" in resultat.resume


# ─────────────────────────────────────────────────────────────────────────────
# Le python qui audite — le repli doit rester VISIBLE
# ─────────────────────────────────────────────────────────────────────────────
def _sans_venv(tmp_path, monkeypatch, py_racine=None, venv=None, souci=None):
    """Place le contrôle dans une situation donnée, sans toucher au disque."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "PY_RACINE", py_racine)
    monkeypatch.setattr(config, "VENV_PROJET", venv)
    monkeypatch.setattr(config, "VENV_SOUCI", souci)
    monkeypatch.setattr(config, "PYTHON", "/usr/bin/python3")
    return lintorn.controles.outillage.python_projet.controle_python_projet()


def test_le_repli_sur_un_autre_python_ne_passe_plus_inapercu(tmp_path, monkeypatch):
    """LA panne que ce contrôle existe pour supprimer.

    Faute de venv, `_python_du_projet()` retombe sur `sys.executable` — le
    python de la MACHINE depuis que Lintorn s'installe par pip. `pip-audit`
    audite alors les failles du système, `Dependances vs venv` compare
    `requirements.txt` aux paquets du système, et les deux RÉPONDENT : un
    verdict plausible sur le mauvais environnement.

    Rien ne le signalait, parce que rien ne pouvait le savoir : la détection
    ne rendait qu'une chaîne, où le repli était indiscernable d'une trouvaille.
    """
    resultat = _sans_venv(tmp_path, monkeypatch, py_racine=tmp_path)

    assert resultat.statut == "ALERTE", "le repli redevient muet"
    assert "aucun venv" in resultat.resume
    # Non bloquant : un projet peut légitimement n'avoir pas encore de venv.
    # Bloquer ferait de ce contrôle une gêne qu'on apprend à contourner.
    assert resultat.bloquant is False


def test_un_projet_sans_python_ne_reclame_pas_de_venv(tmp_path, monkeypatch):
    """Un projet Go ou JavaScript n'a aucun python — et c'est normal.

    Alerter là fabriquerait le faux positif qu'on apprend à ignorer, ce qui
    tuerait la valeur du contrôle sur les projets qui, eux, en ont besoin.
    Mais `OK` mentirait aussi : rien n'a été vérifié.
    """
    resultat = _sans_venv(tmp_path, monkeypatch, py_racine=None)

    assert resultat.statut == "INDISPONIBLE", "ni alerte injustifiee, ni faux vert"
    assert "rien a verifier" in resultat.resume


def test_un_venv_declare_mais_absent_ne_se_replie_pas_en_silence(tmp_path, monkeypatch):
    """Le projet a répondu à la question, et sa réponse est fausse.

    C'est le pire cas : quelqu'un a pris la peine de déclarer où chercher.
    Se rabattre sans rien dire sur un autre python trahirait cette confiance
    — il croirait auditer son venv.
    """
    resultat = _sans_venv(tmp_path, monkeypatch, py_racine=tmp_path,
                          souci="venv declare introuvable : ../ailleurs")

    assert resultat.statut == "ALERTE"
    assert "introuvable" in resultat.resume
    # Le chemin DÉCLARÉ, pas sa forme absolue : celle-ci porte le nom de
    # l'utilisateur et de sa machine, or ce resume part dans un rapport versionné.
    assert str(tmp_path) not in resultat.resume


def test_un_venv_hors_du_projet_n_est_pas_pris_pour_le_sien(tmp_path, monkeypatch):
    """`VIRTUAL_ENV` renseigné ne désigne pas forcément le venv DU PROJET.

    Développer Lintorn, c'est activer le venv de Lintorn. Le prendre pour
    celui du projet audité reviendrait à auditer un projet avec
    l'environnement de l'outil — précisément ce que tout ce fichier interdit.
    """
    etranger = tmp_path / "ailleurs" / ".venv"
    (etranger / "bin").mkdir(parents=True)
    (etranger / "bin" / "python").write_text("", encoding="utf-8")

    projet = tmp_path / "projet"
    projet.mkdir()
    monkeypatch.setenv("VIRTUAL_ENV", str(etranger))
    monkeypatch.setattr(config, "RACINE", projet)
    monkeypatch.setattr(config, "BACKEND", None)
    monkeypatch.setattr(config, "PY_RACINE", projet)
    monkeypatch.setattr(config, "PROJET", {})

    _, venv, _ = config._python_du_projet()

    assert venv is None, "un venv EXTERIEUR au projet a ete pris pour le sien"


def test_le_venv_declare_par_le_projet_prime_sur_les_conventions(tmp_path, monkeypatch):
    """Poetry, pdm et conda rangent leur venv hors du projet.

    Aucune convention de nom ne permet de le deviner. Sans cette porte de
    sortie, ces projets seraient condamnés à une alerte qu'ils ne peuvent pas
    lever — donc à apprendre à l'ignorer.
    """
    ailleurs = tmp_path / "caches" / "mon-venv"
    (ailleurs / "bin").mkdir(parents=True)
    (ailleurs / "bin" / "python").write_text("", encoding="utf-8")

    projet = tmp_path / "projet"
    (projet / ".venv" / "bin").mkdir(parents=True)
    (projet / ".venv" / "bin" / "python").write_text("", encoding="utf-8")

    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(config, "RACINE", projet)
    monkeypatch.setattr(config, "BACKEND", None)
    monkeypatch.setattr(config, "PY_RACINE", projet)
    monkeypatch.setattr(config, "PROJET", {"venv": "../caches/mon-venv"})

    _, venv, souci = config._python_du_projet()

    assert souci is None
    assert venv == ailleurs, "la declaration du projet doit avoir le dernier mot"


def test_un_venv_nomme_env_est_trouve(tmp_path, monkeypatch):
    """`env/` est une convention aussi repandue que `venv/` et `.venv/`.

    Elle manquait a la liste : ces projets tombaient dans le repli silencieux
    sans avoir rien fait de particulier.
    """
    (tmp_path / "env" / "bin").mkdir(parents=True)
    (tmp_path / "env" / "bin" / "python").write_text("", encoding="utf-8")

    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "BACKEND", None)
    monkeypatch.setattr(config, "PY_RACINE", tmp_path)
    monkeypatch.setattr(config, "PROJET", {})

    _, venv, _ = config._python_du_projet()

    assert venv == tmp_path / "env"


def test_le_verdict_ne_dement_plus_le_rapport(capsys):
    """Une alerte NON BLOQUANTE doit survivre jusqu'au verdict.

    Le hook pre-push et le python qui audite sont non bloquants par
    construction : quand le hook n'est pas branche, bloquer un push serait de
    toute facon impossible. `en_echec` ne les retenait donc pas, et la derniere
    ligne annoncait « rien a signaler » trois lignes sous un `[ !! ]` disant
    que `git push` ne controlait plus rien.

    Qui ne lit que le verdict — tout le monde, une fois l'outil devenu routine
    — repartait en croyant son push protege par un hook mort.
    """
    resultats = [
        Resultat("Doc vs code", "OK", "12 chemins"),
        Resultat("Hook pre-push (Lintorn)", "ALERTE",
                 "NON BRANCHE - `git push` ne controle RIEN", bloquant=False),
        Resultat("Ruff (lint Python)", "INDISPONIBLE", "pas installe", bloquant=False),
    ]

    combien = lintorn.rapport.console.signaler_non_bloquants(resultats)
    sortie = capsys.readouterr().out

    assert combien == 1
    assert "Hook pre-push" in sortie, "l'alerte non bloquante reste invisible"
    # INDISPONIBLE n'est PAS une alerte : le compter noierait les vraies sous
    # le bruit des outils absents, et on reapprendrait a ignorer la ligne.
    assert "Ruff" not in sortie


def test_une_alerte_bloquante_n_est_pas_comptee_deux_fois(capsys):
    """Les bloquantes ont deja leur liste juste au-dessus.

    Les repeter ferait passer le meme probleme pour deux, et brouillerait la
    seule distinction qui compte au moment de pusher : ce qui arrete le push,
    et ce qui se contente de le signaler.
    """
    resultats = [Resultat("Ruff (lint Python)", "ALERTE", "3 lignes", bloquant=True)]

    combien = lintorn.rapport.console.signaler_non_bloquants(resultats)

    assert combien == 0
    assert capsys.readouterr().out == ""


def test_tout_controle_declare_actif_est_reellement_branche():
    """Un contrôle actif dans `config` mais absent de `noyau` est SAUTÉ.

    `executer()` filtre par `nom in CONTROLES_INTERNES` : un nom oublié dans
    le noyau ne provoque ni erreur, ni ligne au rapport, ni même un
    `INDISPONIBLE`. Le contrôle disparaît purement et simplement, et
    l'utilisateur le croit tenu parce qu'il l'a activé dans sa config.

    C'est la panne exacte que tout ce dépôt combat, à l'endroit qui la rendrait
    la plus invisible : l'aiguillage lui-même.
    """
    declares = set(config.CONTROLES_INTERNES)
    branches = set(noyau.CONTROLES_INTERNES)

    assert declares == branches, (
        f"declares sans etre branches (donc muets) : {sorted(declares - branches)} | "
        f"branches sans etre declares (donc morts) : {sorted(branches - declares)}"
    )


def test_docs_exclus_accepte_les_globs_traversants(tmp_path, monkeypatch):
    """`docs_exclus` doit écarter toute une arborescence, pas juste un niveau.

    Première version écrite avec `Path.match` : `**` n'y est un glob récursif
    qu'à partir de Python 3.13, alors que Lintorn tourne dès 3.11. Les motifs
    étaient donc silencieusement ignorés — l'utilisateur configurait une
    exclusion qui ne s'appliquait jamais, sans le moindre avertissement.
    """
    chemins = ["docs/en/tutorial/index.md", "docs/fr/advanced/x.md", "README.md"]
    gardes = [c for c in chemins if not fnmatch(c, "docs/*")]

    assert gardes == ["README.md"], "le glob ne traverse pas les sous-dossiers"


# ─────────────────────────────────────────────────────────────────────────────
# Le périmètre : ce que git ignore n'appartient pas au projet
# ─────────────────────────────────────────────────────────────────────────────
def _petit_depot(tmp_path, gitignore, fichiers):
    """Un vrai dépôt git jetable — `git check-ignore` ne se simule pas."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / ".gitignore").write_text(gitignore, encoding="utf-8")
    crees = []
    for nom in fichiers:
        chemin = tmp_path / nom
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text("peu importe", encoding="utf-8")
        crees.append(chemin)
    return crees


def test_un_fichier_ignore_par_git_sort_du_perimetre(tmp_path, monkeypatch):
    """Une note perso citant un fichier « a creer un jour » rendait l'audit
    rouge, donc bloquait un push — pour un brouillon qui ne part meme pas sur
    le depot."""
    prive, public = _petit_depot(tmp_path, ".notes/\n", [".notes/reprise.md", "README.md"])
    monkeypatch.setattr(config, "RACINE", tmp_path)
    # Dit explicitement : sinon le test depend du dossier d'ou on le lance, et
    # echoue depuis l'archive publiee, qui n'a pas de `.git`.
    monkeypatch.setattr(config, "SOUS_GIT", True)

    gardes = config.hors_gitignore([prive, public])

    assert gardes == [public], "un fichier ignore par git n'a rien a faire dans l'audit"


def test_un_fichier_deja_suivi_reste_audite(tmp_path, monkeypatch):
    """LA subtilité de `.gitignore` : une règle n'agit que sur ce qui n'est
    PAS encore suivi. Un fichier déjà indexé part malgré tout sur le dépôt —
    il reste donc dans le périmètre, et le taire serait le pire des services.

    C'est aussi pour ça qu'on délègue à `git check-ignore` au lieu de relire
    le `.gitignore` nous-mêmes : il consulte l'index, une réimplémentation
    maison l'oublierait.
    """
    suivi, = _petit_depot(tmp_path, "secret/\n", ["secret/deja_commite.md"])
    subprocess.run(["git", "add", "-f", str(suivi)], cwd=tmp_path,
                   capture_output=True, check=True)
    monkeypatch.setattr(config, "RACINE", tmp_path)

    assert config.hors_gitignore([suivi]) == [suivi]


def test_hors_depot_git_on_n_exclut_rien(tmp_path, monkeypatch):
    """Tous les projets ne sont pas sous git. Dans le doute on garde tout :
    un contrôle de trop se voit et se corrige, un fichier disparu de l'audit
    ne se voit jamais."""
    fichier = tmp_path / "note.md"
    fichier.write_text("peu importe", encoding="utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)

    assert config.hors_gitignore([fichier]) == [fichier]


# ─────────────────────────────────────────────────────────────────────────────
# Le garde-fou que `--init` pose dans `.lintorn/`
# ─────────────────────────────────────────────────────────────────────────────
def _ignore(depot, chemin):
    # check=False EXPRES : `check-ignore` sort en 1 quand rien n'est ignore,
    # et c'est une reponse, pas une panne.
    return subprocess.run(["git", "check-ignore", "-q", "--", chemin],
                          cwd=depot, capture_output=True, check=False).returncode == 0


def test_le_gitignore_interne_se_suffit_a_lui_meme(tmp_path, monkeypatch):
    """Sans TOUCHER au .gitignore du projet : les sorties sortent du depot,
    la config y reste.

    C'est ce qui supprime l'etape « ajoute ces deux lignes a ton .gitignore ».
    Un utilisateur avait copie la ligne de PROSE — backticks compris — et
    oublie la negation : sa config etait ignoree, sans le moindre message.
    Une etape supprimee est une etape qu'on ne peut plus rater.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, capture_output=True, check=True)
    monkeypatch.setattr(config, "RACINE", tmp_path)   # Lintorn n'écrit que DANS le projet
    dossier = tmp_path / ".lintorn"
    dossier.mkdir()
    (dossier / "config.toml").write_text("", encoding="utf-8")
    (dossier / "rapport.md").write_text("", encoding="utf-8")

    lintorn.commandes.dossier_lintorn.poser_gitignore_interne(dossier)

    assert not _ignore(tmp_path, ".lintorn/config.toml"), "la config doit se versionner"
    assert _ignore(tmp_path, ".lintorn/rapport.md"), "le rapport est une sortie, il sort"


def test_une_regle_sur_le_DOSSIER_defait_le_garde_fou(tmp_path, monkeypatch):
    """La limite, connue et assumée : `.lintorn/` (barre finale) exclut le
    dossier, git n'y descend pas, aucune exception interne ne le rattrape.
    `--init` teste donc l'effet obtenu au lieu de le supposer.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, capture_output=True, check=True)
    monkeypatch.setattr(config, "RACINE", tmp_path)
    (tmp_path / ".gitignore").write_text(".lintorn/\n", encoding="utf-8")
    dossier = tmp_path / ".lintorn"
    dossier.mkdir()
    (dossier / "config.toml").write_text("", encoding="utf-8")

    lintorn.commandes.dossier_lintorn.poser_gitignore_interne(dossier)

    assert _ignore(tmp_path, ".lintorn/config.toml"), (
        "si ce cas cesse d'ignorer la config, l'avertissement de --init n'a plus de raison d'etre"
    )


def test_le_gitignore_interne_n_ecrase_jamais_celui_du_dev(tmp_path):
    dossier = tmp_path / ".lintorn"
    dossier.mkdir()
    (dossier / ".gitignore").write_text("a moi\n", encoding="utf-8")

    lintorn.commandes.dossier_lintorn.poser_gitignore_interne(dossier)

    assert (dossier / ".gitignore").read_text(encoding="utf-8") == "a moi\n"


# ─────────────────────────────────────────────────────────────────────────────
# Les outils Python ne sont pas réservés aux projets Django
# ─────────────────────────────────────────────────────────────────────────────
def test_vulture_et_pip_audit_ne_sont_pas_enfermes_dans_django():
    """LE défaut du 21/08/2026, et le plus grave possible pour cet outil.

    `vulture` et `pip-audit` vivaient dans `COMMANDES_DJANGO`, donc n'étaient
    ajoutés que `if BACKEND`. Sur tout projet Python NON-Django — Lintorn
    lui-même compris — un `failles = true` dans la config était ignoré EN
    SILENCE : pas d'audit de sécurité, pas de message, du vert.

    C'est exactement le mode de panne que Lintorn existe pour combattre.
    Ce sont des outils Python, la seule condition qui les concerne est
    l'existence d'une racine Python.
    """
    dans_django = {commande["cle"] for commande in lintorn.outils.django.commandes()}

    assert "code_mort" not in dans_django
    assert "failles" not in dans_django


def test_toute_commande_sait_depuis_ou_elle_se_lance():
    """Un `cwd` à None fait tourner l'outil dans le dossier COURANT.

    `vulture .` y scannerait ce que l'utilisateur a sous les pieds au lieu du
    projet, et rendrait un verdict sur autre chose sans jamais le dire. C'est
    la seconde moitié du même défaut : `cwd = BACKEND` valait None hors Django.
    """
    for commande in config.COMMANDES:
        assert commande["cwd"] is not None, (
            f"{commande['cle']} : sans cwd, l'outil tourne n'importe ou"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Le numéro de version, à deux endroits
# ─────────────────────────────────────────────────────────────────────────────
def test_les_deux_numeros_de_version_sont_d_accord():
    """`CLAUDE.md` l'exige, et aucune règle maison ne peut le vérifier.

    Un seul numéro : celui de `src/lintorn/__init__.py`. `pyproject.toml` ne
    le répète pas, il le LIT (`dynamic`). Deux copies finissaient par diverger :
    PyPI servait `0.2.0` pendant que `lintorn version` annonçait `0.1.1`, et un
    numéro publié étant définitif, le rattrapage coûtait une version entière.

    Une regex lit UN fichier à la fois : c'est donc un test, pas un `[[regles]]`.
    """
    racine = Path(Lintorn.__file__).parents[2]
    pyproject = racine / "pyproject.toml"
    if not pyproject.is_file():
        pytest.skip("paquet installé depuis un wheel : pas de pyproject.toml autour")
    donnees = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    assert "version" not in donnees["project"], "pyproject.toml repete la version : elle doit venir de __init__.py"
    assert "version" in donnees["project"].get("dynamic", [])
    source = racine / donnees["tool"]["hatch"]["version"]["path"]
    assert source.resolve() == Path(Lintorn.__file__).with_name("__init__.py").resolve()
    assert f'__version__ = "{__version__}"' in source.read_text(encoding="utf-8")


def test_les_motifs_de_regles_sont_compiles_en_multiline():
    """Sans MULTILINE, `^` designe le debut du FICHIER, pas celui d'une ligne.

    Une règle maison est ligne-orientée : on écrit `^\\s+print\\(` pour dire
    « une ligne qui commence par ». Compilée sans le drapeau, une telle règle
    ne matche JAMAIS — et affiche vert sans rien contrôler.

    Ce n'est pas theorique : la règle « print() de debogage oublie » de ce
    dépôt était morte depuis le jour de son écriture. Un contrôle vert qui ne
    contrôle rien, c'est la panne que Lintorn existe pour combattre.
    """
    if not config.REGLES_MAISON:
        pytest.skip("ce depot ne declare aucune regle maison")

    for regle in config.REGLES_MAISON:
        assert regle["motif"].flags & re.MULTILINE, (
            f"{regle['nom']} : motif compile sans MULTILINE, un ^ n'y matchera jamais"
        )


# ─────────────────────────────────────────────────────────────────────────────
# --installer-outils : ne proposer que ce que le projet appelle
# ─────────────────────────────────────────────────────────────────────────────


def _front_npm(dossier, verrou=True):
    (dossier / "package.json").write_text("{}", encoding="utf-8")
    if verrou:
        (dossier / config.VERROU_NPM).write_text("{}", encoding="utf-8")
    return dossier


def test_sans_python_aucun_outil_python_n_est_propose(tmp_path, monkeypatch):
    """Le besoin d'origine : un front seul n'a que faire de pip-audit."""
    _projet_detecte(monkeypatch, front=_front_npm(tmp_path))

    noms = [outil["nom"] for outil in lintorn.commandes.outils._outillage_du_projet()]

    assert noms == ["npm audit"]


def test_sans_front_npm_audit_n_est_pas_propose(tmp_path, monkeypatch):
    _projet_detecte(monkeypatch, py=tmp_path)

    noms = [outil["nom"] for outil in lintorn.commandes.outils._outillage_du_projet()]

    assert "pip-audit" in noms
    assert "npm audit" not in noms


def test_un_front_sans_verrou_ne_propose_pas_npm_audit(tmp_path, monkeypatch):
    _projet_detecte(monkeypatch, front=_front_npm(tmp_path, verrou=False))

    assert lintorn.commandes.outils._outillage_du_projet() == []


def test_l_etat_d_activation_suit_la_config(tmp_path, monkeypatch):
    _projet_detecte(monkeypatch, py=tmp_path, controles={"failles": True})

    actif = {outil["nom"]: outil["actif"] for outil in lintorn.commandes.outils._outillage_du_projet()}

    assert actif["pip-audit"] is True
    assert actif["pytest"] is False
    assert actif["ruff"] is True, "ruff n'a pas de cle : il tourne toujours"


_CONFIG_DE_INIT = (
    "[controles]\n"
    "tests          = true    # pytest — EXECUTE le code du projet\n"
    "# failles_npm    = false   # npm audit — sort sur le RESEAU\n"
    "\n"
    "[[regles]]\n"
    'nom = "x"\n'
)


def test_activer_decommente_la_ligne_existante():
    """Le commentaire de la ligne reste : il dit ce que l'accord implique."""
    texte = lintorn.commandes.outils._activer_dans(_CONFIG_DE_INIT, "controles", "failles_npm")

    assert "failles_npm    = true   # npm audit — sort sur le RESEAU" in texte
    assert texte.count("failles_npm") == 1, "une seconde ligne rendrait le TOML invalide"
    assert tomllib.loads(texte)["controles"] == {"tests": True, "failles_npm": True}


def test_activer_une_cle_absente_l_ajoute_sous_sa_table():
    source = '[controles]\ntests = true\n\n[[regles]]\nnom = "x"\n'

    lu = tomllib.loads(lintorn.commandes.outils._activer_dans(source, "controles", "failles_npm"))

    assert lu["controles"] == {"tests": True, "failles_npm": True}
    assert lu["regles"] == [{"nom": "x"}], "la cle a atterri dans une AUTRE table"


def test_activer_sans_table_la_cree():
    texte = lintorn.commandes.outils._activer_dans('venv = "env"\n', "controles", "failles")

    assert tomllib.loads(texte) == {"venv": "env", "controles": {"failles": True}}


def test_activer_ne_touche_pas_la_cle_homonyme_d_une_autre_table():
    texte = lintorn.commandes.outils._activer_dans("[controles]\n\n[autre]\n# failles = false\n",
                                  "controles", "failles")

    assert tomllib.loads(texte)["controles"] == {"failles": True}
    assert "# failles = false" in texte, "la ligne d'une autre table a ete modifiee"


def test_activer_dans_un_pyproject_vise_tool_lintorn():
    source = '[project]\nname = "x"\n\n[tool.lintorn.controles]\n# failles = false\n'

    lu = tomllib.loads(lintorn.commandes.outils._activer_dans(source, "tool.lintorn.controles", "failles"))

    assert lu["tool"]["lintorn"]["controles"] == {"failles": True}
    assert lu["project"] == {"name": "x"}




def test_activer_ecrit_la_config_que_lintorn_a_lue(tmp_path, monkeypatch):
    fichier = _config_lue(tmp_path, monkeypatch, _CONFIG_DE_INIT)

    assert lintorn.commandes.outils._activer(["failles_npm"]) == ".lintorn/config.toml"
    assert tomllib.loads(fichier.read_text(encoding="utf-8"))["controles"]["failles_npm"] is True


def test_une_config_que_la_retouche_casserait_n_est_pas_ecrite(tmp_path, monkeypatch, capsys):
    """Une config cassée ferait repartir Lintorn sur ses DÉFAUTS : tous les
    contrôles opt-in coupés d'un coup. Mieux vaut ne rien écrire, et le dire."""
    en_ligne = "controles = { tests = true }\n"      # table en ligne : pas d'en-tête
    fichier = _config_lue(tmp_path, monkeypatch, en_ligne)

    assert lintorn.commandes.outils._activer(["failles_npm"]) is None
    assert fichier.read_text(encoding="utf-8") == en_ligne
    assert "failles_npm = true" in capsys.readouterr().out, "l'utilisateur doit savoir quoi ecrire"


# ─────────────────────────────────────────────────────────────────────────────
# Une option inconnue n'est pas un audit
# ─────────────────────────────────────────────────────────────────────────────
def test_une_option_mal_tapee_ne_lance_aucun_audit(monkeypatch, capsys):
    """`lintorn --vresion` lançait un audit complet : l'option inconnue était
    ignorée en silence, et l'outil faisait autre chose que ce qu'on demandait."""
    monkeypatch.setattr("sys.argv", ["lintorn", "--vresion"])
    monkeypatch.setattr(noyau, "executer", lambda **_: pytest.fail("un audit a ete lance"))

    assert Lintorn.main() == 2
    sortie = capsys.readouterr().out
    assert "--vresion" in sortie
    assert "lintorn version" in sortie, "la commande la plus proche doit etre proposee"


def test_un_mot_nu_n_est_pas_pris_pour_une_commande():
    """`lintorn version`, sans tirets, lançait lui aussi un audit."""
    assert Lintorn._arguments_inconnus(["version"]) == ["version"]


def test_les_fichiers_du_push_ne_sont_pas_des_options():
    arguments = ["--rapide", "--fichiers", "api/vues.py", "front/App.tsx"]

    assert Lintorn._arguments_inconnus(arguments) == []


def test_toute_option_de_l_aide_est_reconnue():
    """Une option documentée mais absente d'OPTIONS serait REFUSÉE : l'aide
    promettrait une commande que l'outil rejette."""
    documentees = set(re.findall(r"(?<![\w-])(--?[a-zA-Z][\w-]*)", lintorn.commandes.aide.AIDE))

    assert documentees, "l'aide ne documente plus aucune option ?"
    assert documentees <= Lintorn.OPTIONS, documentees - Lintorn.OPTIONS


def test_toute_option_des_hooks_est_reconnue():
    """LE cas qui ne pardonne pas : une option du hook refusée, et le push
    n'est plus contrôlé — ou plus possible."""
    paquet = Path(Lintorn.__file__).parent
    utilisees = set()
    for hook in (paquet / "hooks").iterdir():
        for ligne in hook.read_text(encoding="utf-8").splitlines():
            if ligne.lstrip().startswith("#") or "lintorn" not in ligne.lower():
                continue
            utilisees |= set(re.findall(r"(?<![\w-])(--[a-z][\w-]*)", ligne))

    assert "--rapide" in utilisees, "les hooks ne sont plus lus : ce test serait muet"
    assert utilisees <= Lintorn.OPTIONS, utilisees - Lintorn.OPTIONS


# ─────────────────────────────────────────────────────────────────────────────
# git se lit en UTF-8, quelle que soit la langue de la machine
# ─────────────────────────────────────────────────────────────────────────────
def test_un_depot_accentue_se_reconnait_sur_une_machine_qui_ne_parle_pas_utf8(tmp_path):
    """git se lit COMME PYTHON LIT LES CHEMINS, pas « toujours en UTF-8 ».

    Le bug d'origine (Windows 11 : git lu en cp1252, chemins en UTF-8) ne se
    reproduit pas sous Linux, ou langue et chemins parlent le meme encodage.
    Ce test verrouille l'autre moitie, qui a failli casser en le corrigeant :
    sur une machine Latin-1, forcer UTF-8 creait le decalage inverse, et le
    depot redevenait meconnaissable. Le premier correctif echouait ici."""
    depot = tmp_path / "essai é"
    depot.mkdir()
    subprocess.run(["git", "init", "-q", str(depot)], check=True, timeout=30)
    # `json.dumps` echappe tout hors ASCII : la reponse traverse intacte,
    # quel que soit l'encodage de la sortie du processus enfant.
    code = ("import json, locale; from lintorn import config; print(json.dumps("
            "[locale.getencoding(), str(config.SOMMET_GIT), str(config.RACINE), "
            "config.HOOKS_POUR_GIT]))")
    environnement = {**os.environ, "LC_ALL": "fr_FR.ISO-8859-1", "PYTHONUTF8": "0",
                     "LINTORN_RACINE": str(depot)}
    sortie = subprocess.run([sys.executable, "-X", "utf8=0", "-c", code], cwd=depot,
                            capture_output=True, env=environnement, timeout=60, check=False)
    assert sortie.returncode == 0, sortie.stderr.decode("utf-8", errors="replace")
    encodage, sommet, racine, pour_git = json.loads(sortie.stdout)
    if "8859" not in encodage:
        pytest.skip(f"locale Latin-1 absente de cette machine ({encodage})")

    assert sommet == racine, "le sommet du depot doit etre lu tel que git l'ecrit"
    assert pour_git == ".lintorn/hooks", "un chemin mal lu donnait un hooksPath absolu"


def test_l_historique_git_rend_les_noms_accentues_tels_quels(tmp_path, monkeypatch):
    """Par defaut, git ecrit `caf\\303\\251.py` dans ses listes : une fiche
    memoire citant `café.py` n'etait jamais vue comme concernee par un
    commit. Vrai sous Linux aussi."""
    git = ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
    (tmp_path / "café.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True, timeout=30)
    subprocess.run([*git, "commit", "-qm", "un"], check=True, timeout=30)
    monkeypatch.setattr(config, "RACINE", tmp_path)

    nombre, touches = lintorn.controles.projet.fraicheur_memoire._commits_depuis("2000-01-01", ["café.py"])

    assert nombre == 1
    assert touches == ["café.py"]


def test_git_ne_s_appelle_que_par_config_git():
    """Un seul endroit sait lire git correctement. Un appel direct de plus, et
    le bug du « é » revient par la porte de derriere."""
    directs = []
    # `rglob` : un appel direct caché dans un sous-dossier passerait sinon.
    for source in Path(config.PAQUET).rglob("*.py"):
        nom = source.relative_to(config.PAQUET).as_posix()
        arbre = ast.parse(source.read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            if (isinstance(noeud, ast.FunctionDef) and noeud.name == "git"
                    and nom == "config/projet.py"):
                continue
            if (isinstance(noeud, ast.List) and noeud.elts
                    and isinstance(noeud.elts[0], ast.Constant) and noeud.elts[0].value == "git"):
                directs.append(f"{nom}:{noeud.lineno}")
    autorise = [d for d in directs if d.startswith("config/projet.py:")]
    assert len(autorise) == 1 and len(directs) == 1, f"appels directs a git : {directs}"
