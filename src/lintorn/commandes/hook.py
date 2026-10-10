# Lintorn
"""`lintorn hook` : brancher le hook pre-push sur ce clone."""

from __future__ import annotations

import subprocess

from .. import base, config


# ─────────────────────────────────────────────────────────────────────────────
# INSTALLATION DU HOOK
# ─────────────────────────────────────────────────────────────────────────────
def installer_hook() -> int:
    """Branche le hook pre-push sur CE clone. Idempotent, sans effet de bord.

    Le réglage `core.hooksPath` n'est pas versionné : il doit être reposé sur
    chaque clone. Plutôt que de laisser l'utilisateur retenir la commande git,
    Lintorn la joue lui-même — et son contrôle « Hook pre-push » dit quand c'est
    nécessaire.
    """
    # 0. Y A-T-IL SEULEMENT UN DEPOT ? Verifie AVANT de creer quoi que ce
    #    soit : la copie se faisait en premier, puis `git config` echouait, et
    #    il restait un `.lintorn/hooks/pre-push` orphelin — que le controle
    #    suivant prenait pour un hook mal branche, donc un ROUGE de plus.
    if config.SOUS_GIT is None:
        print("Echec : git est introuvable sur cette machine.")
        return 1

    if not config.SOUS_GIT:
        print("Echec : ce dossier n'est pas un depot git.")
        print("Le hook pre-push s'installe DANS un depot ; il n'y a rien a")
        print("brancher ici. `lintorn` lance a la main fonctionne normalement.")
        return 1

    # 1. COPIER le hook du paquet vers le projet.
    #
    # ⚠️ Cette étape n'existait pas tant que Lintorn vivait DANS le projet :
    # le hook y était déjà, seul `core.hooksPath` manquait. Installé par pip,
    # le hook vit dans le paquet — poser le réglage sans copier le fichier
    # laissait `core.hooksPath` pointer sur un dossier VIDE, soit exactement
    # la panne muette que ce contrôle est censé détecter.
    try:
        cible = config.HOOKS / "pre-push"
        # Octets pour octets — une réécriture en texte changerait les fins de
        # ligne sous Windows, et `#!/bin/sh\r` n'est plus un interpréteur.
        base.ecrire_sortie(cible, (config.HOOKS_SOURCE / "pre-push").read_bytes())
        # Sans le bit exécutable, git ignore le hook EN SILENCE. `copyfile` ne
        # transporte pas les permissions : on les pose explicitement plutôt que
        # d'espérer qu'elles aient suivi.
        cible.chmod(cible.stat().st_mode | 0o111)
    except OSError as erreur:
        print(f"Echec : impossible d'installer le hook ({erreur})")
        return 1

    # 2. Dire à git d'aller le chercher là.
    try:
        sortie = config.git("config", "core.hooksPath", config.HOOKS_POUR_GIT)
    except (OSError, subprocess.SubprocessError) as erreur:
        print(f"Echec : impossible de configurer git ({erreur})")
        return 1
    if sortie.returncode != 0:
        # La phrase de git, pas seulement son code : elle dit exactement ce
        # qui cloche, là où « code 128 » ne dit rien.
        print(f"Echec : git a refuse - {sortie.stderr.strip() or f'code {sortie.returncode}'}")
        return 1

    print(f"Hook installe : {config.HOOKS_ATTENDU}/pre-push")
    print(f"Hook branche  : core.hooksPath = {config.HOOKS_POUR_GIT}")
    print("Lintorn tournera desormais avant chaque git push.")
    # ⚠️ Il conseillait de VERSIONNER la copie — que le `.gitignore` de
    # `.lintorn/` écarte pourtant. Et versionnée, deux versions de Lintorn
    # dans une équipe se la disputeraient à chaque commit.
    print("A relancer sur chaque clone, et apres chaque mise a jour de Lintorn")
    print("(le controle 'Hook pre-push' te le rappellera).")
    return 0
