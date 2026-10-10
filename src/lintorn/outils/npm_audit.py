# Lintorn
"""npm audit : les failles connues des paquets JS. Sa commande et sa traduction."""

from __future__ import annotations

from pathlib import Path

from .. import base, config, traductions
from . import commun


def commande(front: Path | None) -> dict | None:
    """La commande `npm audit` de ce front, ou None si elle n'aurait rien à lire.

    ⚠️ npm audit lit le VERROU, pas `package.json` : sans lui, il refuse de
    répondre. Proposé sans verrou, le contrôle resterait « INDISPONIBLE » à
    vie — un voyant qu'on apprend à ignorer.

    ⚠️ Sa propre clé d'accord, `failles_npm`, et non `failles` : un accord
    donné pour pip-audit ne vaut pas pour un AUTRE appel réseau. Réutiliser la
    clé ferait sortir sur le réseau, à la simple mise à jour de Lintorn, un
    projet qui n'avait rien demandé de tel.
    """
    if front is None or not (front / config.VERROU_NPM).is_file():
        return None
    return {
        "cle": "failles_npm",
        "opt_in": True,      # sort sur le RESEAU
        "titre": "Failles connues JS (npm audit)",
        # `--json` et pas le texte : npm sort en 1 aussi bien quand il TROUVE
        # des failles que quand il ne PEUT PAS répondre (réseau coupé, verrou
        # illisible). Seul le JSON sépare les deux — `traduire()`, plus bas.
        "cmd": [config.NPM, "audit", "--json"],
        "cwd": front,
        "bloquant": False,
        "traduction": "npm_audit",
        "lent": True,
        # 0 AUSSI : un registre qui refuse l'audit peut sortir en 0 avec une
        # erreur dans son JSON — « rien a signaler » alors que rien n'a été
        # vérifié. Le traducteur rend lui-même le vert quand il est mérité.
        "codes_alerte": (0, 1),
    }



def _correctif_npm(correctif) -> str:
    """La colonne « Correctif » : `fixAvailable` vaut True, False ou un objet."""
    if correctif is True:
        return "`npm audit fix`"
    if isinstance(correctif, dict):
        cible = f"`{commun.cellule(correctif.get('name'), 80)}@{commun.cellule(correctif.get('version'), 40)}`"
        if correctif.get("isSemVerMajor") is True:
            return f"{cible} — version MAJEURE, à tester à part (`npm audit fix --force`)"
        return cible
    return "aucun pour l'instant"


def _paquets_audites_npm(donnees: dict) -> int | None:
    """Le nombre de paquets que npm a audités, ou None s'il ne le dit pas.

    npm 7 et suivants : `metadata.dependencies.total` ; npm 6 :
    `metadata.totalDependencies`. Le paquet du projet lui-même n'y compte pas.
    """
    meta = commun.table(donnees.get("metadata"))
    dependances = meta.get("dependencies")
    total = (dependances.get("total") if isinstance(dependances, dict)
             else meta.get("totalDependencies", dependances))
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        return None
    return total


def traduire(resultat: base.Resultat) -> base.Resultat:
    """Lit le JSON de `npm audit` : des failles TROUVÉES, ou une réponse IMPOSSIBLE ?

    ⚠️ npm sort en 1 dans les deux cas — failles trouvées, verrou absent,
    registre injoignable. Au seul code de sortie, un réseau coupé passait pour
    des failles : un rouge qui ne dit rien de vrai, et qu'on apprend vite à
    ignorer. Seul le JSON sépare la trouvaille de la panne.

    ⚠️ Et le code 0 n'est pas un feu vert : un registre qui refuse l'audit peut
    sortir en 0 avec une erreur dans son JSON. Ce traducteur voit donc AUSSI
    les sorties en 0 (`codes_alerte` de la commande).

    Défensif à chaque niveau : un JSON de forme inattendue ne fait jamais
    tomber l'audit — il retombe sur la sortie brute, affichée telle quelle.
    """
    donnees = commun.premier_json(resultat.detail)
    if donnees is None:
        # Aucun JSON : on ne sait RIEN des failles. Le rouge dirait « il y en
        # a », le vert « il n'y en a pas » ; les deux mentiraient.
        return base.Resultat(
            resultat.titre, "INDISPONIBLE",
            "npm audit n'a pas repondu en JSON - rien n'a ete verifie",
            resultat.detail, bloquant=False, code_sortie=resultat.code_sortie,
        )

    if "error" in donnees:
        erreur = donnees.get("error")
        erreur = erreur if isinstance(erreur, dict) else {"summary": erreur}
        message = str(donnees.get("message") or "")
        raison = (erreur.get("code")
                  or message.rsplit("reason:", 1)[-1].strip()
                  or erreur.get("summary")
                  or "raison inconnue")
        explication = "\n".join(
            str(morceau) for morceau in
            (erreur.get("summary"), erreur.get("detail"), message) if morceau
        )
        return base.Resultat(
            resultat.titre, "INDISPONIBLE",
            f"npm audit n'a pas pu repondre ({commun.cellule(raison, 60)}) - rien n'a ete verifie",
            explication, bloquant=False, code_sortie=resultat.code_sortie,
        )

    failles = donnees.get("vulnerabilities")
    if not isinstance(failles, dict):
        return resultat
    failles = {str(nom): faille for nom, faille in failles.items() if isinstance(faille, dict)}
    if not failles:
        # Une liste VIDE est une vraie réponse : le cas d'erreur est traité
        # plus haut, et n'arrive jamais jusqu'ici. Mais un verrou sans aucune
        # dépendance rend la même liste vide : le vert dit donc SUR QUOI il
        # porte, et zéro paquet n'est pas un vert.
        total = _paquets_audites_npm(donnees)
        if total == 0:
            return base.Resultat(resultat.titre, "INDISPONIBLE",
                            "le verrou ne liste aucune dependance - rien a verifier",
                            resultat.detail, bloquant=False, code_sortie=resultat.code_sortie)
        resume = (f"aucune faille connue dans {total} paquet(s)" if total is not None
                  else "rien a signaler (npm ne dit pas combien de paquets il a audites)")
        return base.Resultat(resultat.titre, "OK", resume, resultat.detail,
                        resultat.bloquant, code_sortie=resultat.code_sortie)

    rang = {gravite: i for i, gravite in enumerate(traductions.GRAVITES)}

    def gravite_de(faille: dict) -> str:
        gravite = faille.get("severity")
        return gravite if isinstance(gravite, str) and gravite in rang else "unknown"

    compte = dict.fromkeys(traductions.GRAVITES, 0)
    lignes = [
        "| Paquet | Gravité | Versions touchées | Correctif | Pourquoi |",
        "|---|---|---|---|---|",
    ]
    for nom, faille in sorted(failles.items(),
                              key=lambda item: (rang[gravite_de(item[1])], item[0])):
        gravite = gravite_de(faille)
        compte[gravite] += 1
        raisons = []
        for source in commun.liste(faille.get("via")):
            if isinstance(source, dict):
                raisons.append(commun.lien_web(source.get("title", "avis de sécurité"), source.get("url")))
            elif isinstance(source, str):
                raisons.append(f"via `{commun.cellule(source, 80)}`")
        direct = " (direct)" if faille.get("isDirect") is True else ""
        lignes.append(
            f"| `{commun.cellule(nom, 80)}`{direct} | {traductions.GRAVITES[gravite]} "
            f"| {commun.cellule(faille.get('range', '?'), 80)} "
            f"| {_correctif_npm(faille.get('fixAvailable'))} "
            f"| {'<br>'.join(raisons) or '—'} |"
        )

    dossier = "."
    if config.FRONTEND and config.FRONTEND != config.RACINE:
        dossier = config.FRONTEND.relative_to(config.RACINE).as_posix()
    lignes += [
        "",
        f"Corriger : `npm audit fix` dans `{dossier}`, puis relancer les tests et le "
        "build. Une version MAJEURE peut casser l'application : à faire à part, en "
        "lisant ses notes de version.",
    ]

    detail_gravites = ", ".join(
        f"{traductions.GRAVITES[gravite]} : {nombre}"
        for gravite, nombre in compte.items() if nombre
    )
    resultat.detail = "\n".join(lignes)
    resultat.resume = f"{len(failles)} paquet(s) vulnerable(s) - {detail_gravites}"
    resultat.detail_markdown = True
    return resultat
