"""Le poste de test accorde tout : les tests lancent de faux outils qu'ils ont écrits.

`tests/test_confiance.py` retire cet accord pour éprouver la question elle-même.
Le fichier d'accord est envoyé dans un dossier jetable : jamais celui de
l'utilisateur qui lance les tests.
"""

import pytest

from lintorn import confiance


@pytest.fixture(autouse=True)
def _poste_de_test(monkeypatch, tmp_path_factory):
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
