# Lintorn
"""Lintorn a-t-il pu lire la config du projet, et que reste-t-il à accorder ?"""

from __future__ import annotations

from ... import config
from ...base import Resultat

TITRE = "Configuration (Lintorn)"


def controle_configuration() -> Resultat:
    """Ce que Lintorn n'a pas réussi à charger, et qu'il taisait.

    Un TOML illisible, une règle au motif invalide, une commande dont le
    dossier n'existe pas : chacun était écarté en silence, et le rapport
    restait complet et confiant. Un TOML cassé fait même repartir Lintorn sur
    ses valeurs par DÉFAUT — `docs_exclus`, contrôles coupés et règles maison
    ignorés en bloc.

    NON BLOQUANT, comme le hook et le venv : c'est l'outillage qui est abîmé,
    pas le code du projet. `_signaler_non_bloquants()` le nomme dans le
    verdict, il ne se tait pas pour autant.
    """
    titre = TITRE

    if config.SOUCIS_CONFIG:
        return Resultat(
            titre, "ALERTE",
            f"{len(config.SOUCIS_CONFIG)} consigne(s) NON CHARGEE(S) - "
            "Lintorn controle moins que tu ne crois",
            "Lintorn n'a pas pu charger tout ce que ce projet lui demande. Ce "
            "qui suit **n'est donc surveille par personne**, et les autres "
            "controles du rapport restent verts sans le savoir :\n\n"
            + "\n".join(f"- {souci}" for souci in config.SOUCIS_CONFIG)
            + "\n\nUn TOML illisible fait repartir Lintorn sur ses **valeurs "
            "par defaut** : `docs_exclus`, les controles que tu avais coupes "
            "et tes regles maison sont alors ignores en bloc.",
            bloquant=False, detail_markdown=True,
        )

    # Aucun fichier lu n'est PAS un feu vert : il n'y a simplement rien a
    # valider. Le dire, plutot que d'afficher un OK sur le vide.
    if not config.FICHIERS_CONFIG_LUS:
        return Resultat(
            titre, "INDISPONIBLE",
            "aucun fichier de configuration - `lintorn init`"
            + _combien_de_disponibles(),
            # C'est le PREMIER lancement : le moment ou savoir ce qui existe
            # sert le plus. Le nommer ici, et pas seulement une fois configure.
            _disponibles_md(), bloquant=False, detail_markdown=True,
        )

    # Le DÉNOMINATEUR : sans lui, ce vert ne distingue pas « tout va bien » de
    # « je n'ai rien ouvert ».
    resume = (f"{' + '.join(config.FICHIERS_CONFIG_LUS)} lu(s), "
              f"{len(config.REGLES_MAISON)} regle(s) maison chargee(s)")
    if not config.CONTROLES_DISPONIBLES:
        return Resultat(titre, "OK", resume, bloquant=False)

    return Resultat(
        titre, "OK", resume + _combien_de_disponibles(), _disponibles_md(),
        bloquant=False, detail_markdown=True, detail_meme_au_vert=True,
    )


def _combien_de_disponibles() -> str:
    """« , 3 controle(s) disponible(s) NON actives » — ou rien."""
    if not config.CONTROLES_DISPONIBLES:
        return ""
    return f", {len(config.CONTROLES_DISPONIBLES)} controle(s) disponible(s) NON actives"


def _disponibles_md() -> str:
    """Les contrôles qui s'appliquent au projet et qu'il n'a pas accordés.

    ⚠️ Un contrôle opt-in non activé DISPARAÎT du rapport : rien ne distingue
    alors « ce projet n'a pas de front » de « tu n'as jamais accordé npm
    audit ». Un silence pareil se lit comme un feu vert.
    """
    if not config.CONTROLES_DISPONIBLES:
        return ""
    return (
        "Ces contrôles s'appliquent à ce projet mais **n'ont pas tourné** : ils "
        "exécutent ton code, ouvrent ta base ou sortent sur le réseau, et "
        "attendent donc un accord explicite. Leur silence n'est pas un feu "
        "vert :\n\n"
        + "\n".join(f"- `{cle}` — {titre_controle}"
                     for cle, titre_controle in config.CONTROLES_DISPONIBLES)
        + "\n\n`lintorn outils` les propose un par un, ou "
        "directement dans ta configuration :\n\n```toml\n[controles]\n"
        + "\n".join(f"{cle} = true" for cle, _ in config.CONTROLES_DISPONIBLES)
        + "\n```"
    )
