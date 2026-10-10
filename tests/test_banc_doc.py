# Lintorn
#
# Doc vs code et les règles énoncées, face aux dépôts du banc d'essai.
#
# Chaque test rejoue, en miniature, une situation trouvée sur un vrai projet :
# un faux positif qui bloquait le push, ou une doc que personne ne lisait.
# Les verdicts passent par le VRAI circuit (`noyau.executer`, dans un
# processus neuf) : la découverte des documents se joue à l'import de
# `config`, et un test qui appellerait le contrôle seul resterait vert sur
# un câblage mort.

import json
import os
import subprocess
import sys
from pathlib import Path

import lintorn
import lintorn.controles
from lintorn import config

# Le processus neuf doit charger CE code, pas une autre installation : un
# PYTHONPATH relatif se résoudrait dans le faux projet.
_PAQUET = str(Path(lintorn.__file__).resolve().parents[1])

_CIRCUIT = (
    "import json; from lintorn import config, noyau\n"
    "config.COMMANDES = []\n"
    "config.CONTROLES_INTERNES = {'doc_vs_code': True}\n"
    "r = [x for x in noyau.executer() if x.titre == 'Doc vs code'][0]\n"
    "print(json.dumps({'statut': r.statut, 'resume': r.resume,"
    " 'detail': r.detail, 'bloquant': r.bloquant}))\n"
)


def _projet(tmp_path, fichiers: dict[str, str], gitignore: str | None = None):
    """Écrit un faux projet. Avec `gitignore`, c'est un vrai dépôt git :
    `git check-ignore` ne se simule pas."""
    if gitignore is not None:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, capture_output=True, check=True)
        (tmp_path / ".gitignore").write_text(gitignore, encoding="utf-8")
    for chemin, contenu in fichiers.items():
        cible = tmp_path / chemin
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(contenu, encoding="utf-8")


def _doc_vs_code(tmp_path, fichiers: dict[str, str], gitignore: str | None = None) -> dict:
    """Le verdict de « Doc vs code » sur ce faux projet, par `noyau.executer`."""
    _projet(tmp_path, fichiers, gitignore)
    environnement = {**os.environ, "LINTORN_RACINE": str(tmp_path),
                     "PYTHONPATH": os.pathsep.join(
                         [_PAQUET, *filter(None, [os.environ.get("PYTHONPATH")])])}
    sortie = subprocess.run([sys.executable, "-c", _CIRCUIT], cwd=tmp_path,
                            capture_output=True, text=True, env=environnement,
                            timeout=60, check=False)
    assert sortie.returncode == 0, f"Lintorn est tombe :\n{sortie.stderr}"
    return json.loads(sortie.stdout.strip().splitlines()[-1])


# ─────────────────────────────────────────────────────────────────────────────
# C1 e — `vendor/` : la doc des dépendances n'est pas celle du projet
# ─────────────────────────────────────────────────────────────────────────────
def test_une_doc_sous_vendor_n_est_pas_lue_mais_elle_est_comptee(tmp_path):
    """Le commentaire de config.py annonçait `vendor` dans IGNORES ; il n'y
    était pas. Sur un projet Go ou PHP qui commite ses dépendances, c'est la
    doc de chacune qui aurait été vérifiée — et qui aurait bloqué le push."""
    verdict = _doc_vs_code(tmp_path, {
        "src/app.py": "",
        "README.md": "Le point d'entree est `src/app.py`.",
        "vendor/lib/README.md": "Voir `lib/interne.py`.",
    })

    assert verdict["statut"] == "OK", verdict
    assert "1 doc(s) sous vendor/ non lu(s)" in verdict["resume"], (
        "une doc du depot qu'on ne lit pas doit etre COMPTEE, pas sautee en silence")
    assert "vendor/lib/README.md" in verdict["detail"], "et NOMMEE, meme au vert"


# ─────────────────────────────────────────────────────────────────────────────
# C1 d — un `.md` de fixtures est l'entrée d'un test, pas de la doc
# ─────────────────────────────────────────────────────────────────────────────
def test_une_fixture_markdown_n_est_pas_de_la_doc(tmp_path):
    """Un `.md` sous `tests/fixtures/` nomme des fichiers imaginaires que le
    test fabrique : lu comme de la doc, il bloquait le push."""
    verdict = _doc_vs_code(tmp_path, {
        "src/app.py": "",
        "README.md": "Le point d'entree est `src/app.py`.",
        "tests/fixtures/entree.md": "Le module `virtuel/runtime.py` n'existe pas.",
        "pkg/testdata/cas.md": "Voir `autre/virtuel.go`.",
    })

    assert verdict["statut"] == "OK", verdict
    assert "2 doc(s) de fixtures de test non lu(s)" in verdict["resume"]
    assert "tests/fixtures/entree.md" in verdict["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# C2 a — la doc en `.mdx` et en `.rst` est lue, avec SA syntaxe
# ─────────────────────────────────────────────────────────────────────────────
_RST = """\
Le module ``src/app.py`` demarre tout, :file:`src/disparu.py` n'existe plus.
Il s'appuie sur ``src/b.py`` et sur :file:`src/c.py`.

Le fournisseur :mod:`flask.json` est une reference, pas un fichier.

Exemple::

    ``bloc/de/code.py`` est un exemple, pas une citation.

.. code-block:: python
   :caption: ``encore/un/exemple.py``

   print("rien")

.. note::

   Une note est de la prose : ``src/aussi_disparu.py`` y est lu.
"""


def test_une_doc_sphinx_est_lue_avec_la_syntaxe_du_rest(tmp_path):
    """Les 79 `.rst` d'une doc Sphinx n'étaient pas ouverts, et le rapport
    conseillait de « mettre les chemins entre backticks » — c'était déjà le
    cas, en double. Lus comme du Markdown, les rôles (`:mod:`) passeraient
    pour des fichiers."""
    verdict = _doc_vs_code(tmp_path, {"src/app.py": "", "src/b.py": "", "src/c.py": "",
                                      "docs/index.rst": _RST})

    assert verdict["statut"] == "ALERTE", verdict
    assert "5 chemin(s) cite(s)" in verdict["resume"], verdict["resume"]
    assert "`src/disparu.py`" in verdict["detail"], ":file: est une citation de fichier"
    assert "`src/aussi_disparu.py`" in verdict["detail"], "le contenu d'une note est lu"
    assert "flask.json" not in verdict["detail"], "un role n'est pas un fichier"
    assert "exemple" not in verdict["detail"], "les blocs de code ne sont pas des citations"


def test_une_doc_mdx_est_lue(tmp_path):
    """Un centre d'aide Docusaurus ou Starlight : 464 `.mdx` jamais ouverts."""
    verdict = _doc_vs_code(tmp_path, {
        "src/app.py": "",
        "docs/guide.mdx": "import X from '@site/x';\n\nVoir `src/app.py` et `src/parti.py`.",
    })

    assert verdict["statut"] == "ALERTE", verdict
    assert "`src/parti.py`" in verdict["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# C2 b — un nom de source Go, Ruby, PHP… cité seul est vérifié
# ─────────────────────────────────────────────────────────────────────────────
def test_un_nom_de_source_hors_python_et_js_est_verifie(tmp_path):
    """Un `explorer.go` ou un `account.rb` cité par son seul nom n'était
    jamais vérifié : sur ces projets, la doc pouvait pourrir sans un mot.
    Un `nginx.conf` cité seul reste hors du contrôle : c'est presque toujours
    celui de la machine du lecteur."""
    verdict = _doc_vs_code(tmp_path, {
        "cmd/serveur.go": "",
        "app/models/compte.rb": "",
        "README.md": "Le serveur `serveur.go` et le modele `compte.rb` ; "
                     "`explorer.go` a disparu. Configure ton `nginx.conf`.",
    })

    assert verdict["statut"] == "ALERTE", verdict
    assert "3 chemin(s) cite(s)" in verdict["resume"], verdict["resume"]
    assert "`explorer.go`" in verdict["detail"]
    assert "nginx.conf" not in verdict["detail"]


def test_les_consignes_anglaises_d_un_agents_md_sont_des_regles(tmp_path, monkeypatch):
    """« aucune regle reperee » sur des AGENTS.md faits de règles : seul le
    français était compris, et seules les lignes de tableau comptaient.
    Le récit reste dehors, dans les deux langues."""
    doc = tmp_path / "AGENTS.md"
    doc.write_text(
        "- **FK filters**: Always add explicit `<field>_id` variants.\n"
        "- Don't prefix tests with `test_`.\n"
        "- In TS, use `!` instead of `?.` when a value always exists.\n"
        "Run it first. Do not use `--skip-provision-check` to work around it.\n"
        "- The `cache` module is never invalidated by hand.\n"
        "- Un devis `VALIDE` n'expire jamais : c'est un engagement signe.\n"
        "```\n"
        "# never call `rm -rf` here\n"
        "```\n",
        encoding="utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "DOCS_IA", [doc])

    lignes = [numero for _, numero, _, _ in lintorn.controles.projet.regles_enoncees.regles_enoncees()]

    assert lignes == [1, 2, 3, 4], "4 consignes ; ni le recit ni le bloc de code"


def test_sans_citation_le_conseil_nomme_les_trois_syntaxes(tmp_path):
    verdict = _doc_vs_code(tmp_path, {"docs/index.rst": "Une doc sans aucun litteral."})

    assert verdict["statut"] == "INDISPONIBLE", verdict
    assert ":file:`services/api.ts`" in verdict["detail"]
    assert "``services/api.ts``" in verdict["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# C1 a — un fichier gitignoré par construction n'est pas « introuvable »
# ─────────────────────────────────────────────────────────────────────────────
def test_un_fichier_local_gitignore_ne_bloque_plus_le_push(tmp_path):
    """Le `configuration.py` qu'on copie depuis l'exemple, et que le
    `.gitignore` exclut : cité 23 fois par une doc, il bloquait le push à
    chaque fois. La doc avait raison."""
    verdict = _doc_vs_code(tmp_path, {
        "app/conf/configuration_example.py": "",
        "README.md": "Copie `configuration_example.py` vers `configuration.py`, "
                     "soit `app/conf/configuration.py`.",
    }, gitignore="/app/conf/configuration.py\n")

    assert verdict["statut"] == "OK", verdict
    assert "2 non verifie(s) : 2 gitignore(s)" in verdict["resume"], (
        "ce qu'on n'a pas verifie doit etre COMPTE, jamais tu")
    assert "gitignore : fichier local" in verdict["detail"], "et NOMME, meme au vert"


def test_un_dossier_entier_hors_du_depot_rend_ses_fichiers_locaux(tmp_path):
    """`var/log/provision.log` : tout `var/` est ignoré, rien n'y est suivi."""
    verdict = _doc_vs_code(tmp_path, {
        "README.md": "Le journal est dans `var/log/provision.log`.",
    }, gitignore="/var\n")

    assert verdict["statut"] == "OK", verdict
    assert "1 gitignore(s)" in verdict["resume"]


def test_une_regle_de_dossier_n_excuse_pas_un_fichier_disparu(tmp_path):
    """`/scripts/*` ignore tout NOM posé dans `scripts/`, qui est pourtant
    suivi (son `__init__.py` est ré-inclus). Accepter n'importe quelle règle
    aurait éteint la vraie trouvaille : un fichier renommé."""
    verdict = _doc_vs_code(tmp_path, {
        "scripts/__init__.py": "",
        "README.md": "Le paquet `scripts/__init__.py`, decrit dans `README.md`, "
                     "contient `scripts/renomme.py`, ou `renomme.py`.",
    }, gitignore="/scripts/*\n!/scripts/__init__.py\n")

    assert verdict["statut"] == "ALERTE", verdict
    assert verdict["bloquant"] is True
    assert "`scripts/renomme.py`" in verdict["detail"]
    assert "`renomme.py`" in verdict["detail"]
    assert "non verifie" not in verdict["resume"]
