"""Doc vs code, règles énoncées, genre des documents, fraîcheur de la mémoire."""

import json
import os
import re
import subprocess
import sys
import tomllib
import unicodedata
from pathlib import Path

import pytest
from aides import _config_doc_ia

import lintorn.commandes
import lintorn.confiance
import lintorn.controles
import lintorn.outils
import lintorn.rapport
from lintorn import config


# ─────────────────────────────────────────────────────────────────────────────
# Le tri des `backticks` du contrôle doc
# ─────────────────────────────────────────────────────────────────────────────
def test_est_un_chemin_accepte_de_vrais_chemins():
    for token in ("services/api.ts", "mixins/models.py", "ARCHITECTURE.md",
                  "pages/Planning/PlanningPrefsContext.tsx", "fixtures/demo"):
        assert lintorn.controles.projet.chemins_cites.est_un_chemin(token), f"{token} devrait etre vu comme un chemin"


def test_est_un_chemin_rejette_ce_qui_est_du_code():
    """Chacun de ces cas a produit un VRAI faux positif avant d'être filtré."""
    for token in (
        "tsc --noEmit",            # une commande
        "Facture.emettre()",       # un appel de méthode
        "var(--bg)",               # du CSS
        "/api/archives/",          # une route d'API, pas un fichier
        ".../debloquer",           # un chemin tronqué dans une phrase
        ".tsx",                    # une extension citée seule
        "https://exemple.fr/x.md",  # une URL
        "STATUT_CHOICES",          # un nom de constante
    ):
        assert not lintorn.controles.projet.chemins_cites.est_un_chemin(token), (
            f"{token} ne devrait PAS etre vu comme un chemin")


def test_existe_retrouve_un_fichier_par_son_nom_seul():
    index = {"ARCHITECTURE.md", "api.ts"}

    assert lintorn.controles.projet.chemins_cites.existe("ARCHITECTURE.md", index)
    assert not lintorn.controles.projet.chemins_cites.existe("FICHIER_QUI_NEXISTE_PAS.md", index)


def test_existe_ignore_le_numero_de_ligne():
    """La doc cite parfois `factures/models.py:17-34`."""
    index = {"models.py"}

    assert lintorn.controles.projet.chemins_cites.existe("models.py:17-34", index)
    assert lintorn.controles.projet.chemins_cites.existe("models.py:151", index)


# ─────────────────────────────────────────────────────────────────────────────
# Le marqueur `lintorn:prospectif`
# ─────────────────────────────────────────────────────────────────────────────
_FANTOME = "`api/fichier_qui_nexiste_vraiment_pas.py`"


def test_un_document_normal_bloque_sur_un_chemin_faux(tmp_path):
    doc = tmp_path / "note.md"
    doc.write_text(f"Le pivot est {_FANTOME}.", encoding="utf-8")

    resultat = lintorn.controles.projet.doc_vs_code._verifier_documents("t", [doc], bloquant_possible=True)

    assert resultat.statut == "ALERTE"
    assert resultat.bloquant is True


def test_un_document_prospectif_informe_sans_bloquer(tmp_path):
    """Une roadmap ou un ADR cite légitimement des fichiers à créer — ou
    supprimés, cités justement parce qu'ils ont disparu. Le contrôle doit les
    LISTER sans interdire le push."""
    doc = tmp_path / "conception.md"
    doc.write_text(f"<!-- lintorn:prospectif -->\n\nÀ écrire : {_FANTOME}.", encoding="utf-8")

    resultat = lintorn.controles.projet.doc_vs_code._verifier_documents("t", [doc], bloquant_possible=True)

    assert resultat.statut == "VERIF"
    assert resultat.bloquant is False
    assert "fichier_qui_nexiste_vraiment_pas.py" in resultat.detail, (
        "le chemin doit rester VISIBLE : on informe, on n'interdit pas"
    )


# ─────────────────────────────────────────────────────────────────────────────
# La fraîcheur de la mémoire (git)
# ─────────────────────────────────────────────────────────────────────────────
def test_un_nom_de_fichier_nu_devient_un_pathspec_glob():
    """Une mémoire écrit « le template `OrPdfTemplate.tsx` », jamais son chemin
    complet. La première version ne résolvait que les chemins complets : elle
    trouvait 0 fichier, donc 0 commit, donc un contrôle vert à jamais."""
    assert lintorn.controles.projet.fraicheur_memoire._pathspecs_cites(
        "le template `OrPdfTemplate.tsx` fait foi"
    ) == [":(glob)**/OrPdfTemplate.tsx"]


def test_un_chemin_complet_devient_repo_relatif(tmp_path, monkeypatch):
    """`_pathspecs_cites` VÉRIFIE que le fichier existe avant de le retenir.

    Le test se fabrique donc son propre dépôt : écrire un chemin en dur le
    rendrait dépendant de l'arborescence du projet audité, et il basculerait
    au vert ou au rouge selon la machine — sans rien prouver.
    """
    (tmp_path / "api" / "factures").mkdir(parents=True)
    (tmp_path / "api" / "factures" / "models.py").touch()
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "RACINES_RESOLUTION", [tmp_path])

    specs = lintorn.controles.projet.fraicheur_memoire._pathspecs_cites("voir `api/factures/models.py`")

    assert "api/factures/models.py" in specs


def test_les_blocs_de_code_ne_sont_pas_des_citations():
    assert lintorn.controles.projet.fraicheur_memoire._pathspecs_cites("```\n`models.py`\n```\nrien d'autre") == []


def test_git_muet_ne_se_confond_pas_avec_rien_n_a_bouge():
    """LE bug du 12/08/2026. `--format=<chaîne libre>` est refusé par git
    (« invalid --pretty format ») : il sortait en 128, l'échec était avalé, et
    la fonction renvoyait « 0 commit » — donc un contrôle VERT sur une mémoire
    périmée. `None` veut dire « je n'ai pas pu regarder », `[]` veut dire
    « rien n'a bougé ». Les confondre est exactement la maladie soignée ici."""
    nb, touches = lintorn.controles.projet.fraicheur_memoire._commits_depuis(
        "2020-01-01", [":(magie_qui_nexiste_pas)x"])

    assert touches is None, "git en panne doit renvoyer None, jamais une liste vide"
    assert nb == 0


@pytest.mark.skipif(
    config.BACKEND is None,
    reason="exige un vrai projet Django : ni pertinent ni concluant sans lui",
)
def test_git_retrouve_un_vrai_commit():
    """Contre-épreuve : sur un fichier réel du dépôt, git DOIT répondre.
    Si ce test casse, c'est le format de la commande qui est reparti en vrille."""
    nb, touches = lintorn.controles.projet.fraicheur_memoire._commits_depuis("2020-01-01", [":(glob)**/CLAUDE.md"])

    assert touches is not None, "git n'a pas repondu → le controle serait faussement vert"
    assert nb > 0
    assert any("CLAUDE.md" in fichier for fichier in touches)


def test_la_date_de_verification_doit_etre_une_vraie_date():
    assert lintorn.controles.projet.fraicheur_memoire._RX_VERIFIE_LE.search("---\nname: x\nverifie_le: 2026-08-12\n---")
    assert not lintorn.controles.projet.fraicheur_memoire._RX_VERIFIE_LE.search("verifie_le: bientot")


# ─────────────────────────────────────────────────────────────────────────────
# Les règles ÉNONCÉES dans le fichier d'instructions IA
# ─────────────────────────────────────────────────────────────────────────────


def _regles_enoncees(tmp_path, monkeypatch, texte, regles=()):
    _config_doc_ia(tmp_path, monkeypatch, texte, regles)
    return lintorn.controles.projet.regles_enoncees.controle_regles_declarees()


def test_la_prose_narrative_n_est_pas_prise_pour_une_regle(tmp_path, monkeypatch):
    """Une note qui RACONTE n'énonce pas une règle, même en disant « jamais ».

    Sans ce filtre de forme, un vrai projet remontait 92 lignes — notes
    d'architecture et comptes rendus d'audit compris. Un contrôle qui crie
    92 fois est un contrôle qu'on apprend à ne plus lire.
    """
    texte = (
        "- Un devis `VALIDE` n'expire jamais : c'est un engagement signe.\n"
        "\n"
        "| Axios partage | jamais d'`axios.create()` ailleurs |\n"
    )
    resultat = _regles_enoncees(tmp_path, monkeypatch, texte)

    assert "1 enoncee(s)" in resultat.resume, (
        "seule la ligne de TABLEAU est une regle ; la puce narrative n'en est pas une"
    )


def test_une_regle_pourvue_d_un_motif_sort_du_rapport(tmp_path, monkeypatch):
    texte = "| Axios partage | jamais d'`axios.create()` ailleurs |\n"
    regle = {"nom": "axios hors de api.ts", "motif": re.compile(r"axios\.create\(")}

    resultat = _regles_enoncees(tmp_path, monkeypatch, texte, [regle])

    assert resultat.statut == "OK"


def test_la_phrase_de_la_regle_ne_vaut_pas_couverture(tmp_path, monkeypatch):
    """Le champ `regle` est de la prose : il ne prouve RIEN sur la détection.

    Il cite souvent la doc (« CLAUDE.md : … »). Une règle parlant de `.claude/`
    s'y appariait alors par coïncidence de sous-chaîne — « claude » ⊂
    « claudemd » — et disparaissait du rapport. Un faux « couvert » est pire
    qu'un faux trou : il éteint l'alerte sur une règle que rien ne surveille.
    """
    texte = "| Fichier versionne | jamais de chemin absolu ; `.claude/` est ignore |\n"
    regle = {
        "nom": "axios.create() hors de services/api.ts",
        "regle": "CLAUDE.md : une SEULE instance axios dans tout le projet",
        "motif": re.compile(r"axios\.create\("),
    }

    resultat = _regles_enoncees(tmp_path, monkeypatch, texte, [regle])

    assert "1 SANS controle" in resultat.resume


def test_ce_controle_ne_bloque_jamais_un_push(tmp_path, monkeypatch):
    """Documenter une intention ne doit pas interdire de pousser : ce serait
    punir exactement le geste qu'on veut encourager."""
    texte = "| Statuts | **Source unique** : `StatutBadge.tsx`. Jamais ailleurs |\n"

    resultat = _regles_enoncees(tmp_path, monkeypatch, texte)

    assert resultat.statut == "VERIF"
    assert resultat.bloquant is False
    assert resultat.en_echec is False


# ─────────────────────────────────────────────────────────────────────────────
# Les esquisses de `[[regles]]` tirées de la doc
# ─────────────────────────────────────────────────────────────────────────────
_TABLE = "| Axios partage | jamais d'`axios.create()` hors de `services/api.ts` |\n"


def test_une_esquisse_est_toujours_inerte(tmp_path, monkeypatch):
    """`re.compile("")` réussit, et un motif vide matche PARTOUT.

    Une esquisse laissée active compterait des milliers de fausses
    infractions dès le premier audit — et tuerait la confiance dans l'outil
    avant même que l'utilisateur ait compris ce qu'il regardait. Tant que
    l'humain n'y a pas écrit son motif, ça reste du commentaire.
    """
    _config_doc_ia(tmp_path, monkeypatch, _TABLE)

    esquisses = lintorn.commandes.regles.esquisses_regles()

    assert esquisses, "la ligne de tableau doit produire une esquisse"
    vivantes = [ligne for ligne in esquisses
                if ligne.strip() and not ligne.startswith("#")]
    assert vivantes == [], f"une esquisse ne doit JAMAIS etre active : {vivantes}"


def test_le_champ_source_couvre_exactement_sa_ligne(tmp_path, monkeypatch):
    """Le lien explicite l'emporte sur l'heuristique de jetons.

    Ici, ni le nom ni le motif de la règle ne rappellent la ligne de doc :
    seul `source` fait le lien. C'est ce qui permet d'arrêter de recopier la
    phrase dans le config.toml — donc de la laisser dériver.
    """
    regle = {"nom": "sans aucun rapport", "source": "CLAUDE.md:1",
             "motif": re.compile(r"zzz")}
    _config_doc_ia(tmp_path, monkeypatch, _TABLE, [regle])

    assert lintorn.controles.projet.regles_enoncees.regles_sans_controle() == []


def test_une_esquisse_deja_presente_n_est_pas_reproposee(tmp_path, monkeypatch):
    """`--esquisser-regles` se relance : sans garde, deux passages
    empileraient deux fois les mêmes brouillons."""
    _config_doc_ia(tmp_path, monkeypatch, _TABLE)

    premiere = lintorn.commandes.regles.esquisses_regles()
    seconde = lintorn.commandes.regles.esquisses_regles("\n".join(premiere))

    assert premiere
    assert seconde == []


def test_une_esquisse_se_declare_hors_portee_en_une_ligne(tmp_path, monkeypatch):
    """Déclarer `hors_portee` une règle qu'aucun motif ne peut exprimer
    demandait de réécrire son bloc à la main. L'esquisse le prépare : on la
    décommente, on écrit la raison, et la règle a sa réponse."""
    _config_doc_ia(tmp_path, monkeypatch, _TABLE)
    bloc = "\n".join(ligne.removeprefix("# ")
                     for ligne in lintorn.commandes.regles.esquisses_regles()
                     if ligne.startswith(("# [[regles]]", "# source", "# nom", "# racine",
                                          "# suffixes", "# motif", "# hors_portee", "# bloquant")))
    bloc = bloc.replace("hors_portee = ''", "hors_portee = 'une convention de revue'")
    monkeypatch.setattr(config, "_regles_brutes", lambda: tomllib.loads(bloc)["regles"])
    regles, hors_portee = config._regles_du_projet()
    monkeypatch.setattr(config, "REGLES_MAISON", regles)
    monkeypatch.setattr(config, "HORS_PORTEE", hors_portee)

    resultat = lintorn.controles.projet.regles_enoncees.controle_regles_declarees()

    assert resultat.statut == "OK", resultat.resume
    assert "1 hors de portee" in resultat.resume


def test_une_esquisse_decommentee_reste_un_toml_lisible(tmp_path, monkeypatch):
    """Le nom gardait le `\\` de la phrase : `\\U` d'un chemin Windows, `\\d` d'une
    regex. Décommenté, le brouillon rendait regles.toml illisible, et toutes les
    règles du fichier tombaient avec lui."""
    _config_doc_ia(tmp_path, monkeypatch,
                   "- Never hardcode `C:\\Users` paths\n| Les \\d nus | jamais `\\d` seul |\n")
    bloc = "\n".join(ligne.removeprefix("# ")
                     for ligne in lintorn.commandes.regles.esquisses_regles()
                     if ligne.startswith(("# [[regles]]", "# source", "# nom", "# motif")))

    regles = tomllib.loads(bloc.replace("motif    = ''", "motif    = 'zzz'"))["regles"]

    assert [regle["nom"] for regle in regles] == ["Never hardcode C:\\Users paths", "Les \\d nus"]


def test_une_table_qui_vise_regles_sans_l_ecrire_est_reperee_avec_sa_correction():
    trois = chr(34) * 3
    texte = "\n".join([
        "[[regle]]", "[[Regles]] # note", "[regles]", "[[rules]]", "[[régles]]",
        "[[regles]]", "[[hors_portee]]", "[controles]", f"x = {trois}", "[[regle]]", trois,
        "[tool.lintorn.regles]"])

    corrections = lintorn.config.tables_mal_nommees(texte)

    assert [(numero, corrigee) for numero, _, corrigee, _ in corrections] == [
        (1, "[[regles]]"), (2, "[[regles]] # note"), (3, "[[regles]]"), (4, "[[regles]]"),
        (5, "[[regles]]")], "ni la bonne ecriture, ni une autre table, ni du texte entre guillemets"


def _corriger(tmp_path, monkeypatch, capsys, terminal: bool, reponse: str = "o"):
    """`lintorn corrige` sur un regles.toml et un config.toml pleins de fautes de frappe."""
    lintorn_dir = tmp_path / ".lintorn"
    lintorn_dir.mkdir()
    regles = lintorn_dir / "regles.toml"
    regles.write_bytes(b"[[regle]] # a corriger\r\nnom = 'a'\r\nbloquan = true\r\n"
                       b"[[hors_portee]]\r\nbloquan = true\r\n")
    reglages = lintorn_dir / "config.toml"
    reglages.write_text("[controle]\nfaiiles = true\n", encoding="utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "DOSSIER_LINTORN", lintorn_dir)
    monkeypatch.setattr(config, "FICHIER_REGLES", regles)
    monkeypatch.setattr(lintorn.confiance, "terminal", lambda: terminal)
    monkeypatch.setattr("builtins.input", lambda question: reponse)
    code = lintorn.commandes.corrige.corriger()
    return code, regles.read_bytes(), reglages.read_text(encoding="utf-8"), capsys.readouterr().out


def test_lintorn_corrige_repare_les_fautes_sures_si_on_dit_oui(tmp_path, monkeypatch, capsys):
    """Tables et clés, dans les deux fichiers, chaque ligne montrée avant ; ses fins de
    ligne et son commentaire gardés. `[[hors_portee]]` n'est pas une faute de frappe."""
    code, regles, reglages, sortie = _corriger(tmp_path, monkeypatch, capsys, terminal=True)

    assert code == 0
    assert regles == (b"[[regles]] # a corriger\r\nnom = 'a'\r\nbloquant = true\r\n"
                      b"[[hors_portee]]\r\nbloquan = true\r\n")
    assert reglages == "[controles]\nfailles = true\n"
    assert "ligne 1 : [[regle]] # a corriger  ->  [[regles]] # a corriger" in sortie
    assert "Corrige : 4 ligne(s)" in sortie


@pytest.mark.parametrize("terminal, reponse", [(True, ""), (False, "o")], ids=["non", "sans-terminal"])
def test_lintorn_corrige_ne_touche_a_rien_sans_un_oui(tmp_path, monkeypatch, capsys, terminal,
                                                      reponse):
    """Les fichiers sont versionnés, et une correction devinée peut être fausse."""
    code, regles, reglages, sortie = _corriger(tmp_path, monkeypatch, capsys, terminal, reponse)

    assert code == 1
    assert regles.startswith(b"[[regle]] # a corriger\r\n") and reglages.startswith("[controle]")
    assert "rien n'est corrige" in sortie.lower()


def test_lintorn_regles_ne_corrige_plus_il_renvoie_vers_lintorn_corrige(tmp_path, monkeypatch,
                                                                       capsys):
    """Il ajoute des brouillons : réparer est le métier de `lintorn corrige`."""
    _config_doc_ia(tmp_path, monkeypatch, _TABLE)
    regles = tmp_path / ".lintorn" / "regles.toml"
    regles.parent.mkdir()
    regles.write_text("[[regle]]\nnom = 'a'\n", encoding="utf-8")
    monkeypatch.setattr(config, "FICHIER_REGLES", regles)

    lintorn.commandes.regles.esquisser_regles()

    assert regles.read_text(encoding="utf-8").startswith("[[regle]]\n")
    assert "(ligne 1) : lintorn corrige" in capsys.readouterr().out


# ─────────────────────────────────────────────────────────────────────────────
# `exemple` et `lintorn regles --test` : une règle se prouve sur un cas fautif
# ─────────────────────────────────────────────────────────────────────────────
def _regles_du_texte(tmp_path, monkeypatch, texte: str):
    """Les règles et les soucis que le VRAI chargeur tire de ce regles.toml."""
    (tmp_path / "a.js").write_text('x = eval("1");\n', encoding="utf-8")
    monkeypatch.setattr(config, "RACINE", tmp_path)
    monkeypatch.setattr(config, "SOUCIS_CONFIG", [])
    monkeypatch.setattr(config, "hors_gitignore", lambda chemins: chemins)
    monkeypatch.setattr(config, "_regles_brutes", lambda: tomllib.loads(texte)["regles"])
    regles, hors_portee = config._regles_du_projet()
    monkeypatch.setattr(config, "REGLES_MAISON", regles)
    monkeypatch.setattr(config, "HORS_PORTEE", hors_portee)
    return regles


def _regle(nom: str, sens: str, motif: str, exemple: str) -> str:
    return (f"[[regles]]\nnom = '{nom}'\nracine = '.'\nsuffixes = ['.js']\n"
            f"{sens} = '{motif}'\nexemple = '{exemple}'\n")


@pytest.mark.parametrize("sens, motif, exemple, attrape", [
    ("motif", r"eval\(", 'y = eval("2")', True),
    ("motif", r"evaI\(", 'y = eval("2")', False),             # une faute dans le motif
    ("motif_requis", "SPDX", "rien de requis", True),
    ("motif_requis", "SPDX", "SPDX-License: MIT", False),      # l'exemple n'est pas fautif
])
def test_une_regle_qui_ne_trouve_pas_son_exemple_est_signalee(tmp_path, monkeypatch, sens, motif,
                                                              exemple, attrape):
    """Une règle morte et une règle tenue disent toutes deux « 0 » : l'exemple les sépare,
    à chaque lancement."""
    regles = _regles_du_texte(tmp_path, monkeypatch, _regle("r", sens, motif, exemple))

    assert len(regles) == 1, "la regle reste chargee : elle peut encore trouver autre chose"
    assert bool(config.SOUCIS_CONFIG) is not attrape, config.SOUCIS_CONFIG
    if not attrape:
        assert "la regle ne protege peut-etre rien" in config.SOUCIS_CONFIG[0]


def test_lintorn_regles_test_juge_chaque_regle(tmp_path, monkeypatch, capsys):
    _regles_du_texte(tmp_path, monkeypatch, "\n".join([
        _regle("Marche", "motif", r"eval\(", "eval(2)"),
        _regle("Rate", "motif", r"evaI\(", "eval(2)"),
        "[[regles]]\nnom = 'Sans exemple'\nracine = '.'\nsuffixes = ['.js']\nmotif = 'zzz'\n",
        "[[regles]]\nnom = 'A vide'\nracine = '.'\nsuffixes = ['.rs']\nmotif = 'zzz'\n"]))

    code = lintorn.commandes.regles.tester()

    sortie = capsys.readouterr().out
    assert code == 1
    assert "[ OK ] Marche" in sortie and "1 occurrence(s) dans 1 : a.js" in sortie
    assert "[ !! ] Rate" in sortie and "son exemple n'est pas trouve par son motif" in sortie
    assert "[ ?? ] Sans exemple" in sortie and "sans `exemple`" in sortie
    assert "[ !! ] A vide" in sortie and "ne lit aucun fichier" in sortie
    assert sortie.count("son exemple n'est pas trouve") == 1, "dit une fois, sous la regle"


def test_lintorn_regles_test_sort_en_0_quand_chaque_regle_marche(tmp_path, monkeypatch, capsys):
    _regles_du_texte(tmp_path, monkeypatch, _regle("Marche", "motif", r"eval\(", "eval(2)"))

    assert lintorn.commandes.regles.tester() == 0
    assert "Les 1 regle(s) a motif marchent : chacune trouve son exemple." in capsys.readouterr().out


def test_les_suffixes_se_deduisent_des_chemins_cites():
    assert lintorn.commandes.regles._suffixes_probables(["services/api.ts", "axios.create()"]) == [".ts"]
    assert lintorn.commandes.regles._suffixes_probables(["var(--bg)", "#fff"]) == [], (
        "aucune extension citee : on laisse la liste vide plutot que d'inventer"
    )


def test_une_esquisse_designe_sa_regle_par_sa_phrase(tmp_path, monkeypatch):
    _config_doc_ia(tmp_path, monkeypatch, "Une ligne au-dessus.\n" + _TABLE)

    esquisses = lintorn.commandes.regles.esquisses_regles()

    assert '# source   = "CLAUDE.md#Axios partage"' in esquisses
    assert lintorn.commandes.regles.esquisses_regles('# source   = "CLAUDE.md:2"') == [], (
        "un brouillon plus ancien, ecrit par numero de ligne, ne doit pas etre repropose"
    )


# ─────────────────────────────────────────────────────────────────────────────
# `source` : la règle désignée par le début de sa phrase
# ─────────────────────────────────────────────────────────────────────────────
def test_l_ancre_ignore_le_balisage_et_la_casse_mais_pas_les_mots():
    designee = lintorn.controles.projet.regles_enoncees.ligne_designee
    enoncees = [("CLAUDE.md", 7, "**Zéro dépendance** | `dependencies = []` dans `pyproject.toml`", [])]

    assert designee("CLAUDE.md#zéro DÉPENDANCE", enoncees) == ("CLAUDE.md:7", "")
    assert designee("CLAUDE.md#dépend", enoncees)[0] is None, "des mots entiers, pas un bout de mot"
    assert designee("AUTRE.md#Zéro dépendance", enoncees)[0] is None
    decompose = [("CLAUDE.md", 7, unicodedata.normalize("NFD", enoncees[0][2]), [])]
    assert designee("CLAUDE.md#Zéro dépendance", decompose) == ("CLAUDE.md:7", ""), (
        "un é écrit e + accent (macOS) est le même é")


# Le verdict par le VRAI circuit, dans un processus neuf : `config` lit
# CLAUDE.md et regles.toml à l'import.
_PAQUET = str(Path(lintorn.__file__).resolve().parents[1])
_CIRCUIT_REGLES = (
    "import json; from lintorn import config, noyau\n"
    "config.COMMANDES = []\n"
    "config.CONTROLES_INTERNES = {'regles_declarees': True}\n"
    "r = [x for x in noyau.executer() if x.titre == 'Regles enoncees vs controlees'][0]\n"
    "print(json.dumps({'statut': r.statut, 'resume': r.resume, 'detail': r.detail}))\n"
)
_VERSIONS = "| **Versions** | le numero ne s'ecrit jamais ailleurs que dans `__version__` |\n"


def _regles_par_le_circuit(tmp_path, claude_md: str, source: str,
                           sens: str = 'hors_portee = "comparer deux fichiers depasse un motif"'
                           ) -> dict:
    (tmp_path / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    (tmp_path / ".lintorn").mkdir(exist_ok=True)
    (tmp_path / ".lintorn" / "regles.toml").write_text(
        f'[[regles]]\nsource = "{source}"\nnom = "Versions"\n{sens}\n', encoding="utf-8")
    environnement = {**os.environ, "LINTORN_RACINE": str(tmp_path),
                     "PYTHONPATH": os.pathsep.join(
                         [_PAQUET, *filter(None, [os.environ.get("PYTHONPATH")])])}
    sortie = subprocess.run([sys.executable, "-c", _CIRCUIT_REGLES], cwd=tmp_path,
                            capture_output=True, text=True, env=environnement,
                            timeout=60, check=False)
    assert sortie.returncode == 0, f"Lintorn est tombe :\n{sortie.stderr}"
    return json.loads(sortie.stdout.strip().splitlines()[-1])


def test_une_source_ecrite_par_sa_phrase_survit_a_une_ligne_ajoutee_au_dessus(tmp_path):
    """`CLAUDE.md:1` se périme dès qu'on écrit au-dessus : la règle redevient
    « sans contrôle », et il fallait recaler chaque source à la main. Le début
    de la phrase suit la règle là où elle va."""
    avant = _regles_par_le_circuit(tmp_path, _VERSIONS, "CLAUDE.md#Versions")
    apres = _regles_par_le_circuit(tmp_path, "# Regles\n\nUne note ajoutee.\n\n" + _VERSIONS,
                                   "CLAUDE.md#Versions")

    assert avant["statut"] == "OK", avant
    assert apres["statut"] == "OK", apres
    assert "1 hors de portee" in apres["resume"]


def test_une_source_par_numero_reste_comprise_et_alerte_quand_elle_se_decale(tmp_path):
    juste = _regles_par_le_circuit(tmp_path, _VERSIONS, "CLAUDE.md:1")
    decalee = _regles_par_le_circuit(tmp_path, "Une note ajoutee.\n" + _VERSIONS, "CLAUDE.md:1")

    assert juste["statut"] == "OK", juste
    assert decalee["statut"] == "VERIF", decalee
    assert 'source = "CLAUDE.md#..."' in decalee["detail"], "le message propose l'ancre par la phrase"


def test_la_source_cassee_d_une_regle_a_motif_dit_pourquoi(tmp_path):
    """Phrase renommée dans la doc : la règle redevenait « sans contrôle », et
    rien ne disait qu'une règle de regles.toml la visait encore."""
    doc = "| **Numero de version** | jamais ailleurs que dans `__version__` |\n"

    verdict = _regles_par_le_circuit(tmp_path, doc, "CLAUDE.md#Versions",
                                     sens="motif = 'zzz'\nsuffixes = ['.py']")

    assert verdict["statut"] == "VERIF", verdict
    assert "1 source(s) a recaler" in verdict["resume"]
    assert "**Versions** (CLAUDE.md#Versions) : aucune regle de CLAUDE.md" in verdict["detail"]


def test_lintorn_regles_previent_quand_une_source_ne_designe_plus_rien(tmp_path, monkeypatch, capsys):
    """Son brouillon revenait, en double de la règle déjà écrite, sans un mot."""
    _config_doc_ia(tmp_path, monkeypatch, _TABLE,
                   [{"nom": "Axios", "source": "CLAUDE.md#Axios renomme", "motif": re.compile("z")}])
    monkeypatch.setattr(config, "FICHIER_REGLES", tmp_path / ".lintorn" / "regles.toml")

    lintorn.commandes.regles.esquisser_regles()

    sortie = capsys.readouterr().out
    assert "1 esquisse(s)" in sortie
    assert "Axios (CLAUDE.md#Axios renomme) : aucune regle de CLAUDE.md" in sortie


def test_une_phrase_trouvee_dans_deux_regles_ne_couvre_aucune_des_deux(tmp_path):
    """En choisir une reviendrait à la déclarer couverte sur un pari."""
    doc = _VERSIONS + "| **Versions publiees** | jamais republier un numero, voir `CHANGELOG.md` |\n"

    verdict = _regles_par_le_circuit(tmp_path, doc, "CLAUDE.md#Versions")

    assert verdict["statut"] == "VERIF", verdict
    assert "dans 2 regles" in verdict["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# Reconnaître le GENRE d'un document
# ─────────────────────────────────────────────────────────────────────────────
def test_un_tutoriel_informe_au_lieu_de_bloquer(tmp_path):
    """MESURÉ SUR FASTAPI : 460 chemins bloquants au premier lancement.

    Un tutoriel apprend au lecteur à créer des fichiers CHEZ LUI : il cite donc
    légitimement des chemins absents d'ici. Sans cette distinction, un
    développeur qui découvre Lintorn se prend un mur d'erreurs et referme
    l'outil — et il n'y a qu'une première impression.
    """
    doc = tmp_path / "tutoriel.md"
    doc.write_text(
        "Cree `app/main.py`, puis `app/routers/items.py`, puis `app/models.py`.",
        encoding="utf-8")

    resultat = lintorn.controles.projet.doc_vs_code._verifier_documents("t", [doc], bloquant_possible=True)

    assert resultat.statut == "VERIF"
    assert resultat.bloquant is False
    assert "app/main.py" in resultat.detail, "on LISTE toujours : on informe, on n'interdit pas"


def test_un_seul_chemin_faux_bloque_toujours(tmp_path):
    """LE garde-fou de la règle. Sur UNE citation, un taux de 100 % ne veut
    rien dire — et c'est justement la forme du vrai pourrissement de doc : un
    fichier renommé, cité une fois. On ne l'excuse pas."""
    doc = tmp_path / "architecture.md"
    doc.write_text("Le pivot est `api/fichier_qui_nexiste_vraiment_pas.py`.", encoding="utf-8")

    resultat = lintorn.controles.projet.doc_vs_code._verifier_documents("t", [doc], bloquant_possible=True)

    assert resultat.statut == "ALERTE"
    assert resultat.bloquant is True


def test_un_journal_de_versions_cite_le_passe_sans_mentir(tmp_path):
    """Un changelog cite ce qui existait A L'EPOQUE. Sur FastAPI il pesait à
    lui seul 174 des 460 blocages, avec un taux d'absence de 21 % qu'aucun
    seuil raisonnable n'attraperait."""
    doc = tmp_path / "release-notes.md"
    doc.write_text(
        "0.2.0 : `ancien/module_supprime.py` retire, `autre/parti.py` aussi.",
        encoding="utf-8")

    resultat = lintorn.controles.projet.doc_vs_code._verifier_documents("t", [doc], bloquant_possible=True)

    assert resultat.bloquant is False


def test_les_documents_requalifies_sont_ANNONCES(tmp_path):
    """Requalifier en silence serait exactement la panne que Lintorn combat :
    l'utilisateur croirait sa documentation entierement controlee."""
    doc = tmp_path / "tutoriel.md"
    doc.write_text("Cree `a/b.py` et `c/d.py`.", encoding="utf-8")

    resultat = lintorn.controles.projet.doc_vs_code._verifier_documents("t", [doc], bloquant_possible=True)

    assert "1 doc(s) d'un autre genre" in resultat.resume, resultat.resume


# ─────────────────────────────────────────────────────────────────────────────
# L'index de la mémoire n'est pas une fiche
# ─────────────────────────────────────────────────────────────────────────────
def test_l_index_de_la_memoire_ne_reclame_pas_de_date(tmp_path, monkeypatch):
    """L'index n'a pas d'en-tête par construction : lui réclamer un
    `verifie_le` le condamnait à rester « sans date » à vie. Une FICHE sans
    date, elle, reste signalée."""
    (tmp_path / config.INDEX_MEMOIRE).write_text(
        "- [Une fiche](fiche.md) — voir `README.md`\n", encoding="utf-8")
    (tmp_path / "fiche.md").write_text("cite `README.md`\n", encoding="utf-8")
    monkeypatch.setattr(config, "MEMOIRE_IA", tmp_path)
    monkeypatch.setattr(config, "SOUS_GIT", True)

    resultat = lintorn.controles.projet.fraicheur_memoire.controle_fraicheur_memoire()

    assert "fiche.md" in resultat.detail
    assert config.INDEX_MEMOIRE not in resultat.detail
    assert "index epargne" in resultat.resume, "un fichier ecarte s'ANNONCE, il ne s'escamote pas"
