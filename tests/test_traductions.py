# Lintorn
#
# Tests de l'outil d'audit lui-même.
#
# POURQUOI : `Lintorn.py` lit la sortie de ruff avec une expression régulière.
# Le jour où ruff change son format d'affichage, la regex ne reconnaît plus
# rien — et le code est écrit pour retomber sur la sortie brute SANS rien dire.
# On croirait l'outil en bonne santé alors qu'il aurait cessé de traduire et
# de compter. Ces tests figent le format attendu : si ruff change, ça casse ICI,
# bruyamment, au lieu de dégrader en silence.

"""Lintorn lit la sortie des outils (ruff, npm audit, OSV, Django) : si le format change, ça casse ICI."""

import json
import sys
from pathlib import Path

from aides import _hors_ascii, _projet_detecte, _sortie_npm, _sortie_osv

import lintorn.commandes
import lintorn.controles
import lintorn.outils
import lintorn.rapport
from lintorn import base, config, traductions
from lintorn.base import Resultat


# ─────────────────────────────────────────────────────────────────────────────
# La lecture de la sortie de ruff
# ─────────────────────────────────────────────────────────────────────────────
def test_regex_ruff_reconnait_une_vraie_ligne():
    """Échantillon réel, copié tel quel de la sortie de ruff."""
    ligne = r"accounts\views.py:7:1: F811 redefinition of unused 'login_required_cookie' from line 4"

    trouve = lintorn.outils.ruff.LIGNE_RUFF.match(ligne)

    assert trouve is not None, "ruff a change son format de sortie → la traduction est morte"
    assert trouve["fichier"] == r"accounts\views.py"
    assert trouve["ligne"] == "7"
    assert trouve["code"] == "F811"


def test_regex_ruff_gere_les_chemins_unix():
    """Sur Codespaces les chemins ont des / au lieu des \\."""
    ligne = "clients/models.py:72:9: F401 `planning.models.Intervention` imported but unused"

    trouve = lintorn.outils.ruff.LIGNE_RUFF.match(ligne)

    assert trouve is not None
    assert trouve["code"] == "F401"


def test_tous_les_codes_traduits_ont_un_texte_francais():
    """Un code présent dans le dictionnaire mais avec un texte vide passerait
    inaperçu à l'affichage."""
    for code, texte in {**traductions.RUFF, **traductions.DEPLOY}.items():
        assert texte.strip(), f"{code} n'a pas de traduction"
        assert len(texte) > 20, f"{code} : traduction trop courte pour être utile"


# ─────────────────────────────────────────────────────────────────────────────
# La distinction « problèmes trouvés » / « outil en panne »
# ─────────────────────────────────────────────────────────────────────────────
def test_un_outil_absent_ne_bloque_pas():
    resultat = base.lancer("Outil imaginaire", ["ceci_nexiste_pas_du_tout"], config.RACINE)

    assert resultat.statut == "INDISPONIBLE"
    assert resultat.bloquant is False


def test_code_de_sortie_inattendu_signale_une_panne_d_outil():
    """Python sort en code 2 sur une option inconnue → ce n'est PAS une alerte
    de code, c'est l'outil qui n'a pas pu tourner."""
    resultat = base.lancer(
        "Panne simulee", [config.PYTHON, "--option-qui-nexiste-pas"], config.RACINE,
    )

    assert resultat.statut == "ERREUR"
    assert "plante" in resultat.resume


# ─────────────────────────────────────────────────────────────────────────────
# npm audit — les failles des dépendances JavaScript
# ─────────────────────────────────────────────────────────────────────────────
# Sorties RÉELLES de npm 11, raccourcies. Les trois sortent en code 1 : seul
# leur JSON dit s'il y a des failles, ou si npm n'a pas pu répondre.
_NPM_SANS_VERROU = (
    '{\n  "error": {\n    "code": "ENOLOCK",\n'
    '    "summary": "This command requires an existing lockfile.",\n'
    '    "detail": "Try creating one first with: npm i --package-lock-only"\n  }\n}\n'
    "npm error code ENOLOCK\nnpm error audit This command requires an existing lockfile.\n"
)
_NPM_SANS_RESEAU = (
    '{\n  "message": "request to https://registry.npmjs.org/-/npm/v1/security/advisories/bulk'
    ' failed, reason: connect ECONNREFUSED 127.0.0.1:443",\n'
    '  "error": {\n    "summary": "",\n    "detail": ""\n  }\n}\n'
    "npm error audit endpoint returned an error\n"
)
_NPM_FAILLES = json.dumps({
    "auditReportVersion": 2,
    "vulnerabilities": {
        "vitest": {
            "name": "vitest", "severity": "moderate", "isDirect": True,
            "via": ["@vitest/mocker"], "range": "2.1.0 - 4.1.10",
            "fixAvailable": {"name": "vitest", "version": "5.0.0", "isSemVerMajor": True},
        },
        "react-router": {
            "name": "react-router", "severity": "high", "isDirect": False,
            "via": [{"title": "React Router: RSC Mode CSRF Bypass",
                     "url": "https://github.com/advisories/GHSA-qwww-vcr4-c8h2",
                     "severity": "high"}],
            "range": "7.12.0 - 7.18.1", "fixAvailable": True,
        },
    },
    "metadata": {"vulnerabilities": {"info": 0, "low": 0, "moderate": 1, "high": 1,
                                     "critical": 0, "total": 2}},
}) + "\nnpm warn audit une ligne de bruit apres le JSON\n"




def test_npm_audit_n_est_propose_qu_avec_un_verrou(tmp_path):
    """npm audit lit le VERROU, pas package.json : sans lui il refuse de
    répondre, et le contrôle resterait « INDISPONIBLE » à vie."""
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert lintorn.outils.npm_audit.commande(tmp_path) is None
    assert lintorn.outils.npm_audit.commande(None) is None

    (tmp_path / config.VERROU_NPM).write_text("{}", encoding="utf-8")
    commande = lintorn.outils.npm_audit.commande(tmp_path)

    assert commande["cwd"] == tmp_path
    assert commande["opt_in"] is True, "npm audit sort sur le reseau : jamais sans accord"
    assert commande["cle"] == "failles_npm", "l'accord donne a pip-audit ne vaut pas pour npm"
    assert commande["lent"] is True and commande["bloquant"] is False
    assert "--json" in commande["cmd"], "sans JSON, une panne ressemble a une trouvaille"


def test_npm_audit_sans_verrou_n_est_pas_une_faille():
    """npm sort en 1 aussi quand il ne PEUT PAS répondre. Au seul code de
    sortie, ce refus passait pour des failles trouvées."""
    resultat = lintorn.outils.npm_audit.traduire(_sortie_npm(_NPM_SANS_VERROU))

    assert resultat.statut == "INDISPONIBLE"
    assert resultat.bloquant is False
    assert "ENOLOCK" in resultat.resume
    assert "rien n'a ete verifie" in resultat.resume


def test_npm_audit_sans_reseau_n_est_pas_une_faille():
    resultat = lintorn.outils.npm_audit.traduire(_sortie_npm(_NPM_SANS_RESEAU))

    assert resultat.statut == "INDISPONIBLE"
    assert "ECONNREFUSED" in resultat.resume


def test_npm_audit_presente_ses_failles_de_la_plus_grave_a_la_moins_grave():
    resultat = lintorn.outils.npm_audit.traduire(_sortie_npm(_NPM_FAILLES))

    assert resultat.statut == "ALERTE"
    assert resultat.resume == "2 paquet(s) vulnerable(s) - haute : 1, moyenne : 1"
    assert resultat.detail.index("`react-router`") < resultat.detail.index("`vitest`")
    assert "GHSA-qwww-vcr4-c8h2" in resultat.detail
    assert "via `@vitest/mocker`" in resultat.detail
    assert "MAJEURE" in resultat.detail, "une montee majeure doit s'annoncer comme telle"
    assert resultat.detail_markdown
    assert not _hors_ascii(resultat.resume), "le resume part vers la console"


def test_une_sortie_npm_sans_json_ne_dit_rien_des_failles():
    """npm a changé de format, ou n'a rien répondu : sans JSON, on ne SAIT pas.

    Le rouge dirait « il y a des failles », le vert « il n'y en a pas » ; les
    deux mentiraient. La sortie brute reste affichée, telle quelle.
    """
    brut = _sortie_npm("npm error quelque chose d'inattendu")

    resultat = lintorn.outils.npm_audit.traduire(brut)

    assert resultat.statut == "INDISPONIBLE"
    assert resultat.bloquant is False
    assert "npm error quelque chose d'inattendu" in resultat.detail


# ─────────────────────────────────────────────────────────────────────────────
# check --deploy : un contrôle maison garde son message
# ─────────────────────────────────────────────────────────────────────────────
_DEPLOY_BRUT = (
    "SystemCheckError: System check identified some issues:\n\n"
    "ERRORS:\n"
    "?: (monapp.E001) MON_URL n'est pas definie : les liens envoyes seront inutilisables.\n"
    "\tHINT: Poser MON_URL=https://exemple.fr dans le .env.\n\n"
    "WARNINGS:\n"
    "?: (security.W004) You have not set a value for the SECURE_HSTS_SECONDS setting.\n\n"
    "System check identified 2 issues (0 silenced).\n"
)


def test_un_check_maison_garde_son_message_et_son_conseil():
    """« (non traduit) » remplaçait le message : les contrôles qu'un projet
    écrit pour lui-même étaient justement ceux dont on ne lisait plus rien."""
    resultat = lintorn.outils.django.traduire(
        Resultat("Django check --deploy", "ALERTE", "x", _DEPLOY_BRUT, bloquant=False))

    assert "(non traduit)" not in resultat.detail
    assert "MON_URL n'est pas definie" in resultat.detail
    assert "Poser MON_URL=https://exemple.fr" in resultat.detail
    assert traductions.DEPLOY["security.W004"] in resultat.detail, "un code connu reste traduit"
    assert resultat.resume == "2 point(s) a regler avant la prod"


# ─────────────────────────────────────────────────────────────────────────────
# OSV-Scanner — les failles des autres langages
# ─────────────────────────────────────────────────────────────────────────────
def test_le_code_de_sortie_voyage_avec_le_resultat():
    """Sans lui, un traducteur ne peut pas distinguer une sortie vide d'un échec."""
    resultat = base.lancer("x", [sys.executable, "-c", "import sys; sys.exit(3)"],
                           config.RACINE, codes_alerte=(3,))

    assert resultat.code_sortie == 3


def test_osv_ne_prend_que_ce_qu_aucun_audit_natif_ne_lit(tmp_path):
    """Le verrou du front est à npm audit, le Python à pip-audit ; un second
    package-lock.json, lui, n'est vu par personne : il revient à OSV."""
    front = tmp_path / "front"
    fichiers = [front / "package-lock.json", tmp_path / "api" / "requirements.txt",
                tmp_path / "moteur" / "Cargo.lock", tmp_path / "outil" / "package-lock.json"]

    ecosystemes = config._ecosystemes_osv(fichiers, front)

    assert ecosystemes == {"Rust": [tmp_path / "moteur" / "Cargo.lock"],
                           "JS (npm)": [tmp_path / "outil" / "package-lock.json"]}


def test_la_commande_osv_ne_compile_pas_le_projet():
    """L'analyse d'appels COMPILE le projet — et lance ses scripts de build en
    Rust. L'accord donné pour un audit porte sur le réseau, pas sur ça."""
    assert lintorn.outils.osv.commande({}) is None

    commande = lintorn.outils.osv.commande({"Rust": [Path("Cargo.lock")]})

    assert commande["opt_in"] is True
    assert commande["cle"] == "failles_osv"
    assert "--no-call-analysis=all" in commande["cmd"]
    assert commande["cmd"][commande["cmd"].index("--format") + 1] == "json"
    assert set(commande["codes_alerte"]) == {0, 1, 127, 128}, "0, 127 et 128 doivent passer par la traduction"
    assert commande["lent"] is True and commande["bloquant"] is False


# Sortie RÉELLE d'OSV-Scanner 2.6, raccourcie à un paquet et deux failles.
_OSV_FAILLES = json.dumps({"results": [{
    "source": {"path": "/ailleurs/moteur/Cargo.lock", "type": "lockfile"},
    "packages": [{
        "package": {"name": "smallvec", "version": "0.6.9", "ecosystem": "crates.io"},
        "vulnerabilities": [
            {"id": "RUSTSEC-2018-0018",
             "summary": "smallvec creates uninitialized value of any type",
             "affected": [{"package": {"ecosystem": "crates.io", "name": "smallvec"},
                           "ranges": [{"type": "SEMVER", "events": [
                               {"introduced": "0.0.0-0"}, {"fixed": "0.6.13"}]}]}]},
            {"id": "RUSTSEC-2019-0009",
             "summary": "Double-free and use-after-free in SmallVec::grow()",
             "affected": [{"package": {"ecosystem": "crates.io", "name": "smallvec"},
                           "ranges": [{"type": "SEMVER", "events": [
                               {"introduced": "0.6.5"}, {"fixed": "0.6.10"}]}]}]},
        ],
        "groups": [
            {"ids": ["RUSTSEC-2018-0018", "GHSA-55m5-whcv-c49c"], "max_severity": "7.5"},
            {"ids": ["RUSTSEC-2019-0009", "GHSA-mm7v-vpv8-xfc3"], "max_severity": "9.8"},
        ],
    }],
}]})




def test_osv_presente_ses_failles_de_la_plus_grave_a_la_moins_grave():
    resultat = lintorn.outils.osv.traduire(_sortie_osv(_OSV_FAILLES, 1))

    assert resultat.statut == "ALERTE"
    assert resultat.resume == "2 faille(s) dans 1 paquet(s) - critique : 1, haute : 1"
    assert resultat.detail.index("RUSTSEC-2019-0009") < resultat.detail.index("RUSTSEC-2018-0018")
    assert "| 0.6.10 |" in resultat.detail, "la version qui corrige doit etre donnee"
    assert "https://osv.dev/vulnerability/RUSTSEC-2019-0009" in resultat.detail
    assert not _hors_ascii(resultat.resume)


def test_osv_sans_reseau_n_affiche_pas_zero_faille():
    """LE PIÈGE : réseau coupé, OSV sort en 127 mais écrit un JSON VALIDE et
    VIDE. Lu seul, il annonçait « aucune faille » — le faux vert parfait."""
    sortie = ('{"results": []}\n'
              "Error during extraction: (extracting as vulnmatch/osvdev) request failed: "
              "dial tcp 127.0.0.1:9: connect: connection refused\n")

    resultat = lintorn.outils.osv.traduire(_sortie_osv(sortie, 127))

    assert resultat.statut == "INDISPONIBLE"
    assert "connection refused" in resultat.resume
    assert "rien n'a ete verifie" in resultat.resume


def test_osv_sans_verrou_lisible_n_est_pas_un_vert():
    resultat = lintorn.outils.osv.traduire(_sortie_osv("No package sources found", 128))

    assert resultat.statut == "INDISPONIBLE"
    assert "aucun verrou lisible" in resultat.resume


def test_osv_ne_fait_disparaitre_aucune_faille_meme_deja_auditee(tmp_path, monkeypatch):
    """C'était un faux vert : une faille était écartée comme « vue par un audit
    natif » sur la foi de son EMPLACEMENT. Or pip-audit lit le venv, pas les
    fichiers de dépendances, et un npm audit en panne ne couvre rien. Un
    doublon vaut mieux qu'un oubli."""
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "FRONTEND", tmp_path)
    monkeypatch.setattr(config, "PY_RACINE", tmp_path)
    monkeypatch.setattr(config, "COMMANDES", [{"cle": "failles_npm"}, {"cle": "failles"}])
    sortie = _OSV_FAILLES.replace("/ailleurs/moteur/Cargo.lock",
                                  str(tmp_path / "package-lock.json"))

    resultat = lintorn.outils.osv.traduire(_sortie_osv(sortie, 1))

    assert resultat.statut == "ALERTE"
    assert "RUSTSEC-2019-0009" in resultat.detail


def test_une_cle_mal_tapee_est_signalee():
    """`faiiles = true` : aucun contrôle ne tournait, et rien ne le disait."""
    soucis = config._cles_sans_effet({"faiiles": True}, set())

    assert len(soucis) == 1
    assert "cle inconnue" in soucis[0] and "failles" in soucis[0]


def test_un_controle_active_sans_rien_a_controler_est_signale():
    soucis = config._cles_sans_effet({"failles_npm": True}, set())

    assert len(soucis) == 1
    assert "rien n'est controle" in soucis[0]


def test_une_config_saine_ne_declenche_rien():
    surcharges = {"failles": True, "deploy": False, "memoire_ia": False}

    assert config._cles_sans_effet(surcharges, {"failles"}) == []


def test_un_projet_rust_ne_se_voit_proposer_que_osv(tmp_path, monkeypatch):
    _projet_detecte(monkeypatch)
    monkeypatch.setattr(config, "ECOSYSTEMES_OSV", {"Rust": [tmp_path / "Cargo.lock"]})

    outils = lintorn.commandes.outils._outillage_du_projet()

    assert [outil["nom"] for outil in outils] == ["osv-scanner"]
    assert "Rust" in outils[0]["role"]
    assert outils[0]["cle"] == "failles_osv"
