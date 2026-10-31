# Lintorn
"""`lintorn corrige` : réparer les fautes de frappe de regles.toml et config.toml, sur un oui."""

from __future__ import annotations

from .. import base, chemins, confiance, config
from . import outils


def corriger() -> int:
    """Montre chaque faute et sa correction, puis ne touche aux fichiers que sur un « o ».

    ⚠️ JAMAIS sans un oui : ces fichiers sont versionnés, et une correction
    devinée peut être fausse. Sans terminal pour répondre (hook, CI), rien
    n'est touché, et c'est dit. Seules les fautes SÛRES sont proposées (voir
    `fautes_de_frappe`) : le reste se corrige à la main, le rapport dit quoi.
    """
    trouvees = config.fautes_des_fichiers()
    if not trouvees:
        lus = [chemins.relatif(fichier) for fichier in config._schemas() if fichier.is_file()]
        if not lus:
            print("Rien a corriger : ce projet n'a ni regles.toml ni config.toml (lintorn init).")
            return 0
        print(f"Aucune faute de frappe que Lintorn sache corriger dans {', '.join(lus)}.")
        if config.SOUCIS_CONFIG:
            print(f"{len(config.SOUCIS_CONFIG)} souci(s) de configuration restent, a corriger a la main :")
            for souci in config.SOUCIS_CONFIG[:5]:
                print(f"    - {souci}")
        return 0

    nombre = sum(len(fautes) for _, fautes in trouvees)
    print(f"{nombre} faute(s) de frappe : Lintorn ne lit pas ces lignes telles qu'elles sont.")
    for fichier, fautes in trouvees:
        print(f"\n{chemins.relatif(fichier)} :")
        for faute in fautes:
            print(f"    ligne {faute.numero} : {faute.ligne.strip()}  ->  {faute.corrigee.strip()}")
    print()
    if not confiance.terminal():
        print("Pas de terminal pour te le demander : rien n'est corrige.")
        print("Relance `lintorn corrige` dans un terminal, ou corrige ces lignes a la main.")
        return 1
    if not outils._oui("Corriger ? [o/N] "):
        print("Rien n'est corrige.")
        return 1

    corrigees = 0
    for fichier, fautes in trouvees:
        try:
            # En octets décodés, pas `read_text` : les fins de ligne restent celles du fichier.
            lignes = fichier.read_bytes().decode("utf-8").splitlines(keepends=True)
        except (OSError, ValueError) as erreur:
            print(f"Echec : {chemins.relatif(fichier)} illisible ({erreur}), rien n'y est corrige")
            continue
        for faute in fautes:
            ancienne = lignes[faute.numero - 1] if faute.numero <= len(lignes) else ""
            fin = ancienne[len(ancienne.rstrip("\r\n")):]
            # Le fichier a pu changer depuis qu'on l'a lu : ne remplacer que la ligne montrée.
            if ancienne[:len(ancienne) - len(fin)] != faute.ligne:
                print(f"    ligne {faute.numero} de {fichier.name} a change entre-temps : laissee telle quelle")
                continue
            lignes[faute.numero - 1] = faute.corrigee + fin
            corrigees += 1
        try:
            base.ecrire_fichier_du_projet(fichier, "".join(lignes))
        except OSError as erreur:
            print(f"Echec : {chemins.relatif(fichier)} n'a PAS ete corrige ({erreur})")
            return 1
    print(f"Corrige : {corrigees} ligne(s). Elles comptent des le prochain lancement de Lintorn.")
    return 0
