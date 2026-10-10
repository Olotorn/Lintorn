# Lintorn
"""Les outils lents (audits de failles, code mort) ont-ils tourné récemment ?"""

from __future__ import annotations

import datetime

from ... import config
from ...base import Resultat, etat_suivi_par_git, lire_etat


def controle_audit_complet() -> Resultat:
    """`--rapide` saute vulture et les audits de failles. Qui rappelle de les lancer ?

    Personne, jusqu'ici — et c'est comme ça que des failles de sécurité connues
    ont dormi dans le projet : `pip-audit` ne tourne ni en
    `--rapide`, ni dans le hook pre-push.

    POURQUOI UN RAPPEL DANS L'OUTIL plutôt qu'une tâche planifiée : un
    planificateur qui meurt ne prévient personne. Le rappel, lui, apparaît dans
    l'audit qu'on lance déjà tous les jours. Et il marche sur n'importe quel OS.

    ⚠️ Ce contrôle est le seul dont la valeur DÉCROÎT avec le temps sans que le
    code change : une faille publiée demain concerne un projet figé depuis un an.
    """
    titre = "Audit complet (outils lents)"
    # Aucun outil lent accordé : il n'y a rien à rafraîchir. Ni « jamais
    # lancé », qui réclame un audit qu'aucune commande ne ferait, ni OK.
    if not any(entree["lent"] for entree in config.COMMANDES):
        return Resultat(
            titre, "INDISPONIBLE", "aucun outil lent active - rien a rafraichir",
            "Les audits de failles (`failles`, `failles_npm`, `failles_osv`) et "
            "`code_mort` sont opt-in : ils sortent sur le réseau ou sont bavards. "
            "Le contrôle `Configuration (Lintorn)` dit lesquels s'appliquent à ce "
            "projet ; les activer se fait dans `.lintorn/config.toml`.",
            bloquant=False, detail_markdown=True,
        )
    dernier = lire_etat().get("dernier_audit_complet")

    relance = ("Les outils **lents** — `vulture` et surtout les **audits de failles** "
               "(`pip-audit`, `npm audit`, OSV-Scanner) — ne tournent ni en "
               "`--rapide`, ni dans le hook pre-push. Ces audits signalent les "
               "**failles de sécurité connues** de tes dépendances : elles "
               "apparaissent sans que ton code bouge.\n\n"
               "```bash\nlintorn\n```")

    if etat_suivi_par_git():
        return Resultat(
            titre, "VERIF", "l'etat est commite dans le depot - sa date n'est pas celle d'ici",
            "`.lintorn/etat.json` est **suivi par git** : la date qu'il porte est celle de "
            "son auteur, pas d'un audit lancé sur cette machine. Elle est ignorée.\n\n"
            + relance, bloquant=False, detail_markdown=True)

    if not dernier:
        return Resultat(titre, "VERIF", "jamais lance sur cette machine",
                        relance, bloquant=False, detail_markdown=True)

    try:
        date = datetime.date.fromisoformat(str(dernier)[:10])
    except ValueError:
        return Resultat(titre, "VERIF", "date illisible dans .lintorn/etat.json",
                        relance, bloquant=False, detail_markdown=True)

    jours = (datetime.date.today() - date).days
    # Une date à venir n'est pas « récente » : `jours` négatif passait sous le
    # seuil, donc au vert, pour toujours.
    if jours < 0:
        return Resultat(titre, "VERIF", "date a venir dans .lintorn/etat.json",
                        relance, bloquant=False, detail_markdown=True)
    if jours <= config.JOURS_AUDIT_COMPLET:
        return Resultat(titre, "OK", f"lance il y a {jours} jour(s)", bloquant=False)

    return Resultat(
        titre, "VERIF",
        f"{jours} jours sans audit complet (seuil : {config.JOURS_AUDIT_COMPLET})",
        relance, bloquant=False, detail_markdown=True,
    )
