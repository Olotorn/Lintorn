# Lintorn
#
# Tests des correctifs issus du banc d'essai sur de vrais projets : les
# rapports (`rapport.md`, `rapport.html`) et les traducteurs de sorties.
#
# Un correctif qui change un STATUT se teste par le circuit complet
# (`noyau.executer`), avec un faux exécutable : un test qui appelle le
# traducteur directement reste vert sur un câblage mort.

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import lintorn.outils
import lintorn.rapport
from lintorn import base, config, noyau
from lintorn.base import Resultat
from lintorn.rapport import html as rapport_html


def _rapports(tmp_path, monkeypatch, resultats):
    """(rapport.md, rapport.html) tels que Lintorn les écrit."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "RAPPORT", tmp_path / ".lintorn" / "rapport.md")
    assert lintorn.rapport.markdown.ecrire_rapport(resultats) is True
    dossier = tmp_path / ".lintorn"
    return ((dossier / "rapport.md").read_text(encoding="utf-8"),
            (dossier / "rapport.html").read_text(encoding="utf-8"))


def _section_md(markdown, titre):
    debut = markdown.index(f"{titre}\n")
    fin = markdown.find("\n## ", debut)
    return markdown[debut:] if fin < 0 else markdown[debut:fin]


def _fiche_html(page, titre):
    debut = page.index(f"<h2>{titre}</h2>")
    return page[debut:page.index("</article>", debut)]


def _annonce(texte):
    """(lignes manquantes, lignes en tout) annoncées par la coupe."""
    trouve = re.search(r"… (\d+) ligne\(s\) sur (\d+) non affichée\(s\)", texte)
    assert trouve, "la coupe doit dire combien de lignes manquent"
    return int(trouve[1]), int(trouve[2])


# ─────────────────────────────────────────────────────────────────────────────
# D1 — la coupe d'un détail trop long
# ─────────────────────────────────────────────────────────────────────────────
def _osv_bavard(nombre):
    """Une vraie forme de sortie OSV, avec `nombre` paquets vulnérables."""
    paquets = []
    for rang in range(nombre):
        ident = f"GHSA-{rang:04d}-aaaa-bbbb"
        paquets.append({
            "package": {"name": f"paquet-{rang}", "version": "1.0.0", "ecosystem": "npm"},
            "vulnerabilities": [{"id": ident, "summary": "Un resume assez long " * 6,
                                 "affected": [{"package": {"name": f"paquet-{rang}",
                                                           "ecosystem": "npm"},
                                               "ranges": [{"type": "SEMVER", "events": [
                                                   {"introduced": "0"}, {"fixed": "1.0.1"}]}]}]}],
            "groups": [{"ids": [ident], "max_severity": "5.0"}],
        })
    return json.dumps({"results": [{"source": {"path": "front/yarn.lock"}, "packages": paquets}]})


def test_d1_la_coupe_garde_le_conseil_et_le_decompte_d_osv(tmp_path, monkeypatch):
    """La coupe tombait au milieu d'une ligne du tableau OSV, et avalait le
    « … et N autre(s) » et le conseil « Corriger : … » écrits après."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    osv = lintorn.outils.osv.traduire(Resultat("Failles connues (OSV-Scanner)", "ALERTE", "x",
                                     _osv_bavard(70), bloquant=False, code_sortie=1))
    assert len(osv.detail) > base.DETAIL_MAX, "le test doit forcer la coupe"

    markdown, page = _rapports(tmp_path, monkeypatch, [osv])

    section = _section_md(markdown, osv.titre)
    fiche = _fiche_html(page, osv.titre)
    for rendu in (section, fiche):
        assert "Corriger :" in rendu, "le conseil de correction a disparu"
        assert "… et 10 autre(s)." in rendu, "le decompte du traducteur a disparu"
    lignes_tableau = [ligne for ligne in section.splitlines() if ligne.startswith("|")]
    assert all(ligne.endswith("|") for ligne in lignes_tableau), "ligne coupee en son milieu"
    # Les deux rapports montrent EXACTEMENT les mêmes lignes.
    montrees = len(lignes_tableau) - 2           # en-tête et séparation
    assert fiche.count("<tr>") - 1 == montrees
    assert all(ligne.count("<td>") == 5 for ligne in fiche.split("<tr>")[2:])
    manque, total = _annonce(section)
    assert _annonce(fiche) == (manque, total)
    assert manque == 60 - montrees, "le compte des lignes manquantes est faux"


def test_d1_une_sortie_brute_garde_sa_derniere_ligne(tmp_path, monkeypatch):
    """Le bilan de pytest est la DERNIÈRE ligne de sa sortie."""
    brut = "\n".join([f"tests/test_x.py::test_{n} FAILED - assert {n} == {n + 1}"
                      for n in range(600)] + ["===== 600 failed in 3.21s ====="])
    pytest_rouge = Resultat("Tests (pytest)", "ALERTE", "601 ligne(s) de sortie", brut)

    markdown, page = _rapports(tmp_path, monkeypatch, [pytest_rouge])

    section = _section_md(markdown, "Tests (pytest)")
    fiche = _fiche_html(page, "Tests (pytest)")
    assert "600 failed in 3.21s" in section and "600 failed in 3.21s" in fiche
    montrees = len(re.findall(r"^tests/test_x\.py::", section, re.M))
    assert _annonce(section) == (600 - montrees, 601)
    assert _annonce(fiche) == _annonce(section)
    assert "test_0 FAILED" in section, "le debut aussi doit rester"


def test_d1_une_coupe_dans_un_bloc_de_code_le_referme(tmp_path, monkeypatch):
    """Un bloc ``` coupé avant sa clôture avalait l'annonce de la coupe."""
    detail = "Avant le bloc.\n\n```text\n" + "\n".join(
        f"ligne de code {n} " + "x" * 60 for n in range(400)) + "\n```\n\nConseil final."
    resultat = Resultat("Maison", "ALERTE", "x", detail, detail_markdown=True)

    markdown, page = _rapports(tmp_path, monkeypatch, [resultat])

    section = _section_md(markdown, "Maison")
    assert section.count("```") % 2 == 0, "bloc laisse ouvert"
    fiche = _fiche_html(page, "Maison")
    annonce = re.search(r"<p><em>… \d+ ligne\(s\)", fiche)
    assert annonce, "l'annonce doit etre du texte, hors du bloc de code"
    assert fiche.rindex("</pre>") < annonce.start()


def test_d1_une_ligne_geante_est_coupee_quand_meme(tmp_path, monkeypatch):
    """Un JSON sur une seule ligne (pip-audit) n'a aucune frontière de ligne."""
    resultat = Resultat("Brut", "ALERTE", "x", "{" + "a" * 30000 + "}")

    detail = base.detail_du_rapport(resultat)

    assert len(detail) < base.DETAIL_MAX + 200
    assert _annonce(detail) == (1, 1)


def test_d1_un_detail_court_n_est_pas_touche():
    resultat = Resultat("Court", "ALERTE", "x", "| a | b |\n|---|---|\n| 1 | 2 |",
                        detail_markdown=True)

    assert base.detail_du_rapport(resultat) == resultat.detail


# ─────────────────────────────────────────────────────────────────────────────
# D2 — la page HTML dit la même chose que le reste
# ─────────────────────────────────────────────────────────────────────────────
def _outil_rouge(tmp_path):
    """Une commande bloquante qui sort en 1 : un contrôle en alerte."""
    script = tmp_path / "outil-rouge"
    script.write_text("#!/bin/sh\necho 'un defaut'\nexit 1\n", encoding="utf-8")
    script.chmod(0o755)
    return {"cle": "rouge", "titre": "Outil rouge", "cmd": [str(script)], "cwd": tmp_path,
            "bloquant": True, "traduction": None, "lent": False}


@pytest.mark.skipif(os.name == "nt", reason="faux outil en script shell")
def test_d2_sans_hook_la_page_ne_promet_pas_un_push_refuse(tmp_path, monkeypatch):
    """Par le vrai circuit, dans un vrai dépôt sans hook : la page disait « le
    push est refusé », et la même page « hook pas encore installe »."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "SOUS_GIT", True)
    monkeypatch.setattr(config, "SOMMET_GIT", tmp_path)
    monkeypatch.setattr(config, "HOOKS", tmp_path / ".lintorn" / "hooks")
    monkeypatch.setattr(config, "COMMANDES", [_outil_rouge(tmp_path)])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {"hook_git": True})

    resultats = noyau.executer()
    _, page = _rapports(tmp_path, monkeypatch, resultats)

    assert [r.statut for r in resultats] == ["ALERTE", "INDISPONIBLE"]
    verdict = re.search(r'<p class="verdict alerte">(.*?)</p>', page)[1]
    assert "1 contrôle(s) bloquant(s) en alerte" in verdict
    assert "refus" not in verdict.replace("rien ne refuse", ""), verdict
    assert "rien ne refuse le push" in verdict and "pas encore installe" in verdict


def test_d2_avec_un_hook_actif_la_page_annonce_le_refus(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RACINE", tmp_path)
    resultats = [Resultat("Outil rouge", "ALERTE", "1 defaut"),
                 Resultat("Hook pre-push (Lintorn)", "OK", "branche et executable",
                          bloquant=False)]

    page = rapport_html.page(resultats)

    assert "le hook pre-push refuse le push tant qu'ils le sont" in page


def test_d2_sans_controle_du_hook_la_page_ne_dit_rien_du_push(monkeypatch, tmp_path):
    """`--doc` ne lance pas le contrôle du hook : on ne sait pas, on ne dit rien."""
    monkeypatch.setattr(config, "RACINE", tmp_path)

    page = rapport_html.page([Resultat("Doc vs code", "ALERTE", "1 introuvable")])

    assert "1 contrôle(s) bloquant(s) en alerte.</p>" in page


_NPM_PLAGES = json.dumps({
    "vulnerabilities": {
        "brace-expansion": {
            "severity": "high", "isDirect": False, "range": "<=1.1.17 || 2.0.0 - 2.1.3",
            "fixAvailable": True,
            "via": [{"title": "[security] ReDoS in brace-expansion",
                     "url": "https://github.com/advisories/GHSA-v6h2-p8h4-qcjw"}],
        },
    },
    "metadata": {"dependencies": {"total": 12}},
})


def test_d2_une_plage_npm_a_deux_branches_ne_decale_pas_le_tableau(tmp_path, monkeypatch):
    """`a || b` est échappé en `\\|\\|` dans le Markdown. La page coupait
    dessus : 7 cellules pour 5 colonnes, et « Correctif » affichait `\\`."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    npm = lintorn.outils.npm_audit.traduire(Resultat("Failles connues JS (npm audit)", "ALERTE", "x",
                                           _NPM_PLAGES, bloquant=False, code_sortie=1))

    _, page = _rapports(tmp_path, monkeypatch, [npm])

    fiche = _fiche_html(page, npm.titre)
    ligne = fiche.split("<tr>")[2]
    cellules = re.findall(r"<td>(.*?)</td>", ligne)
    assert len(cellules) == 5, cellules
    assert cellules[2] == "&lt;=1.1.17 || 2.0.0 - 2.1.3"
    assert cellules[3] == "<code>npm audit fix</code>"
    assert ('<a href="https://github.com/advisories/GHSA-v6h2-p8h4-qcjw">'
            "[security] ReDoS in brace-expansion</a>") in cellules[4], \
        "un titre d'avis entre crochets doit rester un lien, sans ses echappements"


def test_d2_les_echappements_du_markdown_ne_s_affichent_pas_dans_la_page():
    rendu = rapport_html._rendre("- chemin\\_bizarre et \\*pas en italique\\* et `a\\|b`")

    assert "chemin_bizarre" in rendu
    assert "*pas en italique*" in rendu and "<em>" not in rendu
    assert "<code>a\\|b</code>" in rendu, "dans du code, rien n'est interprete"


# ─────────────────────────────────────────────────────────────────────────────
# D5 — tsc sort en 2 pour des erreurs de type ET pour une panne
# ─────────────────────────────────────────────────────────────────────────────
# Sorties RÉELLES de tsc 6.0.3, recopiées telles quelles.
_TSC_ERREURS = (
    "src/a.ts(1,7): error TS2322: Type 'string' is not assignable to type 'number'.\n"
    "src/a.ts(3,3): error TS2345: Argument of type 'number' is not assignable to "
    "parameter of type 'string'.\n"
    "src/a.ts(4,27): error TS2322: Type 'number' is not assignable to type 'string'.\n"
    "src/b.ts(1,32): error TS2353: Object literal may only specify known properties, "
    "and 'b' does not exist in type '{ a: number; }'.\n"
)
_TSC_OPTION_INCONNUE = "tsconfig.json(1,38): error TS5023: Unknown compiler option 'optionInconnue'.\n"
_TSC_RIEN_A_LIRE = ("error TS18003: No inputs were found in config file '/projet/tsconfig.json'. "
                    "Specified 'include' paths were '[\"src\"]' and 'exclude' paths were '[]'.\n")
_TSC_EN_CHAINE = (
    "src/a.ts(5,7): error TS2322: Type '{ k: number; }' is not assignable to type 'T'.\n"
    "  Types of property 'k' are incompatible.\n"
    "    Type 'number' is not assignable to type 'string'.\n"
)
_TSC_PRETTY = (
    "\x1b[96msrc/a.ts\x1b[0m:\x1b[93m1\x1b[0m:\x1b[93m7\x1b[0m - \x1b[91merror\x1b[0m"
    "\x1b[90m TS2322: \x1b[0mType 'string' is not assignable to type 'number'.\n\n"
    "\x1b[7m1\x1b[0m const x: number = \"a\";\n\x1b[7m \x1b[0m \x1b[91m      ~\x1b[0m\n\n\n"
    "Found 1 error in src/a.ts\x1b[90m:1\x1b[0m\n\n"
)


def _controle_typescript(tmp_path, sortie_tsc, code):
    """Le contrôle TypeScript d'un faux projet, par le VRAI circuit : la config
    importée dans un processus neuf (l'entrée tsc telle qu'elle est livrée),
    un faux tsc qui rejoue une sortie réelle, `lancer`, puis `noyau`."""
    front = tmp_path / "front"
    binaires = front / "node_modules" / ".bin"
    binaires.mkdir(parents=True)
    (front / "package.json").write_text("{}", encoding="utf-8")
    (front / "tsconfig.json").write_text("{}", encoding="utf-8")
    (binaires / "sortie.txt").write_text(sortie_tsc, encoding="utf-8")
    faux_tsc = binaires / "tsc"
    faux_tsc.write_text(f'#!/bin/sh\ncat "$(dirname "$0")/sortie.txt"\nexit {code}\n',
                        encoding="utf-8")
    faux_tsc.chmod(0o755)
    programme = (
        "import json; from lintorn import config, noyau; "
        "config.COMMANDES = [c for c in config.COMMANDES if c['cle'] == 'typescript']; "
        "config.CONTROLES_INTERNES = {}; "
        "r = noyau.executer(rapide=True)[0]; "
        "print(json.dumps({'statut': r.statut, 'resume': r.resume, 'detail': r.detail, "
        "'bloquant': r.bloquant, 'fichiers': r.fichiers}))"
    )
    environnement = {**os.environ, "LINTORN_RACINE": str(tmp_path),
                     "PYTHONPATH": str(Path(base.__file__).parents[1])}
    sortie = subprocess.run([sys.executable, "-c", programme], cwd=tmp_path,
                            capture_output=True, text=True, env=environnement,
                            timeout=60, check=False)
    assert sortie.returncode == 0, sortie.stderr
    return json.loads(sortie.stdout)


_SANS_SH = pytest.mark.skipif(os.name == "nt", reason="faux tsc en script shell")


@_SANS_SH
def test_d5_des_erreurs_de_type_sont_une_alerte_comptee(tmp_path):
    """C'était « l'outil a plante (code 2) — plus aucune analyse », sans un compte."""
    tsc = _controle_typescript(tmp_path, _TSC_ERREURS, 2)

    assert tsc["statut"] == "ALERTE" and tsc["bloquant"] is True
    assert tsc["resume"] == "4 erreur(s) de type dans 2 fichier(s)"
    assert "[`front/src/a.ts:3`](../front/src/a.ts#L3)" in tsc["detail"], \
        "tsc nomme ses fichiers depuis le front : le lien part de la racine"
    assert tsc["fichiers"] == {"front/src/a.ts": "3 erreur(s) de type",
                               "front/src/b.ts": "1 erreur(s) de type"}


@_SANS_SH
@pytest.mark.parametrize("sortie_tsc, code", [(_TSC_OPTION_INCONNUE, 2), (_TSC_RIEN_A_LIRE, 2)])
def test_d5_un_tsconfig_refuse_est_une_panne_pas_des_erreurs_de_type(tmp_path, sortie_tsc, code):
    """Même code 2 : seule la sortie dit que tsc n'a rien pu analyser."""
    tsc = _controle_typescript(tmp_path, sortie_tsc, code)

    assert tsc["statut"] == "ERREUR" and tsc["bloquant"] is True
    assert "tsc refuse la configuration du projet" in tsc["resume"]
    assert re.search(r"\(TS(5023|18003)\)", tsc["resume"])
    assert "/projet" not in tsc["resume"], "un chemin de la machine n'a rien a faire en console"


@_SANS_SH
def test_d5_des_erreurs_trouvees_malgre_un_tsconfig_refuse_restent_une_panne(tmp_path):
    tsc = _controle_typescript(tmp_path, _TSC_ERREURS + _TSC_OPTION_INCONNUE, 2)

    assert tsc["statut"] == "ERREUR"
    assert "Erreurs de type trouvées malgré tout (4)" in tsc["detail"]
    assert "front/src/b.ts" in tsc["fichiers"], "le focus doit voir ces fichiers"


@_SANS_SH
def test_d5_une_sortie_illisible_n_est_jamais_un_vert(tmp_path):
    tsc = _controle_typescript(tmp_path, "Segmentation fault\n", 2)

    assert tsc["statut"] == "ERREUR"
    assert "sans erreur lisible" in tsc["resume"]


@_SANS_SH
def test_d5_un_tsc_en_mode_pretty_est_lu_aussi(tmp_path):
    """Le tsconfig du projet peut activer `pretty` : couleurs et extraits de code."""
    tsc = _controle_typescript(tmp_path, _TSC_PRETTY, 2)

    assert tsc["resume"] == "1 erreur(s) de type dans 1 fichier(s)"
    assert "const x" not in tsc["detail"], "l'extrait de code n'est pas un message"


@_SANS_SH
def test_d5_un_message_en_chaine_garde_sa_suite(tmp_path):
    tsc = _controle_typescript(tmp_path, _TSC_EN_CHAINE, 2)

    assert tsc["resume"] == "1 erreur(s) de type dans 1 fichier(s)"
    assert "Types of property 'k' are incompatible." in tsc["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# D6 — un vert d'audit dit sur combien de paquets il porte
# ─────────────────────────────────────────────────────────────────────────────
def _faux_outil(tmp_path, sortie, code):
    """Un exécutable qui écrit `sortie` et sort en `code`."""
    (tmp_path / "sortie.txt").write_text(sortie, encoding="utf-8")
    script = tmp_path / "faux-outil"
    script.write_text(f"#!/bin/sh\ncat '{tmp_path / 'sortie.txt'}'\nexit {code}\n",
                      encoding="utf-8")
    script.chmod(0o755)
    return [str(script)]


def _par_le_circuit(monkeypatch, commande):
    monkeypatch.setattr(config, "COMMANDES", [commande])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {})
    [resultat] = noyau.executer()
    return resultat


def _npm(tmp_path, monkeypatch, sortie, code=0):
    (tmp_path / config.VERROU_NPM).write_text("{}", encoding="utf-8")
    commande = lintorn.outils.npm_audit.commande(tmp_path)
    return _par_le_circuit(monkeypatch, {**commande, "cmd": _faux_outil(tmp_path, sortie, code)})


@_SANS_SH
def test_d6_le_vert_de_npm_audit_donne_son_denominateur(tmp_path, monkeypatch):
    sortie = json.dumps({"vulnerabilities": {},
                         "metadata": {"dependencies": {"prod": 1, "total": 708}}})

    npm = _npm(tmp_path, monkeypatch, sortie)

    assert (npm.statut, npm.resume) == ("OK", "aucune faille connue dans 708 paquet(s)")


@_SANS_SH
def test_d6_npm_audit_sur_zero_paquet_n_est_pas_un_vert(tmp_path, monkeypatch):
    """Sortie RÉELLE de npm 11 sur un verrou sans dépendance."""
    sortie = json.dumps({"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {
        "vulnerabilities": {"total": 0},
        "dependencies": {"prod": 1, "dev": 0, "optional": 0, "peer": 0,
                         "peerOptional": 0, "total": 0}}})

    npm = _npm(tmp_path, monkeypatch, sortie)

    assert npm.statut == "INDISPONIBLE"
    assert "rien a verifier" in npm.resume


def _pip_audit_livre(tmp_path):
    """L'entrée pip-audit telle que config.py la livre, lue dans un processus neuf."""
    projet = tmp_path / "projet"
    projet.mkdir()
    (projet / "pyproject.toml").write_text(
        '[project]\nname = "x"\n\n[tool.lintorn.controles]\nfailles = true\n', encoding="utf-8")
    # Un témoin sans aucun `.py` n'est plus un projet Python : pas de pip-audit.
    (projet / "app.py").write_text("", encoding="utf-8")
    programme = ("import json; from lintorn import config; "
                 "[c] = [c for c in config.COMMANDES if c['cle'] == 'failles']; "
                 "print(json.dumps({'traduction': c['traduction'], "
                 "'codes_alerte': list(c.get('codes_alerte', (1,))), 'bloquant': c['bloquant']}))")
    environnement = {**os.environ, "LINTORN_RACINE": str(projet),
                     "PYTHONPATH": str(Path(base.__file__).parents[1])}
    sortie = subprocess.run([sys.executable, "-c", programme], cwd=projet,
                            capture_output=True, text=True, env=environnement,
                            timeout=60, check=False)
    assert sortie.returncode == 0, sortie.stderr
    return {"cle": "failles", "titre": "Failles connues (pip-audit)", "cwd": tmp_path,
            "lent": False, **json.loads(sortie.stdout)}


def _pip_audit(tmp_path, monkeypatch, sortie, code=0):
    entree = {**_pip_audit_livre(tmp_path), "cmd": _faux_outil(tmp_path, sortie, code)}
    entree["codes_alerte"] = tuple(entree["codes_alerte"])
    return _par_le_circuit(monkeypatch, entree)


@_SANS_SH
def test_d6_pip_audit_compte_ses_paquets_et_nomme_ceux_qu_il_saute(tmp_path, monkeypatch):
    """Le paquet du projet lui-même, absent de PyPI, est sauté sans un mot."""
    sortie = json.dumps({"dependencies": [
        {"name": "flask", "skip_reason": "Dependency not found on PyPI and could not be "
                                         "audited: flask (3.2.0.dev0)"},
        *({"name": f"dep{n}", "version": "1.0", "vulns": []} for n in range(36)),
    ], "fixes": []}) + "\nNo known vulnerabilities found\n"

    pip = _pip_audit(tmp_path, monkeypatch, sortie)

    assert pip.statut == "OK"
    assert pip.resume == "aucune faille connue dans 36 paquet(s), 1 non audite(s)"
    assert pip.detail_meme_au_vert and "`flask`" in pip.detail


@_SANS_SH
def test_d6_pip_audit_qui_a_tout_saute_n_est_pas_un_vert(tmp_path, monkeypatch):
    sortie = json.dumps({"dependencies": [
        {"name": "local", "skip_reason": "Dependency not found on PyPI"}], "fixes": []})

    pip = _pip_audit(tmp_path, monkeypatch, sortie)

    assert pip.statut == "INDISPONIBLE"
    assert "aucun paquet audite (1 saute(s))" in pip.resume


@_SANS_SH
def test_d6_pip_audit_illisible_en_code_0_n_est_pas_un_vert(tmp_path, monkeypatch):
    pip = _pip_audit(tmp_path, monkeypatch, "No known vulnerabilities found\n")

    assert pip.statut == "INDISPONIBLE"


def _source_osv(chemin, nombre, vulnerable=False):
    paquets = [{"package": {"name": f"p{n}", "version": "1.0", "ecosystem": "Packagist"}}
               for n in range(nombre)]
    if vulnerable:
        paquets[0] = {**paquets[0], "vulnerabilities": [{"id": "GHSA-xxxx"}],
                      "groups": [{"ids": ["GHSA-xxxx"], "max_severity": "7.5"}]}
    return {"source": {"path": str(chemin), "type": "lockfile"}, "packages": paquets}


def _osv(tmp_path, monkeypatch, sortie, code, attendus=()):
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "ECOSYSTEMES_OSV",
                        {"Autre": [tmp_path / chemin for chemin in attendus]})
    commande = lintorn.outils.osv.commande({"PHP": [tmp_path / "composer.lock"]})
    assert "--all-packages" in commande["cmd"], "sans lui, un vert ne dit rien de ce qu'il a lu"
    return _par_le_circuit(monkeypatch, {**commande, "cmd": _faux_outil(tmp_path, sortie, code)})


@_SANS_SH
def test_d6_le_vert_d_osv_dit_quels_verrous_il_a_lus(tmp_path, monkeypatch):
    sortie = json.dumps({"results": [_source_osv(tmp_path / "composer.lock", 150),
                                     _source_osv(tmp_path / "package-lock.json", 678)]})

    osv = _osv(tmp_path, monkeypatch, sortie, 0, attendus=["composer.lock"])

    assert osv.statut == "OK"
    assert osv.resume == "aucune faille connue dans 828 paquet(s) de 2 verrou(s)"
    assert "`composer.lock` (150 paquet(s))" in osv.detail and osv.detail_meme_au_vert


@_SANS_SH
def test_d6_un_verrou_annonce_mais_pas_lu_n_est_pas_un_vert(tmp_path, monkeypatch):
    """« 0 faille Dart » ne se distinguait pas d'un `pubspec.lock` jamais lu."""
    sortie = json.dumps({"results": [_source_osv(tmp_path / "composer.lock", 150)]})

    osv = _osv(tmp_path, monkeypatch, sortie, 0,
               attendus=["composer.lock", "mobile/pubspec.lock"])

    assert osv.statut == "VERIF"
    assert "1 verrou(s) NON lu(s)" in osv.resume
    assert "`mobile/pubspec.lock`" in osv.detail


@_SANS_SH
@pytest.mark.parametrize("sortie", ['{"results": []}', "pas du JSON"])
def test_d6_un_osv_en_code_0_sans_rien_de_lu_n_est_pas_un_vert(tmp_path, monkeypatch, sortie):
    osv = _osv(tmp_path, monkeypatch, sortie, 0)

    assert osv.statut == "INDISPONIBLE"
    assert "rien n'a ete verifie" in osv.resume


@_SANS_SH
def test_d6_le_tableau_d_osv_dit_aussi_ce_qu_il_a_lu(tmp_path, monkeypatch):
    sortie = json.dumps({"results": [_source_osv(tmp_path / "composer.lock", 3, True)]})

    osv = _osv(tmp_path, monkeypatch, sortie, 1, attendus=["composer.lock", "pubspec.lock"])

    assert osv.statut == "ALERTE"
    assert "`composer.lock` (3 paquet(s))" in osv.detail
    assert "`pubspec.lock`" in osv.detail
