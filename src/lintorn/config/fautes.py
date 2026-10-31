# Lintorn
"""Les fautes de frappe des fichiers de Lintorn, celles que `lintorn corrige` répare sans deviner."""

from __future__ import annotations

import difflib
import re
import unicodedata
from pathlib import Path
from typing import NamedTuple

from .. import config


class Faute(NamedTuple):
    numero: int       # la ligne, à partir de 1
    ligne: str        # telle qu'elle est écrite
    corrigee: str     # telle qu'elle devrait l'être
    ecrit: str        # le nom mal tapé
    juste: str        # le nom qu'il visait
    table: bool       # un en-tête de table, pas une clé


# Un en-tête de table : `[nom]` ou `[[nom]]`, suivi au plus d'un commentaire.
_RX_ENTETE = re.compile(r"^(\s*)(\[\[?)\s*([^\[\]#]+?)\s*(\]\]?)(\s*(?:#.*)?)$")
# Une clé nue en début de ligne : `bloquan = true`.
_RX_CLE = re.compile(r"^(\s*)([A-Za-z0-9_-]+)(\s*=)")
# Assez proche pour être SÛR. `rules` vise `regles` ; pour une clé, plus strict :
# `regex` n'est pas une faute de `regle`, c'est une autre idée.
_PROCHE_TABLE = 0.7
_PROCHE_CLE = 0.85


def _simple(nom: str) -> str:
    """Sans accent ni majuscule : `Régles` et `regles` sont le même nom."""
    return "".join(c for c in unicodedata.normalize("NFKD", nom)
                   if not unicodedata.combining(c)).lower()


def _le_plus_proche(nom: str, connus, seuil: float) -> str | None:
    simple = _simple(nom)
    exact = [connu for connu in connus if _simple(connu) == simple]
    if exact:
        return exact[0]
    proche = difflib.get_close_matches(simple, sorted(connus), n=1, cutoff=seuil)
    return proche[0] if proche else None


def fautes_de_frappe(texte: str, tables: dict[str, bool],
                     cles: dict[str, set[str]]) -> list[Faute]:
    """Les en-têtes et les clés mal tapés de `texte`, avec leur correction.

    `tables` : {nom: est une liste} des tables que le fichier peut ouvrir,
    `[[regles]]` (liste) ou `[controles]`. `cles` : {table: clés connues}, la
    table `""` étant le haut du fichier. Un nom loin de tout nom connu n'est
    pas corrigé : `[[hors_portee]]` n'est pas une faute de `[[regles]]`, et le
    « corriger » fabriquerait une règle. Une ligne dans une chaîne sur plusieurs
    lignes n'est ni un en-tête ni une clé.
    """
    fautes = []
    table: str | None = ""
    dans_une_chaine = False
    for numero, ligne in enumerate(texte.splitlines(), 1):
        if (ligne.count('"' * 3) + ligne.count("'" * 3)) % 2:
            dans_une_chaine = not dans_une_chaine
            continue
        if dans_une_chaine:
            continue
        entete = _RX_ENTETE.match(ligne)
        if entete:
            retrait, ouvre, nom, ferme, fin = entete.groups()
            nom = nom.strip().strip("\"'")
            juste = (nom if nom in tables else _le_plus_proche(nom, tables, _PROCHE_TABLE)
                     ) if "." not in nom else None
            table = juste
            if juste is None:
                continue        # une table inconnue : rien de sûr à dire de ses clés
            liste = tables[juste]
            if nom != juste or (ouvre, ferme) != (("[[", "]]") if liste else ("[", "]")):
                bonne = f"{retrait}{'[[' if liste else '['}{juste}{']]' if liste else ']'}{fin}"
                fautes.append(Faute(numero, ligne, bonne, nom, juste, table=True))
            continue
        cle = _RX_CLE.match(ligne) if table is not None else None
        if not cle:
            continue
        retrait, nom, _ = cle.groups()
        connues = cles.get(table)
        if connues is None or nom in connues:
            continue
        juste = _le_plus_proche(nom, connues, _PROCHE_CLE)
        if juste:
            fautes.append(Faute(numero, ligne, retrait + juste + ligne[len(retrait) + len(nom):],
                                nom, juste, table=False))
    return fautes


def _schemas() -> dict[Path, tuple[dict[str, bool], dict[str, set[str]]]]:
    """Ce que chaque fichier de Lintorn peut contenir : ses tables, et les clés de chacune."""
    controles = {*config.OBJET_DES_CLES, *config._CONTROLES_DEFAUT}
    return {
        config.FICHIER_REGLES: ({"regles": True},
                                {"": {"regles"}, "regles": config._CLES_REGLE}),
        config.DOSSIER_LINTORN / "config.toml": (
            {"controles": False, "regles": True, "commandes": True},
            {"": set(config._TYPES_CONFIG), "controles": controles,
             "regles": config._CLES_REGLE, "commandes": config._CLES_COMMANDE}),
    }


def fautes_des_fichiers() -> list[tuple[Path, list[Faute]]]:
    """(fichier, ses fautes) pour regles.toml et config.toml, ceux qui en ont."""
    trouvees = []
    for fichier, (tables, cles) in config._schemas().items():
        try:
            texte = fichier.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        fautes = config.fautes_de_frappe(texte, tables, cles)
        if fautes:
            trouvees.append((fichier, fautes))
    return trouvees
