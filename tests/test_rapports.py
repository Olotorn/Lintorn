"""Ce que Lintorn montre : le focus d'un push, la console, la page HTML, la ligne qui tourne."""

import ast
import io
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from aides import _hook_pose, _hors_ascii, _regle

import lintorn.commandes
import lintorn.controles
import lintorn.outils
import lintorn.rapport
from lintorn import __version__, base, cli as Lintorn, config, noyau
from lintorn.base import Resultat
from lintorn.rapport import html as rapport_html


# ─────────────────────────────────────────────────────────────────────────────
# Le focus sur les fichiers d'un push
# ─────────────────────────────────────────────────────────────────────────────
def test_focus_ne_garde_que_les_fichiers_pousses(monkeypatch):
    """git parle en chemins depuis la racine, ruff depuis le backend :
    le focus doit reconnaître le même fichier sous ses deux formes.

    ⚠️ On FIXE les préfixes au lieu de laisser la détection les fournir : ce
    test vérifie la mécanique de rapprochement, pas l'arborescence de la
    machine qui l'exécute. Sans ça il passait ou échouait selon le projet
    audité — un test qui dépend de son environnement ne prouve rien.
    """
    monkeypatch.setattr(config, "PREFIXES_PROJET", ["api/", "front/src/"])
    faux = base.Resultat(
        "Ruff", "ALERTE", "2 alertes",
        "accounts/views.py:7\n    F401 import inutile\n"
        "stock/models.py:121\n    E741 nom ambigu",
    )

    focus = lintorn.rapport.focus.focus_sur([faux], ["api/accounts/views.py"])

    assert focus.statut == "ALERTE"
    assert "accounts/views.py" in focus.detail
    assert "stock/models.py" not in focus.detail


def test_le_focus_ne_change_pas_la_gravite_de_ce_qu_il_reprend(monkeypatch):
    """Deux `[ ?? ]` ne font pas un `[ !! ]`.

    Il rendait « ALERTE » en dur : juste avant un push, une memoire a relire
    devenait un rouge que rien ne pouvait eteindre.
    """
    monkeypatch.setattr(config, "PREFIXES_PROJET", [])
    doute = base.Resultat("Fraicheur memoire (git)", "VERIF", "1 suspecte",
                          "- `src/x.py`")

    focus = lintorn.rapport.focus.focus_sur([doute], ["src/x.py"])

    assert focus.statut == "VERIF"
    assert "point(s) a verifier" in focus.resume
    assert "defaut" not in focus.resume


def test_une_vraie_alerte_prime_sur_un_simple_doute(monkeypatch):
    monkeypatch.setattr(config, "PREFIXES_PROJET", [])
    doute = base.Resultat("Fraicheur", "VERIF", "", "- `src/x.py`")
    casse = base.Resultat("Ruff", "ALERTE", "", "src/x.py:7 F401")

    for ordre in ([doute, casse], [casse, doute]):
        assert lintorn.rapport.focus.focus_sur(ordre, ["src/x.py"]).statut == "ALERTE"


def test_le_focus_ne_compte_pas_une_citation_comme_un_defaut(monkeypatch):
    """Une regle CITEE peut nommer un fichier pousse : c'est de la prose.

    Elle etait comptee en plus de la trouvaille — la meme regle apparaissait
    deux fois, et le total ne voulait plus rien dire.
    """
    monkeypatch.setattr(config, "PREFIXES_PROJET", [])
    resultat = base.Resultat(
        "Regles enoncees vs controlees", "VERIF", "",
        "- [`CLAUDE.md:47`](../CLAUDE.md#L47)\n"
        "  > Langue | le `README.md` est en anglais",
        detail_markdown=True,
    )

    focus = lintorn.rapport.focus.focus_sur([resultat], ["CLAUDE.md", "README.md"])

    assert focus.detail.count("CLAUDE.md:47") == 1
    assert "Langue |" not in focus.detail


def test_la_sortie_brute_de_pytest_garde_ses_lignes_en_chevron(monkeypatch):
    """pytest marque l'assertion fautive par `>`. Le filtre a prose ne doit
    valoir que pour le markdown que Lintorn ecrit lui-meme."""
    monkeypatch.setattr(config, "PREFIXES_PROJET", [])
    brut = base.Resultat("Tests (pytest)", "ALERTE", "",
                         ">       assert charger('src/x.py')")

    assert "assert charger" in lintorn.rapport.focus.focus_sur([brut], ["src/x.py"]).detail


def test_un_outil_absent_n_alimente_pas_le_focus(monkeypatch):
    """INDISPONIBLE = l'outil n'a pas tourne. Son message n'est pas une
    trouvaille sur les fichiers pousses."""
    monkeypatch.setattr(config, "PREFIXES_PROJET", [])
    absent = base.Resultat("Ruff", "INDISPONIBLE", "ruff n'est pas installe",
                           "No module named ruff, en lisant src/x.py")

    assert lintorn.rapport.focus.focus_sur([absent], ["src/x.py"]).statut == "OK"


def test_focus_est_vert_quand_le_push_ne_touche_rien_de_casse(monkeypatch):
    monkeypatch.setattr(config, "PREFIXES_PROJET", ["api/", "front/src/"])
    faux = base.Resultat("Ruff", "ALERTE", "1 alerte", "stock/models.py:121\n    E741")

    focus = lintorn.rapport.focus.focus_sur([faux], ["front/src/App.tsx"])

    assert focus.statut == "OK"


def test_focus_reconnait_les_chemins_windows(monkeypatch):
    """Sous Windows, ruff écrit `api\\outils\\noyau.py` ; git parle en slashs.

    Sans normaliser AVANT de comparer, le focus ne reconnaissait plus RIEN sur
    cette machine — et comme le hook pre-push l'utilise, il annonçait « aucun
    defaut connu dedans » au moment précis du push. Faux vert, 12/08/2026.
    """
    monkeypatch.setattr(config, "PREFIXES_PROJET", ["api/"])
    faux = base.Resultat(
        "Ruff", "ALERTE", "1 alerte",
        r"api\outils\noyau.py:300:121: E501 Line too long",
    )

    focus = lintorn.rapport.focus.focus_sur([faux], ["api/outils/noyau.py"])

    assert focus.statut == "ALERTE", "chemins Windows non reconnus → faux vert au push"
    assert "noyau.py" in focus.detail


# ─────────────────────────────────────────────────────────────────────────────
# Un detail qui compte MEME au vert — sans laisser entrer ruff et pytest
# ─────────────────────────────────────────────────────────────────────────────
def _rapport_de(resultat, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "RAPPORT", tmp_path / "rapport.md")
    lintorn.rapport.markdown.ecrire_rapport([resultat])
    return (tmp_path / "rapport.md").read_text(encoding="utf-8")


def test_le_detail_d_un_controle_vert_reste_hors_du_rapport(tmp_path, monkeypatch):
    """Sans ce filtre, la sortie brute de ruff et de pytest — plusieurs pages —
    entrerait dans le fichier que lit l'assistant a chaque audit."""
    vert = Resultat("Ruff", "OK", "rien a signaler", "des pages de sortie brute")

    assert "sortie brute" not in _rapport_de(vert, tmp_path, monkeypatch)


def test_un_vert_peut_exiger_que_son_detail_passe(tmp_path, monkeypatch):
    """Une regle qui n'a rien verifie est un vert qui a quelque chose a
    MONTRER : le resume n'en donne que le nombre, jamais lesquelles."""
    vert = Resultat("Regles maison", "OK", "2 jamais declenchee(s)",
                    "- **Ma regle** — regles.toml:12", detail_meme_au_vert=True)

    assert "Ma regle" in _rapport_de(vert, tmp_path, monkeypatch)


def test_une_regle_jamais_declenchee_est_nommee_dans_le_rapport(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("un texte sans aucun chiffre", encoding="utf-8")
    _regle(tmp_path, monkeypatch, nom="Ma conditionnelle",
           motif_requis=r"\b69\b", si=r"\b110\b")

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.statut == "OK"
    assert resultat.detail_meme_au_vert is True
    assert "Ma conditionnelle" in resultat.detail


def test_une_regle_qu_on_n_a_pas_su_situer_est_quand_meme_nommee():
    """Le lien est un CONFORT. Sans numero de ligne, on donne le nom : taire
    la regle parce qu'on n'a pas su la localiser serait absurde."""
    rendu = lintorn.controles.projet.regles_maison._ou_est_ecrite({"nom": "Sans adresse", "ou": (None, None)})

    assert "Sans adresse" in rendu


# ─────────────────────────────────────────────────────────────────────────────
# Ce qui s'imprime dans une console reste en ASCII
# ─────────────────────────────────────────────────────────────────────────────
def _litteraux(noeud):
    """Tous les morceaux littéraux d'une expression, où qu'ils soient.

    ⚠️ Lire seulement les f-strings et les concaténations laissait passer
    `"..." + (f"  ·  ..." if ... else "")` : le « · » de la ligne du rapport
    est arrivé sous Windows par ce chemin-là.
    """
    return [n.value for n in ast.walk(noeud)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]




def test_la_console_ne_peut_plus_planter_sur_un_caractere():
    """`_console_sure()` degrade au lieu d'exploser.

    Sous Git Bash, `sys.stdout` herite du codepage cp1252 : un caractere
    absent de cette table y levait une UnicodeEncodeError, donc un hook
    pre-push qui echoue sans message exploitable.
    """
    flux = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    flux.reconfigure(errors="replace")          # ce que fait _console_sure()

    flux.write("Lintorn \u273b pret\n")        # une etoile absente de cp1252
    flux.flush()

    assert flux.buffer.getvalue().decode("cp1252") == "Lintorn ? pret\n"


def test_ce_qui_s_imprime_reste_lisible_sur_une_console_etroite():
    """Ce qui part vers la console doit s'AFFICHER, pas seulement ne pas planter.

    ⚠️ cp1252 ne suffit pas. Sous Windows, python écrit en cp1252 quand sa
    sortie n'est pas une console, et pre-commit la relit en UTF-8 : un « · »,
    pourtant dans cp1252, s'affichait « � » à chaque push. Seul l'ASCII
    s'affiche partout.

    Le RAPPORT, lui, est un fichier UTF-8 : il garde tout. Seule la console
    est etroite.
    """
    fautifs = []
    # ⚠️ On CHERCHE les modules au lieu de les nommer. Nommes un par un
    # ("noyau.py", "cli.py"), ce test a cesse de voir 32 des 35 appels a
    # `Resultat(...)` le jour ou le code a ete scinde en quatre fichiers — sans
    # echouer, donc sans que personne ne s'en apercoive. Un test muet est la
    # panne exacte que Lintorn combat ; il n'avait pas le droit d'en etre un.
    # `rglob` : un module rangé dans un sous-dossier (`commandes/`) échapperait
    # sinon à ce test, sans qu'il échoue.
    paquet = Path(Lintorn.__file__).parent
    for chemin in sorted(paquet.rglob("*.py")):
        nom = chemin.relative_to(paquet).as_posix()
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call):
                continue
            appele = getattr(noeud.func, "id", "")
            if appele == "print":
                cibles = noeud.args
            elif appele == "Resultat":
                # 0 = titre, 2 = resume : affiches. 3 = detail : va au rapport.
                cibles = [a for i, a in enumerate(noeud.args) if i in (0, 2)]
            else:
                continue
            for arg in cibles:
                for texte in _litteraux(arg):
                    hors = _hors_ascii(texte)
                    if hors:
                        fautifs.append(f"{nom}:{noeud.lineno} {hors} {texte[:45]}")

    for texte in (lintorn.commandes.aide.GUIDE, lintorn.commandes.aide.AIDE):
        hors = _hors_ascii(texte)
        if hors:
            fautifs.append(f"texte fixe {hors}")

    assert fautifs == [], "hors ASCII, donc illisible sous pre-commit Windows :\n  " + "\n  ".join(fautifs)


# ─────────────────────────────────────────────────────────────────────────────
# La page HTML : la MEME matiere que rapport.md, jamais un second verdict
# ─────────────────────────────────────────────────────────────────────────────
def test_la_page_html_ne_laisse_pas_passer_le_html_d_un_depot(tmp_path, monkeypatch):
    """Un depot peut nommer un fichier `<img onerror=...>` : ce nom arrive
    dans le rapport, donc dans une page qui s'ouvre sur la machine du
    lecteur."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    mechant = Resultat("<script>alert(1)</script>", "ALERTE", "<b>resume</b>",
                       "- `<img onerror=x>` trouve", detail_markdown=True)

    page = rapport_html.page([mechant])

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<img onerror" not in page


def test_la_page_html_rend_ce_que_lintorn_ecrit():
    """Citations, tableaux, liens relatifs et `<br>` : le sous-ensemble de
    Markdown que les details utilisent vraiment."""
    rendu = rapport_html._rendre(
        "> une regle citee\n\n### Un titre\n\n| A | B |\n|---|---|\n| `x` | 1 |\n\n"
        "- **gras** et [lien](../src/x.py#L4)<br>suite")

    assert "<blockquote>une regle citee</blockquote>" in rendu
    assert "<h3>Un titre</h3>" in rendu
    assert "<th>A</th>" in rendu and "<td><code>x</code></td>" in rendu
    assert '<a href="../src/x.py#L4">lien</a>' in rendu
    assert "<br>suite" in rendu, "le <br> des details est celui de Lintorn"


def test_la_page_html_refuse_un_lien_qui_executerait_du_code():
    assert "javascript:" not in rapport_html._rendre("- [clique](javascript:alert(1))")


def test_la_page_html_dit_la_meme_chose_que_le_verdict(tmp_path, monkeypatch):
    """Deux rendus qui se contrediraient seraient pires que pas de page."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    resultats = [Resultat("Bloquant", "ALERTE", "3 defauts", bloquant=True),
                 Resultat("Consultatif", "VERIF", "a relire", bloquant=False)]

    page = rapport_html.page(resultats)

    assert "1 contrôle(s) bloquant(s) en alerte" in page
    assert "1 alerte" in page and "1 à vérifier" in page


def test_la_page_html_s_ecrit_a_cote_du_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "RAPPORT", tmp_path / ".lintorn" / "rapport.md")
    monkeypatch.setattr(config, "RAPPORT_HTML", tmp_path / ".lintorn" / "rapport.html")

    assert lintorn.rapport.markdown.ecrire_rapport([Resultat("Ruff", "OK", "rien a signaler")]) is True

    assert (tmp_path / ".lintorn" / "rapport.md").is_file()
    assert "<!DOCTYPE html>" in (tmp_path / ".lintorn" / "rapport.html").read_text(encoding="utf-8")


def test_une_doc_qui_cite_les_rapports_ne_ment_pas_sur_un_clone_neuf(tmp_path, monkeypatch):
    """Le controle de la doc tourne AVANT l'ecriture du rapport. Sur un clone
    neuf de Lintorn, son README citait `rapport.md` et `rapport.html` —
    absents — et le premier push d'un contributeur etait bloque."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "RAPPORT", tmp_path / ".lintorn" / "rapport.md")
    monkeypatch.setattr(config, "RAPPORT_HTML", tmp_path / ".lintorn" / "rapport.html")
    monkeypatch.setattr(config, "ETAT", tmp_path / ".lintorn" / "etat.json")
    doc = tmp_path / "README.md"
    doc.write_text("Voir `rapport.md`, `.lintorn/rapport.html` et `etat.json`, "
                   "`rapport-push.md` et `.lintorn/rapport-push.html`. "
                   "Mais `rapport_fantome.md` n'existe pas.", encoding="utf-8")

    resultat = lintorn.controles.projet.doc_vs_code._verifier_documents("t", [doc], bloquant_possible=True)

    assert resultat.resume.startswith("6 chemin(s) cite(s), 1 introuvable(s)")
    assert "rapport_fantome.md" in resultat.detail


@pytest.mark.parametrize("hook, nom, quand", [
    (False, "rapport", "hors push"),
    (True, "rapport-push", "pendant un push"),
], ids=["commande", "push"])
def test_les_deux_rendus_portent_le_meme_moment_la_meme_version_et_d_ou_ils_viennent(
        tmp_path, monkeypatch, hook, nom, quand):
    """Vu par le dev : un `rapport.md` neuf, une page de la veille, et rien
    pour dire qu'ils ne venaient ni du meme passage, ni du meme Lintorn."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "RAPPORT", tmp_path / ".lintorn" / "rapport.md")

    assert lintorn.rapport.markdown.ecrire_rapport(
        [Resultat("Ruff", "OK", "rien a signaler")], hook=hook) is True

    markdown = (tmp_path / ".lintorn" / f"{nom}.md").read_text(encoding="utf-8")
    page = (tmp_path / ".lintorn" / f"{nom}.html").read_text(encoding="utf-8")
    jour, heure, version, origine = re.search(
        r"Généré le (\S+) (\S+) par `lintorn ([^`]+)`, \*\*([^*]+)\*\*", markdown).groups()
    assert f"Généré le {jour} à {heure} par lintorn {version}, {quand}." in page
    assert version == __version__
    assert origine == quand
    assert f"<code>{nom}.md</code>, qui reste la source" in page
    assert sorted(p.name for p in (tmp_path / ".lintorn").iterdir()) == [f"{nom}.html", f"{nom}.md"]


def test_une_page_qui_ne_peut_pas_etre_reecrite_ne_survit_pas(tmp_path, monkeypatch):
    """La page d'un audit precedent, a cote d'un rapport neuf, le
    contredirait : deux verdicts pour un meme projet."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "RAPPORT", tmp_path / ".lintorn" / "rapport.md")
    (tmp_path / ".lintorn").mkdir()
    (tmp_path / ".lintorn" / "rapport.html").write_text("verdict d'hier", encoding="utf-8")
    ecrire = base.ecrire_sortie

    def page_impossible(fichier, contenu):
        if fichier.suffix == ".html":
            raise OSError("disque plein")
        ecrire(fichier, contenu)
    monkeypatch.setattr(base, "ecrire_sortie", page_impossible)

    assert lintorn.rapport.markdown.ecrire_rapport([Resultat("Ruff", "OK", "rien")]) is True

    assert (tmp_path / ".lintorn" / "rapport.md").is_file()
    assert not (tmp_path / ".lintorn" / "rapport.html").exists(), "une page perimee a survecu"


def test_retirer_une_sortie_ne_passe_pas_par_un_dossier_lie_ailleurs(tmp_path, monkeypatch):
    """Le retrait d'une page perimee contournait les gardes de l'ecriture : a
    travers un `.lintorn` lie ailleurs, il aurait efface un fichier HORS du
    projet."""
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    (ailleurs / "rapport.html").write_text("a quelqu'un d'autre", encoding="utf-8")
    projet = tmp_path / "projet"
    projet.mkdir()
    (projet / ".lintorn").symlink_to(ailleurs)
    monkeypatch.setattr(config, "RACINE", projet)

    with pytest.raises(OSError):
        base.retirer_sortie(projet / ".lintorn" / "rapport.html")

    assert (ailleurs / "rapport.html").read_text(encoding="utf-8") == "a quelqu'un d'autre"


def test_la_page_html_n_est_pas_lue_par_les_regles_maison(tmp_path, monkeypatch):
    """Une regle qui lit les .html comptait ses propres citations dans la
    page, un peu plus a chaque passage — comme jadis avec rapport.md."""
    (tmp_path / ".lintorn").mkdir()
    (tmp_path / ".lintorn" / "rapport.html").write_text("interdit interdit", encoding="utf-8")
    (tmp_path / "vrai.html").write_text("interdit", encoding="utf-8")
    monkeypatch.setattr(config, "RAPPORT_HTML", tmp_path / ".lintorn" / "rapport.html")
    _regle(tmp_path, monkeypatch, suffixes=[".html"])

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.fichiers == {"vrai.html": "interdit : 1"}


def test_une_regle_ne_se_trouve_pas_dans_sa_propre_definition(tmp_path, monkeypatch):
    """Un brouillon de `lintorn regles` sur un `.toml`, décommenté avec un motif
    littéral : la règle se trouvait dans regles.toml, et dans la table du
    pyproject qui la déclare. Le reste du pyproject reste lu."""
    (tmp_path / ".lintorn").mkdir()
    (tmp_path / ".lintorn" / "regles.toml").write_text(
        "[[regles]]\nnom = 'interdit'\nmotif = 'interdit'\n", encoding="utf-8")
    (tmp_path / ".lintorn" / "config.toml").write_text("[controles]\n# interdit\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'interdit'\n\n[[tool.lintorn.regles]]\nnom = 'interdit'\n"
        "motif = 'interdit'\n\n[tool.ruff]\nline-length = 99\n", encoding="utf-8")
    monkeypatch.setattr(config, "DOSSIER_LINTORN", tmp_path / ".lintorn")
    monkeypatch.setattr(config, "FICHIER_REGLES", tmp_path / ".lintorn" / "regles.toml")
    _regle(tmp_path, monkeypatch, suffixes=[".toml"])

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.fichiers == {".lintorn/config.toml": "interdit : 1",
                                 "pyproject.toml": "interdit : 1"}, resultat.fichiers


@pytest.mark.parametrize("sortie", ["rapport-push.md", "rapport-push.html"])
def test_le_rapport_du_push_n_est_pas_lu_par_les_regles_maison(tmp_path, monkeypatch, sortie):
    """Il cite les fautes qu'il a trouvées : une règle qui le lisait les
    comptait une seconde fois, et une de plus à chaque push."""
    (tmp_path / ".lintorn").mkdir()
    (tmp_path / ".lintorn" / sortie).write_text("interdit interdit", encoding="utf-8")
    (tmp_path / "vrai.md").write_text("interdit", encoding="utf-8")
    monkeypatch.setattr(config, "RAPPORT", tmp_path / ".lintorn" / "rapport.md")
    _regle(tmp_path, monkeypatch, suffixes=[".md", ".html"])

    resultat = lintorn.controles.projet.regles_maison.controle_regles_maison()

    assert resultat.fichiers == {"vrai.md": "interdit : 1"}


@pytest.mark.skipif(os.name == "nt", reason="le hook est un script sh")
def test_le_hook_audite_le_projet_ou_il_est_pose_pas_le_sommet_du_depot(tmp_path):
    """git lance ses hooks depuis le SOMMET du depot, et Lintorn remonte au
    `.git` pour trouver sa racine : sur un monorepo, le hook auditait le
    sommet, n'y trouvait aucune regle, et laissait passer un push que le
    sous-projet interdisait — en affichant « Lintorn tournera avant chaque
    push »."""
    depot = tmp_path / "depot"
    (depot / "api" / ".lintorn" / "hooks").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(depot)], check=True, timeout=30)
    hook = depot / "api" / ".lintorn" / "hooks" / "pre-push"
    hook.write_bytes((config.HOOKS_SOURCE / "pre-push").read_bytes())
    hook.chmod(0o755)
    # Un faux `lintorn` qui note d'ou on l'appelle, et quelle racine on lui nomme.
    binaire = tmp_path / "bin"
    binaire.mkdir()
    trace = tmp_path / "trace"
    (binaire / "lintorn").write_text(
        f'#!/bin/sh\necho "$PWD|$LINTORN_RACINE" > {trace}\n', encoding="utf-8")
    (binaire / "lintorn").chmod(0o755)

    subprocess.run(["sh", str(hook)], cwd=depot, input="", text=True, timeout=60,
                   env={**os.environ, "PATH": f"{binaire}:{os.environ['PATH']}"}, check=False)

    ou, racine = trace.read_text(encoding="utf-8").strip().split("|")
    projet = (depot / "api").resolve()
    assert Path(ou).resolve() == projet, "le hook doit se placer dans le projet"
    assert Path(racine).resolve() == projet, "et NOMMER la racine : sans elle, Lintorn remonte"


def _hook_avec_un_faux_lintorn(tmp_path, projet, avant, apres):
    """Joue le vrai hook devant un faux `lintorn` qui note ses arguments et
    ce qu'il recoit sur son entree standard."""
    hook = projet / ".lintorn" / "hooks" / "pre-push"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_bytes((config.HOOKS_SOURCE / "pre-push").read_bytes())
    hook.chmod(0o755)
    binaire = tmp_path / "bin"
    binaire.mkdir()
    arguments, entree = tmp_path / "arguments", tmp_path / "entree"
    (binaire / "lintorn").write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{arguments}'\ncat > '{entree}'\n",
        encoding="utf-8")
    (binaire / "lintorn").chmod(0o755)

    subprocess.run(["sh", str(hook)], cwd=projet, text=True, timeout=120, check=False,
                   input=f"refs/heads/main {apres} refs/heads/main {avant}\n",
                   env={**os.environ, "PATH": f"{binaire}:{os.environ['PATH']}"})

    return (arguments.read_text(encoding="utf-8").splitlines(),
            [ligne for ligne in entree.read_text(encoding="utf-8").splitlines() if ligne])


@pytest.mark.skipif(os.name == "nt", reason="le hook est un script sh")
def test_le_hook_pousse_des_milliers_de_fichiers_sans_ligne_de_commande(tmp_path):
    """Trouve sous Windows : une ligne de commande y tient en 32 767
    caracteres. Un push de mille fichiers — premier push d'un projet, venv
    commite par erreur — empechait Lintorn de demarrer, et le push etait
    refuse sans un mot. Linux tolere bien plus : ce qu'on verifie ici, c'est
    le MECANISME — les noms ne passent plus du tout par la ligne de commande."""
    git = ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
    (tmp_path / "debut.md").write_text("rien", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True, timeout=30)
    subprocess.run([*git, "commit", "-qm", "un"], check=True, timeout=30)
    avant = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True,
                           check=True, timeout=30).stdout.strip()
    (tmp_path / "beaucoup").mkdir()
    for numero in range(3000):
        (tmp_path / "beaucoup" / f"fichier_numero_{numero:04}_au_nom_assez_long.txt").touch()
    subprocess.run([*git, "add", "-A"], check=True, timeout=60)
    subprocess.run([*git, "commit", "-qm", "deux"], check=True, timeout=60)
    apres = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True,
                           check=True, timeout=30).stdout.strip()

    arguments, entree = _hook_avec_un_faux_lintorn(tmp_path, tmp_path, avant, apres)

    assert arguments == ["--rapide", "--fichiers-stdin"]
    assert len(entree) == 3000, "chaque fichier pousse doit arriver, et un seul par ligne"


def test_les_fichiers_pousses_se_lisent_comme_des_chemins(monkeypatch):
    """Lus en octets et decodes comme un chemin : la console de Windows parle
    cp1252, git ecrit ses noms en UTF-8. Et coupes sur \\n seulement."""
    brut = "a.py\ncafé.py\nnom\u2028etrange.md\n\n".encode("utf-8")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(brut), encoding="cp1252"))

    assert lintorn.commandes.audit._fichiers_de_l_entree() == ["a.py", "café.py", "nom\u2028etrange.md"]


@pytest.mark.skipif(os.name == "nt", reason="le hook est un script sh")
def test_le_hook_transmet_les_noms_avec_espace_et_accent(tmp_path):
    """Deux pieges, un seul symptome : le hook decoupait sa liste sur les
    espaces, et git echappe les noms non-ASCII (`\\303\\251`). Le focus
    cherchait donc des noms qui ne designaient rien, et annoncait « aucun
    defaut dedans » sur un fichier fautif."""
    projet = tmp_path / "projet"
    (projet / ".lintorn" / "hooks").mkdir(parents=True)
    git = ["git", "-C", str(projet)]
    subprocess.run(["git", "init", "-q", str(projet)], check=True, timeout=30)
    for reglage, valeur in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run([*git, "config", reglage, valeur], check=True, timeout=30)
    (projet / "debut.md").write_text("rien", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True, timeout=30)
    subprocess.run([*git, "commit", "-qm", "un"], check=True, timeout=30)
    avant = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True,
                           check=True, timeout=30).stdout.strip()
    (projet / "notes de réunion éxotiques.md").write_text("INTERDIT", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True, timeout=30)
    subprocess.run([*git, "commit", "-qm", "deux"], check=True, timeout=30)
    apres = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True,
                           check=True, timeout=30).stdout.strip()

    arguments, entree = _hook_avec_un_faux_lintorn(tmp_path, projet, avant, apres)

    assert "notes de réunion éxotiques.md" in entree, f"nom abime : {entree}"
    assert arguments == ["--rapide", "--fichiers-stdin"], "plus aucun nom en argument"


def test_un_chemin_de_hooks_absolu_n_est_pas_un_autre_dossier(tmp_path, monkeypatch):
    """`git config core.hooksPath "$PWD/.lintorn/hooks"` est valide et marche.
    Compare comme une CHAINE, il rendait « NON BRANCHE - git push ne controle
    RIEN » : un rouge permanent, qu'aucune commande ne pouvait eteindre."""
    (tmp_path / ".lintorn" / "hooks").mkdir(parents=True)
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "SOMMET_GIT", tmp_path)

    assert lintorn.controles.outillage.hook_git._meme_dossier(str(tmp_path / ".lintorn" / "hooks"),
                                             ".lintorn/hooks") is True
    assert lintorn.controles.outillage.hook_git._meme_dossier("autre/hooks", ".lintorn/hooks") is False
    assert lintorn.controles.outillage.hook_git._meme_dossier("", ".lintorn/hooks") is False


def test_des_crlf_ailleurs_que_dans_le_shebang_cassent_aussi_le_hook(tmp_path, monkeypatch):
    """`sh` lit le `\r` comme un caractere de la commande. Ne regarder que la
    premiere ligne annoncait « PERIME » sur un hook cassé."""
    livre = (config.HOOKS_SOURCE / "pre-push").read_bytes()
    _hook_pose(tmp_path, monkeypatch, livre.replace(b"echo", b"echo\r", 1))

    resultat = lintorn.controles.outillage.hook_git._controle_hook_executable("t")

    assert resultat.statut == "ALERTE"
    assert "retour chariot" in resultat.resume


def test_le_resume_d_un_outil_en_panne_n_affiche_pas_d_echappements():
    """Le resume part vers la CONSOLE : les echappements Markdown des tableaux
    s'y affichaient tels quels — `(\\[Errno 111\\] Connection refused"))))`."""
    raison = lintorn.outils.commun.raison_de_l_echec("ProxyError: [Errno 111] Connection refused")

    assert "\\[" not in raison
    assert "[Errno 111] Connection refused" in raison


def test_ce_un_monorepo_branche_le_hook_la_ou_git_le_cherchera(tmp_path, monkeypatch):
    """git resout un `core.hooksPath` relatif depuis le SOMMET du depot : sur
    un sous-projet, `.lintorn/hooks` designait un dossier inexistant. git ne
    lancait rien, sans un mot, et le controle affichait « branche »."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=30)
    api = tmp_path / "api"
    api.mkdir()
    monkeypatch.setattr(config, "RACINE", api)
    monkeypatch.setattr(config, "HOOKS", api / ".lintorn" / "hooks")
    monkeypatch.setattr(config, "SOUS_GIT", True)
    # Le sommet est demande a git, comme au demarrage.
    monkeypatch.setattr(config, "SOMMET_GIT", config._sommet_git())

    assert config._hooks_pour_git() == "api/.lintorn/hooks"


# ─────────────────────────────────────────────────────────────────────────────
# La ligne qui tourne pendant l'audit
# ─────────────────────────────────────────────────────────────────────────────
class _Terminal(io.StringIO):
    def isatty(self):
        return True


def test_l_attente_ne_s_affiche_que_dans_un_terminal():
    """Redirigée dans un fichier ou lue par la CI, une ligne réécrite cent fois n'est que du bruit."""
    flux = io.StringIO()

    with lintorn.rapport.attente.Attente(flux) as ligne:
        ligne.etape("Tests (pytest)")
        time.sleep(0.25)

    assert flux.getvalue() == ""


def test_l_attente_nomme_l_etape_puis_s_efface():
    """Effacée avant le verdict : sinon le rapport s'écrirait par-dessus."""
    flux = _Terminal()

    with lintorn.rapport.attente.Attente(flux) as ligne:
        ligne.etape("Tests (pytest)")
        time.sleep(0.25)

    ecrit = flux.getvalue()
    assert "Lintorn travaille : Tests (pytest)" in ecrit
    assert re.search(r"\r +\r$", ecrit), "la ligne doit etre effacee a la fin"


def test_l_attente_ne_demarre_pas_avant_la_premiere_etape():
    """La question de l'accord passe avant : une ligne qui tourne la couvrirait."""
    flux = _Terminal()

    with lintorn.rapport.attente.Attente(flux):
        time.sleep(0.25)

    assert flux.getvalue() == ""


def test_le_noyau_annonce_chaque_outil_avant_de_le_lancer(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "COMMANDES", [{
        "cle": "x", "titre": "Outil X", "cmd": [sys.executable, "-c", "pass"], "cwd": tmp_path,
        "bloquant": False, "traduction": None, "lent": False}])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {"configuration": True})
    # Sans venv du projet, un outil lancé par `sys.executable` est refusé.
    monkeypatch.setattr(config, "VENV_PROJET", tmp_path / ".venv")
    annonces: list[str] = []

    noyau.executer(etape=annonces.append)

    assert annonces == ["Outil X", "configuration"]
