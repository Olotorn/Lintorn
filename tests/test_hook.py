"""Le hook pre-push : branché, à jour, et ce qu'il dit à git."""

import ast
import json
import os
import select
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aides import _ILLISIBLE_POSSIBLE, _config_de, _hook_pose, _regle

import lintorn.commandes
import lintorn.controles
import lintorn.outils
import lintorn.rapport
from lintorn import base, cli as Lintorn, config, noyau
from lintorn.base import Resultat

try:
    import pty
except ImportError:          # Windows : pas de terminal à simuler
    pty = None


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
    monkeypatch.setattr(lintorn.rapport.markdown, "ecrire_rapport", lambda resultats, hook=False: True)

    Lintorn.main()

    assert "USAGE" not in capsys.readouterr().out, "le nom de fichier a ete lu comme --help"


# ─────────────────────────────────────────────────────────────────────────────
# Les hooks des autres outils : Lintorn ne les fait jamais taire
# ─────────────────────────────────────────────────────────────────────────────
POSIX = pytest.mark.skipif(os.name == "nt", reason="hooks en script shell")


def _depot(tmp_path, monkeypatch):
    # Ni la config git de la machine (un `core.hooksPath` global changerait tout),
    # ni son identité : chaque test pose la sienne.
    vide = tmp_path.parent / f"{tmp_path.name}-gitconfig"
    vide.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(vide))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for qui in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{qui}_NAME", "essai")
        monkeypatch.setenv(f"GIT_{qui}_EMAIL", "essai@exemple.invalid")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "SOUS_GIT", True)
    monkeypatch.setattr(config, "SOMMET_GIT", tmp_path)
    monkeypatch.setattr(config, "HOOKS", tmp_path / ".lintorn" / "hooks")
    monkeypatch.setattr(config, "HOOKS_POUR_GIT", config.HOOKS_ATTENDU)
    monkeypatch.setattr(config, "ETAT", tmp_path / ".lintorn" / "etat.json")
    return tmp_path


def _un_hook(dossier, nom, contenu="#!/bin/sh\nexit 0\n"):
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / nom).write_text(contenu, encoding="utf-8")
    (dossier / nom).chmod(0o755)


def _hooks_path(depot):
    return subprocess.run(["git", "config", "--get", "core.hooksPath"], cwd=depot,
                          capture_output=True, text=True, check=False).stdout.strip()


def _commiter(depot) -> str:
    """Un commit de plus ; rend son identifiant."""
    # Un contenu jamais vu : deux commits pareils, dans la même seconde, auraient
    # le même identifiant — et le test comparerait un commit à lui-même.
    (depot / "fichier.txt").write_text(os.urandom(8).hex(), encoding="utf-8")
    subprocess.run(["git", "add", "fichier.txt"], cwd=depot, check=True)
    subprocess.run(["git", "commit", "-qm", "essai"], cwd=depot, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=depot, capture_output=True, text=True,
                          check=True).stdout.strip()


def _passage(quand: str, *commits: str):
    """Ce que Lintorn noterait en tournant dans un hook, à `quand`, pour `commits`."""
    base.ecrire_etat(lintorn.controles.outillage.hook_git.CLE_PASSAGE,
                     {"quand": quand, "commits": list(commits)})


def _pousser(depot, *options, heure=None):
    """Un commit, puis un vrai `git push` vers un dépôt nu voisin."""
    _commiter(depot)
    return _envoyer(depot, *options, heure=heure)


def _envoyer(depot, *options, heure=None):
    """Un vrai `git push` vers un dépôt nu voisin.

    `heure` (secondes epoch) date l'entrée que git note pour ce push.
    """
    distant = depot.parent / f"{depot.name}-distant.git"
    if not distant.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(distant)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(distant)], cwd=depot, check=True)
    env = {**os.environ, **({"GIT_COMMITTER_DATE": f"@{heure} +0000"} if heure else {})}
    # Sans terminal : si le hook posait sa question, elle échouerait au lieu d'attendre.
    return subprocess.run(["git", "push", "-q", *options, "origin", "HEAD:refs/heads/main"],
                          cwd=depot, env=env, capture_output=True, text=True, timeout=120,
                          start_new_session=True, check=False)


def _lintorn_dans_le_path(tmp_path, monkeypatch):
    """Le VRAI Lintorn, celui de ces tests, trouvé par le hook comme `lintorn`."""
    binaire = tmp_path.parent / f"{tmp_path.name}-bin"
    binaire.mkdir()
    (binaire / "lintorn").write_text(f'#!/bin/sh\nexec "{sys.executable}" -m lintorn "$@"\n',
                                     encoding="utf-8")
    (binaire / "lintorn").chmod(0o755)
    monkeypatch.setenv("PATH", f"{binaire}{os.pathsep}{os.environ['PATH']}")


@POSIX
def test_lintorn_hook_dit_ce_qu_il_a_trouve_et_ce_qu_il_a_change(tmp_path, monkeypatch, capsys):
    """« Hook installe » s'affichait aussi sur un hook déjà en place et à jour : on ne
    savait pas s'il l'était avant."""
    _depot(tmp_path, monkeypatch)
    installer = lintorn.commandes.hook.installer_hook

    assert installer() == 0
    premiere = capsys.readouterr().out
    assert installer() == 0
    seconde = capsys.readouterr().out
    (config.HOOKS / "version").write_text("lintorn 0.6.0\n", encoding="utf-8")
    assert installer() == 0
    troisieme = capsys.readouterr().out

    assert "Hook installe" in premiere and "Hook branche" in premiere
    assert "Hook deja a jour" in seconde and "Deja branche" in seconde
    assert "Rien a changer." in seconde and "Hook installe" not in seconde
    assert "Hook mis a jour" in troisieme and "a la place de lintorn 0.6.0" in troisieme
    assert "[ OK ] Hook pre-push (Lintorn)" in seconde, "et ce qu'en dit le controle"


@POSIX
def test_juste_apres_la_pose_le_push_d_avant_n_est_pas_accuse(tmp_path, monkeypatch, capsys):
    """Un script pousse, pose le hook dans la même seconde : « parti SANS Lintorn »
    s'affichait sous « Hook installe », pour un push fait avant que le hook existe."""
    depot = _depot(tmp_path, monkeypatch)
    _pousser(depot, heure=int(time.time()))

    assert lintorn.commandes.hook.installer_hook() == 0

    sortie = capsys.readouterr().out
    assert "Hook installe" in sortie and "parti SANS" not in sortie, sortie


@POSIX
def test_lintorn_hook_etat_dit_l_etat_sans_rien_toucher(tmp_path, monkeypatch, capsys):
    """Savoir si le hook tourne sans le reposer : le code de sortie le dit à un script."""
    _depot(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.argv", ["lintorn", "hook", "--status"])

    absent = Lintorn.main()
    sortie = capsys.readouterr().out
    rien_pose = not (config.HOOKS / "pre-push").exists()
    assert lintorn.commandes.hook.installer_hook() == 0
    capsys.readouterr()
    branche = Lintorn.main()

    assert absent == 1 and "pas encore installe" in sortie
    assert "    lintorn hook" in sortie, "le detail dit quoi faire"
    assert rien_pose, "--status ne pose rien"
    assert branche == 0 and "[ OK ] Hook pre-push" in capsys.readouterr().out


@POSIX
def test_lintorn_hook_rm_debranche_et_retire_la_copie(tmp_path, monkeypatch, capsys):
    """Défaire `lintorn hook` demandait de connaître la commande git."""
    depot = _depot(tmp_path, monkeypatch)
    assert lintorn.commandes.hook.installer_hook() == 0
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["lintorn", "hook", "--rm"])

    retire = Lintorn.main()
    sortie = capsys.readouterr().out
    encore = Lintorn.main()

    assert retire == 0 and "Hook debranche" in sortie and "Copie retiree" in sortie
    assert _hooks_path(depot) == ""
    assert not (config.HOOKS / "pre-push").exists() and not (config.HOOKS / "version").exists()
    assert encore == 0 and "Rien a retirer" in capsys.readouterr().out


@POSIX
def test_lintorn_hook_rm_rend_leur_place_aux_hooks_que_force_avait_remplaces(tmp_path, monkeypatch):
    """Après `lintorn hook --force`, les hooks d'avant se taisaient : les retirer de
    Lintorn les rend à git."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / "mes-hooks", "pre-push")
    _git(depot, "config", "core.hooksPath", "mes-hooks")
    assert lintorn.commandes.hook.installer_hook(forcer=True) == 0

    assert lintorn.commandes.hook.retirer_hook() == 0

    assert _hooks_path(depot) == "mes-hooks"


@POSIX
def test_lintorn_hook_rm_previent_quand_un_autre_hook_appelle_encore_lintorn(
        tmp_path, monkeypatch, capsys):
    """Sans la copie, ce hook s'arrêterait sur « not found » au prochain push."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    assert lintorn.commandes.hook.installer_hook() == 1           # pose le script, sans brancher
    _un_hook(depot / ".git" / "hooks", "pre-push",
             f'#!/bin/sh\n{lintorn.controles.outillage.hook_git.ligne_a_ajouter()}\n')
    capsys.readouterr()

    assert lintorn.commandes.hook.retirer_hook() == 0

    sortie = capsys.readouterr().out
    assert "Copie retiree" in sortie
    assert ".git/hooks/pre-push appelle encore le hook de Lintorn" in sortie


@POSIX
def test_lintorn_hook_ne_fait_pas_taire_les_hooks_existants(tmp_path, monkeypatch, capsys):
    """`core.hooksPath` REMPLACE le dossier de hooks : un pre-commit écrit à la
    main (ou posé par l'outil pre-commit) cessait de tourner, sans un mot."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")

    assert lintorn.commandes.hook.installer_hook() == 1

    assert _hooks_path(depot) == "", "core.hooksPath pose : le pre-commit est devenu muet"
    # Le script est posé SANS être branché : c'est lui que la ligne conseillée appelle.
    assert os.access(depot / ".lintorn" / "hooks" / "pre-push", os.X_OK)
    sortie = capsys.readouterr().out
    assert "pre-commit" in sortie
    assert lintorn.controles.outillage.hook_git.ligne_a_ajouter() in sortie


@POSIX
def test_lintorn_hook_respecte_le_dossier_d_un_autre_outil(tmp_path, monkeypatch):
    """husky pose son propre `core.hooksPath` : on ne le remplace pas."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".husky", "pre-push")
    subprocess.run(["git", "config", "core.hooksPath", ".husky"], cwd=depot, check=True)

    assert lintorn.commandes.hook.installer_hook() == 1

    assert _hooks_path(depot) == ".husky"


@POSIX
def test_avec_husky_la_ligne_va_dans_son_script_pas_dans_le_relais(tmp_path, monkeypatch, capsys):
    """husky 9 fait lire `.husky/_/` à git : des relais qui rendent la main avant
    une ligne ajoutée, et que `npm install` régénère. Le conseil visait le relais :
    suivi à la lettre, Lintorn ne tournait jamais."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".husky" / "_", "pre-push")
    subprocess.run(["git", "config", "core.hooksPath", ".husky/_"], cwd=depot, check=True)

    lintorn.commandes.hook.installer_hook()

    sortie = capsys.readouterr().out
    assert "ajoute cette ligne a .husky/pre-push" in sortie
    assert ".husky/_/pre-push" not in sortie
    assert "TOUS tes projets" not in sortie, "le dossier de CE projet annonce comme partage"


@POSIX
def test_un_dossier_de_hooks_global_est_annonce_comme_partage(tmp_path, monkeypatch, capsys):
    """Un `core.hooksPath` global sert à tous les projets : la ligne conseillée y
    tournerait partout, et ceux sans Lintorn refuseraient leurs push sur « not found »."""
    depot = _depot(tmp_path, monkeypatch)
    commun = tmp_path.parent / f"{tmp_path.name}-hooks-communs"
    _un_hook(commun, "pre-commit")
    subprocess.run(["git", "config", "--global", "core.hooksPath", str(commun)], cwd=depot,
                   check=True)

    assert lintorn.commandes.hook.installer_hook() == 1

    assert "TOUS tes projets" in capsys.readouterr().out
    assert "TOUS tes projets" in _verdict_du_hook(monkeypatch).detail


def test_en_monorepo_la_ligne_lance_le_hook_du_sous_projet(monkeypatch):
    """git lance les hooks depuis le SOMMET : `lintorn rapide` y auditait la racine
    du dépôt, sans config, et laissait partir ce que les règles de `api/` interdisaient."""
    monkeypatch.setattr(config, "HOOKS_POUR_GIT", "api/.lintorn/hooks")

    assert lintorn.controles.outillage.hook_git.ligne_a_ajouter() == (
        'api/.lintorn/hooks/pre-push "$@" || exit 1')


@POSIX
def test_lintorn_hook_force_branche_quand_meme(tmp_path, monkeypatch):
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")

    assert lintorn.commandes.hook.installer_hook(forcer=True) == 0

    assert _hooks_path(depot) == config.HOOKS_ATTENDU


def test_les_exemples_de_git_ne_sont_pas_des_hooks_actifs(tmp_path, monkeypatch):
    """`git init` pose des `*.sample` : ce ne sont pas des hooks, rien a proteger."""
    depot = _depot(tmp_path, monkeypatch)

    assert lintorn.commandes.hook.installer_hook() == 0

    assert _hooks_path(depot) == config.HOOKS_ATTENDU


@POSIX
def test_un_executable_qui_n_est_pas_un_nom_de_hook_n_est_pas_un_hook(tmp_path, monkeypatch):
    """git ne lance que les noms qu'il connaît : un README exécutable faisait refuser
    l'installation pour un hook qui n'existe pas."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "README")

    assert lintorn.commandes.hook.installer_hook() == 0


@_ILLISIBLE_POSSIBLE
def test_un_dossier_de_hooks_illisible_n_est_pas_un_dossier_vide(tmp_path, monkeypatch,
                                                                  illisible, capsys):
    """Compté comme vide, il laissait brancher Lintorn par-dessus des hooks jamais vus."""
    depot = _depot(tmp_path, monkeypatch)
    illisible(depot / ".git" / "hooks")

    assert lintorn.commandes.hook.installer_hook() == 1

    assert _hooks_path(depot) == ""
    assert "illisible" in capsys.readouterr().out


def _verdict_du_hook(monkeypatch):
    monkeypatch.setattr(config, "COMMANDES", [])
    monkeypatch.setattr(config, "CONTROLES_INTERNES", {"hook_git": True})
    return next(r for r in noyau.executer() if r.titre.startswith("Hook pre-push"))


@POSIX
@pytest.mark.parametrize("contenu", [
    "#!/bin/sh\n# TODO : brancher lintorn un jour\n",
    "#!/bin/sh\n# lintorn rapide || exit 1\n",
    '#!/bin/sh\necho "pense a installer lintorn"\n',
    "#!/bin/sh\nexit 0\nlintorn rapide || exit 1\n",
], ids=["commentaire", "ligne-commentee", "echo", "apres-exit"])
def test_le_mot_lintorn_dans_un_hook_n_est_pas_un_appel(tmp_path, monkeypatch, contenu):
    """Le contrôle cherchait le mot « lintorn » dans le pre-push : un commentaire
    suffisait à dire « appele depuis ton hook », et le push fautif partait."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".husky", "pre-push", contenu)
    subprocess.run(["git", "config", "core.hooksPath", ".husky"], cwd=depot, check=True)
    assert _pousser(depot).returncode == 0

    resultat = _verdict_du_hook(monkeypatch)

    assert resultat.statut == "ALERTE"
    assert "pas branche" in resultat.resume


@POSIX
def test_un_pre_push_qui_lance_vraiment_lintorn_est_vert(tmp_path, monkeypatch):
    """De bout en bout : le pre-push d'un autre outil, la ligne conseillée, un vrai
    `git push`. Le vert vient de ce que Lintorn a noté en tournant, pas du texte."""
    depot = _depot(tmp_path, monkeypatch)
    _lintorn_dans_le_path(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    assert lintorn.commandes.hook.installer_hook() == 1      # refuse, pose le script
    ligne = lintorn.controles.outillage.hook_git.ligne_a_ajouter()
    _un_hook(depot / ".git" / "hooks", "pre-push", f"#!/bin/sh\n{ligne}\n")

    pousse = _pousser(depot)

    assert pousse.returncode == 0, pousse.stdout + pousse.stderr
    assert "Lintorn controle avant push" in pousse.stdout + pousse.stderr
    resultat = _verdict_du_hook(monkeypatch)
    assert resultat.statut == "OK", resultat.resume
    assert "vu tourner" in resultat.resume
    # Le hook a transmis ce qu'il poussait : c'est ce commit-là qui est prouvé.
    pousse = subprocess.run(["git", "rev-parse", "HEAD"], cwd=depot, capture_output=True,
                            text=True, check=True).stdout.strip()
    trace = base.lire_etat()[lintorn.controles.outillage.hook_git.CLE_PASSAGE]
    assert pousse in trace["commits"]


@POSIX
def test_un_push_parti_sans_lintorn_apres_un_push_vu_est_rouge(tmp_path, monkeypatch):
    """La ligne a marché, puis a été retirée (ou `--no-verify`) : le dernier push
    est parti sans contrôle, et le passage d'avant ne doit pas le couvrir."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    _passage("2026-01-01T10:00:00+00:00", _commiter(depot))
    _envoyer(depot, heure=1767261660)     # 10:01 : le push que Lintorn a vu
    _pousser(depot, heure=1767265200)     # 11:00 : un autre commit, plus rien n'a tourné

    resultat = _verdict_du_hook(monkeypatch)

    assert resultat.statut == "ALERTE"
    assert "est parti SANS Lintorn" in resultat.resume


@POSIX
def test_le_commit_verifie_par_lintorn_couvre_son_push(tmp_path, monkeypatch):
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    _pousser(depot, heure=1767261600)     # 10:00
    _passage("2026-01-01T10:59:00+00:00", _commiter(depot))
    _envoyer(depot, heure=1767265200)     # 11:00

    assert _verdict_du_hook(monkeypatch).statut == "OK"


@POSIX
def test_une_tentative_refusee_ne_couvre_pas_le_push_d_un_autre_commit(tmp_path, monkeypatch):
    """Lintorn refuse un push ; puis `lefthook install` réécrit le script et l'appel
    disparaît ; un autre commit part. Comparer les heures disait « vu tourner »
    sur ce push que personne n'avait vérifié."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    _pousser(depot, heure=1767261600)                       # 10:00
    _passage("2026-01-01T10:30:00+00:00", _commiter(depot))   # refusé par Lintorn
    subprocess.run(["git", "reset", "-q", "--hard", "HEAD~1"], cwd=depot, check=True)
    _pousser(depot, heure=1767265200)                       # 11:00, sans Lintorn

    assert _verdict_du_hook(monkeypatch).statut == "ALERTE"


def _deux_branches(tmp_path, monkeypatch, *, sous_pre_commit: bool, heure_du_push: int):
    """`premiere` vérifiée par Lintorn à 10:00, puis `premiere` et `seconde` poussées d'un coup."""
    hook_git = lintorn.controles.outillage.hook_git
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit", "#!/bin/sh\n# File generated by pre-commit\n")
    heure = 1767261600                                                 # 10:00

    class _Horloge(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(heure, tz=tz or UTC)

    monkeypatch.setattr(hook_git, "datetime", _Horloge)
    _pousser(depot, heure=heure)
    premiere = _commiter(depot)
    _git(depot, "branch", "premiere")
    _git(depot, "checkout", "-qb", "seconde")
    _commiter(depot)
    _git(depot, "checkout", "-q", "premiere")           # HEAD aussi est noté : pas seconde
    monkeypatch.setenv("LINTORN_POUSSE", premiere)
    if sous_pre_commit:
        monkeypatch.setenv("PRE_COMMIT_TO_REF", premiere)
    hook_git.noter_passage()
    monkeypatch.delenv("LINTORN_POUSSE")
    monkeypatch.delenv("PRE_COMMIT_TO_REF", raising=False)
    env = {**os.environ, "GIT_COMMITTER_DATE": f"@{heure_du_push} +0000"}
    subprocess.run(["git", "push", "-q", "origin", "premiere", "seconde"], cwd=depot, env=env,
                   check=True, capture_output=True, start_new_session=True)
    return _verdict_du_hook(monkeypatch)


@POSIX
def test_sous_pre_commit_un_push_de_deux_branches_dont_une_seule_est_verifiee_est_signale(
        tmp_path, monkeypatch):
    """pre-commit ne transmet que la première branche d'un push qui en envoie
    plusieurs : Lintorn ne vérifiait qu'elle, et une seule branche vérifiée
    suffisait à dire tout le push couvert."""
    resultat = _deux_branches(tmp_path, monkeypatch, sous_pre_commit=True,
                              heure_du_push=1767265200)                # 11:00

    assert resultat.statut == "ALERTE", resultat.resume
    assert "une partie de ton dernier push" in resultat.resume
    assert "pousse-les une par une" in resultat.detail


@POSIX
def test_hors_pre_commit_une_autre_branche_dans_la_meme_seconde_est_un_autre_push(
        tmp_path, monkeypatch):
    """git donne toutes les branches au hook : celle qu'il n'a pas vue vient d'un
    autre push, ici le tout premier, fait dans la seconde même par un script."""
    resultat = _deux_branches(tmp_path, monkeypatch, sous_pre_commit=False,
                              heure_du_push=1767261600)                # 10:00, même seconde

    assert resultat.statut == "OK", resultat.resume


@POSIX
def test_un_no_verify_du_commit_refuse_reste_couvert(tmp_path, monkeypatch):
    """Le hook est branché : c'est ce push-là qui l'a contourné, en connaissance de cause."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    _pousser(depot, heure=1767261600)
    _passage("2026-01-01T10:30:00+00:00", _commiter(depot))
    _envoyer(depot, "--no-verify", heure=1767265200)

    assert _verdict_du_hook(monkeypatch).statut == "OK"


@POSIX
def test_une_tentative_refusee_apres_le_dernier_push_prouve_le_branchement(tmp_path, monkeypatch):
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    _pousser(depot, heure=1767261600)                       # 10:00
    _passage("2026-01-01T10:30:00+00:00", _commiter(depot))   # refusé, rien poussé depuis

    assert _verdict_du_hook(monkeypatch).statut == "OK"


@POSIX
def test_un_passage_note_dans_un_etat_commite_ne_prouve_rien(tmp_path, monkeypatch):
    """Un dépôt piégé commite `.lintorn/etat.json` avec un passage tout frais."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    _passage("2099-01-01T00:00:00+00:00")
    subprocess.run(["git", "add", "-f", ".lintorn/etat.json"], cwd=depot, check=True)
    _pousser(depot)

    assert _verdict_du_hook(monkeypatch).statut == "ALERTE"


@POSIX
def test_les_hooks_rendus_muets_par_un_ancien_branchement_sont_signales(tmp_path, monkeypatch,
                                                                       capsys):
    """Un projet branché AVANT ce garde-fou : son pre-commit est muet depuis, et
    la mise à jour (`lintorn hook`) comme le contrôle disaient que tout allait bien."""
    depot = _depot(tmp_path, monkeypatch)
    assert lintorn.commandes.hook.installer_hook() == 0
    _un_hook(depot / ".git" / "hooks", "pre-commit")

    assert lintorn.commandes.hook.installer_hook() == 0
    assert "ne tournent plus" in capsys.readouterr().out

    resultat = _verdict_du_hook(monkeypatch)
    assert resultat.statut == "ALERTE"
    assert "pre-commit" in resultat.resume
    assert "git config --unset core.hooksPath" in resultat.detail


@POSIX
def test_force_nomme_les_hooks_qu_il_fait_taire_et_le_controle_s_en_souvient(
        tmp_path, monkeypatch, capsys):
    """Après coup, plus rien ne désigne le dossier remplacé : sans note prise au
    moment du `--force`, husky restait muet derrière un vert."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".husky" / "_", "pre-push")
    subprocess.run(["git", "config", "core.hooksPath", ".husky/_"], cwd=depot, check=True)

    assert lintorn.commandes.hook.installer_hook(forcer=True) == 0

    sortie = capsys.readouterr().out
    assert ".husky/_/ : pre-push" in sortie
    assert "git config core.hooksPath .husky/_" in sortie
    resultat = _verdict_du_hook(monkeypatch)
    assert resultat.statut == "ALERTE"
    assert ".husky/_/" in resultat.resume


@POSIX
def test_le_controle_ne_conseille_pas_de_faire_taire_les_autres_hooks(tmp_path, monkeypatch):
    """Il conseillait `git config core.hooksPath .lintorn/hooks` : husky devenait muet."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".husky", "pre-push")
    subprocess.run(["git", "config", "core.hooksPath", ".husky"], cwd=depot, check=True)

    resultat = _verdict_du_hook(monkeypatch)

    assert resultat.statut == "ALERTE"
    assert lintorn.controles.outillage.hook_git.ligne_a_ajouter() in resultat.detail
    assert "git config core.hooksPath" not in resultat.detail


def test_le_hook_livre_trouve_sh_par_le_path():
    """L'outil pre-commit lit la première ligne au pied de la lettre : sous
    Windows, `#!/bin/sh` donnait « Executable `/bin/sh` not found » et chaque
    push était refusé. `env sh` cherche `sh` dans le PATH, comme husky."""
    premiere = (config.HOOKS_SOURCE / "pre-push").read_bytes().split(b"\n")[0]

    assert premiere == b"#!/usr/bin/env sh"


def test_la_copie_du_hook_ne_part_pas_dans_le_depot_sans_init(tmp_path, monkeypatch):
    """Sans `lintorn init`, rien n'écartait la copie : un `git add -A` la commitait
    (en 100644 sous Windows), et le contrôle la déclarait muette."""
    depot = _depot(tmp_path, monkeypatch)

    assert lintorn.commandes.hook.installer_hook() == 0
    subprocess.run(["git", "add", "-A"], cwd=depot, check=True)

    suivis = subprocess.run(["git", "ls-files"], cwd=depot, capture_output=True, text=True,
                            check=True).stdout.split()
    assert ".lintorn/hooks/pre-push" not in suivis


@POSIX
@pytest.mark.parametrize("marque, fichier, ensuite", [
    ("# File generated by pre-commit: https://pre-commit.com", ".pre-commit-config.yaml",
     "pre-commit install --hook-type pre-push"),
    ("call_lefthook()", "lefthook.yml", "lefthook install"),
    ('[ "$SKIP_SIMPLE_GIT_HOOKS" = "1" ] && exit 0', "package.json", "npx simple-git-hooks"),
], ids=["pre-commit", "lefthook", "simple-git-hooks"])
def test_un_outil_qui_reecrit_ses_hooks_recoit_un_conseil_pour_sa_config(
        tmp_path, monkeypatch, capsys, marque, fichier, ensuite):
    """Ces outils réécrivent leurs scripts à chaque install : une ligne ajoutée à la
    main y disparaissait, et Lintorn cessait de tourner. Seule leur config dure."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit", f"#!/bin/sh\n{marque}\n")

    assert lintorn.commandes.hook.installer_hook() == 1

    sortie = capsys.readouterr().out
    assert f"a {fichier}" in sortie
    assert ensuite in sortie
    assert ".git/hooks/pre-push" not in sortie


@POSIX
@pytest.mark.parametrize("marque, reglage", [
    ("# File generated by pre-commit: https://pre-commit.com", "verbose: true"),
    ("call_lefthook()", "use_stdin: true"),
], ids=["pre-commit", "lefthook"])
def test_le_bloc_conseille_garde_ce_qui_fait_parler_lintorn(
        tmp_path, monkeypatch, capsys, marque, reglage):
    """Sans `use_stdin`, lefthook garde pour lui ce qui part. Sans `verbose`,
    pre-commit n'affiche Lintorn que s'il refuse : « SANS verification complete »
    devenait « Passed »."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit", f"#!/bin/sh\n{marque}\n")

    assert lintorn.commandes.hook.installer_hook() == 1

    assert reglage in capsys.readouterr().out


@POSIX
def test_lefthook_lance_lintorn_par_un_script_pas_par_une_commande(tmp_path, monkeypatch, capsys):
    """lefthook saute une commande quand il ne voit aucun fichier à pousser (une
    branche où l'on n'est pas) : le push partait sans Lintorn. Un script tourne
    à chaque push, depuis le dossier que dit `source_dir`."""
    depot = _depot(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "SOMMET_GIT", depot)
    (depot / "lefthook.yml").write_text('source_dir: "outils/hooks/"\n', encoding="utf-8")
    _un_hook(depot / ".git" / "hooks", "pre-commit", "#!/bin/sh\n# call_lefthook\n")

    assert lintorn.commandes.hook.installer_hook() == 1

    sortie = capsys.readouterr().out
    assert '  scripts:\n        "lintorn.sh":' in sortie, sortie
    assert "commands:" not in sortie
    assert "outils/hooks/pre-push/lintorn.sh :" in sortie
    assert 'exec .lintorn/hooks/pre-push "$@"' in sortie


@POSIX
def test_lintorn_lance_par_une_commande_lefthook_est_signale(tmp_path, monkeypatch):
    """L'ancien bloc conseillé (`run:`) : Lintorn tourne, mais pas à chaque push."""
    depot = _depot(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "SOMMET_GIT", depot)
    _un_hook(depot / ".git" / "hooks", "pre-commit", "#!/bin/sh\n# call_lefthook\n")
    (depot / "lefthook.yml").write_text(
        "pre-push:\n  commands:\n    lintorn:\n      run: .lintorn/hooks/pre-push\n"
        "      use_stdin: true\n", encoding="utf-8")
    _pousser(depot, heure=1767261600)
    _passage("2026-01-01T10:30:00+00:00", _commiter(depot))

    resultat = _verdict_du_hook(monkeypatch)

    assert resultat.statut == "VERIF", resultat.resume
    assert "par un script" in resultat.resume
    assert '"lintorn.sh":' in resultat.detail


@POSIX
@pytest.mark.skipif(shutil.which("lefthook") is None, reason="lefthook absent")
def test_le_bloc_conseille_a_lefthook_lance_lintorn_pour_une_branche_non_extraite(
        tmp_path, monkeypatch):
    """Le vrai lefthook, et le bloc tel que `lintorn hook` le donne."""
    depot = _projet_js(tmp_path, monkeypatch, branche=False)
    (depot / "lefthook.yml").write_text("pre-commit:\n  commands:\n    rien:\n      run: 'true'\n",
                                        encoding="utf-8")
    assert _git(depot, "config", "--unset", "core.hooksPath").returncode in (0, 5)
    assert _git(depot, "-c", "core.hooksPath=.git/hooks", "status").returncode == 0
    assert subprocess.run(["lefthook", "install"], cwd=depot, capture_output=True,
                          check=False).returncode == 0
    monkeypatch.setattr(config, "SOMMET_GIT", depot)
    quoi = lintorn.controles.outillage.hook_git.conseil(
        lintorn.controles.outillage.hook_git.autres_hooks())
    with (depot / "lefthook.yml").open("a", encoding="utf-8") as flux:
        flux.write(quoi.ajout + "\n")
    quoi.script[0].parent.mkdir(parents=True)
    quoi.script[0].write_text(quoi.script[1] + "\n", encoding="utf-8")
    assert lintorn.commandes.hook.installer_hook() == 1           # pose le script de Lintorn
    assert subprocess.run(["lefthook", "install"], cwd=depot, capture_output=True,
                          check=False).returncode == 0
    _git(depot, "add", "-A")
    _git(depot, "commit", "-qm", "lefthook")
    _envoyer(depot, "--no-verify")
    _git(depot, "checkout", "-qb", "fonction")
    _commit_fautif(depot)
    _git(depot, "checkout", "-q", "-")

    pousse = _git(depot, "push", "origin", "fonction")

    sortie = pousse.stdout + pousse.stderr
    assert "Lintorn controle avant push" in sortie, "une commande lefthook ne tournait pas ici"
    assert "Lintorn OK" not in sortie, sortie
    assert "SANS verification complete" in sortie and "f.js" in sortie, sortie


def test_un_chemin_a_espace_reste_entier_dans_la_config_de_l_outil(tmp_path, monkeypatch):
    """Écrit tel quel, `'mon api/…'` perdait ses apostrophes en YAML, et pre-commit
    coupait le chemin en deux."""
    monkeypatch.setattr(config, "HOOKS_POUR_GIT", "mon api/.lintorn/hooks")
    _un_hook(tmp_path, "pre-commit", "#!/bin/sh\n# File generated by pre-commit\n")

    quoi = lintorn.controles.outillage.hook_git.conseil(
        lintorn.controles.outillage.hook_git.AutresHooks(tmp_path, ["pre-commit"]))

    entree = next(ligne for ligne in quoi.ajout.split("\n") if "entry:" in ligne)
    valeur = json.loads(entree.split("entry:", 1)[1])          # une chaîne JSON est du YAML
    assert shlex.split(valeur) == ["mon api/.lintorn/hooks/pre-push"]


# ─────────────────────────────────────────────────────────────────────────────
# Les worktrees : `core.hooksPath` commun, une copie du hook par worktree
# ─────────────────────────────────────────────────────────────────────────────
def _worktree(depot, nom="agent"):
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "base"], cwd=depot, check=True)
    arbre = depot.parent / f"{depot.name}-{nom}"
    subprocess.run(["git", "worktree", "add", "-q", "-b", nom, str(arbre)], cwd=depot, check=True)
    return arbre


@POSIX
def test_un_worktree_sans_sa_copie_du_hook_n_est_pas_un_vert(tmp_path, monkeypatch):
    """Le hook branché ici, un worktree créé ensuite (ceux de Claude Code compris) :
    ses push ne lançaient rien, et le contrôle disait « Lintorn tournera avant
    chaque push »."""
    depot = _depot(tmp_path, monkeypatch)
    assert lintorn.commandes.hook.installer_hook() == 0
    arbre = _worktree(depot)

    resultat = _verdict_du_hook(monkeypatch)

    assert resultat.statut == "ALERTE"
    assert "worktree" in resultat.resume
    assert f"../{arbre.name}" in resultat.resume, "un chemin absolu porterait le nom de l'utilisateur"
    (arbre / ".lintorn" / "hooks").mkdir(parents=True)
    copie = arbre / ".lintorn" / "hooks" / "pre-push"
    copie.write_bytes((config.HOOKS_SOURCE / "pre-push").read_bytes())
    copie.chmod(0o755)
    assert _verdict_du_hook(monkeypatch).statut == "OK"


@POSIX
def test_un_push_verifie_depuis_un_autre_worktree_couvre_le_dernier_push(tmp_path, monkeypatch):
    """Le journal des push est commun à tous les worktrees, le passage noté ne l'est
    pas : lu ici seul, un push vérifié depuis un autre worktree passait pour parti
    sans Lintorn."""
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    _pousser(depot, heure=1767261600)                           # le 1er janvier, depuis ici
    arbre = _worktree(depot)
    pousse = _commiter(arbre)
    (arbre / ".lintorn").mkdir()
    (arbre / ".lintorn" / "etat.json").write_text(json.dumps({
        lintorn.controles.outillage.hook_git.CLE_PASSAGE: {
            "quand": "2026-01-01T10:00:00+00:00", "commits": [pousse]}}), encoding="utf-8")
    subprocess.run(["git", "push", "-q", "origin", "agent"], cwd=arbre, check=True)  # le dernier

    assert _verdict_du_hook(monkeypatch).statut == "OK"


@POSIX
def test_un_passage_date_du_futur_ne_prouve_rien(tmp_path, monkeypatch):
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    _pousser(depot)
    _passage("2099-01-01T00:00:00+00:00")

    assert _verdict_du_hook(monkeypatch).statut == "ALERTE"


# ─────────────────────────────────────────────────────────────────────────────
# Ce que le hook dit au push : jamais « OK » sur ce qu'il n'a pas vérifié
# ─────────────────────────────────────────────────────────────────────────────
_REGLE_EVAL = ('[[regles]]\nnom = "Pas eval"\nracine = "."\nsuffixes = [".js"]\n'
               "motif = 'eval\\('\nbloquant = true\n")


def _projet_js(tmp_path, monkeypatch, branche=True, pousser=True):
    """Un dépôt JavaScript avec une règle maison BLOQUANTE (`eval(` interdit), poussé une fois."""
    depot = _depot(tmp_path, monkeypatch)
    _lintorn_dans_le_path(tmp_path, monkeypatch)
    (depot / "app.js").write_text("console.log(1);\n", encoding="utf-8")
    (depot / "README.md").write_text("# P\n\nLe code vit dans `app.js`.\n", encoding="utf-8")
    (depot / ".lintorn").mkdir()
    (depot / ".lintorn" / "config.toml").write_text("", encoding="utf-8")
    (depot / ".lintorn" / "regles.toml").write_text(_REGLE_EVAL, encoding="utf-8")
    if branche:
        assert lintorn.commandes.hook.installer_hook() == 0
    subprocess.run(["git", "add", "-A"], cwd=depot, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=depot, check=True)
    if pousser:
        premier = _envoyer(depot)
        assert premier.returncode == 0, premier.stdout + premier.stderr
    return depot


def _commit_fautif(depot, nom="f.js"):
    (depot / nom).write_text('x = eval("1");\n', encoding="utf-8")
    subprocess.run(["git", "add", nom], cwd=depot, check=True)
    subprocess.run(["git", "commit", "-qm", "fautif"], cwd=depot, check=True)


@POSIX
def test_une_correction_pas_commitee_ne_fait_pas_dire_ok_au_push(tmp_path, monkeypatch):
    """Commiter une faute, la corriger sur le disque sans commiter, pousser : le hook
    lisait le disque, concluait « Lintorn OK », et la faute partait."""
    depot = _projet_js(tmp_path, monkeypatch)
    _commit_fautif(depot)
    (depot / "f.js").write_text("x = 1;\n", encoding="utf-8")

    pousse = _envoyer(depot)

    sortie = pousse.stdout + pousse.stderr
    assert "Lintorn OK" not in sortie
    assert "SANS verification complete" in sortie
    assert "f.js" in sortie, "dire QUEL fichier n'est pas ce qui part"


@POSIX
@pytest.mark.parametrize("drapeau", ["--assume-unchanged", "--skip-worktree"])
def test_un_fichier_que_git_ne_compare_plus_au_disque_ne_fait_pas_dire_ok(tmp_path, monkeypatch,
                                                                         drapeau):
    """Faute commitée, corrigée sur le disque, puis cachée à `git diff` par un drapeau
    d'index : Lintorn lisait le disque propre et concluait « Lintorn OK »."""
    depot = _projet_js(tmp_path, monkeypatch)
    _commit_fautif(depot)
    (depot / "f.js").write_text("x = 1;\n", encoding="utf-8")
    subprocess.run(["git", "update-index", drapeau, "f.js"], cwd=depot, check=True)

    pousse = _envoyer(depot)

    sortie = pousse.stdout + pousse.stderr
    assert "Lintorn OK" not in sortie, sortie
    assert "SANS verification complete" in sortie and "f.js" in sortie


@POSIX
def test_un_fichier_hors_du_sparse_checkout_ne_fait_pas_dire_ok(tmp_path, monkeypatch):
    """Absent du disque, le fichier fautif n'est lu par personne : « aucun defaut connu »."""
    depot = _projet_js(tmp_path, monkeypatch)
    (depot / "cache").mkdir()
    _commit_fautif(depot, "cache/f.js")
    subprocess.run(["git", "sparse-checkout", "set", "--no-cone", "/*", "!/cache/"],
                   cwd=depot, check=True)
    assert not (depot / "cache" / "f.js").exists()

    pousse = _envoyer(depot)

    sortie = pousse.stdout + pousse.stderr
    assert "Lintorn OK" not in sortie, sortie
    assert "cache/f.js" in sortie


@POSIX
def test_un_fichier_marque_mais_identique_au_commit_garde_son_ok(tmp_path, monkeypatch):
    """Le drapeau seul ne prouve rien : un fichier caché mais identique reste lu."""
    depot = _projet_js(tmp_path, monkeypatch)
    (depot / "g.js").write_text("y = 2;\n", encoding="utf-8")
    subprocess.run(["git", "add", "g.js"], cwd=depot, check=True)
    subprocess.run(["git", "commit", "-qm", "propre"], cwd=depot, check=True)
    subprocess.run(["git", "update-index", "--assume-unchanged", "g.js"], cwd=depot, check=True)

    pousse = _envoyer(depot)

    assert "Lintorn OK" in pousse.stdout + pousse.stderr, pousse.stdout + pousse.stderr


@POSIX
def test_pousser_une_autre_branche_que_celle_du_disque_ne_dit_pas_ok(tmp_path, monkeypatch):
    depot = _projet_js(tmp_path, monkeypatch)
    subprocess.run(["git", "checkout", "-qb", "travail"], cwd=depot, check=True)
    _commit_fautif(depot)
    subprocess.run(["git", "checkout", "-q", "-"], cwd=depot, check=True)

    pousse = subprocess.run(["git", "push", "-q", "origin", "travail"], cwd=depot,
                            capture_output=True, text=True, timeout=120,
                            start_new_session=True, check=False)

    sortie = pousse.stdout + pousse.stderr
    assert "Lintorn OK" not in sortie
    assert "f.js" in sortie


@POSIX
def test_une_faute_de_frappe_dans_regles_toml_ne_fait_pas_dire_ok(tmp_path, monkeypatch):
    """Un guillemet oublié retirait TOUTES les règles maison, et le push fautif
    recevait « Lintorn OK »."""
    depot = _projet_js(tmp_path, monkeypatch)
    (depot / ".lintorn" / "regles.toml").write_text(
        _REGLE_EVAL.replace('"Pas eval"', '"Pas eval'), encoding="utf-8")
    _commit_fautif(depot)

    pousse = _envoyer(depot)

    sortie = pousse.stdout + pousse.stderr
    assert "Lintorn OK" not in sortie
    assert "SANS verification complete" in sortie
    assert "regles.toml" in sortie, "dire POURQUOI"


@POSIX
@pytest.mark.parametrize("table", ["regle", "régles"])
def test_une_table_mal_nommee_dans_regles_toml_ne_fait_pas_dire_ok(tmp_path, monkeypatch, table):
    """`[[regle]]` au lieu de `[[regles]]` : la règle bloquante disparaissait sans un
    mot, la ligne Configuration restait verte et le push fautif partait sur « Lintorn OK ».
    `[[régles]]` rend même le fichier illisible : le dire en français, avec la ligne."""
    depot = _projet_js(tmp_path, monkeypatch)
    regles = depot / ".lintorn" / "regles.toml"
    regles.write_text(regles.read_text(encoding="utf-8") + "\n" + _REGLE_EVAL.replace(
        "[[regles]]", f"[[{table}]]").replace("Pas eval", "Pas de debugger").replace(
        "eval\\(", "debugger"), encoding="utf-8")
    (depot / "f.js").write_text("debugger;\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=depot, check=True)
    subprocess.run(["git", "commit", "-qm", "fautif"], cwd=depot, check=True)

    pousse = _envoyer(depot)

    sortie = pousse.stdout + pousse.stderr
    assert "Lintorn OK" not in sortie, sortie
    assert "SANS verification complete" in sortie
    assert f"[[{table}]] n'est pas lu - ecris [[regles]]" in sortie, "la faute, et la bonne ecriture"


@POSIX
def test_pousser_la_seule_version_d_un_sous_module_dit_ok(tmp_path, monkeypatch):
    """Le push n'envoie que la version du sous-module, son code part dans son
    propre dépôt : « aucun controle ne lit ces fichiers : lib », à chaque fois."""
    lib = tmp_path.parent / f"{tmp_path.name}-lib"
    lib.mkdir()
    _git(lib, "init", "-q")
    (lib / "outil.js").write_text("console.log(1);\n", encoding="utf-8")
    _git(lib, "add", "-A")
    _git(lib, "commit", "-qm", "un")
    depot = _projet_js(tmp_path, monkeypatch)
    assert _git(depot, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(lib),
                "lib").returncode == 0
    _git(depot, "commit", "-qm", "sous-module")
    assert _envoyer(depot, "--no-verify").returncode == 0
    (depot / "lib" / "outil.js").write_text("console.log(2);\n", encoding="utf-8")
    _git(depot / "lib", "commit", "-qam", "deux")
    _git(depot, "add", "lib")
    _git(depot, "commit", "-qm", "monte lib")

    pousse = _envoyer(depot)

    sortie = pousse.stdout + pousse.stderr
    assert pousse.returncode == 0, sortie
    assert "Lintorn OK" in sortie, sortie
    assert "sous-module" in sortie


@POSIX
def test_un_push_que_rien_ne_lit_ne_fait_pas_dire_ok(tmp_path, monkeypatch):
    depot = _projet_js(tmp_path, monkeypatch)
    (depot / "style.css").write_text("a { color: red; }\n", encoding="utf-8")
    subprocess.run(["git", "add", "style.css"], cwd=depot, check=True)
    subprocess.run(["git", "commit", "-qm", "style"], cwd=depot, check=True)

    pousse = _envoyer(depot)

    sortie = pousse.stdout + pousse.stderr
    assert pousse.returncode == 0
    assert "Lintorn OK" not in sortie
    assert "aucun controle ne lit ces fichiers : style.css" in sortie


@POSIX
def test_un_push_en_partie_lu_dit_ok_et_nomme_ce_qu_il_n_a_pas_lu(tmp_path, monkeypatch):
    """Choix voulu : seul un push que RIEN ne lit perd son « Lintorn OK ». Sinon une
    image poussée avec du code suffirait à le retirer ; la ligne du focus la nomme."""
    depot = _projet_js(tmp_path, monkeypatch)
    (depot / "style.css").write_text("a { color: red; }\n", encoding="utf-8")
    (depot / "app.js").write_text("console.log(2);\n", encoding="utf-8")
    subprocess.run(["git", "add", "style.css", "app.js"], cwd=depot, check=True)
    subprocess.run(["git", "commit", "-qm", "style"], cwd=depot, check=True)

    pousse = _envoyer(depot)

    sortie = pousse.stdout + pousse.stderr
    assert pousse.returncode == 0
    assert "Lintorn OK" in sortie, sortie
    assert "1 que rien ne lit : style.css" in sortie, sortie


def test_un_outil_ne_recoit_ni_le_depot_du_hook_ni_les_reglages_d_un_git_c(tmp_path, monkeypatch):
    """`git -c user.name=... push` exporte GIT_CONFIG_PARAMETERS : les `git` des tests du
    projet tournaient avec les réglages d'un push."""
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "ailleurs.git"))
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'user.name'='piege'")
    lire = "import os; print(sorted(n for n in os.environ if n in ('GIT_DIR', 'GIT_CONFIG_PARAMETERS')))"

    resultat = base.lancer("Outil", [sys.executable, "-c", lire], tmp_path,
                           codes_alerte=(0,))

    assert "[]" in resultat.detail, resultat.detail


@POSIX
def test_un_outil_lance_depuis_un_worktree_n_ecrit_pas_dans_le_depot(tmp_path, monkeypatch):
    """Dans un worktree, git exporte GIT_DIR vers le hook. Les tests du projet, lancés par
    Lintorn, faisaient `git init` et `git commit` dans un dossier jetable : 48 commits
    dans le vrai dépôt, et `core.bare = true`."""
    depot = _projet_js(tmp_path, monkeypatch)
    temoin = tmp_path.parent / f"{tmp_path.name}-a-tourne"
    piege = (f'd=$(mktemp -d) && cd "$d" && git init -q && git commit -q --allow-empty -m piege'
             f' ; touch "{temoin}"')
    (depot / ".lintorn" / "config.toml").write_text(
        f'[[commandes]]\ncle = "piege"\ntitre = "Piege git"\ncmd = ["sh", "-c", \'{piege}\']\n'
        "bloquant = false\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "commande"], cwd=depot, check=True)
    annexe = tmp_path.parent / f"{tmp_path.name}-annexe"
    subprocess.run(["git", "worktree", "add", "-q", str(annexe), "-b", "annexe"], cwd=depot, check=True)
    subprocess.run(["lintorn", "hook"], cwd=annexe, capture_output=True, check=True)

    pousse = subprocess.run(["git", "push", "-q", "origin", "HEAD:refs/heads/annexe"], cwd=annexe,
                            capture_output=True, text=True, timeout=120, start_new_session=True,
                            check=False)

    assert temoin.exists(), "la commande n'a pas tourne, rien n'est prouve :\n" + pousse.stdout + pousse.stderr
    journal = subprocess.run(["git", "log", "--format=%s", "annexe"], cwd=depot,
                             capture_output=True, text=True, check=True).stdout
    assert "piege" not in journal.split()
    assert subprocess.run(["git", "config", "core.bare"], cwd=depot, capture_output=True,
                          text=True, check=False).stdout.strip() != "true"


@POSIX
def test_supprimer_une_branche_n_est_pas_refuse_pour_une_faute_du_disque(tmp_path, monkeypatch):
    """Rien ne part, mais la règle bloquante trouvait une faute sur le disque : la
    suppression était refusée, et seul `--no-verify` passait."""
    depot = _projet_js(tmp_path, monkeypatch)
    _envoyer(depot, "--no-verify")
    assert _git(depot, "push", "-q", "--no-verify", "origin", "HEAD:refs/heads/jetable").returncode == 0
    (depot / "f.js").write_text('x = eval("1");\n', encoding="utf-8")

    supprime = _git(depot, "push", "origin", "--delete", "jetable")

    sortie = supprime.stdout + supprime.stderr
    assert supprime.returncode == 0, sortie
    assert "rien de nouveau ne part" in sortie.lower(), sortie


@POSIX
def test_un_nom_neuf_sur_un_commit_deja_parti_dit_que_rien_ne_part(tmp_path, monkeypatch):
    """Rien de nouveau ne partait, aucun fichier n'était lu, et le hook disait « Lintorn OK »
    comme après une vérification."""
    depot = _projet_js(tmp_path, monkeypatch)

    pousse = _git(depot, "push", "origin", "HEAD:refs/heads/autre-nom")

    sortie = pousse.stdout + pousse.stderr
    assert pousse.returncode == 0, sortie
    assert "rien de nouveau ne part" in sortie.lower(), sortie


@POSIX
def test_le_hook_dit_quand_une_autre_version_de_lintorn_tourne(tmp_path, monkeypatch):
    """Le venv d'un autre projet, activé dans le terminal, faisait tourner sa propre
    version de Lintorn sous ce hook, sans un mot."""
    depot = _projet_js(tmp_path, monkeypatch)
    (depot / "g.js").write_text("y = 1;\n", encoding="utf-8")
    _git(depot, "add", "g.js")
    _git(depot, "commit", "-qm", "g")
    assert "ATTENTION : ce hook a ete pose" not in _envoyer(depot).stdout, "meme version : rien a dire"
    autre = tmp_path.parent / f"{tmp_path.name}-autre-venv"
    autre.mkdir()
    (autre / "lintorn").write_text(
        f'#!/bin/sh\n[ "$1" = version ] && {{ echo "lintorn 0.5.0"; exit 0; }}\n'
        f'exec "{sys.executable}" -m lintorn "$@"\n', encoding="utf-8")
    (autre / "lintorn").chmod(0o755)
    monkeypatch.setenv("PATH", f"{autre}{os.pathsep}{os.environ['PATH']}")
    (depot / "g.js").write_text("y = 2;\n", encoding="utf-8")
    _git(depot, "commit", "-qam", "g2")

    pousse = _envoyer(depot)

    sortie = pousse.stdout + pousse.stderr
    assert f"pose par lintorn {lintorn.__version__}, mais c'est lintorn 0.5.0" in sortie, sortie


@POSIX
def test_un_push_parti_avec_lintorn_introuvable_n_est_plus_vert(tmp_path, monkeypatch):
    """Lintorn absent du PATH du push (un éditeur sans le venv) : le hook laisse
    passer, et le contrôle disait ensuite « Lintorn tournera avant chaque push »."""
    depot = _projet_js(tmp_path, monkeypatch)
    _commit_fautif(depot)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    # git note ses push à la seconde : deux push dans la même seconde se confondent.
    pousse = _envoyer(depot, heure=int(time.time()) + 2)

    assert pousse.returncode == 0
    assert "Lintorn introuvable" in pousse.stdout + pousse.stderr
    resultat = _verdict_du_hook(monkeypatch)
    assert resultat.statut == "ALERTE"
    assert "est parti SANS Lintorn" in resultat.resume


@POSIX
def test_branche_par_lintorn_un_refus_annule_vraiment_le_push(tmp_path, monkeypatch):
    depot = _projet_js(tmp_path, monkeypatch)
    _commit_fautif(depot)

    pousse = _envoyer(depot)

    assert pousse.returncode != 0
    assert "PUSH ANNULE" in pousse.stdout + pousse.stderr
    assert "outil de hooks" not in pousse.stdout + pousse.stderr, "aucun outil ici"
    # Puis `--no-verify` : c'est un choix, le hook est bien branché.
    assert _envoyer(depot, "--no-verify").returncode == 0
    assert _verdict_du_hook(monkeypatch).statut == "OK"


@POSIX
def test_un_appel_qui_ignore_le_refus_ne_dit_plus_push_annule(tmp_path, monkeypatch, capsys):
    """La ligne sans `|| exit 1` : Lintorn affichait « PUSH ANNULE », le push
    partait quand même, et le contrôle disait « appele par ton hook »."""
    depot = _projet_js(tmp_path, monkeypatch, branche=False)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    assert lintorn.commandes.hook.installer_hook() == 1      # refuse, pose le script
    script = lintorn.controles.outillage.hook_git.script_du_hook()
    _un_hook(depot / ".git" / "hooks", "pre-push",
             f'#!/bin/sh\n{script} "$@"\necho "fin de mon pre-push"\n')
    _commit_fautif(depot)

    pousse = _envoyer(depot)

    sortie = pousse.stdout + pousse.stderr
    assert pousse.returncode == 0, "c'est son hook qui decide : il n'a pas transmis le refus"
    assert "PUSH ANNULE" not in sortie
    assert "LINTORN REFUSE CE PUSH" in sortie
    resultat = _verdict_du_hook(monkeypatch)
    assert resultat.statut == "ALERTE"
    assert "l'avait REFUSE" in resultat.resume
    capsys.readouterr()
    assert lintorn.commandes.hook.installer_hook() == 1
    assert "malgre son refus" in capsys.readouterr().out, "et pas « ton hook l'appelle deja »"


@POSIX
def test_une_tentative_refusee_dans_la_meme_seconde_garde_le_push_verifie(tmp_path, monkeypatch):
    """La trace était remplacée à chaque passage : une tentative refusée dans la
    seconde du push précédent effaçait son commit, et ce push passait pour parti
    sans Lintorn."""
    hook_git = lintorn.controles.outillage.hook_git
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    heure = 1767261600

    class _Horloge(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(heure, tz=tz or UTC)

    monkeypatch.setattr(hook_git, "datetime", _Horloge)
    monkeypatch.setenv("LINTORN_POUSSE", _commiter(depot))
    hook_git.noter_passage()                    # Lintorn vérifie ce commit…
    _envoyer(depot, heure=heure)                # …qui part, à cette seconde-là
    monkeypatch.setenv("LINTORN_POUSSE", _commiter(depot))
    hook_git.noter_passage()                    # puis une tentative refusée, même seconde

    assert _verdict_du_hook(monkeypatch).statut == "OK"


@POSIX
def test_un_push_sans_lintorn_dans_la_seconde_de_son_passage_n_est_pas_couvert(tmp_path,
                                                                               monkeypatch):
    """Les heures comparées avec `>=` : un autre commit, poussé sans Lintorn dans
    la seconde même de son dernier passage, passait pour vérifié."""
    hook_git = lintorn.controles.outillage.hook_git
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    heure = 1767261600

    class _Horloge(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(heure, tz=tz or UTC)

    monkeypatch.setattr(hook_git, "datetime", _Horloge)
    monkeypatch.setenv("LINTORN_POUSSE", _commiter(depot))
    hook_git.noter_passage()                    # Lintorn vérifie ce commit…
    _commiter(depot)
    _envoyer(depot, heure=heure)                # …un autre part sans lui, même seconde

    resultat = _verdict_du_hook(monkeypatch)
    assert resultat.statut == "ALERTE", resultat.resume
    assert "est parti SANS Lintorn" in resultat.resume


@POSIX
def test_pendant_un_push_le_push_d_avant_dans_la_meme_seconde_n_est_pas_accuse(tmp_path,
                                                                             monkeypatch):
    """Un script qui pose le hook et pousse dans la seconde de son premier push :
    le passage noté par CE lancement vient après, et le push d'avant était accusé."""
    hook_git = lintorn.controles.outillage.hook_git
    depot = _depot(tmp_path, monkeypatch)
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    heure = 1767261600

    class _Horloge(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(heure, tz=tz or UTC)

    monkeypatch.setattr(hook_git, "datetime", _Horloge)
    _pousser(depot, heure=heure)                # sans Lintorn, à cette seconde-là
    monkeypatch.setenv("LINTORN_HOOK", "1")
    monkeypatch.setenv("LINTORN_POUSSE", _commiter(depot))
    hook_git.noter_passage()                    # puis Lintorn, pendant le push suivant

    assert _verdict_du_hook(monkeypatch).statut == "OK"


def _git(depot, *arguments):
    return subprocess.run(["git", *arguments], cwd=depot, capture_output=True, text=True,
                          timeout=120, start_new_session=True, check=False)


def _corrige_sans_commiter(depot, nom="f.js"):
    (depot / nom).write_text("x = 1;\n", encoding="utf-8")


# Le cadre vient du hook : `sh` écrit de l'UTF-8, que pre-commit relit tel quel.
# Le reste vient de python, qui écrit en cp1252 sous Windows : ASCII seulement.
_DESSIN_DU_HOOK = set("─═║╔╗╚╝")


def _ne_dit_pas_ok(pousse, *noms):
    sortie = pousse.stdout + pousse.stderr
    assert "Lintorn OK" not in sortie, sortie
    assert "SANS verification complete" in sortie, sortie
    for nom in noms:
        assert nom in sortie, f"dire lequel : {nom}"
    hors = {c for c in sortie if not c.isascii()} - _DESSIN_DU_HOOK - set("".join(noms))
    assert not hors, f"illisible sous pre-commit Windows : {sorted(hors)}"


@POSIX
def test_le_tout_premier_push_compare_aussi_le_disque(tmp_path, monkeypatch):
    """Rien encore sur le distant : le hook ne savait lister aucun fichier, ne
    comparait rien, et concluait « Lintorn OK »."""
    depot = _projet_js(tmp_path, monkeypatch, pousser=False)
    _commit_fautif(depot)
    _corrige_sans_commiter(depot)

    _ne_dit_pas_ok(_envoyer(depot), "f.js")


@POSIX
def test_une_branche_neuve_d_un_depot_en_develop_est_comparee(tmp_path, monkeypatch):
    """Ni `origin/HEAD`, ni `main`, ni `master` : « le focus est saute », puis « Lintorn OK »."""
    depot = _projet_js(tmp_path, monkeypatch, pousser=False)
    _envoyer(depot)
    assert _git(depot, "push", "-q", "origin", "HEAD:refs/heads/develop", "--no-verify").returncode == 0
    assert _git(depot, "push", "-q", "origin", "--delete", "main", "--no-verify").returncode == 0
    _git(depot, "checkout", "-qb", "fonction")
    _commit_fautif(depot)
    _corrige_sans_commiter(depot)

    _ne_dit_pas_ok(_git(depot, "push", "-q", "origin", "fonction"), "f.js")


@POSIX
def test_une_branche_orpheline_est_comparee(tmp_path, monkeypatch):
    depot = _projet_js(tmp_path, monkeypatch)
    _git(depot, "checkout", "-q", "--orphan", "pages")
    _git(depot, "rm", "-rq", "--cached", "app.js", "README.md")
    _commit_fautif(depot, "site.js")
    _corrige_sans_commiter(depot, "site.js")

    _ne_dit_pas_ok(_git(depot, "push", "-q", "origin", "pages"), "site.js")


@POSIX
def test_un_force_push_par_dessus_un_commit_inconnu_est_compare(tmp_path, monkeypatch):
    """Le commit d'un collègue, pas encore récupéré : `git diff` échouait en
    silence, aucun avis, et « Lintorn OK »."""
    depot = _projet_js(tmp_path, monkeypatch)
    collegue = tmp_path.parent / f"{tmp_path.name}-collegue"
    subprocess.run(["git", "clone", "-q", "-b", "main", str(depot.parent / f"{depot.name}-distant.git"),
                    str(collegue)], check=True)
    (collegue / "autre.txt").write_text("du collegue\n", encoding="utf-8")
    _git(collegue, "add", "autre.txt")
    _git(collegue, "commit", "-qm", "collegue")
    assert _git(collegue, "push", "-q", "origin", "HEAD:main").returncode == 0
    _commit_fautif(depot)
    _corrige_sans_commiter(depot)

    _ne_dit_pas_ok(_envoyer(depot, "--force"), "f.js")


def _cohabiter_avec(depot, script_pre_push: str):
    """Un autre outil tient les hooks : Lintorn pose son script, l'outil l'appelle."""
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    assert lintorn.commandes.hook.installer_hook() == 1      # refuse, pose le script
    script = lintorn.controles.outillage.hook_git.script_du_hook()
    _un_hook(depot / ".git" / "hooks", "pre-push",
             "#!/bin/sh\n" + script_pre_push.replace("LINTORN", f'{script} "$@"'))


# Ce que fait pre-commit : il lit lui-même ce que git envoie, et donne la
# première branche poussée dans ses variables.
_COMME_PRE_COMMIT = """read -r ref_locale sha_local ref_distante sha_distant
PRE_COMMIT_FROM_REF=$sha_distant PRE_COMMIT_TO_REF=$sha_local
PRE_COMMIT_LOCAL_BRANCH=$ref_locale PRE_COMMIT_REMOTE_BRANCH=$ref_distante
PRE_COMMIT_REMOTE_NAME=$1 PRE_COMMIT_REMOTE_URL=$2
export PRE_COMMIT_FROM_REF PRE_COMMIT_TO_REF PRE_COMMIT_LOCAL_BRANCH
export PRE_COMMIT_REMOTE_BRANCH PRE_COMMIT_REMOTE_NAME PRE_COMMIT_REMOTE_URL
LINTORN < /dev/null || exit 1
"""


@POSIX
def test_derriere_pre_commit_le_hook_sait_ce_qui_part(tmp_path, monkeypatch):
    """pre-commit garde l'entrée de git pour lui : Lintorn ne savait rien de ce
    qui partait, et concluait « OK » sur une correction seulement indexée."""
    depot = _projet_js(tmp_path, monkeypatch, branche=False)
    _cohabiter_avec(depot, _COMME_PRE_COMMIT)
    _commit_fautif(depot, "g.js")
    _corrige_sans_commiter(depot, "g.js")
    _git(depot, "add", "g.js")

    _ne_dit_pas_ok(_envoyer(depot, heure=int(time.time()) + 2), "g.js")
    # Et le commit noté est bien celui qui est parti : pas de « parti SANS Lintorn ».
    assert _verdict_du_hook(monkeypatch).statut == "OK"


@POSIX
def test_un_outil_qui_garde_la_liste_pour_lui_ne_fait_pas_dire_ok(tmp_path, monkeypatch):
    depot = _projet_js(tmp_path, monkeypatch, branche=False)
    _cohabiter_avec(depot, "cat > /dev/null\nLINTORN < /dev/null || exit 1\n")
    _commiter(depot)

    pousse = _envoyer(depot)

    _ne_dit_pas_ok(pousse, "ne lui a pas transmis ce qui part")
    # Rien à pousser : là, le silence de l'outil ne cache rien.
    assert "Lintorn OK" in _envoyer(depot).stdout + _envoyer(depot).stderr


@POSIX
def test_une_copie_du_hook_d_une_version_precedente_ne_fait_pas_dire_ok(tmp_path, monkeypatch):
    """La copie posée par une version précédente ne dit pas ce qui part : le
    même écart concluait « Lintorn OK » chez qui n'avait pas relancé `lintorn hook`."""
    depot = _projet_js(tmp_path, monkeypatch)
    copie = depot / ".lintorn" / "hooks" / "pre-push"
    texte = copie.read_text(encoding="utf-8")
    assert "export LINTORN_POUSSE LINTORN_LISTE" in texte
    copie.write_text(texte.replace("export LINTORN_POUSSE LINTORN_LISTE",
                                   "export LINTORN_POUSSE"), encoding="utf-8")
    _commiter(depot)

    _ne_dit_pas_ok(_envoyer(depot), "relance `lintorn hook`")


@POSIX
@pytest.mark.parametrize("fichier", ["regles.toml", "config.toml"])
def test_pousser_la_config_de_lintorn_seule_dit_ok(tmp_path, monkeypatch, fichier):
    """« aucun controle ne lit ces fichiers » sur `regles.toml`, que Lintorn
    venait de lire : chaque règle ajoutée finissait « SANS verification complete »."""
    depot = _projet_js(tmp_path, monkeypatch)
    with (depot / ".lintorn" / fichier).open("a", encoding="utf-8") as flux:
        flux.write("\n# une ligne de plus\n")
    _git(depot, "commit", "-qam", "config")

    pousse = _envoyer(depot)

    assert "Lintorn OK" in pousse.stdout + pousse.stderr, pousse.stdout + pousse.stderr


@POSIX
def test_un_tag_pose_avant_les_derniers_commits_n_est_pas_un_ecart(tmp_path, monkeypatch):
    """`git tag v1`, un commit de plus, `push --follow-tags` : le fichier ajouté
    après le tag était dit « pas sur ton disque tel qu'il part »."""
    depot = _projet_js(tmp_path, monkeypatch)
    (depot / "a.js").write_text("const a = 1;\n", encoding="utf-8")
    _git(depot, "add", "a.js")
    _git(depot, "commit", "-qm", "a")
    _git(depot, "tag", "-a", "v1", "-m", "v1")
    (depot / "b.js").write_text("const b = 2;\n", encoding="utf-8")
    _git(depot, "add", "b.js")
    _git(depot, "commit", "-qm", "b")

    pousse = _envoyer(depot, "--follow-tags")

    assert "Lintorn OK" in pousse.stdout + pousse.stderr, pousse.stdout + pousse.stderr


@POSIX
def test_un_chmod_pas_commite_n_est_pas_un_ecart(tmp_path, monkeypatch):
    depot = _projet_js(tmp_path, monkeypatch)
    (depot / "outil.js").write_text("console.log(2);\n", encoding="utf-8")
    _git(depot, "add", "outil.js")
    _git(depot, "commit", "-qm", "outil")
    (depot / "outil.js").chmod(0o755)

    pousse = _envoyer(depot)

    assert "Lintorn OK" in pousse.stdout + pousse.stderr, pousse.stdout + pousse.stderr


def _pousser_dans_un_terminal(depot, reponse: str, delai: float = 90):
    """`git push` dans un VRAI terminal : attend la question, y répond.

    Rend (code de sortie, ce qui s'est affiché AVANT la réponse).
    """
    pid, maitre = pty.fork()
    if pid == 0:
        os.chdir(depot)
        os.execvp("git", ["git", "push", "-q", "origin", "HEAD:refs/heads/main"])
    avant, vu, fin = None, b"", time.monotonic() + delai
    try:
        while time.monotonic() < fin:
            if select.select([maitre], [], [], 0.2)[0]:
                try:
                    bloc = os.read(maitre, 4096)
                except OSError:
                    break
                if not bloc:
                    break
                vu += bloc
            if avant is None and b"Pousser quand meme" in vu:
                avant = vu.decode(errors="replace")
                os.write(maitre, reponse.encode() + b"\n")
        else:
            os.kill(pid, 9)
    finally:
        os.close(maitre)
    return os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]), avant


@POSIX
def test_un_outil_qui_garde_la_sortie_n_empeche_pas_de_voir_la_question(tmp_path, monkeypatch):
    """pre-commit et lefthook gardent la sortie du hook jusqu'à sa fin : la
    question n'apparaissait jamais, et le push attendait une réponse en silence."""
    depot = _projet_js(tmp_path, monkeypatch, branche=False)
    _cohabiter_avec(depot, 'sortie=$(LINTORN 2>&1); code=$?\nprintf "%s\\n" "$sortie"\n'
                           "exit $code\n")
    _commit_fautif(depot)

    code, avant = _pousser_dans_un_terminal(depot, "N")

    assert avant is not None, "la question n'est jamais apparue"
    assert "Des controles BLOQUANTS" in avant
    assert code != 0


@POSIX
def test_o_dans_un_terminal_efface_le_refus_d_un_editeur(tmp_path, monkeypatch):
    """Refusé sans terminal (le bouton d'un éditeur), puis « o » dans un
    terminal : le contrôle accusait le hook de ne pas transmettre le refus."""
    depot = _projet_js(tmp_path, monkeypatch, branche=False)
    _cohabiter_avec(depot, "LINTORN || exit 1\n")
    _commit_fautif(depot)
    assert _envoyer(depot).returncode != 0                  # sans terminal : refusé

    code, avant = _pousser_dans_un_terminal(depot, "o")

    assert avant is not None and code == 0
    resultat = _verdict_du_hook(monkeypatch)
    assert "REFUSE" not in resultat.resume, resultat.resume


@POSIX
def test_sans_terminal_derriere_un_outil_de_hooks_le_refus_dit_comment_passer(
        tmp_path, monkeypatch):
    """Sous Windows, pre-commit ne laisse pas le terminal au hook : le refus
    renvoyait vers un terminal, là où la question ne pouvait déjà pas s'afficher."""
    depot = _projet_js(tmp_path, monkeypatch, branche=False)
    _cohabiter_avec(depot, "LINTORN || exit 1\n")
    _commit_fautif(depot)

    pousse = _envoyer(depot)

    sortie = pousse.stdout + pousse.stderr
    assert pousse.returncode != 0
    assert "LINTORN REFUSE CE PUSH : pas de terminal" in sortie
    assert "ton outil de hooks ne laisse pas Lintorn" in sortie
    assert "git push --no-verify passe alors outre" in sortie


@POSIX
def test_un_refus_sans_la_liste_de_ce_qui_part_dit_que_lintorn_a_lu_le_disque(
        tmp_path, monkeypatch):
    """Sans la liste, le refus peut venir d'un fichier du disque qui ne part pas :
    il ne se donnait pas pour ce qu'il est."""
    depot = _projet_js(tmp_path, monkeypatch, branche=False)
    _cohabiter_avec(depot, "cat > /dev/null\nLINTORN < /dev/null || exit 1\n")
    _commit_fautif(depot)

    pousse = _envoyer(depot)

    assert pousse.returncode != 0
    assert ("Attention : Lintorn a lu ton disque, pas ce que tu pousses"
            in pousse.stdout + pousse.stderr), pousse.stdout + pousse.stderr


@POSIX
def test_deux_branches_qui_envoient_le_meme_fichier_le_nomment_une_fois(tmp_path, monkeypatch):
    depot = _projet_js(tmp_path, monkeypatch)
    (depot / "style.css").write_text("a { color: red; }\n", encoding="utf-8")
    _git(depot, "add", "style.css")
    _git(depot, "commit", "-qm", "style")
    _git(depot, "branch", "copie")

    pousse = _git(depot, "push", "-q", "origin", "HEAD:refs/heads/main", "copie")

    sortie = pousse.stdout + pousse.stderr
    assert "aucun controle ne lit ces fichiers : style.css" in sortie, sortie
    assert "style.css, style.css" not in sortie


@POSIX
def test_un_nom_accentue_d_une_branche_neuve_est_compare(tmp_path, monkeypatch):
    """Sans `core.quotePath=false`, git rend « \\303\\251.js » : un nom qui ne
    désigne aucun fichier, donc rien à comparer, et « Lintorn OK »."""
    depot = _projet_js(tmp_path, monkeypatch, pousser=False)
    _commit_fautif(depot, "été.js")
    _corrige_sans_commiter(depot, "été.js")

    _ne_dit_pas_ok(_envoyer(depot), "été.js")


@POSIX
def test_les_tests_passent_aussi_lances_par_un_push(tmp_path):
    """Lancés par le hook de ce dépôt (`tests = true`), les tests héritaient de ce
    qu'il exporte : un test échouait, et bloquait le push sans que rien soit cassé."""
    du_hook = {"LINTORN_HOOK": "1", "LINTORN_LISTE": "complete", "LINTORN_TERMINAL": "0",
               "LINTORN_DISTANT": "origin", "LINTORN_POUSSE": "", "PRE_COMMIT_TO_REF": "HEAD"}
    cible = "test_une_copie_du_hook_d_une_version_precedente_ne_fait_pas_dire_ok"

    fini = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--basetemp", str(tmp_path / "base"), f"{__file__}::{cible}"],
        cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=300,
        env={**os.environ, **du_hook, "PYTHONDONTWRITEBYTECODE": "1"}, check=False)

    assert fini.returncode == 0, fini.stdout + fini.stderr


@POSIX
def test_le_rapport_du_push_survit_a_la_commande_suivante(tmp_path, monkeypatch):
    """Un seul rapport : le `lintorn` lancé pour comprendre un refus écrasait
    ce que le push venait de dire."""
    depot = _projet_js(tmp_path, monkeypatch)
    _commit_fautif(depot)
    lintorn_dir = depot / ".lintorn"

    pousse = _envoyer(depot)

    sortie = pousse.stdout + pousse.stderr
    assert pousse.returncode != 0
    assert "Le rapport de ce push : .lintorn/rapport-push.md" in sortie
    assert "Detail complet : .lintorn/rapport-push.md" in sortie
    du_push = (lintorn_dir / "rapport-push.md").read_text(encoding="utf-8")
    assert "**pendant un push**" in du_push and "Pas eval" in du_push

    (depot / "f.js").write_text("x = 1;\n", encoding="utf-8")
    commande = subprocess.run([sys.executable, "-m", "lintorn", "rapide"], cwd=depot,
                              capture_output=True, text=True, timeout=120, check=False)

    assert "Le rapport de Lintorn : .lintorn/rapport.md" in commande.stdout, commande.stdout
    assert "**hors push**" in (lintorn_dir / "rapport.md").read_text(encoding="utf-8")
    assert (lintorn_dir / "rapport-push.md").read_text(encoding="utf-8") == du_push


# ─────────────────────────────────────────────────────────────────────────────
# Un monorepo à deux Lintorn : git ne lance qu'un hook, qui lance l'autre
# ─────────────────────────────────────────────────────────────────────────────
def _monorepo(tmp_path, monkeypatch):
    """`api/` et `web/`, chacun son Lintorn et sa règle bloquante, poussés une fois."""
    depot = _depot(tmp_path, monkeypatch)
    _lintorn_dans_le_path(tmp_path, monkeypatch)
    for sous in ("api", "web"):
        (depot / sous / ".lintorn").mkdir(parents=True)
        (depot / sous / "app.js").write_text("console.log(1);\n", encoding="utf-8")
        (depot / sous / "README.md").write_text("# P\n\nLe code vit dans `app.js`.\n",
                                                encoding="utf-8")
        (depot / sous / ".lintorn" / "config.toml").write_text("", encoding="utf-8")
        (depot / sous / ".lintorn" / "regles.toml").write_text(_REGLE_EVAL, encoding="utf-8")
    _git(depot, "add", "-A")
    _git(depot, "commit", "-qm", "init")
    assert _envoyer(depot).returncode == 0
    return depot


def _lintorn(depot, sous, *arguments):
    """Lintorn lancé pour un sous-projet, comme on le tape depuis le sommet du dépôt."""
    return subprocess.run([sys.executable, "-m", "lintorn", *arguments], cwd=depot,
                          env={**os.environ, "LINTORN_RACINE": str(depot / sous)},
                          capture_output=True, text=True, timeout=120, check=False)


@POSIX
def test_le_hook_d_un_sous_projet_lance_celui_de_l_autre(tmp_path, monkeypatch):
    """La ligne conseillée vivait dans la copie du hook d'`api/` : `lintorn hook`
    la réécrivait, et l'`eval` de `web/` partait avec « Lintorn OK »."""
    depot = _monorepo(tmp_path, monkeypatch)
    assert _lintorn(depot, "api", "hook").returncode == 0
    pour_web = _lintorn(depot, "web", "hook")
    assert pour_web.returncode == 0, pour_web.stdout
    assert "il lance aussi celui-ci" in pour_web.stdout
    _commit_fautif(depot, "web/f.js")

    for _ in range(2):                          # avant, puis après une mise à jour d'api
        pousse = _envoyer(depot)
        assert pousse.returncode != 0, pousse.stdout + pousse.stderr
        assert "controle avant push : web/" in pousse.stdout + pousse.stderr
        assert _lintorn(depot, "api", "hook").returncode == 0

    _corrige_sans_commiter(depot, "web/f.js")
    _git(depot, "commit", "-qam", "corrige")
    pousse = _envoyer(depot, heure=int(time.time()) + 2)
    sortie = pousse.stdout + pousse.stderr
    assert pousse.returncode == 0, sortie
    assert "controle avant push : api/" in sortie and "controle avant push : web/" in sortie
    assert sortie.count("Lintorn OK") == 2
    assert "lance par le hook Lintorn de api/" in _lintorn(depot, "web", "rapide").stdout


def _worktree_du_monorepo(tmp_path, monkeypatch):
    """Le monorepo, puis un worktree où chaque sous-projet a posé son hook."""
    depot = _monorepo(tmp_path, monkeypatch)
    annexe = tmp_path.parent / f"{tmp_path.name}-annexe"
    _git(depot, "worktree", "add", "-q", str(annexe), "-b", "annexe")
    for sous in ("api", "web"):
        assert _lintorn(annexe, sous, "hook").returncode == 0
    return annexe


def _pousser_le_worktree(annexe, heure=None):
    env = {**os.environ, **({"GIT_COMMITTER_DATE": f"@{heure} +0000"} if heure else {})}
    return subprocess.run(["git", "push", "-q", "origin", "HEAD:refs/heads/annexe"], cwd=annexe,
                          env=env, capture_output=True, text=True, timeout=120,
                          start_new_session=True, check=False)


@POSIX
def test_depuis_un_worktree_le_hook_d_un_sous_projet_lance_encore_son_voisin(tmp_path, monkeypatch):
    """Dans un worktree, git donne GIT_DIR au hook sans GIT_WORK_TREE : git prenait `api/`
    pour la racine du dépôt, `web/` disparaissait, et son `eval` partait."""
    annexe = _worktree_du_monorepo(tmp_path, monkeypatch)
    _commit_fautif(annexe, "web/f.js")

    refuse = _pousser_le_worktree(annexe)
    _corrige_sans_commiter(annexe, "web/f.js")
    _git(annexe, "commit", "-qam", "corrige")
    accepte = _pousser_le_worktree(annexe, heure=int(time.time()) + 2)

    assert refuse.returncode != 0, refuse.stdout + refuse.stderr
    assert "controle avant push : web/" in refuse.stdout + refuse.stderr
    sortie = accepte.stdout + accepte.stderr
    assert accepte.returncode == 0, sortie
    assert sortie.count("Lintorn OK") == 2, sortie
    assert "NON BRANCHE" not in sortie and "pas sur ton disque" not in sortie


@POSIX
def test_lintorn_appele_sans_le_hook_avec_le_git_dir_d_un_worktree_lit_le_bon_depot(tmp_path,
                                                                                    monkeypatch):
    """Appelé par pre-commit ou un script, Lintorn reçoit GIT_DIR tel quel : il disait le
    hook « NON BRANCHE » et comparait ses chemins depuis la mauvaise racine."""
    annexe = _worktree_du_monorepo(tmp_path, monkeypatch)
    git_dir = _git(annexe, "rev-parse", "--absolute-git-dir").stdout.strip()

    sortie = subprocess.run([sys.executable, "-m", "lintorn", "rapide"], cwd=annexe / "api",
                            env={**os.environ, "GIT_DIR": git_dir,
                                 "LINTORN_RACINE": str(annexe / "api")},
                            capture_output=True, text=True, timeout=120, check=False).stdout

    hook = next(ligne for ligne in sortie.splitlines() if "Hook pre-push (Lintorn)" in ligne)
    assert "NON BRANCHE" not in hook, hook
    assert "branche ici" in hook, "le dossier principal n'a pas sa copie : c'est la seule reserve"


@POSIX
def test_un_hook_voisin_d_une_version_precedente_est_signale(tmp_path, monkeypatch):
    depot = _monorepo(tmp_path, monkeypatch)
    assert _lintorn(depot, "api", "hook").returncode == 0
    _un_hook(depot / "api" / ".lintorn" / "hooks", "pre-push",
             "#!/bin/sh\n# un hook Lintorn d'avant\nexit 0\n")

    pour_web = _lintorn(depot, "web", "hook")

    assert pour_web.returncode == 1
    assert "LINTORN_RACINE=api lintorn hook" in pour_web.stdout
    controle = _lintorn(depot, "web", "rapide").stdout
    assert "ne lance pas celui-ci" in controle, controle


@POSIX
def test_un_sous_projet_que_git_ignore_n_est_pas_dit_couvert(tmp_path, monkeypatch):
    depot = _monorepo(tmp_path, monkeypatch)
    assert _lintorn(depot, "api", "hook").returncode == 0
    (depot / ".gitignore").write_text("web/.lintorn/\n", encoding="utf-8")
    _git(depot, "rm", "-rq", "--cached", "web/.lintorn")

    pour_web = _lintorn(depot, "web", "hook")

    assert pour_web.returncode == 1
    assert "ignore par git" in pour_web.stdout
    assert "ignore par git" in _lintorn(depot, "web", "rapide").stdout


def test_un_chemin_du_meme_depot_ne_porte_pas_le_nom_de_la_machine(tmp_path, monkeypatch):
    """Le conseil d'un sous-projet de monorepo affichait `/home/<utilisateur>/…/.husky/pre-push`."""
    monkeypatch.setattr(config, "SOMMET_GIT", tmp_path)
    monkeypatch.setattr(config, "RACINE", tmp_path / "api")

    assert lintorn.chemins.relatif(tmp_path / ".husky" / "pre-push") == "../.husky/pre-push"
    assert lintorn.chemins.relatif(tmp_path.parent / "ailleurs") == str(tmp_path.parent / "ailleurs")


@POSIX
def test_juste_apres_une_mise_a_jour_le_dernier_push_n_est_pas_accuse(tmp_path, monkeypatch):
    """La 0.5.0 vérifiait sans noter ses passages : sitôt Lintorn mis à jour, le
    contrôle disait parti SANS Lintorn le push qu'elle venait de vérifier."""
    depot = _projet_js(tmp_path, monkeypatch, pousser=False)
    copie = depot / ".lintorn" / "hooks" / "pre-push"
    copie.write_text(copie.read_text(encoding="utf-8") + "# une version precedente\n",
                     encoding="utf-8")
    assert _envoyer(depot, "--no-verify", heure=int(time.time()) + 2).returncode == 0

    resultat = _verdict_du_hook(monkeypatch)

    assert resultat.statut == "VERIF", resultat.resume
    assert "PERIME" in resultat.resume


@POSIX
def test_un_bloc_pre_commit_sans_verbose_est_signale(tmp_path, monkeypatch):
    """Copié avant la 0.6.0, le bloc n'a pas `verbose: true` : « Push autorise SANS
    verification complete » devenait « Passed », et rien ne le disait."""
    depot = _projet_js(tmp_path, monkeypatch, branche=False)
    _cohabiter_avec(depot, "# File generated by pre-commit: https://pre-commit.com\n"
                           "LINTORN < /dev/null || exit 1\n")
    bloc = lintorn.controles.outillage.hook_git.conseil(
        lintorn.controles.outillage.hook_git.autres_hooks()).ajout
    config_pc = depot / ".pre-commit-config.yaml"
    config_pc.write_text("repos:\n" + bloc.replace("        verbose: true", "") + "\n",
                         encoding="utf-8")
    _commiter(depot)
    assert _envoyer(depot).returncode == 0

    resultat = _verdict_du_hook(monkeypatch)
    assert resultat.statut == "VERIF" and "verbose: true" in resultat.resume, resultat.resume

    config_pc.write_text("repos:\n" + bloc + "\n", encoding="utf-8")
    assert _verdict_du_hook(monkeypatch).statut == "OK"


@POSIX
def test_apres_un_no_verify_lintorn_hook_n_accuse_pas_des_hooks_qui_ne_l_appellent_pas(
        tmp_path, monkeypatch, capsys):
    """Refus en mode direct, `--no-verify`, puis `core.hooksPath` retiré : il disait
    « Ton hook appelle Lintorn » d'un pre-commit qui ne l'appelait pas."""
    depot = _projet_js(tmp_path, monkeypatch)
    _commit_fautif(depot)
    assert _envoyer(depot).returncode != 0
    assert _envoyer(depot, "--no-verify").returncode == 0
    _git(depot, "config", "--unset", "core.hooksPath")
    _un_hook(depot / ".git" / "hooks", "pre-commit")
    capsys.readouterr()

    assert lintorn.commandes.hook.installer_hook() == 1

    sortie = capsys.readouterr().out
    assert "Ton hook appelle Lintorn" not in sortie
    assert "--no-verify" in sortie


@POSIX
def test_reposer_le_meme_hook_n_efface_pas_l_alerte(tmp_path, monkeypatch):
    """La date de la copie est celle de la pose : la réécrire à l'identique effaçait
    « parti SANS Lintorn », alors que l'éditeur ne trouvait toujours pas Lintorn."""
    depot = _projet_js(tmp_path, monkeypatch, pousser=False)
    maintenant = int(time.time())
    os.utime(depot / ".lintorn" / "hooks" / "pre-push", (maintenant - 100, maintenant - 100))
    _commit_fautif(depot)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert _envoyer(depot, heure=maintenant - 50).returncode == 0
    assert _verdict_du_hook(monkeypatch).statut == "ALERTE"

    assert lintorn.commandes.hook.installer_hook() == 0

    assert "parti SANS Lintorn" in _verdict_du_hook(monkeypatch).resume


@POSIX
def test_sans_journal_des_push_le_controle_ne_dit_pas_ok(tmp_path, monkeypatch):
    """`core.logAllRefUpdates = false` : un push parti sans Lintorn ne se voyait plus."""
    depot = _projet_js(tmp_path, monkeypatch)
    _git(depot, "config", "core.logAllRefUpdates", "false")
    _commit_fautif(depot)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert _envoyer(depot, heure=int(time.time()) + 2).returncode == 0

    resultat = _verdict_du_hook(monkeypatch)

    assert resultat.statut == "VERIF", resultat.resume
    assert "logAllRefUpdates" in resultat.resume


def test_les_fichiers_tapes_depuis_un_sous_dossier_sont_ceux_du_sous_dossier(tmp_path, monkeypatch):
    """`lintorn --fichiers f.js` lancé dans `sous/` : le focus cherchait `f.js` à la racine,
    et disait « aucun defaut connu » d'un `sous/f.js` fautif."""
    depot = _depot(tmp_path, monkeypatch)
    (depot / "sous").mkdir()
    (depot / "sous" / "f.js").write_text('x = eval("1");\n', encoding="utf-8")
    (depot / ".lintorn").mkdir()
    (depot / ".lintorn" / "config.toml").write_text("", encoding="utf-8")
    (depot / ".lintorn" / "regles.toml").write_text(_REGLE_EVAL, encoding="utf-8")

    fini = subprocess.run([sys.executable, "-m", "lintorn", "--fichiers", "f.js"],
                          cwd=depot / "sous", capture_output=True, text=True, timeout=120,
                          check=False)

    ligne = next(x for x in fini.stdout.splitlines() if "Defauts dans les fichiers" in x)
    assert "[ !! ]" in ligne, ligne
