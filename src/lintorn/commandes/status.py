# Lintorn
"""`lintorn status` : où en est Lintorn dans ce projet, sur un écran, sans rien lancer."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .. import __version__, confiance, config, noyau
from ..base import MARQUEUR
from ..controles.outillage import audit_complet, configuration, hook_git
from ..controles.projet import memoire_ia

# L'en-tête que `rapport.markdown` écrit en tête de chaque rapport.
_RX_GENERE = re.compile(r"Généré le (\d{2}/\d{2}/\d{4} \d{2}:\d{2}) par `lintorn ([^`]+)`")


def afficher() -> int:
    """Le hook, l'accord, la config, ce qui est contrôlé, les derniers rapports.

    Rien n'est lancé ni écrit : c'est ce que Lintorn SAIT déjà. Et chaque ligne
    qui n'est pas au vert dit la commande qui la règle.
    """
    a_faire: list[str] = []
    print(f"lintorn {__version__} - projet : {config.RACINE.name}")
    print()

    hook = hook_git.controle_hook_git()
    _ligne("Hook", f"{MARQUEUR[hook.statut]} {hook.resume}")
    if hook.statut == "INDISPONIBLE":
        a_faire.append("lintorn hook            pour que Lintorn tourne avant chaque push")
    elif hook.statut != "OK":
        a_faire.append("lintorn hook --status   pour le detail du hook")

    _ligne("Confiance", _confiance(a_faire))

    reglages = configuration.controle_configuration()
    _ligne("Configuration", f"{MARQUEUR[reglages.statut]} {reglages.resume}")
    if reglages.statut == "ALERTE":
        for souci in config.SOUCIS_CONFIG[:3]:
            _ligne("", f"  {souci}")
        if any(config.fautes_des_fichiers()):
            a_faire.append("lintorn corrige         pour les fautes de frappe")

    _ligne("Controles", _controles(a_faire))
    _ligne("Instructions IA", ", ".join(_montrer(doc) for doc in config.DOCS_IA)
           or "aucun fichier (CLAUDE.md, AGENTS.md...)")
    _ligne("Memoire IA", _memoire())
    _ligne("Dernier lancement", _rapport(push=False))
    _ligne("Dernier push", _rapport(push=True))
    audit = audit_complet.controle_audit_complet()
    _ligne("Audit complet", f"{MARQUEUR[audit.statut]} {audit.resume}")

    if a_faire:
        print()
        print("A faire :")
        for action in a_faire:
            print(f"    {action}")
    return 0


def _ligne(nom: str, texte: str) -> None:
    print(f"{nom:<19}{texte}")


def _montrer(chemin: Path) -> str:
    """Depuis le projet si c'est dedans ; sinon `~/...`, sans le nom de la machine."""
    try:
        return chemin.relative_to(config.RACINE).as_posix()
    except ValueError:
        return str(chemin).replace(str(Path.home()), "~", 1)


def _confiance(a_faire: list[str]) -> str:
    a_lancer = noyau.a_lancer(rapide=False)
    if not a_lancer:
        return "rien a accorder : Lintorn ne lance aucune commande ici"
    if os.environ.get(confiance.VARIABLE_CI, "").strip().lower() in ("oui", "1", "true"):
        return f"tout est accorde par {confiance.VARIABLE_CI} (CI, banc d'essai)"
    manquants = confiance.nouveaux(a_lancer)
    accordes = len(a_lancer) - len(manquants)
    if not manquants:
        return f"{MARQUEUR['OK']} {accordes} commande(s) accordee(s) dans ce projet"
    a_faire.append("lintorn confiance       pour accorder ce qui attend")
    changes = sum(1 for entree in manquants if confiance.modifies(entree))
    noms = ", ".join(entree["titre"] for entree in manquants[:3])
    suite = f" (dont {changes} modifiee(s) depuis ton accord)" if changes else ""
    return (f"{MARQUEUR['VERIF']} {accordes} accordee(s), {len(manquants)} attendent ton "
            f"accord{suite} : {noms}" + (" ..." if len(manquants) > 3 else ""))


def _controles(a_faire: list[str]) -> str:
    internes = [nom for nom, actif in config.CONTROLES_INTERNES.items()
                if actif and nom in noyau.CONTROLES_INTERNES]
    lents = sum(1 for entree in config.COMMANDES if entree["lent"])
    texte = (f"{len(internes)} controle(s) de Lintorn, {len(config.COMMANDES)} outil(s) actif(s)"
             f" (dont {lents} lent(s)), {len(config.REGLES_MAISON)} regle(s) maison")
    if config.HORS_PORTEE:
        texte += f", {len(config.HORS_PORTEE)} hors de portee"
    if config.CONTROLES_DISPONIBLES:
        texte += f" ; {len(config.CONTROLES_DISPONIBLES)} disponible(s) pas actif(s)"
        a_faire.append("lintorn outils          pour activer ce qui s'applique ici")
    return texte


def _memoire() -> str:
    if config.MEMOIRE_IA is None:
        return f"introuvable ({config.MEMOIRE_IA_ORIGINE})"
    fiches = memoire_ia._fiches_memoire()
    combien = "ILLISIBLE" if fiches is None else f"{len(fiches)} fiche(s)"
    return f"{_montrer(config.MEMOIRE_IA)} ({combien})"


def _rapport(push: bool) -> str:
    """La date du dernier rapport, et ce qu'il a trouvé. Un rapport VERSIONNÉ ne compte pas.

    Commité, il vient d'ailleurs : un dépôt piégé y mettrait un audit tout vert
    daté d'aujourd'hui, et `status` le croirait.
    """
    rapport = config.rapport_du(push)
    commande = "lintorn rapport-push" if push else "lintorn rapport"
    if not rapport.is_file() or rapport.is_symlink():
        return "aucun push vu par Lintorn" if push else "jamais lance ici - lintorn"
    if config.suivi_par_git(rapport):
        return f"{rapport.name} est versionne : il ne vient pas de cette machine, ignore"
    try:
        texte = rapport.read_text(encoding="utf-8", errors="replace")[:200_000]
    except OSError as erreur:
        return f"illisible ({erreur})"
    genere = _RX_GENERE.search(texte)
    quand = f"{genere.group(1)} (lintorn {genere.group(2)})" if genere else "date illisible"
    alertes = texte.count(f"| {MARQUEUR['ALERTE']} |") + texte.count(f"| {MARQUEUR['ERREUR']} |")
    doutes = texte.count(f"| {MARQUEUR['VERIF']} |")
    trouve = ", ".join(filter(None, [f"{alertes} alerte(s)" if alertes else "",
                                     f"{doutes} a verifier" if doutes else ""]))
    return f"{quand} : {trouve or 'rien a signaler'} - {commande}"
