"""Les fonctions d'aide partagées par plusieurs fichiers de tests."""

import json
import os
import subprocess
import sys

import pytest

import lintorn.commandes
import lintorn.controles
import lintorn.outils
import lintorn.rapport
from lintorn import config
from lintorn.base import Resultat

# Un test qui retire des droits ne prouve rien la ou les droits ne comptent
# pas : sous Windows, et pour root — le cas de beaucoup de CI en conteneur.
_ILLISIBLE_POSSIBLE = pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="ni Windows ni root ne sont arretes par un chmod",
)
def _regle(tmp_path, monkeypatch, **champs):
    """Une règle maison pointée sur `tmp_path`, sans toucher au vrai dépôt.

    Construite par le VRAI chargeur : un test qui fabrique le dictionnaire à
    la main dérive du schéma dès qu'il bouge, et ne le dit jamais.
    """
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "hors_gitignore", lambda chemins: chemins)
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])

    defaut = {"nom": "interdit", "regle": "ne pas ecrire ceci", "racine": "",
              "suffixes": [".md"], "bloquant": False}
    if "motif_requis" not in champs:
        defaut["motif"] = "interdit"

    monkeypatch.setattr(config, "_regles_brutes", lambda: [{**defaut, **champs}])
    monkeypatch.setattr(config, "REGLES_MAISON", config._regles_du_projet()[0])
def _config_doc_ia(tmp_path, monkeypatch, texte, regles=()):
    """Un CLAUDE.md fabriqué pour l'occasion, et la config qui va avec."""
    doc = tmp_path / "CLAUDE.md"
    doc.write_text(texte, encoding="utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "DOCS_IA", [doc])
    monkeypatch.setattr(config, "REGLES_MAISON", list(regles))
    # Les `hors_portee` du VRAI regles.toml visent de vraies lignes de ce
    # dépôt : dans ce CLAUDE.md fabriqué, elles seraient « sans objet ».
    monkeypatch.setattr(config, "HORS_PORTEE", [])
    return doc
def _hors_cp1252(texte: str) -> list[str]:
    mauvais = []
    for caractere in texte:
        try:
            caractere.encode("cp1252")
        except UnicodeEncodeError:
            mauvais.append(caractere)
    return sorted(set(mauvais))
def _sortie_npm(sortie):
    """Ce que `lancer()` rend quand npm sort en 1 : une ALERTE, par défaut."""
    return Resultat("Failles connues JS (npm audit)", "ALERTE", "1 ligne(s) de sortie",
                    sortie, bloquant=False)
def _projet_detecte(monkeypatch, py=None, backend=None, front=None, controles=None):
    monkeypatch.setattr(config, "PY_RACINE", py)
    monkeypatch.setattr(config, "BACKEND", backend)
    monkeypatch.setattr(config, "FRONTEND", front)
    monkeypatch.setattr(config, "PROJET", {"controles": controles or {}})
    monkeypatch.setattr(lintorn.commandes.outils, "_importable", lambda module: True)
def _config_lue(tmp_path, monkeypatch, texte):
    dossier = tmp_path / ".lintorn"
    dossier.mkdir()
    fichier = dossier / "config.toml"
    fichier.write_text(texte, encoding="utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "DOSSIER_LINTORN", dossier)
    monkeypatch.setattr(config, "FICHIERS_CONFIG_LUS", ["config.toml"])
    return fichier
def _sortie_osv(sortie, code):
    return Resultat("Failles connues (OSV-Scanner)", "ALERTE", "x", sortie,
                    bloquant=False, code_sortie=code)
def _config_de(tmp_path, fichiers: dict) -> dict:
    """Charge la config d'un faux projet dans un VRAI processus neuf.

    `config.py` calcule tout à l'import : un défaut qui s'y joue — un
    traceback, un accord mal lu — ne se voit qu'en l'important pour de bon.
    """
    for chemin, contenu in fichiers.items():
        cible = tmp_path / chemin
        cible.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contenu, bytes):
            cible.write_bytes(contenu)
        else:
            cible.write_text(contenu, encoding="utf-8")
    code = ("import json; from lintorn import config; print(json.dumps({"
            "'cles': [c['cle'] for c in config.COMMANDES], "
            "'cmd': {c['cle']: [str(m) for m in c['cmd']] for c in config.COMMANDES}, "
            "'soucis': config.SOUCIS_CONFIG, "
            "'regles': [r['nom'] for r in config.REGLES_MAISON], "
            "'memoire': config.ENV.get('LINTORN_MEMOIRE', '')}))")
    environnement = {**os.environ, "LINTORN_RACINE": str(tmp_path)}
    environnement.pop("LINTORN_MEMOIRE", None)
    sortie = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True,
                            text=True, env=environnement, timeout=60, check=False)
    assert sortie.returncode == 0, f"la config a fait tomber Lintorn :\n{sortie.stderr}"
    return json.loads(sortie.stdout)
def _hook_pose(tmp_path, monkeypatch, contenu: bytes):
    hooks = tmp_path / ".lintorn" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "pre-push").write_bytes(contenu)
    (hooks / "pre-push").chmod(0o755)
    monkeypatch.setattr(config, "HOOKS", hooks)
    monkeypatch.setattr(lintorn.controles.outillage.hook_git, "_mode_git", lambda _chemin: None)
