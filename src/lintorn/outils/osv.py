# Lintorn
"""OSV-Scanner : les failles des AUTRES langages, lues dans leurs verrous."""

from __future__ import annotations

from pathlib import Path

from .. import base, config, traductions
from . import commun


def commande(ecosystemes: dict, demande: bool = False) -> dict | None:
    """La commande OSV-Scanner, ou None si le projet n'a rien pour elle.

    `demande` : le projet l'a ACCORDÉE explicitement. Elle tourne alors même
    sans verrou reconnu ici — OSV-Scanner connaît plus de formats que
    `VERROUS_OSV`, et s'il ne trouve rien, il le dit lui-même (code 128).
    Refuser l'accord, c'était priver d'audit un projet qu'OSV sait lire, avec
    un message qui affirmait qu'il n'y avait rien à lire.
    """
    if not ecosystemes and not demande:
        return None
    return {
        "cle": "failles_osv",
        "opt_in": True,      # sort sur le RESEAU
        "titre": "Failles connues (OSV-Scanner)",
        # `--no-call-analysis=all` : l'analyse d'appels COMPILE le projet — et
        # lance ses scripts de build en Rust. L'accord donné ici porte sur le
        # réseau, pas sur l'exécution du code du projet.
        # `--all-packages` : sans lui, un OSV sans faille rend un JSON vide,
        # et le vert ne peut pas dire quels verrous il a lus.
        "cmd": [config.OSV, "scan", "source", "--recursive", "--format", "json",
                "--no-call-analysis=all", "--all-packages", "--verbosity", "error", "."],
        "cwd": config.RACINE,
        "bloquant": False,
        "traduction": "osv",
        "lent": True,
        # 0 = aucune faille, 1 = failles trouvées, 128 = aucun verrou lisible,
        # 127 = pas de réponse (réseau, verrou illisible) : `traduire()`, plus bas
        # départage, et ne rend le vert qu'en disant ce qu'il a lu.
        "codes_alerte": (0, 1, 127, 128),
    }



def _gravite_cvss(score) -> str:
    """Le score CVSS qu'OSV donne à une faille (« 7.5 », ou vide), ramené aux
    niveaux de `traductions.GRAVITES` — l'échelle officielle du CVSS 3."""
    try:
        valeur = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if valeur >= 9.0:
        return "critical"
    if valeur >= 7.0:
        return "high"
    if valeur >= 4.0:
        return "moderate"
    return "low" if valeur > 0 else "unknown"


def _corrige_en(failles: list, ids: list, paquet: dict) -> str:
    """Les versions qui corrigent ces failles POUR ce paquet, lues dans OSV.

    Les plages `GIT` sont ignorées : elles donnent un commit, pas une version
    qu'on pourrait demander à son gestionnaire de paquets.
    """
    versions: list[str] = []
    for faille in failles:
        if faille.get("id") not in ids:
            continue
        for affecte in commun.liste(faille.get("affected")):
            affecte = commun.table(affecte)
            cible = commun.table(affecte.get("package"))
            if (cible.get("name"), cible.get("ecosystem")) != (paquet.get("name"),
                                                              paquet.get("ecosystem")):
                continue
            for plage in commun.liste(affecte.get("ranges")):
                plage = commun.table(plage)
                if plage.get("type") == "GIT":
                    continue
                for evenement in commun.liste(plage.get("events")):
                    version = commun.table(evenement).get("fixed")
                    if isinstance(version, str) and version and version not in versions:
                        versions.append(version)
    return commun.cellule(", ".join(versions), 80) or "aucune pour l'instant"


_LIGNES_OSV_MAX = 60


def _fichier_depuis_la_racine(chemin: str) -> str:
    """Un fichier nommé depuis la racine du projet ; son seul nom s'il est ailleurs."""
    try:
        return Path(chemin).resolve().relative_to(config.RACINE.resolve()).as_posix()
    except (ValueError, OSError):
        return Path(chemin).name


def _verrous_lus_par_osv(lus: dict[str, int]) -> tuple[list[str], list[str]]:
    """(le paragraphe « Verrous lus » du rapport, les verrous attendus NON lus).

    Les verrous attendus sont ceux que la détection a annoncés comme raison
    d'activer OSV. Un verrou dont OSV n'a tiré aucun paquet n'est pas audité :
    le dire, plutôt que laisser croire que son écosystème est sain.
    """
    attendus = sorted({_fichier_depuis_la_racine(str(chemin))
                       for chemins in config.ECOSYSTEMES_OSV.values() for chemin in chemins})
    non_lus = [verrou for verrou in attendus if not lus.get(verrou)]
    lecture = ["Verrous lus : " + (", ".join(
        f"`{commun.cellule(verrou, 120)}` ({nombre} paquet(s))"
        for verrou, nombre in sorted(lus.items()) if nombre) or "aucun") + "."]
    if non_lus:
        lecture += ["", f"**Non lus ({len(non_lus)})** — OSV-Scanner n'en a tiré aucun "
                    "paquet : leurs failles ne sont pas cherchées. "
                    + ", ".join(f"`{commun.cellule(verrou, 120)}`" for verrou in non_lus) + "."]
    return lecture, non_lus


def _osv_sans_faille(resultat: base.Resultat, lus: dict[str, int], lecture: list[str],
                     non_lus: list[str]) -> base.Resultat:
    """Le vert d'OSV — seulement s'il a lu quelque chose, et en disant quoi."""
    titre, code = resultat.titre, resultat.code_sortie
    total = sum(lus.values())
    if not total:
        return base.Resultat(titre, "INDISPONIBLE",
                        "OSV-Scanner n'a lu aucun paquet - rien n'a ete verifie",
                        "\n".join(lecture), bloquant=False, detail_markdown=True,
                        code_sortie=code)
    resume = (f"aucune faille connue dans {total} paquet(s) de "
              f"{sum(1 for nombre in lus.values() if nombre)} verrou(s)")
    if non_lus:
        # Gris-jaune, pas vert : un écosystème annoncé n'a pas été audité.
        return base.Resultat(titre, "VERIF", f"{resume}, mais {len(non_lus)} verrou(s) NON lu(s)",
                        "\n".join(lecture), resultat.bloquant, detail_markdown=True,
                        code_sortie=code)
    return base.Resultat(titre, "OK", resume, "\n".join(lecture), resultat.bloquant,
                    detail_markdown=True, detail_meme_au_vert=True, code_sortie=code)


def traduire(resultat: base.Resultat) -> base.Resultat:
    """Lit OSV-Scanner. LE CODE DE SORTIE D'ABORD, le JSON ensuite.

    ⚠️ Réseau coupé, OSV-Scanner sort en 127 mais écrit quand même un JSON
    VALIDE — et VIDE : `"results": []`. Lu seul, ce JSON annonçait « aucune
    faille » : le faux vert parfait, sur un contrôle de sécurité. C'est le
    code de sortie qui tranche, avant toute lecture.

      0   aucune faille         → vert, avec ce qui a été lu
      1   des failles trouvées  → le tableau
      128 aucun verrou lisible  → rien n'a été vérifié
      127 pas de réponse (réseau coupé, verrou illisible) → idem

    ⚠️ Le vert dit SUR QUOI il porte : combien de paquets, dans quels
    verrous. Sans cela, « 0 faille Dart » ne se distinguait pas d'un
    `pubspec.lock` jamais lu. D'où `--all-packages` dans la commande : sans
    lui, un OSV sans faille rend `"results": []` et ne dit rien de ce qu'il a
    lu.

    ⚠️ Aucune faille n'est écartée comme « déjà vue » par npm audit ou
    pip-audit : pip-audit lit le venv, pas les fichiers de dépendances, et un
    audit natif en panne ne couvre rien. Un doublon plutôt qu'un oubli.
    """
    titre, code = resultat.titre, resultat.code_sortie
    if code == 128:
        return base.Resultat(titre, "INDISPONIBLE",
                        "OSV-Scanner n'a trouve aucun verrou lisible - rien n'a ete verifie",
                        resultat.detail, bloquant=False, code_sortie=code)
    if code not in (0, 1):
        return base.Resultat(
            titre, "INDISPONIBLE",
            f"OSV-Scanner n'a pas pu repondre ({commun.raison_de_l_echec(resultat.detail)})"
            " - rien n'a ete verifie",
            resultat.detail, bloquant=False, code_sortie=code,
        )

    donnees = commun.premier_json(resultat.detail)
    sources = donnees.get("results") if donnees else None
    if not isinstance(sources, list):
        if code == 0:
            # Sorti en 0 sans réponse lisible : on ne sait RIEN. Pas un vert.
            return base.Resultat(titre, "INDISPONIBLE",
                            "OSV-Scanner a repondu sans JSON lisible - rien n'a ete verifie",
                            resultat.detail, bloquant=False, code_sortie=code)
        return resultat          # format inattendu : on garde le brut

    rang = {gravite: i for i, gravite in enumerate(traductions.GRAVITES)}
    compte = dict.fromkeys(traductions.GRAVITES, 0)
    lignes: list[tuple[int, str, str]] = []
    paquets: set[tuple] = set()
    lus: dict[str, int] = {}             # {verrou : paquets lus dedans}
    for source in sources:
        source = commun.table(source)
        ou = _fichier_depuis_la_racine(str(commun.table(source.get("source")).get("path", "")))
        lus[ou] = lus.get(ou, 0) + len(commun.liste(source.get("packages")))
        for entree in commun.liste(source.get("packages")):
            entree = commun.table(entree)
            paquet = commun.table(entree.get("package"))
            failles = [faille for faille in commun.liste(entree.get("vulnerabilities"))
                       if isinstance(faille, dict)]
            nom, version, ecosysteme = (commun.cellule(paquet.get(champ, ""), 80)
                                        for champ in ("name", "version", "ecosystem"))
            for groupe in commun.liste(entree.get("groups")):
                groupe = commun.table(groupe)
                ids = [ident for ident in commun.liste(groupe.get("ids")) if isinstance(ident, str)]
                if not ids:
                    continue
                gravite = _gravite_cvss(groupe.get("max_severity"))
                compte[gravite] += 1
                paquets.add((ecosysteme, nom, version))
                resume = next((commun.cellule(faille.get("summary") or "", 140) for faille in failles
                               if faille.get("id") == ids[0]), "")
                lignes.append((rang[gravite], nom,
                    f"| `{nom}` {version} ({ecosysteme or '?'}) | `{commun.cellule(ou, 120)}` "
                    f"| {traductions.GRAVITES[gravite]} "
                    f"({commun.cellule(groupe.get('max_severity') or '?', 10)}) "
                    f"| {commun.lien_web(ids[0], 'https://osv.dev/vulnerability/' + ids[0])} {resume} "
                    f"| {_corrige_en(failles, ids, paquet)} |"))

    lecture, non_lus = _verrous_lus_par_osv(lus)
    if not lignes:
        if code == 1:
            # Code 1 — « des failles » — mais aucune lisible : la forme a
            # changé. Surtout pas un vert : on garde la sortie brute, en alerte.
            return resultat
        return _osv_sans_faille(resultat, lus, lecture, non_lus)

    lignes.sort()
    tableau = [
        *lecture,
        "",
        "| Paquet | Où | Gravité | Faille | Corrigé en |",
        "|---|---|---|---|---|",
        *(ligne for _, _, ligne in lignes[:_LIGNES_OSV_MAX]),
    ]
    if len(lignes) > _LIGNES_OSV_MAX:
        tableau.append(f"\n*… et {len(lignes) - _LIGNES_OSV_MAX} autre(s).*")
    tableau += [
        "",
        "Corriger : monter chaque paquet à une version « Corrigé en » avec l'outil "
        "de son écosystème (`cargo update`, `go get`, `composer update`…), puis "
        "relancer les tests. OSV-Scanner lit aussi les verrous npm et Python : une "
        "faille déjà signalée par npm audit ou pip-audit peut réapparaître ici.",
    ]
    detail_gravites = ", ".join(f"{traductions.GRAVITES[gravite]} : {nombre}"
                                for gravite, nombre in compte.items() if nombre)
    resultat.detail = "\n".join(tableau)
    resultat.resume = f"{len(lignes)} faille(s) dans {len(paquets)} paquet(s) - {detail_gravites}"
    resultat.detail_markdown = True
    return resultat
