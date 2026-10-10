# Lintorn
"""Ce que les traductions partagent : lire un JSON, écrire une cellule, un lien sûr."""

from __future__ import annotations

import json
import re


def premier_json(texte: str) -> dict | None:
    """Le premier objet JSON de `texte`, ou None s'il n'y en a pas de lisible.

    `lancer()` colle la sortie d'erreur APRÈS la sortie standard : les
    avertissements de npm suivent son JSON. On lit le premier objet complet et
    on ignore ce qui le suit, au lieu d'échouer sur le mélange des deux. Un
    JSON imbriqué à l'extrême (`RecursionError`) compte comme illisible.
    """
    debut = texte.find("{")
    if debut < 0:
        return None
    try:
        objet, _ = json.JSONDecoder().raw_decode(texte[debut:])
    except (ValueError, RecursionError):
        return None
    return objet if isinstance(objet, dict) else None


# ⚠️ Un titre d'avis ou un nom de paquet vient de L'EXTÉRIEUR — un registre,
# une base publique. Un saut de ligne suivi de `## [ OK ]` y injectait une
# fausse section verte, qu'un humain ou un assistant IA aurait pu croire. Dans
# une cellule : une seule ligne, et rien qui fabrique du Markdown ou du HTML.
_RX_URL_SURE = re.compile(r"^https?://[^\s()<>\[\]]+$")


def cellule(valeur, longueur: int = 160) -> str:
    texte = " ".join(str(valeur).split())
    for brut, sur in (("\\", "\\\\"), ("|", "\\|"), ("`", "'"), ("[", "\\["),
                      ("]", "\\]"), ("<", "&lt;"), (">", "&gt;")):
        texte = texte.replace(brut, sur)
    return texte[:longueur]


def lien_web(titre, url) -> str:
    """Un lien Markdown — seulement vers une adresse http(s) sans surprise."""
    titre = cellule(titre) or "avis"
    url = str(url or "")
    return f"[{titre}]({url})" if _RX_URL_SURE.match(url) else titre


def liste(valeur) -> list:
    return valeur if isinstance(valeur, list) else []


def table(valeur) -> dict:
    return valeur if isinstance(valeur, dict) else {}


def raison_de_l_echec(sortie: str) -> str:
    """La dernière erreur d'un outil, réduite à ce qui tient dans un résumé.

    ⚠️ PAS `_cellule` : elle échappe le Markdown pour les tableaux du rapport,
    et ces échappements s'affichaient tels quels dans la console —
    `(\\[Errno 111\\] Connection refused"))))`.
    """
    for ligne in reversed(sortie.splitlines()):
        if "rror" in ligne or "failed" in ligne:
            return " ".join(ligne.rsplit(": ", 1)[-1].split())[:60]
    return "raison inconnue"
