# Lintorn
"""pip-audit : les failles connues des paquets Python. Sa commande et sa traduction."""

from __future__ import annotations

from .. import base, config
from . import commun


# `BACKEND or PY_RACINE` : même dossier que vulture (voir `outils/vulture.py`).
def commande() -> dict:
    """Les failles connues des paquets Python — opt-in : réseau."""
    return {
        "cle": "failles",
        "opt_in": True,      # sort sur le RESEAU
        "titre": "Failles connues (pip-audit)",
        # `--format json` : sans lui, une panne de reseau et des failles
        # trouvees rendaient le meme rouge (voir `traduire()`, plus bas).
        "cmd": [config.PYTHON, "-m", "pip_audit", "--progress-spinner", "off", "--format", "json"],
        "cwd": config.BACKEND or config.PY_RACINE,
        "bloquant": False,
        "traduction": "pip_audit",
        "lent": True,
        # 0 AUSSI : le vert doit dire sur combien de paquets, et lesquels
        # pip-audit a sautés. Le traducteur le rend lui-même quand il est mérité.
        "codes_alerte": (0, 1),
    }



def traduire(resultat: base.Resultat) -> base.Resultat:
    """Lit le JSON de pip-audit : des failles TROUVÉES, ou pas de réponse ?

    ⚠️ pip-audit sort en 1 dans les deux cas — failles trouvées, et service
    injoignable (proxy d'entreprise, réseau coupé). Sans ce tri, le rapport
    affichait « 78 ligne(s) de sortie » sur un audit qui n'avait rien audité :
    un rouge qui ressemble à des failles. npm et OSV savaient déjà le dire ;
    Python était le dernier écosystème à ne pas le savoir.

    ⚠️ Le code 0 passe AUSSI par ici (`codes_alerte` de la commande) : rendu
    vert d'office, il ne disait ni sur combien de paquets, ni lesquels
    pip-audit avait SAUTÉS — le paquet du projet lui-même, absent de PyPI,
    l'est toujours. Un venv dont tout est sauté donnait le même vert.
    """
    donnees = commun.premier_json(resultat.detail)
    paquets = donnees.get("dependencies") if donnees else None
    if not isinstance(paquets, list):
        return base.Resultat(
            resultat.titre, "INDISPONIBLE",
            f"pip-audit n'a pas pu repondre ({commun.raison_de_l_echec(resultat.detail)})"
            " - rien n'a ete verifie",
            resultat.detail, bloquant=False, code_sortie=resultat.code_sortie,
        )

    lignes = ["| Paquet | Faille | Corrige en |", "|---|---|---|"]
    touches = 0
    audites = 0
    sautes: list[str] = []
    for paquet in paquets:
        paquet = commun.table(paquet)
        if paquet.get("skip_reason"):
            sautes.append(f"- `{commun.cellule(paquet.get('name', '?'), 80)}` — "
                          f"{commun.cellule(paquet['skip_reason'], 200)}")
            continue
        audites += 1
        failles = [faille for faille in commun.liste(paquet.get("vulns")) if isinstance(faille, dict)]
        if not failles:
            continue
        touches += 1
        nom = commun.cellule(paquet.get("name", "?"), 80)
        version = commun.cellule(paquet.get("version", "?"), 40)
        for faille in failles:
            noms = [str(faille.get("id", "?"))] + [alias for alias in commun.liste(faille.get("aliases"))
                                                   if isinstance(alias, str)]
            corrige = ", ".join(f"`{commun.cellule(version_sure, 40)}`"
                                for version_sure in commun.liste(faille.get("fix_versions"))
                                if isinstance(version_sure, str))
            lignes.append(f"| `{nom}` {version} | {commun.cellule(' / '.join(noms), 80)} "
                          f"| {corrige or 'aucun pour l instant'} |")

    non_audites = ([f"**Non audités ({len(sautes)})** — pip-audit les a sautés : leurs "
                    "failles ne sont pas cherchées.", "", *sautes] if sautes else [])

    if not touches:
        if resultat.code_sortie != 0:
            # Sorti en 1 sans une seule faille : on ne comprend pas, donc on
            # ne traduit pas. Le brut reste affiche, tel quel.
            return resultat
        if not audites:
            return base.Resultat(
                resultat.titre, "INDISPONIBLE",
                "aucun paquet audite" + (f" ({len(sautes)} saute(s))" if sautes else "")
                + " - rien n'a ete verifie",
                "\n".join(non_audites), bloquant=False, detail_markdown=True,
                code_sortie=resultat.code_sortie,
            )
        resume = f"aucune faille connue dans {audites} paquet(s)"
        if sautes:
            resume += f", {len(sautes)} non audite(s)"
        return base.Resultat(resultat.titre, "OK", resume, "\n".join(non_audites),
                        resultat.bloquant, detail_markdown=True,
                        detail_meme_au_vert=bool(sautes), code_sortie=resultat.code_sortie)

    if non_audites:
        lignes += ["", *non_audites]
    lignes += ["", "Corriger : `lintorn pip-audit` liste les montees, "
               "`--maj-securite --appliquer` les installe et repingle `requirements.txt`."]
    resultat.detail = "\n".join(lignes)
    resultat.resume = f"{touches} paquet(s) vulnerable(s)"
    resultat.detail_markdown = True
    return resultat
