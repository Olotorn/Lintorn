"""Les contrôles muets et les écritures trouvés par le banc d'essai.

Chaque test passe par le circuit complet (`noyau.executer`, `cli.main`) : un
test qui appelle la fonction seule reste vert sur un câblage mort.
"""

from __future__ import annotations

import importlib.util

import pytest

import lintorn.commandes
import lintorn.controles
import lintorn.rapport
from lintorn import base, cli, config, noyau
from lintorn.base import Resultat

_RUFF_PRESENT = importlib.util.find_spec("ruff") is not None


def _entree(cle: str) -> dict:
    for commande in config.COMMANDES:
        if commande["cle"] == cle:
            return commande
    pytest.skip(f"pas de commande {cle} dans ce dépôt")


# ─────────────────────────────────────────────────────────────────────────────
# L'audit n'écrit jamais dans le code du projet
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _RUFF_PRESENT, reason="ruff absent de cet environnement")
def test_ruff_ne_corrige_jamais_le_projet_audite(tmp_path, monkeypatch):
    """`fix = true` dans la config ruff du projet : l'audit effaçait l'import
    inutilisé, puis affichait un vert sur ce qu'il venait de faire."""
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nfix = true\n", encoding="utf-8")
    source = tmp_path / "app.py"
    source.write_text("import os\nimport sys\n\nprint(sys.argv)\n", encoding="utf-8")
    avant = source.read_text(encoding="utf-8")
    monkeypatch.setattr(config, "COMMANDES", [{**_entree("ruff"), "cwd": tmp_path}])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {})
    monkeypatch.setattr(config, "VENV_PROJET", tmp_path)

    [resultat] = noyau.executer()

    assert source.read_text(encoding="utf-8") == avant, "l'audit a modifié le code du projet"
    assert resultat.statut == "ALERTE", "l'import inutilisé doit être SIGNALÉ, pas corrigé"
    assert not (tmp_path / ".ruff_cache").exists(), "ruff a écrit son cache dans le projet"


# ─────────────────────────────────────────────────────────────────────────────
# Sans venv du projet, les outils Python ne tournent pas sur celui de Lintorn
# ─────────────────────────────────────────────────────────────────────────────
def _sans_venv(monkeypatch, racine):
    monkeypatch.setattr(config, "RACINE", racine)
    monkeypatch.setattr(config, "PY_RACINE", racine)
    monkeypatch.setattr(config, "VENV_PROJET", None)
    monkeypatch.setattr(config, "VENV_SOUCI", None)


def test_sans_venv_un_outil_python_n_est_pas_lance(tmp_path, monkeypatch):
    """pip-audit auditait le venv de Lintorn et affichait OK, pendant qu'OSV
    trouvait des failles dans les verrous du projet."""
    _sans_venv(monkeypatch, tmp_path)
    temoin = tmp_path / "a_tourne"
    python = {"cle": "failles", "titre": "Failles connues (pip-audit)",
              "cmd": [str(config.PYTHON), "-c", f"open({str(temoin)!r}, 'w')"],
              "cwd": tmp_path, "bloquant": True, "traduction": None, "lent": False}
    monkeypatch.setattr(config, "COMMANDES", [python])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {"python_projet": True})

    outil, venv = noyau.executer()

    assert not temoin.exists(), "l'outil a tourné avec le python de Lintorn"
    assert (outil.statut, outil.bloquant) == ("INDISPONIBLE", False)
    assert "aucun venv" in outil.resume
    assert venv.statut == "ALERTE" and "ne sont pas lances" in venv.resume


def test_sans_venv_une_commande_d_un_autre_langage_tourne_toujours(tmp_path, monkeypatch):
    _sans_venv(monkeypatch, tmp_path)
    autre = {"cle": "vrai", "titre": "Autre langage", "cmd": ["git", "--version"], "cwd": tmp_path,
             "bloquant": True, "traduction": None, "lent": False}
    monkeypatch.setattr(config, "COMMANDES", [autre])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {})

    [resultat] = noyau.executer()

    assert resultat.statut == "OK"


def test_sans_venv_un_projet_uv_se_voit_conseiller_uv_sync(tmp_path, monkeypatch):
    _sans_venv(monkeypatch, tmp_path)
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "COMMANDES", [])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {"python_projet": True})

    [venv] = noyau.executer()

    assert "uv sync" in venv.detail
    assert "python3 -m venv" not in venv.detail
    assert str(tmp_path) not in venv.detail, "un chemin absolu porte le nom de l'utilisateur"


def test_un_outil_introuvable_affiche_son_remede(tmp_path, monkeypatch):
    """« outil introuvable : tsc » laissait l'utilisateur deviner quoi installer,
    et avec quel gestionnaire de paquets."""
    absent = {"cle": "typescript", "titre": "TypeScript (tsc --noEmit)",
              "cmd": [str(tmp_path / "node_modules" / ".bin" / "tsc"), "--noEmit"],
              "cwd": tmp_path, "bloquant": True, "traduction": None, "lent": False,
              "remede": "pnpm install (dans web)"}
    monkeypatch.setattr(config, "COMMANDES", [absent])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {})

    [resultat] = noyau.executer()

    assert resultat.statut == "INDISPONIBLE"
    assert resultat.resume.endswith("pnpm install (dans web)")


# ─────────────────────────────────────────────────────────────────────────────
# « Audit complet » ne passe au vert que si les outils lents ont répondu
# ─────────────────────────────────────────────────────────────────────────────
def _audit(tmp_path, monkeypatch, commandes):
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "ETAT", tmp_path / ".lintorn" / "etat.json")
    monkeypatch.setattr(config, "COMMANDES", commandes)
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {"audit_complet": True})
    monkeypatch.setattr(lintorn.rapport.markdown, "ecrire_rapport", lambda resultats, hook=False: True)
    monkeypatch.setattr("sys.argv", ["lintorn"])

    def lancer_une_fois(capsys):
        cli.main()
        ligne = next(ligne for ligne in capsys.readouterr().out.splitlines()
                     if "Audit complet" in ligne)
        return ligne, base.lire_etat().get("dernier_audit_complet")
    return lancer_une_fois


def _lent(tmp_path, cmd):
    return {"cle": "failles_osv", "titre": "Failles connues (OSV-Scanner)", "cmd": cmd,
            "cwd": tmp_path, "bloquant": False, "traduction": None, "lent": True}


def test_sans_outil_lent_l_audit_complet_ne_passe_jamais_au_vert(tmp_path, monkeypatch, capsys):
    """Le premier `lintorn` notait la date sans qu'aucun outil lent ait tourné :
    « Audit complet » était au vert dès le lancement suivant."""
    lancer = _audit(tmp_path, monkeypatch, [])

    lancer(capsys)
    ligne, date = lancer(capsys)

    assert date is None
    assert "[ OK ]" not in ligne
    assert "aucun outil lent active" in ligne


def test_un_outil_lent_qui_n_a_pas_repondu_ne_compte_pas(tmp_path, monkeypatch, capsys):
    """Un audit de failles tombé sur un délai réseau réécrivait quand même la date."""
    lancer = _audit(tmp_path, monkeypatch, [_lent(tmp_path, [str(tmp_path / "absent")])])

    _, date = lancer(capsys)

    assert date is None


def test_un_outil_lent_qui_a_repondu_note_la_date(tmp_path, monkeypatch, capsys):
    lancer = _audit(tmp_path, monkeypatch, [_lent(tmp_path, ["git", "--version"])])

    lancer(capsys)
    ligne, date = lancer(capsys)

    assert date is not None
    assert "[ OK ]" in ligne


# ─────────────────────────────────────────────────────────────────────────────
# Le focus du push ne dit « aucun défaut » que sur ce qu'un contrôle a lu
# ─────────────────────────────────────────────────────────────────────────────
def _pousser(tmp_path, monkeypatch, capsys, *fichiers):
    for nom in fichiers:
        (tmp_path / nom).write_text("", encoding="utf-8")
    faux_ruff = {"cle": "ruff", "titre": "Ruff (lint Python)", "cmd": ["git", "--version"],
                 "cwd": tmp_path, "bloquant": True, "traduction": None, "lent": False}
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "SOMMET_GIT", None)
    monkeypatch.setattr(config, "COMMANDES", [faux_ruff])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {})
    monkeypatch.setattr(lintorn.rapport.markdown, "ecrire_rapport", lambda resultats, hook=False: True)
    monkeypatch.setattr("sys.argv", ["lintorn", "--rapide", "--fichiers", *fichiers])
    cli.main()
    return next(ligne for ligne in capsys.readouterr().out.splitlines()
                if "Defauts dans les fichiers pousses" in ligne)


def test_le_focus_ne_dit_pas_propre_un_fichier_qu_aucun_controle_ne_lit(tmp_path, monkeypatch, capsys):
    """`[ OK ] aucun defaut connu dedans` sur un `.cs` : aucun contrôle ne lit le C#."""
    ligne = _pousser(tmp_path, monkeypatch, capsys, "Commande.cs")

    assert "[ OK ]" not in ligne
    assert "aucun controle ne lit" in ligne and "Commande.cs" in ligne


def test_le_focus_nomme_la_part_non_lue_d_un_push_mixte(tmp_path, monkeypatch, capsys):
    ligne = _pousser(tmp_path, monkeypatch, capsys, "vues.py", "main.go")

    assert "[ ?? ]" in ligne
    assert "1 que rien ne lit : main.go" in ligne


def test_le_focus_reste_vert_quand_tout_a_ete_lu(tmp_path, monkeypatch, capsys):
    ligne = _pousser(tmp_path, monkeypatch, capsys, "vues.py")

    assert "[ OK ]" in ligne and "aucun defaut connu dedans" in ligne


# ─────────────────────────────────────────────────────────────────────────────
# La conclusion ne dit « tout est au vert » que si tout a tourné
# ─────────────────────────────────────────────────────────────────────────────
def _conclusion(tmp_path, monkeypatch, capsys, commandes, internes=None, rapide=False):
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "ETAT", tmp_path / ".lintorn" / "etat.json")
    monkeypatch.setattr(config, "COMMANDES", commandes)
    monkeypatch.setattr(config, "CONTROLES_INTERNES", dict.fromkeys(internes or {}, True))
    for nom, controle in (internes or {}).items():
        monkeypatch.setitem(noyau.CONTROLES_INTERNES, nom, controle)
    monkeypatch.setattr(lintorn.rapport.markdown, "ecrire_rapport", lambda resultats, hook=False: True)
    monkeypatch.setattr("sys.argv", ["lintorn", *(["--rapide"] if rapide else [])])
    cli.main()
    return capsys.readouterr().out


def test_un_audit_accorde_qui_n_a_pas_repondu_empeche_le_tout_vert(tmp_path, monkeypatch, capsys):
    """OSV tombé sur un délai réseau : la conclusion disait « tous les controles
    bloquants sont au vert »."""
    ok = {"cle": "ruff", "titre": "Ruff (lint Python)", "cmd": ["git", "--version"],
          "cwd": tmp_path, "bloquant": True, "traduction": None, "lent": False}
    sortie = _conclusion(tmp_path, monkeypatch, capsys,
                         [ok, _lent(tmp_path, [str(tmp_path / "osv-absent")])])

    assert "tous les controles bloquants sont au vert" not in sortie
    assert "n'ont rien verifie" in sortie and "OSV-Scanner" in sortie


def test_ce_que_rapide_saute_expres_n_est_pas_un_outil_muet(tmp_path, monkeypatch, capsys):
    ok = {"cle": "ruff", "titre": "Ruff (lint Python)", "cmd": ["git", "--version"],
          "cwd": tmp_path, "bloquant": True, "traduction": None, "lent": False}
    sortie = _conclusion(tmp_path, monkeypatch, capsys,
                         [ok, _lent(tmp_path, ["git", "--version"])], rapide=True)

    assert "n'ont rien verifie" not in sortie
    assert "tous les controles bloquants sont au vert" in sortie


def test_un_controle_a_confirmer_a_bien_tourne(tmp_path, monkeypatch, capsys):
    """Doc vs code avait vérifié 6 chemins, et la conclusion disait « Lintorn
    n'a rien verifie du tout »."""
    doc = lambda: Resultat("Doc vs code", "VERIF", "6 chemins, 2 a confirmer",  # noqa: E731
                           bloquant=False)
    sortie = _conclusion(tmp_path, monkeypatch, capsys, [], internes={"doc_vs_code": doc})

    assert "rien verifie du tout" not in sortie


# ─────────────────────────────────────────────────────────────────────────────
# --esquisser-regles ne rassure plus sur zéro règle lue
# ─────────────────────────────────────────────────────────────────────────────
def _esquisser(tmp_path, monkeypatch, capsys, docs_ia, regles):
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "FICHIER_REGLES", tmp_path / ".lintorn" / "regles.toml")
    monkeypatch.setattr(config, "DOCS_IA", docs_ia)
    monkeypatch.setattr(lintorn.controles.projet.regles_enoncees, "regles_enoncees", lambda: regles)
    monkeypatch.setattr(lintorn.controles.projet.regles_enoncees, "regles_sans_controle", lambda: [])
    lintorn.commandes.regles.esquisser_regles()
    return capsys.readouterr().out


def test_sans_fichier_ia_esquisser_ne_dit_pas_que_tout_est_couvert(tmp_path, monkeypatch, capsys):
    sortie = _esquisser(tmp_path, monkeypatch, capsys, [], [])

    assert "a deja un controle" not in sortie
    assert "aucun fichier d'instructions IA" in sortie


def test_zero_regle_lue_n_est_pas_un_feu_vert(tmp_path, monkeypatch, capsys):
    """« Chaque regle de ta doc a deja un controle » sur un AGENTS.md dont
    aucune règle n'avait été lue."""
    sortie = _esquisser(tmp_path, monkeypatch, capsys, [tmp_path / "AGENTS.md"], [])

    assert "a deja un controle" not in sortie
    assert "aucune regle reperee dans AGENTS.md" in sortie


def test_des_regles_lues_et_couvertes_restent_un_vert(tmp_path, monkeypatch, capsys):
    regle = ("CLAUDE.md", 3, "Jamais de print", ["print"])
    sortie = _esquisser(tmp_path, monkeypatch, capsys, [tmp_path / "CLAUDE.md"], [regle])

    assert "1 regle(s) lue(s) : chacune a deja un controle" in sortie
