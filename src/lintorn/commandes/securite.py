# Lintorn
"""`lintorn pip-audit` : monter les paquets que pip-audit signale."""

from __future__ import annotations

import json
import re
import subprocess

from .. import base, confiance, config, noyau
from ..outils import pip_audit


# ─────────────────────────────────────────────────────────────────────────────
# MISE À JOUR DES PAQUETS VULNÉRABLES
# ─────────────────────────────────────────────────────────────────────────────
def _version_tuple(version: str) -> tuple:
    return tuple(int(m) if m.isdigit() else 0 for m in re.split(r"[.\-+]", version))


def maj_securite(appliquer: bool) -> int:
    """Met à jour les paquets que pip-audit signale. SIMULATION par défaut.
    Pas de mise à jour automatique, si un paquet change de version majeure
    peut casser le projet.
    """

    racine = config.BACKEND or config.PY_RACINE
    if racine is None:
        print("Aucun code Python dans ce projet : pip-audit n'a rien a mettre a jour.")
        return 1

    # ⚠️ Cette commande lance le python du projet et, avec `--appliquer`, y
    # INSTALLE des paquets : mêmes gardes que l'audit (pas de venv du projet =
    # l'environnement de Lintorn, qu'elle auditerait puis modifierait ; pas
    # d'accord = rien ne part). Un « Tout est OK » sur le mauvais venv est
    # pire qu'un refus.
    audit = pip_audit.commande()
    a_accorder = [audit]
    if appliquer:
        a_accorder.append({
            "cle": "pip_install", "titre": "Installation des paquets corriges (pip install)",
            "cmd": [config.PYTHON, "-m", "pip", "install"], "cwd": racine,
        })
    refus = noyau.refus_sans_lancer(audit, rapide=False)
    if refus is not None:
        print(f"Echec : {refus.resume}")
        return 1
    permises, motif = confiance.accordes(a_accorder)
    if any(confiance.identite(entree) not in permises for entree in a_accorder):
        print(f"Echec : rien n'est lance - {motif}")
        return 1

    print("Interrogation de pip-audit...")
    try:
        sortie = subprocess.run(
            [config.PYTHON, "-m", "pip_audit", "-f", "json",
             "--progress-spinner", "off"],
            cwd=racine, capture_output=True, text=True, timeout=300,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as erreur:
        print(f"Echec : pip-audit injoignable ({erreur})")
        return 1

    try:
        rapport = json.loads(sortie.stdout)
    except ValueError:
        print("Echec : sortie de pip-audit illisible.")
        print((sortie.stdout or sortie.stderr)[:400])
        return 1

    plan, sans_correctif = [], []
    dependances = rapport.get("dependencies") if isinstance(rapport, dict) else None
    for paquet in dependances if isinstance(dependances, list) else []:
        if not isinstance(paquet, dict) or "name" not in paquet or "version" not in paquet:
            continue
        vulns = [vuln for vuln in (paquet.get("vulns") or []) if isinstance(vuln, dict)]
        if not vulns:
            continue
        corrections = {v for vuln in vulns for v in (vuln.get("fix_versions") or [])}
        if not corrections:
            sans_correctif.append(paquet["name"])
            continue
        cible = max(corrections, key=_version_tuple)
        plan.append((paquet["name"], paquet["version"], cible,
                     sorted(v["id"] for v in vulns)))

    if not plan and not sans_correctif:
        print("Aucune faille connue. Tout est OK.")
        return 0

    if plan:
        print(f"\n{len(plan)} paquet(s) a mettre a jour :\n")
        for nom, actuelle, cible, ids in plan:
            print(f"  {nom:<16} {actuelle:>9}  ->  {cible:<9}  {', '.join(ids)}")
    if sans_correctif:
        print("\n/!\\ Faille SANS correctif publie : "
              + ", ".join(sans_correctif))

    if not appliquer:
        print("\nSIMULATION : rien n'a ete touche. Pour appliquer :")
        print("    lintorn pip-audit      --appliquer")
        return 0

    print("\nInstallation...")
    reussis = []
    for nom, _, cible, _ in plan:
        resultat = subprocess.run(
            [config.PYTHON, "-m", "pip", "install", f"{nom}=={cible}"],
            cwd=racine, capture_output=True, text=True, check=False,
        )
        if resultat.returncode == 0:
            reussis.append((nom, cible))
            print(f"  OK   {nom} {cible}")
        else:
            print(f"  ECHEC {nom} -> {cible}")
            # pip peut échouer SANS rien dire : `[-1]` sur une liste vide
            # faisait planter la commande au lieu d'afficher l'échec.
            derniere = (resultat.stderr or "").strip().splitlines()
            print("       " + (derniere[-1][:120] if derniere else "(pip n'a rien dit)"))

    fichier = config.REQUIREMENTS or racine / "requirements.txt"
    epingles = _repingler(fichier, reussis) if reussis else 0

    print("\nA FAIRE MAINTENANT : une montee de version peut casser :")
    print(f"    {config.PYTHON} -m pytest -q")
    print("    lintorn")
    return 0 if len(reussis) == len(plan) == epingles else 1


def _repingler(fichier, reussis: list[tuple[str, str]]) -> int:
    """Repingle `requirements.txt` sur ce qui s'est RÉELLEMENT installé.

    Rend le nombre de lignes vraiment changées  et le dit, paquet par paquet.
    Annoncer « repingle » sans avoir rien changé laissait le venv et le fichier
    en désaccord, exactement la panne que « Dependances vs venv » dénonce.

    """
    try:
        texte = fichier.read_text(encoding="utf-8")
    except (OSError, ValueError) as erreur:
        print(f"\nrequirements.txt NON repingle ({erreur}) : a faire manuellement.")
        return 0
    changes = 0
    for nom, cible in reussis:
        nom_souple = "[-_.]+".join(re.escape(morceau) for morceau in re.split(r"[-_.]+", nom))
        texte, nombre = re.subn(
            rf"(?im)^({nom_souple})==[^\s#;]+([ \t]*(?:[;#].*)?)$",
            lambda trouve, cible=cible: f"{trouve.group(1)}=={cible}{trouve.group(2)}",
            texte,
        )
        if nombre:
            changes += 1
        else:
            print(f"  {nom} : aucune ligne `{nom}==...` dans requirements.txt - a epingler a la main")
    if changes:
        try:
            base.ecrire_fichier_du_projet(fichier, texte)
        except OSError as erreur:
            print(f"\nrequirements.txt NON repingle ({erreur}) : a faire manuellement.")
            return 0
    print(f"\nrequirements.txt repingle sur {changes} paquet(s) sur {len(reussis)} installe(s).")
    return changes
