"""Le hook pre-push : branché, à jour, et ce qu'il dit à git."""

import ast
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from aides import _ILLISIBLE_POSSIBLE, _config_de, _hook_pose, _regle

import lintorn.commandes
import lintorn.controles
import lintorn.outils
import lintorn.rapport
from lintorn import base, cli as Lintorn, config
from lintorn.base import Resultat


# ─────────────────────────────────────────────────────────────────────────────
# Le hook pre-push et les réglages de machine
# ─────────────────────────────────────────────────────────────────────────────
def test_le_chemin_attendu_des_hooks_est_le_bon():
    """Si `tools/hooks/` est déplacé sans mettre à jour `HOOKS_ATTENDU`, Lintorn
    réclamerait un `git config` pointant vers un dossier vide — et le push
    repartirait sans contrôle en croyant être protégé."""
    assert config.HOOKS == config.RACINE / config.HOOKS_ATTENDU
    # Le hook livré DANS le paquet : c'est lui la source de toute installation.
    assert (config.HOOKS_SOURCE / "pre-push").is_file()


def test_le_hook_pre_push_est_executable_dans_git():
    """Git refuse en SILENCE de lancer un hook sans le bit exécutable.

    Panne réelle du 16/08/2026 : le hook, créé sous Windows (où ce bit n'existe
    pas), était parti dans le dépôt en `100644`. Sous Windows Git Bash le
    lançait quand même — au passage sous Linux, `git push` a cessé de contrôler
    quoi que ce soit, sans un message, pendant que Lintorn affichait « branche ».

    ⚠️ On surveille le hook SOURCE — celui livré dans le paquet — et non la
    copie posée dans le projet audité. Depuis le packaging il y a deux objets
    distincts : `installer_hook()` copie le premier vers le second en reposant
    le bit lui-même. Si la SOURCE le perd, toutes les copies naissent
    infirmes : c'est donc là qu'il faut monter la garde, et la copie générée
    n'a elle aucune raison d'être versionnée.

    On lit le mode dans l'INDEX GIT : c'est lui qui voyage avec le dépôt, donc
    lui qui protège les autres machines, et c'est le seul des deux (index ou
    disque) à donner la même réponse sur tous les OS.
    """
    source = config.HOOKS_SOURCE / "pre-push"

    sortie = subprocess.run(
        ["git", "ls-files", "-s", "--", str(source)],
        cwd=source.parent, capture_output=True, text=True, timeout=10, check=False,
    )

    if not sortie.stdout.strip():
        # Paquet installé depuis un wheel : aucun dépôt git autour, l'index
        # n'existe pas. Le bit du disque est alors la seule vérité disponible.
        assert os.access(source, os.X_OK), (
            f"{source} n'est pas executable : git ignorerait ce hook en silence."
        )
        return

    mode = sortie.stdout.split()[0]
    assert mode == "100755", (
        f"{source} est enregistre en {mode} : git ne l'executera JAMAIS, "
        "ni ici ni sur un clone, et sans le moindre message. Reparer avec :\n"
        f"    chmod +x {source} && git add {source}"
    )


def test_le_controle_du_hook_ne_conclut_rien_sans_donnee(tmp_path):
    """`_mode_git` doit rendre None hors dépôt, jamais un mode inventé.

    Un contrôle qui devine un verdict quand il n'a pas la donnée est
    précisément le défaut qu'on vient de corriger : il repasse au vert sur du
    vide. Ici, hors dépôt git, la seule réponse honnête est « je ne sais pas ».
    """
    assert lintorn.controles.outillage.hook_git._mode_git(tmp_path / "inexistant") is None


# ─────────────────────────────────────────────────────────────────────────────
# N3 — un hook installé par une version PRÉCÉDENTE de Lintorn
# ─────────────────────────────────────────────────────────────────────────────


def test_n3_le_hook_de_cette_version_est_vert(tmp_path, monkeypatch):
    _hook_pose(tmp_path, monkeypatch, (config.HOOKS_SOURCE / "pre-push").read_bytes())

    assert lintorn.controles.outillage.hook_git._controle_hook_executable("t").statut == "OK"


def test_b1_un_hook_en_fins_de_ligne_windows_n_est_pas_un_vert(tmp_path, monkeypatch):
    """`#!/bin/sh\r` n'est pas un interpréteur : git répond `cannot exec`, et
    le contrôle annonçait « branche et executable ». Le push échoue alors sur
    un message que rien ne relie au hook."""
    livre = (config.HOOKS_SOURCE / "pre-push").read_bytes()
    _hook_pose(tmp_path, monkeypatch, livre.replace(b"\n", b"\r\n"))

    resultat = lintorn.controles.outillage.hook_git._controle_hook_executable("t")

    assert resultat.statut == "ALERTE"
    assert "retour chariot" in resultat.resume


@_ILLISIBLE_POSSIBLE
def test_b3_un_hook_illisible_est_un_hook_muet(tmp_path, monkeypatch, illisible):
    """git doit LIRE le script pour l'exécuter. « fraicheur inconnue »
    sous-estimait un hook mort."""
    _hook_pose(tmp_path, monkeypatch, (config.HOOKS_SOURCE / "pre-push").read_bytes())
    illisible(tmp_path / ".lintorn" / "hooks" / "pre-push").chmod(0o111)

    resultat = lintorn.controles.outillage.hook_git._controle_hook_executable("t")

    assert resultat.statut == "ALERTE"
    assert "illisible" in resultat.resume


def _git_repond(monkeypatch, hooks_path: str):
    monkeypatch.setattr(config, "SOUS_GIT", True)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *_, **__: subprocess.CompletedProcess([], 0, hooks_path + "\n", ""))


def test_b2_un_hook_efface_apres_installation_n_est_pas_un_gris(tmp_path, monkeypatch):
    """`core.hooksPath` pose, fichier disparu : git ne lance plus rien et ne
    le dit pas. Le controle repondait « pas encore installe » — le message du
    PREMIER lancement — pour un garde-fou mort. Le hook etant ignore par git,
    un `git clean -fdX` suffit a le supprimer."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "HOOKS", tmp_path / ".lintorn" / "hooks")
    _git_repond(monkeypatch, config.HOOKS_ATTENDU)

    resultat = lintorn.controles.outillage.hook_git.controle_hook_git()

    assert resultat.statut == "ALERTE"
    assert "BRANCHE MAIS ABSENT" in resultat.resume
    assert "lintorn hook" in resultat.detail


@_ILLISIBLE_POSSIBLE
def test_b4_un_dossier_memoire_illisible_n_est_pas_un_dossier_vide(tmp_path, monkeypatch, illisible):
    """`glob` rend une liste vide sur un dossier interdit : le controle
    annoncait « aucun fichier memoire » alors qu'il y en avait."""
    (tmp_path / "fiche.md").write_text("cite `README.md`", encoding="utf-8")
    illisible(tmp_path)
    monkeypatch.setattr(config, "MEMOIRE_IA", tmp_path)

    resultat = lintorn.controles.projet.memoire_ia.controle_memoire_ia()

    assert resultat.statut == "INDISPONIBLE"
    assert "ILLISIBLE" in resultat.resume


@pytest.mark.parametrize("temoin", ["Pipfile", "environment.yml"])
def test_un_projet_pipenv_ou_conda_est_un_projet_python(tmp_path, temoin):
    """Ni pyproject.toml ni requirements.txt chez Pipenv et conda : le projet
    etait « rien de connu », ruff ne tournait meme pas."""
    lu = _config_de(tmp_path, {temoin: "", "app.py": "import os\n"})

    assert "ruff" in lu["cles"]


def _sans_temoin(tmp_path, fichiers: dict) -> bool:
    for nom, contenu in fichiers.items():
        (tmp_path / nom).write_text(contenu, encoding="utf-8")
    sortie = subprocess.run(
        [sys.executable, "-c", "from lintorn import config; print(config.PY_SANS_TEMOIN)"],
        cwd=tmp_path, env={**os.environ, "LINTORN_RACINE": str(tmp_path)},
        capture_output=True, text=True, timeout=60, check=True)
    return sortie.stdout.strip() == "True"


def test_des_py_sans_temoin_sont_reperes(tmp_path):
    scripts, projet = tmp_path / "scripts", tmp_path / "projet"
    scripts.mkdir()
    projet.mkdir()

    assert _sans_temoin(scripts, {"outil.py": ""})
    assert not _sans_temoin(projet, {"pyproject.toml": '[project]\nname = "x"\n', "app.py": ""})


def test_des_py_sans_temoin_ne_font_plus_dire_aucun_code_python(monkeypatch):
    """« aucun code Python dans ce projet » etait faux. Et GRIS, pas rouge : un
    projet JS avec un script d'appoint ne doit pas recevoir l'alerte « aucun
    venv », un faux positif deja paye une fois."""
    monkeypatch.setattr(config, "PY_RACINE", None)
    monkeypatch.setattr(config, "PY_SANS_TEMOIN", True)
    monkeypatch.setattr(config, "VENV_SOUCI", None)

    resultat = lintorn.controles.outillage.python_projet.controle_python_projet()

    assert resultat.statut == "INDISPONIBLE"
    assert "aucun code Python" not in resultat.resume
    assert "pyproject.toml" in resultat.detail


def test_tout_controle_opt_in_figure_dans_le_modele_de_init():
    """Deux listes des memes controles : celle de `config.py`, et celle que
    `--init` ecrit. `django_check` et `migrations` sont devenus opt-in sans
    rejoindre la seconde — un projet Django recevait une config qui ne les
    nommait jamais."""
    # Tout le paquet : les commandes vivent dans plusieurs fichiers.
    arbres = [ast.parse(source.read_text(encoding="utf-8"))
              for source in Path(config.PAQUET).rglob("*.py")]
    opt_in = set()
    for noeud in (noeud for arbre in arbres for noeud in ast.walk(arbre)):
        if not isinstance(noeud, ast.Dict):
            continue
        champs = {cle.value: valeur for cle, valeur in zip(noeud.keys, noeud.values, strict=True)
                  if isinstance(cle, ast.Constant)}
        if (isinstance(champs.get("opt_in"), ast.Constant) and champs["opt_in"].value is True
                and isinstance(champs.get("cle"), ast.Constant)):
            opt_in.add(champs["cle"].value)

    assert "django_check" in opt_in, "la lecture du paquet ne trouve plus rien : test muet"
    assert opt_in <= {cle for cle, _, _ in lintorn.commandes.init._controles_du_modele()}, (
        opt_in - {cle for cle, _, _ in lintorn.commandes.init._controles_du_modele()})


def test_init_propose_les_controles_django_sur_un_projet_django(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "lintorn", "--init"], cwd=tmp_path, timeout=60,
                   env={**os.environ, "LINTORN_RACINE": str(tmp_path)},
                   capture_output=True, check=True)

    controles = tomllib.loads(
        (tmp_path / ".lintorn" / "config.toml").read_text(encoding="utf-8"))["controles"]

    assert controles["django_check"] is False and controles["migrations"] is False, (
        "presents et DECOMMENTES : il ne reste qu'a passer a true")


def test_l_exemple_de_commande_du_modele_marche_une_fois_decommente(tmp_path):
    """Le modele disait quoi ecrire, jamais COMMENT l'activer : le dev lui-meme
    n'a pas trouve. Il le dit maintenant — enlever les #. Et un exemple qui,
    decommente comme demande, ne marcherait pas serait une doc qui ment."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    environnement = {**os.environ, "LINTORN_RACINE": str(tmp_path)}
    subprocess.run([sys.executable, "-m", "lintorn", "--init"], cwd=tmp_path, env=environnement,
                   capture_output=True, timeout=60, check=True)
    modele = (tmp_path / ".lintorn" / "config.toml").read_text(encoding="utf-8")
    assert "ENLEVE LES #" in modele

    lignes, dans_le_bloc = [], False
    for ligne in modele.splitlines():
        dans_le_bloc = dans_le_bloc or ligne == "# [[commandes]]"
        if dans_le_bloc and not ligne.strip():
            dans_le_bloc = False
        lignes.append(ligne[2:] if dans_le_bloc and ligne.startswith("# ") else ligne)
    (tmp_path / ".lintorn" / "config.toml").write_text("\n".join(lignes), encoding="utf-8")

    lu = _config_de(tmp_path, {})

    assert "mypy" in lu["cles"], f"l'exemple decommente est refuse : {lu['soucis']}"
    assert not lu["soucis"]
    assert "{python}" not in lu["cmd"]["mypy"][0], "{python} doit devenir le Python du projet"
    assert Path(lu["cmd"]["mypy"][0]).is_file()


def test_un_outil_manquant_recoit_le_conseil_qui_le_concerne(monkeypatch):
    """`--installer-outils` ne connait ni mypy ni eslint : y renvoyer pour un
    outil de l'utilisateur, c'etait un conseil qui ne marche pas."""
    inconnu = ["-m", "module_que_personne_n_a_installe"]

    du_terminal = base.lancer("t", ["python3", *inconnu], config.RACINE, bloquant=False)
    du_projet = base.lancer("t", [str(config.PYTHON), *inconnu], config.RACINE, bloquant=False)
    monkeypatch.setattr(config, "OUTILS_INSTALLABLES", ("module_que_personne_n_a_installe",))
    connu = base.lancer("t", [str(config.PYTHON), *inconnu], config.RACINE, bloquant=False)

    assert "{python}" in du_terminal.resume
    assert "venv du projet" in du_projet.resume
    assert "lintorn outils" in connu.resume


def test_les_outils_installables_sont_ceux_que_l_installeur_connait():
    """Deux listes, un seul sens : les garder d'accord."""
    assert {module for module, *_ in lintorn.commandes.outils.OUTILS_PYTHON} == set(config.OUTILS_INSTALLABLES)


def test_b5_un_codes_alerte_a_zero_sans_traducteur_est_refuse(tmp_path):
    """Depuis que 0 part au traducteur, un 0 declare sans traducteur ferait
    d'une commande REUSSIE une alerte — bloquante, le cas echeant."""
    lu = _config_de(tmp_path, {
        "pyproject.toml": '[project]\nname = "x"\n',
        ".lintorn/config.toml": ('[[commandes]]\ncle = "verif"\n'
                                 'cmd = ["sh", "-c", "exit 0"]\n'
                                 'codes_alerte = [0]\nbloquant = true\n'),
    })

    assert "verif" not in lu["cles"]
    assert any("codes_alerte contient 0" in souci for souci in lu["soucis"])


def test_b5_un_codes_alerte_a_zero_reste_possible_avec_un_traducteur(tmp_path):
    """C'est ainsi que npm audit est branche : il sort en 0 avec une erreur."""
    lu = _config_de(tmp_path, {
        "pyproject.toml": '[project]\nname = "x"\n',
        ".lintorn/config.toml": ('[[commandes]]\ncle = "verif"\n'
                                 'cmd = ["sh", "-c", "exit 0"]\n'
                                 'codes_alerte = [0, 1]\ntraduction = "npm_audit"\n'),
    })

    assert "verif" in lu["cles"]


def test_b2_un_premier_lancement_n_accuse_toujours_personne(tmp_path, monkeypatch):
    """Rien de posé, rien d'installé : c'est un projet neuf, pas une panne."""
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "HOOKS", tmp_path / ".lintorn" / "hooks")
    _git_repond(monkeypatch, "")

    resultat = lintorn.controles.outillage.hook_git.controle_hook_git()

    assert resultat.statut == "INDISPONIBLE"
    assert "pas encore installe" in resultat.resume


def test_n3_un_hook_perime_le_dit_et_donne_la_commande(tmp_path, monkeypatch):
    """`pip install -U lintorn` ne touche jamais à la copie posée dans le
    projet : sans ce contrôle, un correctif du hook n'arrivait nulle part."""
    # Ce qui manquait vraiment a la version precedente : elle n'exportait pas
    # la racine a auditer, et auditait donc le sommet du depot.
    ancien = (config.HOOKS_SOURCE / "pre-push").read_bytes().replace(
        b'LINTORN_RACINE="$(pwd)"\nexport LINTORN_RACINE\n', b"")
    assert ancien != (config.HOOKS_SOURCE / "pre-push").read_bytes()
    _hook_pose(tmp_path, monkeypatch, ancien)

    resultat = lintorn.controles.outillage.hook_git._controle_hook_executable("t")

    assert resultat.statut == "VERIF"
    assert resultat.bloquant is False
    assert "lintorn hook" in resultat.resume


def test_b2_un_motif_qui_accepte_le_vide_est_refuse(tmp_path, monkeypatch):
    """`motif_requis = 'SPDX|'` était satisfait par n'importe quel fichier."""
    _regle(tmp_path, monkeypatch, motif_requis="SPDX|")

    assert config.REGLES_MAISON == []
    assert any("accepte le texte vide" in souci for souci in config.SOUCIS_CONFIG)


@pytest.mark.parametrize("arguments", [
    ["--doc", "--fichiers", "--", "--help"],   # le hook d'aujourd'hui
    ["--doc", "--fichiers", "--help"],         # un hook installé AVANT le séparateur
])
def test_un_fichier_pousse_nomme_comme_une_option_reste_un_fichier(
        tmp_path, monkeypatch, capsys, arguments):
    """Un fichier poussé nommé `--help` affichait l'aide, sortait en 0 — et le
    push passait sans audit."""
    (tmp_path / "--help").write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "RAPPORT", tmp_path / ".lintorn" / "rapport.md")
    monkeypatch.setattr("sys.argv", ["lintorn", *arguments])
    monkeypatch.setattr(lintorn.controles.projet.doc_vs_code, "controle_doc",
                        lambda: Resultat("Doc vs code", "OK", "rien"))
    monkeypatch.setattr(lintorn.rapport.markdown, "ecrire_rapport", lambda resultats: True)

    Lintorn.main()

    assert "USAGE" not in capsys.readouterr().out, "le nom de fichier a ete lu comme --help"
