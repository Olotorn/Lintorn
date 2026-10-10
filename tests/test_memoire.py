"""La mémoire de l'assistant IA : ce qu'elle cite existe-t-il, et est-ce encore frais ?

Tout passe par `noyau.executer` : un contrôle appelé seul resterait vert sur
un câblage mort.
"""

from __future__ import annotations

import datetime
import os
import subprocess

from lintorn import config, noyau

HIER = datetime.date.today() - datetime.timedelta(days=1)


def _git(projet, *arguments, date: str | None = None):
    env = {**os.environ}
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "-c", "user.email=x@x", "-c", "user.name=x", *arguments],
                   cwd=projet, check=True, capture_output=True, env=env)


def _projet(tmp_path, monkeypatch, code: dict[str, str], date: str | None = None):
    projet = tmp_path / "projet"
    projet.mkdir()
    for nom, contenu in code.items():
        (projet / nom).write_text(contenu, encoding="utf-8")
    _git(projet, "init", "-q")
    _git(projet, "add", "-A")
    _git(projet, "commit", "-qm", "un", date=date)
    memoire = tmp_path / "memoire"
    memoire.mkdir()
    monkeypatch.setattr(config, "RACINE", projet)
    monkeypatch.setattr(config, "SOUS_GIT", True)
    monkeypatch.setattr(config, "RACINES_RESOLUTION", [projet])
    monkeypatch.setattr(config, "MEMOIRE_IA", memoire)
    monkeypatch.setattr(config, "MEMOIRE_PAR_RESSEMBLANCE", False)
    monkeypatch.setattr(config, "COMMANDES", [])
    return projet, memoire


def _controle(monkeypatch, nom: str, titre: str):
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {nom: True})
    return next(r for r in noyau.executer() if r.titre.startswith(titre))


def _memoire_ia(monkeypatch):
    return _controle(monkeypatch, "memoire_ia", "Memoire IA")


def _fraicheur(monkeypatch):
    return _controle(monkeypatch, "fraicheur_memoire", "Fraicheur")


# ── Les fonctions citées ─────────────────────────────────────────────────────
def test_une_fonction_renommee_dans_le_code_est_signalee(tmp_path, monkeypatch):
    """`base._dossier_sur()` renommée `dossier_sur()` : la mémoire restait « OK »."""
    _, memoire = _projet(tmp_path, monkeypatch, {"base.py": "def dossier_sur():\n    pass\n"})
    (memoire / "fiche.md").write_text("Tout passe par `base._dossier_sur()`.\n", encoding="utf-8")

    resultat = _memoire_ia(monkeypatch)

    assert resultat.statut == "ALERTE"
    assert resultat.bloquant is False, "la memoire de l'IA ne bloque jamais un push"
    assert "base._dossier_sur()" in resultat.detail


def test_une_fonction_que_le_code_emploie_n_alerte_pas(tmp_path, monkeypatch):
    """`isatty()` vient de la bibliothèque standard : le projet s'en sert, elle existe."""
    _, memoire = _projet(tmp_path, monkeypatch, {
        "base.py": "import sys\n\ndef dossier_sur():\n    return sys.stdout.isatty()\n"})
    (memoire / "fiche.md").write_text(
        "`base.dossier_sur()` appelle `isatty()` et `sys.stdout.isatty()`.\n", encoding="utf-8")

    resultat = _memoire_ia(monkeypatch)

    assert resultat.statut == "OK"
    assert "3 fonction(s) citee(s)" in resultat.resume


def test_une_fonction_sans_module_inconnue_du_code_est_a_verifier(tmp_path, monkeypatch):
    """`fantome()` peut venir d'une autre bibliothèque : un doute, pas un mensonge."""
    _, memoire = _projet(tmp_path, monkeypatch, {"base.py": "x = 1\n"})
    (memoire / "fiche.md").write_text("Penser a `fantome()`.\n", encoding="utf-8")

    resultat = _memoire_ia(monkeypatch)

    assert resultat.statut == "VERIF"
    assert "fantome()" in resultat.detail


def test_la_doc_ne_fait_pas_exister_la_fonction_qu_elle_cite(tmp_path, monkeypatch):
    """L'index ne lit que le code : sinon la doc qui cite un nom le ferait exister."""
    projet, _ = _projet(tmp_path, monkeypatch, {
        "noyau.py": "def executer():\n    pass\n",
        "CLAUDE.md": "Tout part de `noyau.partie()`.\n",
        "NOTES.md": "Voir aussi `noyau.partie()` et partie.\n"})
    monkeypatch.setattr(config, "DOCS_A_VERIFIER", [projet / "CLAUDE.md", projet / "NOTES.md"])
    monkeypatch.setattr(config, "DOCS_ECARTES", {})

    resultat = _controle(monkeypatch, "doc_vs_code", "Doc vs code")

    assert resultat.statut == "ALERTE"
    assert resultat.bloquant is True, "dans la doc du depot, un nom faux bloque comme un chemin faux"
    assert "noyau.partie()" in resultat.detail


# ── La fraîcheur ─────────────────────────────────────────────────────────────
def _fiche(memoire, verifie_le: str):
    (memoire / "fiche.md").write_text(
        f"---\nname: x\nverifie_le: {verifie_le}\n---\nLe code vit dans `app.py`.\n",
        encoding="utf-8")


def test_du_code_cite_modifie_sans_commit_rend_la_fiche_suspecte(tmp_path, monkeypatch):
    """`git log` ne voit que les commits : du code réécrit et pas commité laissait la fiche fraîche."""
    projet, memoire = _projet(tmp_path, monkeypatch, {"app.py": "a = 1\n"},
                              date=f"{HIER} 08:00:00")
    _fiche(memoire, f"{HIER} 09:00")
    (projet / "app.py").write_text("a = 2\n", encoding="utf-8")

    resultat = _fraicheur(monkeypatch)

    assert resultat.statut == "VERIF"
    assert "pas encore commite" in resultat.detail
    assert "app.py" in resultat.detail


def test_une_modification_anterieure_a_la_relecture_ne_compte_pas(tmp_path, monkeypatch):
    """Modifié AVANT la relecture, même pas commité : la fiche a été relue après."""
    projet, memoire = _projet(tmp_path, monkeypatch, {"app.py": "a = 1\n"},
                              date=f"{HIER} 08:00:00")
    (projet / "app.py").write_text("a = 2\n", encoding="utf-8")
    avant = datetime.datetime.fromisoformat(f"{HIER}T08:30").timestamp()
    os.utime(projet / "app.py", (avant, avant))
    _fiche(memoire, f"{HIER} 09:00")

    resultat = _fraicheur(monkeypatch)

    assert resultat.statut == "OK", resultat.detail


def test_une_date_sans_heure_compte_toute_la_journee(tmp_path, monkeypatch):
    """`--since=<date>` se lisait « à l'heure qu'il est » : le verdict changeait selon l'heure."""
    _, memoire = _projet(tmp_path, monkeypatch, {"app.py": "a = 1\n"},
                         date=f"{HIER} 00:30:00")
    _fiche(memoire, str(HIER))

    resultat = _fraicheur(monkeypatch)

    assert resultat.statut == "VERIF"
    assert "toute la journee compte" in resultat.detail


def test_l_heure_ecrite_ne_compte_que_ce_qui_suit(tmp_path, monkeypatch):
    _, memoire = _projet(tmp_path, monkeypatch, {"app.py": "a = 1\n"},
                         date=f"{HIER} 00:30:00")
    _fiche(memoire, f"{HIER} 12:00")

    resultat = _fraicheur(monkeypatch)

    assert resultat.statut == "OK", resultat.detail


def test_une_date_impossible_n_est_pas_une_date(tmp_path, monkeypatch):
    _, memoire = _projet(tmp_path, monkeypatch, {"app.py": "a = 1\n"})
    _fiche(memoire, "2026-02-31")

    resultat = _fraicheur(monkeypatch)

    assert resultat.statut == "VERIF"
    assert "1 sans date" in resultat.resume


# ── Ce qui n'est pas une affirmation sur le projet ───────────────────────────
def test_un_dossier_du_projet_nomme_os_n_en_fait_pas_un_module_du_projet(tmp_path, monkeypatch):
    """ruff a un dossier `os/` : `os.fdopen()` passait pour une fonction du projet, absente."""
    projet, memoire = _projet(tmp_path, monkeypatch, {"base.py": "x = 1\n"})
    (projet / "os").mkdir()
    (projet / "os" / "outil.py").write_text("y = 2\n", encoding="utf-8")
    _git(projet, "add", "-A")
    _git(projet, "commit", "-qm", "deux")
    (memoire / "fiche.md").write_text("Le projet appelle `os.fdopen()`.\n", encoding="utf-8")

    resultat = _memoire_ia(monkeypatch)

    assert resultat.statut == "VERIF", "un doute, pas un mensonge sur le projet"


def test_un_journal_de_versions_cite_ce_qui_existait_a_l_epoque(tmp_path, monkeypatch):
    """`CHANGES.rst` et `docs/release-notes/` citent des fonctions retirées depuis : c'est leur rôle."""
    projet, _ = _projet(tmp_path, monkeypatch, {
        "noyau.py": "def executer():\n    pass\n",
        "CHANGES.rst": "- Retire ``noyau.ancienne()``.\n"})
    (projet / "docs" / "release-notes").mkdir(parents=True)
    notes = projet / "docs" / "release-notes" / "version-3.7.md"
    notes.write_text("Remplace `noyau.vieille()`.\n", encoding="utf-8")
    monkeypatch.setattr(config, "DOCS_A_VERIFIER", [projet / "CHANGES.rst", notes])
    monkeypatch.setattr(config, "DOCS_ECARTES", {})

    resultat = _controle(monkeypatch, "doc_vs_code", "Doc vs code")

    assert resultat.statut == "VERIF", resultat.resume
    assert resultat.bloquant is False
    assert "journal de versions" in resultat.detail


def test_un_vieux_nom_reste_dans_un_reglage_ne_fait_pas_exister_la_fonction(tmp_path, monkeypatch):
    """`bouger_stock()` renommée partout dans le code, mais citée par un commentaire de
    `.lintorn/regles.toml` : la doc qui la citait restait verte."""
    projet, memoire = _projet(tmp_path, monkeypatch, {
        "stock.py": "def deplacer_stock():\n    pass\n",
        "pyproject.toml": "# voir stock.bouger_stock\n[project]\nname = 'x'\n"})
    (projet / ".lintorn").mkdir()
    (projet / ".lintorn" / "regles.toml").write_text(
        "# interdit hors de bouger_stock()\n", encoding="utf-8")
    _git(projet, "add", "-A")
    _git(projet, "commit", "-qm", "deux")
    monkeypatch.setattr(config, "DOSSIER_LINTORN", projet / ".lintorn")
    (memoire / "fiche.md").write_text("Le stock bouge par `stock.bouger_stock()`.\n",
                                      encoding="utf-8")

    resultat = _memoire_ia(monkeypatch)

    assert resultat.statut == "ALERTE", resultat.resume
    assert "stock.bouger_stock()" in resultat.detail
