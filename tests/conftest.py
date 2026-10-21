"""Le poste de test accorde tout : les tests lancent de faux outils qu'ils ont écrits.

`tests/test_confiance.py` retire cet accord pour éprouver la question elle-même.
Le fichier d'accord est envoyé dans un dossier jetable : jamais celui de
l'utilisateur qui lance les tests.
"""

import os

import pytest

from lintorn import confiance


@pytest.fixture(autouse=True)
def _poste_de_test(monkeypatch, tmp_path_factory):
    # Lancés par un hook pre-push (`tests = true`), les tests héritent de ce
    # qu'il exporte : un `LINTORN_LISTE` hérité fait passer la copie du hook
    # d'une version précédente, que simule un test, pour une copie à jour.
    for nom in list(os.environ):
        if nom.startswith(("LINTORN_", "PRE_COMMIT_")):
            monkeypatch.delenv(nom)
    # Et le dépôt du hook : poussés depuis un worktree, les `git init` et
    # `git commit` des tests visaient sinon le vrai dépôt, pas leur dossier jetable.
    from lintorn import base  # noqa: PLC0415 : en tête de fichier, avant confiance, il boucle sur config
    for nom in base.VARIABLES_DU_DEPOT:
        monkeypatch.delenv(nom, raising=False)
    monkeypatch.setenv(confiance.VARIABLE_CI, "oui")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config-utilisateur")))


@pytest.fixture
def illisible():
    """Rend un chemin illisible — et lisible à la fin, sans quoi pytest ne
    sait plus nettoyer son dossier temporaire."""
    fermes = []

    def fermer(chemin):
        chemin.chmod(0)
        fermes.append(chemin)
        return chemin

    yield fermer
    for chemin in fermes:
        chemin.chmod(0o755 if chemin.is_dir() else 0o644)
