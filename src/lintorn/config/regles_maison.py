# Lintorn
"""Les règles maison : les [[regles]] que le projet écrit dans .lintorn/regles.toml."""

from __future__ import annotations

import re

from .. import config

_CLES_REGLE = {"source", "nom", "regle", "racine", "suffixes", "exclure",
               "motif", "motif_requis", "si", "bloquant", "hors_portee", "exemple"}


def _exemples(brute: dict) -> list[str] | None:
    """Le ou les `exemple` d'une règle : des textes FAUTIFS qu'elle doit attraper. None : mal écrits."""
    exemple = brute.get("exemple")
    if exemple is None:
        return []
    liste = [exemple] if isinstance(exemple, str) else exemple
    if isinstance(liste, list) and liste and all(isinstance(x, str) and x for x in liste):
        return liste
    return None


def rate_son_exemple(regle: dict, exemple: str) -> str:
    """Pourquoi la règle ne signalerait PAS cet exemple fautif ; vide si elle le signale.

    ⚠️ Une règle morte et une règle tenue disent toutes deux « 0 » : une regex
    qui ne peut rien attraper (un `\\` en trop, une alternative mal placée) restait
    verte depuis le jour de son écriture. Son exemple la prend en faute.
    """
    if regle["si"] is not None and not regle["si"].search(exemple):
        return "ne contient pas son `si` : la regle ne le lirait meme pas"
    trouve = bool(regle["motif"].search(exemple))
    if regle["requis"] and trouve:
        return "contient ce que la regle exige : ce n'est pas une faute pour elle"
    if not regle["requis"] and not trouve:
        return "n'est pas trouve par son motif"
    return ""


def tables_mal_nommees(texte: str) -> list[tuple[int, str, str, str]]:
    """(numéro, ligne, ligne corrigée, nom écrit) des en-têtes qui visent `[[regles]]` sans l'écrire.

    `[[regle]]`, `[[Regles]]`, `[[rules]]`, `[[régles]]` (un accent est interdit
    dans un nom de table : le fichier entier devenait illisible), `[regles]`
    (une table seule, pas une liste). Le détecteur est celui de `lintorn
    corrige` (`fautes_de_frappe`) : ce qui est signalé ici est ce qu'il répare.
    """
    tables, cles = config._schemas()[config.FICHIER_REGLES]
    return [(faute.numero, faute.ligne, faute.corrigee, faute.ecrit)
            for faute in config.fautes_de_frappe(texte, tables, cles) if faute.table]


def _regles_brutes() -> list[dict]:
    """Les `[[regles]]` declarees, quel que soit le fichier qui les porte.

    Deux sources, FUSIONNEES et non concurrentes :

      1. `.lintorn/regles.toml` — le fichier dedie, la ou `--init` ecrit
      2. la cle `regles` de la config generale (config.toml, ou
         `[tool.lintorn]` du pyproject.toml)

    ⚠️ Fusionner, et surtout pas choisir : les projets qui avaient deja leurs
    regles dans `config.toml` continuent de fonctionner a l'identique, sans
    rien deplacer. Une reorganisation qui casse l'existant n'est pas une
    amelioration, c'est une punition pour ceux qui ont adopte l'outil tot.
    """
    charge = config._charger_toml(config.FICHIER_REGLES)
    # La faute dite avec sa ligne et la bonne écriture : « cle inconnue 'regle' »
    # obligeait à chercher, et `[[régles]]` ne laissait qu'une erreur de TOML.
    try:
        mal_nommees = config.tables_mal_nommees(config.FICHIER_REGLES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        mal_nommees = []
    nom = config.FICHIER_REGLES.name
    for numero, ligne, corrigee, _ in mal_nommees:
        config.SOUCIS_CONFIG.append(
            f"{nom}, ligne {numero} : {ligne.strip()} n'est pas lu - ecris {corrigee.strip()}"
            " (`lintorn corrige` le fait)")
    expliquees = {ecrit for _, _, _, ecrit in mal_nommees}
    if isinstance(charge, dict):
        # Compté même s'il ne déclare aucune règle : « regles.toml lu,
        # 0 regle chargee » est une information, pas un silence.
        config._retenu(nom)
        # Seul `regles` est lu : une `[[regle]]` ou une `[[rules]]` disparaissait
        # sans un mot, et le push fautif partait sur « Lintorn OK ».
        config.SOUCIS_CONFIG.extend(config._cles_inconnues(
            {cle: valeur for cle, valeur in charge.items() if cle not in expliquees},
            {"regles"}, nom))
    dediees = charge.get("regles", []) if isinstance(charge, dict) else []
    if not isinstance(dediees, list):
        if "regles" not in expliquees:
            config.SOUCIS_CONFIG.append(f"{nom} : `regles` doit etre une liste de [[regles]] - ignore")
        dediees = []
    heritees = config.PROJET.get("regles", [])
    toutes = [*dediees, *heritees]
    tables = [brute for brute in toutes if isinstance(brute, dict)]
    if len(tables) != len(toutes):
        config.SOUCIS_CONFIG.append("une [[regles]] qui n'est pas une table a ete ignoree")
    return tables


# `nom = "..."` en debut de ligne. tomllib ne rend aucun numero de ligne : pour
# renvoyer l'utilisateur vers SA regle, on relit le fichier a la main.
_RX_NOM_DE_REGLE = re.compile(r"""^\s*nom\s*=\s*["'](.+?)["']\s*$""")


def _lignes_des_regles() -> dict[str, tuple[str, int]]:
    """{nom de la regle: (chemin depuis la racine, numero de ligne)}.

    Le premier `nom` gagne : deux regles homonymes sont deja une erreur de
    config, et pointer sur la premiere vaut mieux que ne rien pointer.
    """
    reperes: dict[str, tuple[str, int]] = {}
    for chemin in (config.FICHIER_REGLES, config.DOSSIER_LINTORN / "config.toml",
                   config.RACINE / "pyproject.toml"):
        try:
            texte = chemin.read_text(encoding="utf-8")
        # `ValueError` : un fichier qui n'est pas de l'UTF-8. `_charger_toml`
        # l'a déjà signalé ; ici, il ne doit surtout pas faire tomber l'import.
        except (OSError, ValueError):
            continue
        try:
            relatif = chemin.relative_to(config.RACINE).as_posix()
        except ValueError:
            continue
        for numero, ligne in enumerate(texte.splitlines(), 1):
            trouve = config._RX_NOM_DE_REGLE.match(ligne)
            if trouve and trouve.group(1) not in reperes:
                reperes[trouve.group(1)] = (relatif, numero)
    return reperes


def _regles_du_projet() -> tuple[list[dict], list[dict]]:
    """Traduit les `[[tool.lintorn.regles]]` en règles exploitables.

    Deux sens possibles : `motif` = ce texte est INTERDIT, `motif_requis` =
    ce texte DOIT être présent. `si` restreint la règle aux fichiers qui le
    contiennent, ce qui donne « si X apparaît, alors Y doit aussi ».

    Une règle mal écrite est IGNORÉE et signalée, jamais fatale : un motif
    regex invalide ne doit pas priver l'utilisateur des douze autres
    contrôles. Et une règle dont le dossier n'existe pas est écartée plutôt
    que laissée à afficher un tranquille « 0 occurrence » — un vert sur un
    contrôle qui ne contrôle rien est précisément ce que Lintorn combat.
    """
    regles, soucis = [], []
    hors_portee: list[dict] = []
    reperes = config._lignes_des_regles()

    for brute in config._regles_brutes():
        nom = str(brute.get("nom", "(sans nom)"))
        soucis += config._cles_inconnues(brute, config._CLES_REGLE, nom)

        # Une règle déclare UN sens, jamais deux : `motif` = ce texte est
        # interdit, `motif_requis` = il doit être là, `hors_portee` = aucun
        # motif ne peut l'exprimer, et voici pourquoi. Deviner lequel
        # appliquer reviendrait à faire respecter une règle non écrite.
        interdit = brute.get("motif")
        oblige = brute.get("motif_requis")
        hors = brute.get("hors_portee")
        if len([c for c in (interdit, oblige, hors) if c]) != 1:
            soucis.append(f"{nom} : declarer UN seul de `motif` (interdit), "
                          "`motif_requis` (obligatoire) ou `hors_portee`")
            continue

        exemples = _exemples(brute)
        if exemples is None:
            soucis.append(f"{nom} : `exemple` doit etre un texte, ou une liste de textes - ignore")
            exemples = []
        if hors:
            if exemples:
                soucis.append(f"{nom} : `exemple` sans motif - une regle hors_portee n'a rien a tester")
            # Pas une règle à appliquer : une DÉCISION motivée, sur une règle
            # que Lintorn ne sait pas exprimer. `source` est obligatoire —
            # sans lui la décision ne désigne rien et ne couvre donc rien.
            if not brute.get("source"):
                soucis.append(f"{nom} : `hors_portee` exige `source` "
                              '(ex. source = "CLAUDE.md#debut de la phrase de la regle")')
                continue
            hors_portee.append({
                "nom": nom,
                "source": str(brute["source"]),
                "raison": str(hors),
            })
            continue

        try:
            # ⚠️ MULTILINE, sans quoi `^` designe le debut du FICHIER ENTIER et
            # non celui d'une ligne. Une regle maison est ligne-orientee : on
            # ecrit `^\s+print\(` pour dire « une ligne qui commence par ».
            # Sans ce drapeau, une telle regle ne matche JAMAIS — elle affiche
            # vert sans rien controler. C'est arrive a la regle
            # « print() de debogage oublie », verte depuis le jour de son
            # ecriture. Exactement la panne que Lintorn existe pour combattre.
            motif = re.compile(interdit or oblige, re.MULTILINE)
            # `si` restreint la règle aux fichiers qui le contiennent. C'est
            # lui qui permet d'écrire « si X apparaît, alors Y doit aussi » —
            # un motif seul ne sait dire qu'« interdit » ou « obligatoire ».
            condition = brute.get("si")
            si = re.compile(condition, re.MULTILINE) if condition else None
        # `RecursionError` : un motif imbriqué sur des milliers de niveaux fait
        # tomber le compilateur de `re` — et, à l'import, tout Lintorn avec lui.
        except (TypeError, re.error, RecursionError, OverflowError, MemoryError) as erreur:
            raison = str(erreur) if isinstance(erreur, re.error) else type(erreur).__name__
            soucis.append(f"{nom} : motif invalide ({raison})")
            continue

        # ⚠️ UN MOTIF QUI ACCEPTE LE VIDE ne contrôle rien : `motif_requis =
        # 'SPDX|'` est satisfait par N'IMPORTE QUEL fichier (faux vert), et un
        # `motif` interdit qui accepte le vide signalerait chaque position de
        # chaque fichier. Une branche vide est presque toujours une faute.
        if motif.search(""):
            soucis.append(f"{nom} : le motif accepte le texte vide - il ne controlerait rien")
            continue

        racine = config.RACINE / str(brute.get("racine", "")).strip("/")
        if not racine.is_dir():
            soucis.append(f"{nom} : dossier '{brute.get('racine')}' introuvable")
            continue
        # `strip("/")` neutralise un chemin absolu, pas `..` : `racine = "../"`
        # faisait scanner les dépôts VOISINS, et leurs fichiers finissaient
        # dans ce rapport.
        if not racine.resolve().is_relative_to(config.RACINE.resolve()):
            soucis.append(f"{nom} : racine '{brute.get('racine')}' hors du projet - ignoree")
            continue

        # Un texte à la place d'une liste se découpe en LETTRES : `exclure =
        # "tests"` écartait tout chemin contenant un t, un e ou un s — donc
        # presque tout, en silence.
        champs_listes = [champ for champ in ("suffixes", "exclure")
                         if not (isinstance(brute.get(champ, []), list)
                                 and all(isinstance(x, str) for x in brute.get(champ, [])))]
        if champs_listes:
            soucis.append(f"{nom} : {', '.join(champs_listes)} doit etre une liste de textes")
            continue
        if not isinstance(brute.get("bloquant", False), bool):
            soucis.append(f"{nom} : bloquant n'accepte que true ou false")
            continue

        regles.append({
            "nom": nom,
            # Le LIEN vers la ligne de doc qui enonce la regle, ex.
            # « CLAUDE.md#Zéro dépendance » (le début de sa phrase) ou
            # « CLAUDE.md:23 ». Facultatif, mais c'est lui qui rend la
            # couverture EXACTE au lieu d'heuristique — et qui evite de
            # recopier la phrase ici, donc de la laisser deriver.
            "source": str(brute.get("source", "")),
            "regle": str(brute.get("regle", "")),
            "racine": racine,
            "suffixes": tuple(brute.get("suffixes", ())),
            # `motif` porte TOUJOURS le motif cherché, quel que soit le sens :
            # `requis` dit lequel. Deux clés séparées obligeraient chaque
            # lecteur à gérer un `None`.
            "motif": motif,
            "requis": bool(oblige),
            "si": si,
            # Ou la regle est ECRITE, pour renvoyer l'utilisateur dessus quand
            # elle ne verifie rien. (None, None) si on n'a pas su la situer.
            "ou": reperes.get(nom, (None, None)),
            "exclure": tuple(brute.get("exclure", ())),
            "bloquant": bool(brute.get("bloquant", False)),
            "exemples": tuple(exemples),
        })
        # Vérifié à CHAQUE lancement, pas seulement par `lintorn regles --test` :
        # une règle qui ne trouve pas son propre exemple ne protège peut-être rien.
        for numero, exemple in enumerate(exemples, 1):
            raison = config.rate_son_exemple(regles[-1], exemple)
            if raison:
                quel = f"son exemple {numero}" if len(exemples) > 1 else "son exemple"
                soucis.append(f"{nom} : {quel} {raison} - la regle ne protege peut-etre rien")

    config.SOUCIS_CONFIG.extend(soucis)
    return regles, hors_portee
