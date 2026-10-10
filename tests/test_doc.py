"""Doc vs code, règles énoncées, genre des documents, fraîcheur de la mémoire."""

import re

import pytest
from aides import _config_doc_ia

import lintorn.commandes
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


def test_les_suffixes_se_deduisent_des_chemins_cites():
    assert lintorn.commandes.regles._suffixes_probables(["services/api.ts", "axios.create()"]) == [".ts"]
    assert lintorn.commandes.regles._suffixes_probables(["var(--bg)", "#fff"]) == [], (
        "aucune extension citee : on laisse la liste vide plutot que d'inventer"
    )


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
