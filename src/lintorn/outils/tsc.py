# Lintorn
"""TypeScript : `tsc --noEmit`, un par projet TS. Sa commande et sa traduction."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

from .. import base, config
from . import commun


def _cache_dans_lintorn(ou: str | None) -> list[str]:
    """Range le `.tsbuildinfo` dans `.lintorn/` au lieu du projet.

    `tsc --noEmit` écrit `tsconfig.tsbuildinfo` à côté du tsconfig dès que celui-ci
    est `incremental` ou `composite`. `--incremental` sert les projets qui ne
    disent rien : `--tsBuildInfoFile` seul serait refusé sans lui. Si `.lintorn/`
    est un lien, le chemin mènerait ailleurs : on ne le donne pas, et tsc
    retombe sur son défaut, dans le projet.
    """
    try:
        base.dossier_sur(config.DOSSIER_LINTORN)
    except OSError:
        return []
    nom = re.sub(r"[^A-Za-z0-9._-]+", "_", (ou or "racine").strip("/")) or "racine"
    return ["--incremental", "--tsBuildInfoFile",
            str(config.DOSSIER_LINTORN / "cache" / f"tsc-{nom}.tsbuildinfo")]


# Une commande PAR projet TS, toutes sous la clé `typescript` : `typescript =
# false` les coupe ensemble. Le titre nomme le dossier dès qu'il n'est pas la
# racine — deux lignes « TypeScript » identiques ne diraient pas laquelle a
# échoué.
def commandes() -> list[dict]:
    """Un `tsc --noEmit` par projet TypeScript détecté."""
    liste = []
    for projet in config.PROJETS_TS:
        ou = config._prefixe(projet)
        liste.append({
            "cle": "typescript",
            "titre": f"TypeScript {ou} (tsc --noEmit)" if ou else "TypeScript (tsc --noEmit)",
            "cmd": [str(config.tsc_de(projet)), "--noEmit", *_cache_dans_lintorn(ou)],
            "cwd": projet,
            "bloquant": True,
            # tsc sort en 2 pour des erreurs de type ET pour un tsconfig
            # invalide : seule sa sortie les départage (`traduire()`, plus bas).
            "traduction": "tsc",
            "lent": False,
            # 0 aussi : un tsconfig « solution » sort en 0 sans rien lire.
            "codes_alerte": (0, 1, 2),
            # Ce qui installe `tsc` quand il est introuvable : le gestionnaire
            # que désigne le verrou du projet, pas `npm install` d'office.
            "remede": config.remede_js(projet),
        })
    return liste


# Sortie de tsc, une erreur par ligne :
#   src/a.ts(1,7): error TS2322: Type 'string' is not assignable to type 'number'.
# ou, quand le tsconfig du projet active `pretty` (couleurs retirées) :
#   src/a.ts:1:7 - error TS2322: Type 'string' is not assignable to type 'number'.
_RX_TSC = re.compile(
    r"^(?P<fichier>\S.*?)(?:\((?P<ligne>\d+),\d+\):|:(?P<ligne_pretty>\d+):\d+ -)"
    r" error (?P<code>TS\d+): (?P<message>.*)$"
)


# Sans fichier, l'erreur vise le projet TypeScript lui-même :
#   error TS18003: No inputs were found in config file '…/tsconfig.json'.
_RX_TSC_SANS_FICHIER = re.compile(r"^error (?P<code>TS\d+): (?P<message>.*)$")


_RX_COULEURS = re.compile(r"\x1b\[[0-9;]*m")


def _depuis_la_racine(dossier: Path | None) -> str:
    """`dossier` vu depuis la racine du projet (`front`), ou "" s'il n'y est pas."""
    if dossier is None:
        return ""
    try:
        relatif = Path(dossier).resolve().relative_to(config.RACINE.resolve()).as_posix()
    except (ValueError, OSError):
        return ""
    return "" if relatif == "." else relatif


_RX_FICHIERS_VIDES = re.compile(r'"files"\s*:\s*\[\s*\]')
_RX_REFERENCES = re.compile(r'"references"\s*:')
_RX_INCLUDE = re.compile(r'"include"\s*:')


def _tsconfig_solution(dossier: Path | None) -> bool:
    """Le `tsconfig.json` ne fait que renvoyer vers d'autres (`files: []` + `references`) ?

    C'est le gabarit de Vite : `tsc --noEmit` y sort en 0, sans un mot, car il n'a
    AUCUN fichier à lire. Les vrais tsconfig sont à côté (`tsconfig.app.json`).
    Le fichier peut porter des commentaires (JSONC) : on cherche les clés au
    texte plutôt que de le faire lire par `json`.
    """
    if dossier is None:
        return False
    try:
        texte = (Path(dossier) / "tsconfig.json").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_RX_FICHIERS_VIDES.search(texte) and _RX_REFERENCES.search(texte)
                and not _RX_INCLUDE.search(texte))


def traduire(resultat: base.Resultat) -> base.Resultat:
    """Lit la sortie de tsc : des erreurs de TYPE, ou un projet qu'il ne peut pas lire ?

    ⚠️ tsc sort en 2 dans les deux cas : erreurs de type trouvées, et
    tsconfig invalide (`TS5023 Unknown compiler option`) ou sans rien à lire
    (`TS18003 No inputs were found`). Au seul code de sortie, des erreurs de
    type passaient pour un tsc planté, sans un compte ; et un tsc en panne ne
    se distinguait plus d'un code fautif.

    Seule la sortie les sépare. Une erreur de CODE vise une ligne d'un
    fichier source. Une PANNE n'a pas de fichier, vise un `.json`, ou porte
    un code TS5xxx — ceux des options du compilateur. Une sortie où l'on ne
    reconnaît ni l'une ni l'autre reste une panne : jamais un vert.
    """
    titre, bloquant, code_sortie = resultat.titre, resultat.bloquant, resultat.code_sortie
    if code_sortie == 0:
        if _tsconfig_solution(resultat.dossier):
            return base.Resultat(
                titre, "INDISPONIBLE",
                "tsconfig.json ne fait que renvoyer vers d'autres - rien n'a ete verifie",
                "Ce `tsconfig.json` a `files: []` et des `references` : `tsc --noEmit` "
                "n'y lit **aucun fichier** et sort en 0. Les types ne sont pas vérifiés.\n\n"
                "Déclarer les vrais fichiers de config dans une commande du projet, par "
                "exemple `tsc --noEmit -p tsconfig.app.json`.",
                bloquant=False, detail_markdown=True, code_sortie=code_sortie)
        return base.Resultat(titre, "OK", "rien a signaler", resultat.detail, bloquant,
                             code_sortie=code_sortie)
    prefixe = _depuis_la_racine(resultat.dossier)
    erreurs: list[list] = []            # [chemin depuis la racine, ligne, code, message]
    pannes: list[str] = []
    codes_pannes: list[str] = []
    suite_possible = False              # la ligne précédente était une erreur de code
    for brute in resultat.detail.splitlines():
        ligne = _RX_COULEURS.sub("", brute).rstrip()
        trouve = _RX_TSC.match(ligne)
        globale = None if trouve else _RX_TSC_SANS_FICHIER.match(ligne.strip())
        chemin = ""
        if trouve:
            fichier = trouve["fichier"].replace("\\", "/")
            chemin = posixpath.normpath(posixpath.join(prefixe, fichier)) if prefixe else fichier
        if trouve and not (chemin.endswith(".json") or re.fullmatch(r"TS5\d{3}", trouve["code"])):
            erreurs.append([chemin, int(trouve["ligne"] or trouve["ligne_pretty"]),
                            trouve["code"], trouve["message"]])
            # Les messages en chaîne suivent, en retrait ; en mode `pretty`,
            # le retrait porte aussi l'extrait de code : on ne le prend pas.
            suite_possible = trouve["ligne"] is not None
        elif trouve or globale:
            panne = trouve or globale
            ou = f" dans `{commun.cellule(chemin, 120)}`" if trouve else ""
            pannes.append(f"- `{panne['code']}`{ou} — {commun.cellule(panne['message'], 300)}")
            codes_pannes.append(panne["code"])
            suite_possible = False
        elif suite_possible and brute.startswith("  ") and ligne.strip():
            erreurs[-1][3] += " " + ligne.strip()
        else:
            suite_possible = False

    par_fichier: dict[str, int] = {}
    for chemin, _, _, _ in erreurs:
        par_fichier[chemin] = par_fichier.get(chemin, 0) + 1
    fichiers = {chemin: f"{nombre} erreur(s) de type" for chemin, nombre in par_fichier.items()}
    liste = [f"- {base.lien(chemin, numero)}<br>`{code}` — {commun.cellule(message, 300)}"
             for chemin, numero, code, message in erreurs]

    if pannes:
        detail = ["tsc **refuse la configuration** de ce projet. Tant qu'elle l'est, "
                  "l'analyse des types n'est pas fiable : une erreur peut y échapper.",
                  "", *pannes]
        if liste:
            detail += ["", f"**Erreurs de type trouvées malgré tout ({len(liste)}) :**",
                       "", *liste]
        return base.Resultat(
            titre, "ERREUR",
            f"tsc refuse la configuration du projet ({', '.join(sorted(set(codes_pannes)))})"
            " - analyse des types non fiable",
            "\n".join(detail), bloquant, detail_markdown=True, code_sortie=code_sortie,
            fichiers=fichiers,
        )

    if not erreurs:
        return base.Resultat(
            titre, "ERREUR",
            f"tsc a sorti en {code_sortie} sans erreur lisible - rien n'a ete verifie",
            resultat.detail, bloquant, code_sortie=code_sortie,
        )

    compteur: dict[str, int] = {}
    for _, _, code, _ in erreurs:
        compteur[code] = compteur.get(code, 0) + 1
    entete = ["**Résumé par code :**", ""]
    entete += [f"- **{nombre}** × `{code}`"
               for code, nombre in sorted(compteur.items(), key=lambda item: -item[1])]
    return base.Resultat(
        titre, "ALERTE",
        f"{len(erreurs)} erreur(s) de type dans {len(par_fichier)} fichier(s)",
        "\n".join([*entete, "", "**Détail :**", "", *liste]), bloquant,
        detail_markdown=True, code_sortie=code_sortie, fichiers=fichiers,
    )
