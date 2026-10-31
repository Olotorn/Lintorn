# Lintorn
"""La mecanique commune a tous les controles.

La fiche `Resultat`, le lanceur de commandes externes, la traduction
de leurs sorties, et l'etat local de la machine.

  ▸ Pour ajouter un outil       → config.py
  ▸ Pour traduire un code       → traductions.py
  ▸ Pour un controle du PROJET  → controles/projet/
  ▸ Pour un controle de L'OUTIL → controles/outillage/
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote

from . import config


# ─────────────────────────────────────────────────────────────────────────────
# ÉTAT LOCAL — ce qui dépend de la MACHINE, pas du projet
# ─────────────────────────────────────────────────────────────────────────────
# Gitignoré : la date du dernier audit complet n'a de sens que sur le poste où
# il a tourné. La partager par git ferait croire à un collègue que SA machine
# est à jour parce qu'une autre l'était.
def lire_etat() -> dict:
    # `is_file()` : un tube nommé à cette place se lirait sans fin.
    if not config.ETAT.is_file() or etat_suivi_par_git():
        return {}
    try:
        etat = json.loads(config.ETAT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return etat if isinstance(etat, dict) else {}


def etat_suivi_par_git() -> bool:
    """`etat.json` est-il commité ? Alors ce n'est pas l'état de CETTE machine.

    Un dépôt piégé le commite avec un « dernier audit complet » d'aujourd'hui :
    lu, il affichait un vert sur des outils que personne n'a jamais lancés ici.
    """
    return config.suivi_par_git(config.ETAT)


def dossier_sur(dossier: Path) -> None:
    """Lève OSError si `dossier` mène hors du projet, ou y passe par un lien.

    Partagé par l'écriture ET le retrait : un retrait qui contournerait ces
    gardes effacerait, à travers un `.lintorn` lié ailleurs, un fichier hors
    du projet — pire que l'écriture qu'elles refusent.
    """
    if not dossier.resolve().is_relative_to(config.RACINE.resolve()):
        raise OSError(f"{dossier.name}/ mene hors du projet : ecriture refusee")
    # ⚠️ Le fichier n'est pas le seul à pouvoir être un lien : un DOSSIER lié,
    # même vers l'intérieur du projet, faisait écrire ailleurs sous un nom que
    # Lintorn croyait sien — `.lintorn/hooks -> ../outils`, et le script
    # `outils/pre-push` du projet était écrasé par le hook.
    for nom in _sous_la_racine(dossier):
        if nom.is_symlink():
            raise OSError(f"{nom.name}/ est un lien symbolique : Lintorn n'ecrit pas a travers")


def _ecrire(fichier: Path, contenu: str | bytes, remplacer_lien: bool) -> None:
    dossier = fichier.parent
    dossier_sur(dossier)
    if fichier.is_symlink() and not remplacer_lien:
        raise OSError(f"{fichier.name} est un lien symbolique : Lintorn n'ecrit pas a travers")
    dossier.mkdir(parents=True, exist_ok=True)
    donnees = contenu if isinstance(contenu, bytes) else contenu.encode("utf-8")
    # ⚠️ Écrire dans un fichier voisin puis le RENOMMER, jamais ouvrir la cible
    # en troncature. Le rename ne suit pas un lien posé à la place du fichier
    # (il le remplace) ; et un lecteur — le hook, un éditeur, un assistant IA —
    # voit l'ancien contenu ou le nouveau, jamais un fichier vide entre les deux.
    # `O_EXCL` : un lien posé sur le nom temporaire ferait échouer, pas écrire.
    temporaire = dossier / f".{fichier.name}.{uuid.uuid4().hex}.tmp"
    mode = fichier.stat().st_mode & 0o7777 if fichier.is_file() and not fichier.is_symlink() else 0o666
    try:
        descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(descripteur, "wb") as flux:
            flux.write(donnees)
        if mode != 0o666:
            temporaire.chmod(mode)
        os.replace(temporaire, fichier)
    except BaseException as erreur:
        temporaire.unlink(missing_ok=True)
        if isinstance(erreur, OSError) and erreur.errno:
            # Le message nomme le fichier voulu, pas son temporaire.
            raise OSError(erreur.errno, erreur.strerror, str(fichier)) from None
        raise


def _sous_la_racine(dossier: Path) -> list[Path]:
    """Les dossiers traversés SOUS la racine du projet, de haut en bas.

    Seulement ceux-là : la racine peut très bien être atteinte par un lien
    (`/tmp` sur macOS, un `/home` monté ailleurs) sans que ce soit l'affaire
    de Lintorn. Ce qu'on refuse, c'est un détour ajouté DANS le projet.
    """
    try:
        relatif = dossier.relative_to(config.RACINE)
    except ValueError:
        return []
    courant = config.RACINE
    traverses = []
    for nom in relatif.parts:
        courant = courant / nom
        traverses.append(courant)
    return traverses


def ecrire_sortie(fichier: Path, contenu: str | bytes) -> None:
    """Écrit une SORTIE de Lintorn (rapport, état, hook) — dans le projet, jamais ailleurs.

    ⚠️ Un dépôt peut committer `.lintorn/rapport.md` comme LIEN SYMBOLIQUE vers
    n'importe quel fichier de la machine : écrire « à travers » l'écrasait au
    premier `lintorn`, sans que personne l'ait demandé. Un lien à cette place
    est donc retiré — le lien, pas sa cible — avant d'écrire un vrai fichier.
    Et si le dossier lui-même mène hors du projet, on refuse.

    Lève OSError quand l'écriture est refusée ou impossible.
    """
    _ecrire(fichier, contenu, remplacer_lien=True)


def retirer_sortie(fichier: Path) -> None:
    """Retire une SORTIE de Lintorn — derrière les mêmes gardes que l'écriture.

    Un lien à cette place est retiré lui-même, jamais sa cible. Lève OSError
    quand le retrait est refusé ou impossible.
    """
    dossier_sur(fichier.parent)
    if fichier.is_symlink() or fichier.is_file():
        fichier.unlink()


def ecrire_fichier_du_projet(fichier: Path, contenu: str | bytes) -> None:
    """Écrit un fichier qui APPARTIENT au projet : config, règles, dépendances.

    Un lien symbolique à cette place est une décision de l'utilisateur : on ne
    le remplace pas, et on n'écrit pas à travers. Lève OSError en cas de refus.
    """
    _ecrire(fichier, contenu, remplacer_lien=False)


def ecrire_etat(cle: str, valeur) -> None:
    if etat_suivi_par_git():
        return      # le fichier du dépôt n'est pas le nôtre : on ne le réécrit pas
    etat = lire_etat()
    etat[cle] = valeur
    try:
        ecrire_sortie(config.ETAT, json.dumps(etat, indent=2))
    except OSError:
        pass    # ne JAMAIS faire échouer un audit parce qu'on n'a pas pu noter la date

# ─────────────────────────────────────────────────────────────────────────────
# LA FICHE DE RÉSULTAT
# ─────────────────────────────────────────────────────────────────────────────

# Au-dela, un outil bavard rend le rapport illisible. La coupure est
# SIGNALEE dans les deux rendus : un detail coupe en silence ferait croire
# que l'outil n'avait rien de plus a dire.
DETAIL_MAX = 12000

MARQUEUR = {
    "OK": "[ OK ]",
    "ALERTE": "[ !! ]",
    "VERIF": "[ ?? ]",         # rien de cassé, mais un point à confirmer à l'œil
    "ERREUR": "[ERR!]",        # l'outil lui-même est en panne
    "INDISPONIBLE": "[ -- ]",  # outil absent : on prévient, on ne bloque pas
}


# ⚠️ Ce qui s'affiche vient de L'EXTÉRIEUR : la sortie d'un outil, un nom de
# fichier, un texte de règle. Une séquence d'échappement y efface l'écran, change
# le titre de la fenêtre, ou repeint une fausse ligne « [ OK ] » par-dessus la
# vraie ; un caractère de sens de lecture (U+202E) retourne un nom de fichier.
# Rien de tout cela n'a de raison d'atteindre la console ni un rapport : on les
# retire À LA FICHE, donc partout d'un coup.
_RX_SEQUENCES = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"                   # CSI : couleurs, curseur, effacement
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"       # OSC : titre, lien cliquable
    r"|\x1b[@-Z\\-_]"                           # autres séquences à deux octets
)
_RX_CONTROLES = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def sans_controle(texte: str) -> str:
    """`texte` sans séquence de terminal ni caractère de contrôle. Garde \\n et \\t."""
    texte = texte.replace("\r\n", "\n")
    return _RX_CONTROLES.sub("", _RX_SEQUENCES.sub("", texte))


_CHAMPS_TEXTE = ("titre", "resume", "detail")


class Resultat:
    """Issue d'un contrôle : un statut, un résumé court, un détail complet."""

    def __setattr__(self, nom: str, valeur) -> None:
        if nom in _CHAMPS_TEXTE and isinstance(valeur, str):
            valeur = sans_controle(valeur)
        super().__setattr__(nom, valeur)

    def __init__(self, titre: str, statut: str, resume: str, detail: str = "",
                 bloquant: bool = True, detail_markdown: bool = False,
                 detail_meme_au_vert: bool = False, code_sortie: int | None = None,
                 fichiers: dict[str, str] | None = None, dossier: Path | None = None,
                 rappel: bool = False):
        self.titre = titre
        self.statut = statut
        self.resume = resume
        self.detail = detail.strip()
        self.bloquant = bloquant
        # True = le détail contient du Markdown (liens cliquables) → le rapport
        # ne doit PAS l'enfermer dans un bloc ``` , sinon les liens ne
        # fonctionnent plus.
        self.detail_markdown = detail_markdown
        # Le rapport jette le détail des contrôles verts, sinon la sortie brute
        # de ruff et de pytest le rendrait illisible. Sauf demande explicite :
        # un contrôle vert peut avoir quelque chose à MONTRER — les règles qui
        # n'ont rien vérifié, par exemple. Le résumé, lui, n'en dit que le
        # nombre.
        self.detail_meme_au_vert = detail_meme_au_vert
        # Le code de sortie de l'outil, quand il y en a eu un. Gardé pour les
        # traducteurs : certains outils écrivent une sortie VALIDE mais vide
        # quand ils échouent, et seul ce code dit alors la vérité.
        self.code_sortie = code_sortie
        # {fichier du dépôt: ce qu'on y a trouvé}, COMPLET — le détail, lui,
        # peut n'en montrer qu'une partie. C'est ce que lit le focus du push.
        self.fichiers = fichiers or {}
        # Le dossier où l'outil a tourné : c'est de là qu'il nomme ses
        # fichiers. Un traducteur en a besoin pour les ramener à la racine.
        self.dossier = dossier
        # True : un outil qui n'a PAS tourné redit ce qu'il avait trouvé la
        # dernière fois. Le verdict le nomme ; rien ne le compte comme vérifié.
        self.rappel = rappel

    @property
    def en_echec(self) -> bool:
        """Ce résultat doit-il empêcher un push ?

        VERIF n'y figure PAS : c'est un point à confirmer à l'œil, pas un défaut.
        """
        return self.statut in ("ALERTE", "ERREUR") and self.bloquant


# La fin d'un détail porte souvent ce qui sert le plus : le conseil de
# correction, le « … et N autre(s) » d'un traducteur, le bilan de pytest.
# Elle est gardée, dans cette limite.
_FIN_MAX = DETAIL_MAX // 4


def detail_du_rapport(resultat: Resultat) -> str:
    """Le détail tel que les DEUX rapports l'affichent : entier, ou coupé.

    Une seule coupe pour `rapport.md` et `rapport.html` : faite de chaque
    côté, elle finit par différer, et les deux rapports se contredisent.

    La coupe tombe ENTRE deux lignes : au milieu, elle cassait un lien ou une
    ligne de tableau. Elle dit combien de lignes manquent, et garde la fin du
    détail — coupée sans le dire, la liste passait pour complète, et le
    conseil de correction, écrit en dernier, disparaissait avec elle.
    """
    detail = resultat.detail
    if len(detail) <= DETAIL_MAX:
        return detail
    markdown = resultat.detail_markdown
    lignes = detail.split("\n")

    # ouvert[n] : la clôture du bloc ``` encore ouvert AVANT la ligne n. Un
    # bloc coupé avalerait tout ce qui suit, l'annonce de la coupe comprise.
    ouvert: list[str | None] = [None]
    for ligne in lignes:
        nu = ligne.strip()
        cloture = ouvert[-1]
        if markdown and nu.startswith("```"):
            cloture = None if cloture else nu[:len(nu) - len(nu.lstrip("`"))]
        ouvert.append(cloture)

    # La fin : des paragraphes ENTIERS en Markdown (un tableau sans son
    # en-tête ne se lit plus), de simples lignes dans une sortie brute.
    taille = [0] * (len(lignes) + 1)
    for numero in range(len(lignes) - 1, -1, -1):
        taille[numero] = taille[numero + 1] + len(lignes[numero]) + 1
    debut_fin = len(lignes)
    for numero in range(1, len(lignes)):
        coupure_propre = not markdown or (not lignes[numero - 1].strip()
                                          and ouvert[numero] is None)
        if coupure_propre and taille[numero] <= _FIN_MAX:
            debut_fin = numero
            break

    reste = DETAIL_MAX - taille[debut_fin]
    gardees = 0
    while gardees < debut_fin and len(lignes[gardees]) + 1 <= reste:
        reste -= len(lignes[gardees]) + 1
        gardees += 1
    omises = lignes[gardees:debut_fin]
    if not any(ligne.strip() for ligne in omises):
        return detail
    tete = lignes[:gardees]
    if not tete:
        # Une seule ligne dépasse tout le budget : on en montre le début.
        tete, gardees = [lignes[0][:reste] + " …"], 1
    if ouvert[gardees]:
        tete.append(ouvert[gardees])

    total = sum(1 for ligne in lignes if ligne.strip())
    manque = sum(1 for ligne in omises if ligne.strip())
    annonce = (f"… {manque} ligne(s) sur {total} non affichée(s) ici : le détail "
               f"dépasse {DETAIL_MAX:,} caractères.".replace(",", " "))
    if markdown:
        annonce = f"*{annonce}*"
    fin = ["", *lignes[debut_fin:]] if debut_fin < len(lignes) else []
    return "\n".join([*tete, "", annonce, *fin])


def lien(chemin_racine: str, ligne: int | None = None) -> str:
    """Transforme un chemin en lien Markdown cliquable depuis le rapport.

    Le rapport vit dans `.lintorn/`, donc la racine du dépôt est UN cran
    au-dessus — d'où le `../`. VS Code ouvre le fichier au clic et se place
    sur la bonne ligne grâce à l'ancre `#L42`.

    ⚠️ Ce nombre de crans suit l'emplacement du rapport. Il valait `../../`
    du temps où le rapport vivait deux niveaux plus bas : déplacer le rapport
    sans corriger ici casse SILENCIEUSEMENT tous les liens du rapport, qui
    restent cliquables mais ne mènent nulle part.
    """
    chemin = chemin_racine.replace("\\", "/")
    ancre = f"#L{ligne}" if ligne else ""
    # ⚠️ Un nom de fichier est un texte du dépôt, donc de n'importe qui. Un saut
    # de ligne y ouvrait une fausse section « ## [ OK ] » dans le rapport ; un
    # `](` ou une parenthèse y coupait le lien. Le texte tient sur UNE ligne, et
    # l'adresse est encodée : rien n'y ressemble plus à du Markdown.
    brut = f"{chemin}:{ligne}" if ligne else chemin
    texte = " ".join(brut.split()).replace("`", "'")
    adresse = quote(chemin, safe="/._-~@+,=:")
    return f"[`{texte}`](../{adresse}{ancre})"


# ─────────────────────────────────────────────────────────────────────────────
# LANCER UN OUTIL EXTERNE
# ─────────────────────────────────────────────────────────────────────────────
_RX_MODULE_MANQUANT = re.compile(r"No module named ['\"]?([\w.]+)")

DELAI_OUTIL = 600            # secondes : au-delà, on ne sait pas
LIMITE_SORTIE = 32 << 20     # octets gardés par flux : 24 Mo de tête + 8 Mo de queue


def _lire_borne(flux) -> str:
    """Le texte d'un flux de sortie, borné : la tête et la queue, le milieu annoncé.

    Un outil qui crache 300 Mo occupait 2 Go dans Lintorn (`capture_output` garde
    tout, puis chaque copie du texte en refait une). La QUEUE est gardée exprès :
    c'est là que pytest, tsc ou npm écrivent leur bilan.
    """
    flux.flush()
    taille = flux.seek(0, os.SEEK_END)
    flux.seek(0)
    if taille <= LIMITE_SORTIE:
        return flux.read().decode("utf-8", errors="replace")
    tete = flux.read(LIMITE_SORTIE * 3 // 4)
    flux.seek(taille - LIMITE_SORTIE // 4)
    queue = flux.read()
    omis = (taille - len(tete) - len(queue)) >> 20
    return (tete.decode("utf-8", errors="replace")
            + f"\n[... sortie tronquee : {omis} Mo omis au milieu ...]\n"
            + queue.decode("utf-8", errors="replace"))


def _arreter(proc: subprocess.Popen) -> None:
    """Tue l'outil ET ce qu'il a lancé : un test parti en boucle laisse des enfants."""
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        pass
    proc.wait()


# Les variables par lesquelles git désigne SON dépôt (git(1), « The Git Repository »),
# et les réglages d'un `git -c ... push` (GIT_CONFIG_PARAMETERS).
# Dans un worktree, git exporte GIT_DIR vers le hook : un outil lancé par Lintorn
# qui fait `git init` puis `git commit` dans un dossier temporaire (les tests d'un
# projet) écrivait dans le dépôt de l'utilisateur, et `git init --bare` le
# déclarait nu. Un outil trouve son dépôt depuis son dossier, comme partout ailleurs.
VARIABLES_DU_DEPOT = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                      "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                      "GIT_NAMESPACE", "GIT_PREFIX", "GIT_QUARANTINE_PATH",
                      "GIT_CONFIG_PARAMETERS")


def environnement_d_un_outil() -> dict[str, str]:
    """L'environnement d'un outil lancé par Lintorn : celui de Lintorn, sans le dépôt du hook."""
    env = {nom: valeur for nom, valeur in os.environ.items() if nom not in VARIABLES_DU_DEPOT}
    # Un outil de Lintorn ne laisse rien dans le projet audité : pas de
    # `__pycache__` à côté des fichiers que pytest ou vulture importent.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _executer(commande: list[str], cwd: Path) -> tuple[int, str, str]:
    """(code, sortie standard, sortie d'erreur). Lève ce que `subprocess` lève.

    ⚠️ La sortie va dans des FICHIERS, pas des tubes. Avec un tube, un outil qui
    laisse derrière lui un enfant (un serveur de test, un démon) gardait le tube
    ouvert : Lintorn attendait dix minutes un outil déjà terminé. Un fichier
    n'attend personne. Et `stdin` est fermé : un outil qui pose une question
    (`input()`, un débogueur) échoue tout de suite au lieu de geler le push — ou
    de lire les lignes que git envoie au hook.
    """
    with tempfile.TemporaryFile() as sortie, tempfile.TemporaryFile() as erreur:
        proc = subprocess.Popen(
            commande, cwd=cwd, stdin=subprocess.DEVNULL, stdout=sortie, stderr=erreur,
            env=environnement_d_un_outil(),
            start_new_session=hasattr(os, "killpg"),
        )
        try:
            proc.wait(timeout=DELAI_OUTIL)
        except BaseException:
            _arreter(proc)
            raise
        return proc.returncode, _lire_borne(sortie), _lire_borne(erreur)


def _interprete_absent(programme: str) -> str | None:
    """L'interpréteur que réclame la ligne `#!` du programme, s'il est introuvable.

    `node_modules/.bin/tsc` commence par `#!/usr/bin/env node`. Sans `node`
    dans le PATH — le bouton Git de VS Code, une interface graphique, un node
    installé par nvm —, il sort en 127 et le message du système dépend de la
    langue de la machine : on lit la ligne `#!`, pas le message.
    """
    chemin = Path(programme) if Path(programme).is_file() else Path(shutil.which(programme) or "")
    try:
        with chemin.open("rb") as flux:
            premiere = flux.readline(256)
    except OSError:
        return None
    morceaux = premiere[2:].decode("utf-8", errors="replace").split()
    if not premiere.startswith(b"#!") or not morceaux:
        return None
    if Path(morceaux[0]).name == "env":
        noms = [morceau for morceau in morceaux[1:] if not morceau.startswith("-")]
        return noms[0] if noms and not shutil.which(noms[0]) else None
    return None if Path(morceaux[0]).exists() else Path(morceaux[0]).name


def lancer(
    titre: str,
    commande: list[str],
    cwd: Path,
    bloquant: bool = True,
    codes_alerte: tuple[int, ...] = (1,),
) -> Resultat:
    """Lance un outil et transforme son code de sortie en Resultat.

    `codes_alerte` distingue DEUX choses que le code de sortie confond :

      0                    → tout va bien
      dans codes_alerte    → l'outil a fait son travail et a TROUVÉ des problèmes
      tout le reste        → l'OUTIL LUI-MÊME a planté

    Sans cette distinction, un ruff cassé (code 2 = erreur interne) ressemblait
    exactement à un ruff ayant trouvé 12 défauts. On serait resté persuadé
    d'être couvert alors que plus rien n'était analysé.
    """
    try:
        code, sortie_standard, sortie_erreur = _executer(commande, cwd)
    except FileNotFoundError:
        # Le NOM seul : un chemin complet porterait celui de la machine.
        return Resultat(titre, "INDISPONIBLE", f"outil introuvable : {Path(commande[0]).name}",
                        bloquant=False)
    except subprocess.TimeoutExpired:
        # ⚠️ `bloquant` GARDÉ. Rendu non bloquant, un dépassement de délai
        # laissait passer le push : une suite de tests partie en boucle — donc
        # une vraie régression — devenait un feu vert au bout de dix minutes.
        return Resultat(titre, "ERREUR", f"delai depasse ({DELAI_OUTIL // 60} min) - on ne sait pas",
                        bloquant=bloquant)
    except OSError as erreur:
        # Script sans bit exécutable (`PermissionError`), sans shebang
        # (`Exec format error`) : python lève, et l'audit ENTIER tombait sur un
        # traceback, sans rapport. Oublier un `chmod +x` est banal.
        return Resultat(
            titre, "INDISPONIBLE",
            f"impossible de lancer {Path(commande[0]).name} : {erreur.strerror}",
            "Une commande de `.lintorn/config.toml` n'a pas pu demarrer. Les "
            "deux causes habituelles :\n\n"
            "- le fichier n'est pas executable → `chmod +x`\n"
            "- il n'a pas de ligne `#!` en tete → l'appeler par son "
            "interpreteur (`cmd = [\"sh\", \"mon-script.sh\"]`)",
            bloquant=False, detail_markdown=True,
        )

    sortie = (sortie_standard + sortie_erreur).strip()

    # ⚠️ `python -m outil` quand l'outil n'est PAS installé : python existe, il
    # démarre, et sort en 1 avec « No module named x ». Pour le code de sortie
    # c'est indiscernable de « l'outil a tourné et trouvé 1 problème ».
    #
    # Sans ce cas, Lintorn annonçait « 1 alerte de lint » à quiconque n'avait
    # pas ruff — un rouge sur du code qu'il n'avait jamais lu. Trouvé par
    # Lintorn sur son propre depot, le jour ou il a su s'auditer.
    #
    # ⚠️ MAIS SEULEMENT SI LE MODULE MANQUANT EST L'OUTIL LANCÉ. Un import
    # cassé DU PROJET — module renommé, app disparue d'INSTALLED_APPS —
    # produit le même message : le déguiser en « outil non installé »
    # masquait un vrai défaut derrière un conseil absurde.
    outil = commande[2] if len(commande) > 2 and commande[1] == "-m" else None
    manquants = _RX_MODULE_MANQUANT.findall(sortie)
    manquant = manquants[-1] if manquants else ""
    if outil and (manquant == outil or manquant.startswith(outil + ".")):
        if outil in config.OUTILS_INSTALLABLES:
            conseil = "`lintorn outils`"
        elif commande[0] == str(config.PYTHON):
            conseil = "installe-le dans le venv du projet"
        else:
            # Un de TES outils, lancé par le Python du terminal : c'est le
            # plus souvent là qu'est l'erreur, pas dans l'installation.
            conseil = "ecris `{python}` dans `cmd` pour le lancer avec le Python du projet"
        return Resultat(
            titre, "INDISPONIBLE", f"{manquant} n'est pas installe - {conseil}",
            sortie, bloquant=False, code_sortie=code,
        )

    # ⚠️ `codes_alerte` AVANT le vert. Un code qu'on y liste — 0 compris — part
    # au traducteur, qui seul sait lire la sortie : npm peut sortir en 0 avec
    # une ERREUR dans son JSON. Rendu vert d'office, ce 0 ne passait jamais
    # par le traducteur, et « rien a signaler » s'affichait sans rien vérifier.
    if code in codes_alerte:
        lignes = [ligne for ligne in sortie.splitlines() if ligne.strip()]
        return Resultat(titre, "ALERTE", f"{len(lignes)} ligne(s) de sortie", sortie, bloquant,
                        code_sortie=code, dossier=cwd)

    if code == 0:
        # ⚠️ Les `resume` finissent dans la console — et le hook git tourne sous
        # Git Bash, qui n'affiche pas l'UTF-8 correctement. On les garde en
        # ASCII pur. Le RAPPORT, lui, est en UTF-8 et garde tous les accents.
        return Resultat(titre, "OK", "rien a signaler", sortie, bloquant,
                        code_sortie=code)

    # 127 : le système n'a pas trouvé un programme. Quand c'est l'interpréteur
    # de l'outil (`node` pour tsc), l'outil n'a pas tourné : rien vérifié,
    # mais pas en panne non plus — et le remède est le PATH, pas l'outil.
    absent = _interprete_absent(commande[0]) if code == 127 else None
    if absent:
        return Resultat(
            titre, "INDISPONIBLE",
            f"{absent} introuvable - {Path(commande[0]).name} en a besoin (PATH)",
            f"`{Path(commande[0]).name}` se lance avec `{absent}`, que ce terminal ne trouve "
            "pas. Le plus souvent, `git push` part d'une interface (le bouton Git de VS "
            f"Code) dont le PATH n'est pas celui de ton terminal : un `{absent}` installé par "
            "nvm, brew ou dans ton profil shell n'y est pas.\n\n"
            f"Vérifier : `{absent} --version` depuis l'endroit d'où tu pousses.",
            bloquant=False, detail_markdown=True, code_sortie=code)

    # Code inattendu → c'est l'outil qui est en panne, pas ton code.
    # On garde `bloquant` : un contrôle muet est pire qu'un contrôle rouge,
    # il donne l'illusion d'être couvert.
    return Resultat(
        titre, "ERREUR",
        f"l'outil a plante (code {code}) - plus aucune analyse",
        sortie, bloquant, code_sortie=code,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TRADUCTION DES SORTIES
# ─────────────────────────────────────────────────────────────────────────────


# ── Ce qu'un outil tiers écrit finit dans le rapport : on le neutralise ──────
