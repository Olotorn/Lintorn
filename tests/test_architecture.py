"""Ce que le découpage en fichiers ne doit jamais casser."""

import ast
from pathlib import Path

from lintorn import config

DOSSIER_CONFIG = Path(config.__file__).parent


def _noms_de_config() -> set[str]:
    """Tout ce que `config/__init__.py` expose : calculé ici, ou réimporté d'un sous-module."""
    arbre = ast.parse((DOSSIER_CONFIG / "__init__.py").read_text(encoding="utf-8"))
    noms = set()
    for noeud in arbre.body:
        if isinstance(noeud, ast.ImportFrom) and noeud.level == 1:
            noms |= {alias.asname or alias.name for alias in noeud.names}
        elif isinstance(noeud, (ast.FunctionDef, ast.ClassDef)):
            noms.add(noeud.name)
        elif isinstance(noeud, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            cibles = getattr(noeud, "targets", None) or [noeud.target]
            noms |= {n.id for cible in cibles for n in ast.walk(cible) if isinstance(n, ast.Name)}
    return noms


def test_config_outils_et_controles_lisent_config_nom_jamais_leur_copie():
    """Les tests simulent un projet en remplaçant `config.RACINE`, `config.PROJET`…
    Une fonction de `config/projet.py` qui lirait `RACINE` tout court garderait
    SA valeur : le test resterait vert sans plus rien simuler."""
    noms = _noms_de_config()
    assert "RACINE" in noms and "git" in noms, "la lecture de __init__ ne trouve plus rien : test muet"
    fautes = []
    # config/ ET outils/ : les outils montent leur commande avec `config.PYTHON`…
    fichiers = [f for f in DOSSIER_CONFIG.glob("*.py") if f.name != "__init__.py"]
    fichiers += sorted((DOSSIER_CONFIG.parent / "outils").glob("*.py"))
    fichiers += sorted((DOSSIER_CONFIG.parent / "controles").rglob("*.py"))
    for dossier in ("outils", "projet", "outillage"):
        assert any(f.parent.name == dossier for f in fichiers), f"{dossier}/ introuvable : test muet"
    for fichier in sorted(fichiers):
        arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        for fonction in (n for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef)):
            lies = {a.arg for a in ast.walk(fonction) if isinstance(a, ast.arg)}
            lies |= {n.id for n in ast.walk(fonction)
                     if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
            fautes += [f"{fichier.name}:{n.lineno} {fonction.name}() lit `{n.id}`"
                       for n in ast.walk(fonction)
                       if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                       and n.id in noms and n.id not in lies]
    assert not fautes, "lire `config.NOM` à la place :\n" + "\n".join(fautes)
