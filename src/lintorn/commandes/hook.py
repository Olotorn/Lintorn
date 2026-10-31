# Lintorn
"""`lintorn hook` : brancher le hook pre-push sur ce clone."""

from __future__ import annotations

import os
import subprocess

from .. import __version__, base, chemins, config
from ..controles.outillage import hook_git
from . import dossier_lintorn


# ─────────────────────────────────────────────────────────────────────────────
# INSTALLATION DU HOOK
# ─────────────────────────────────────────────────────────────────────────────
def installer_hook(forcer: bool = False) -> int:
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

    # 0 bis. DES HOOKS TOURNENT DÉJÀ ? git ne lit qu'un dossier de hooks :
    #    brancher le nôtre ferait taire les leurs (pre-commit, husky…), sans un
    #    mot. On refuse, et on dit comment faire cohabiter les deux.
    autres = hook_git.autres_hooks()
    if autres and not forcer:
        return _cohabiter(autres)

    # 1. COPIER le hook du paquet vers le projet.
    pose, ancienne = _poser_le_script()
    if pose is None:
        return 1

    # 2. Dire à git d'aller le chercher là, s'il ne le sait pas déjà.
    deja_branche = hook_git.branche_ici()
    if not deja_branche:
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
    # Après coup, plus rien ne désigne le dossier qu'on vient de remplacer : le
    # contrôle ne pourrait plus dire que ses hooks se sont tus.
    if autres and autres.reglage:
        base.ecrire_etat(hook_git.CLE_REMPLACES, autres.reglage)

    # Ce qui a VRAIMENT changé : « Hook installe » s'affichait aussi sur un hook
    # déjà en place et à jour, et l'on ne savait plus s'il l'était avant.
    remplace = f", a la place de {ancienne}" if ancienne and pose == _MIS_A_JOUR else ""
    print(f"{pose:<16} : {config.HOOKS_ATTENDU}/pre-push (lintorn {__version__}{remplace})")
    print(f"{'Deja branche' if deja_branche else 'Hook branche':<16} : core.hooksPath = "
          f"{config.HOOKS_POUR_GIT}")
    if pose == _A_JOUR and deja_branche:
        print("Rien a changer.")
        # L'état, seulement quand rien n'a changé : juste après une pose, un push
        # fait dans la même seconde, AVANT elle, comptait comme parti sans Lintorn.
        _dire_l_etat()
    else:
        print("Lintorn tournera desormais avant chaque git push.")
        # ⚠️ Il conseillait de VERSIONNER la copie — que le `.gitignore` de
        # `.lintorn/` écarte pourtant. Et versionnée, deux versions de Lintorn
        # dans une équipe se la disputeraient à chaque commit.
        print("A relancer sur chaque clone, et apres chaque mise a jour de Lintorn")
        print("(le controle 'Hook pre-push' te le rappellera).")

    # `--force`, ou un branchement d'avant ce garde-fou : le dire, et pas une
    # seule fois — le contrôle « Hook pre-push » le rappellera.
    muets = hook_git.hooks_rendus_muets()
    if muets:
        retour, quoi = hook_git.pour_les_remettre(muets)
        print()
        print("ATTENTION : ces hooks ne tournent plus, git ne lit que celui de Lintorn :")
        for muet in muets:
            print(f"  {chemins.relatif(muet.dossier)}/ : {hook_git.decrire(muet)}")
        print(f"Pour les remettre en service :  {retour}")
        print("Et pour garder Lintorn avec eux, ", end="")
        _montrer(quoi)
    return 0


def _montrer(quoi: hook_git.Conseil) -> None:
    """Le conseil, tel qu'on le copie : la consigne, le bloc, la commande d'après."""
    print(f"{quoi.consigne} :")
    for ligne in quoi.ajout.split("\n"):
        print(f"    {ligne}")
    if quoi.script:
        print(f"et cree le script qu'il lance, {chemins.relatif(quoi.script[0])} :")
        for ligne in quoi.script[1].split("\n"):
            print(f"    {ligne}")
    if quoi.ensuite:
        print(f"puis lance :  {quoi.ensuite}")
    if quoi.garde:
        print(quoi.garde)


def retirer_hook() -> int:
    """`lintorn hook --rm` : débranche le hook de Lintorn et retire sa copie.

    Le dossier de hooks qu'un `lintorn hook --force` avait remplacé est REMIS :
    ses hooks se taisaient à cause de Lintorn, ils reprennent. Le pre-push d'un
    autre outil qui appelle Lintorn n'est pas touché : c'est son fichier. On
    dit quoi y retirer, sinon son prochain push s'arrêterait sur « not found ».
    """
    if config.SOUS_GIT is None:
        print("Echec : git est introuvable sur cette machine.")
        return 1
    if not config.SOUS_GIT:
        print("Rien a retirer : ce dossier n'est pas un depot git.")
        return 0

    fait = []
    if hook_git.branche_ici():
        remis = base.lire_etat().get(hook_git.CLE_REMPLACES)
        remis = remis if isinstance(remis, str) and remis else ""
        arguments = (("config", "core.hooksPath", remis) if remis
                     else ("config", "--unset", "core.hooksPath"))
        try:
            sortie = config.git(*arguments)
        except (OSError, subprocess.SubprocessError) as erreur:
            print(f"Echec : impossible de configurer git ({erreur})")
            return 1
        if sortie.returncode != 0:
            print(f"Echec : git a refuse - {sortie.stderr.strip() or f'code {sortie.returncode}'}")
            return 1
        if remis:
            base.ecrire_etat(hook_git.CLE_REMPLACES, "")
            fait.append(f"Hook debranche  : core.hooksPath remis a {remis}, tes hooks d'avant reprennent")
        else:
            fait.append("Hook debranche  : core.hooksPath retire")

    try:
        for copie in (config.HOOKS / "pre-push", config.HOOKS / "version"):
            if copie.is_file() or copie.is_symlink():
                base.retirer_sortie(copie)
                if copie.name == "pre-push":
                    fait.append(f"Copie retiree   : {config.HOOKS_ATTENDU}/pre-push")
    except OSError as erreur:
        print(f"Echec : la copie du hook n'a PAS ete retiree ({erreur})")
        return 1

    if not fait:
        print("Rien a retirer : le hook de Lintorn n'est ni branche ni pose dans ce projet.")
        return 0
    for ligne in fait:
        print(ligne)
    autres = hook_git.autres_hooks()
    if autres:
        # Un avertissement, pas un verdict : lire le texte suffit pour dire où regarder.
        quoi = hook_git.conseil(autres)
        try:
            appelle = ".lintorn/hooks/pre-push" in quoi.fichier.read_text(encoding="utf-8",
                                                                         errors="replace")
        except OSError:
            appelle = False
        if appelle:
            print()
            print(f"ATTENTION : {chemins.relatif(quoi.fichier)} appelle encore le hook de Lintorn.")
            print("Retire-en l'appel, sinon ton prochain push s'arretera sur 'not found'.")
    print()
    print("Lintorn ne tournera plus avant tes push. Pour le remettre : lintorn hook")
    return 0


# Ce que `_poser_le_script` a fait de la copie : la première ligne du message.
_POSE = "Hook installe"
_MIS_A_JOUR = "Hook mis a jour"
_A_JOUR = "Hook deja a jour"


def etat_du_hook() -> int:
    """`lintorn hook --status` : ce que dit le contrôle « Hook pre-push », sans rien toucher.

    Code 0 seulement au vert : un script peut s'en servir pour vérifier un clone.
    """
    return 0 if _dire_l_etat() == "OK" else 1


def _dire_l_etat() -> str:
    """La ligne du contrôle « Hook pre-push », et son détail s'il n'est pas au vert."""
    verdict = hook_git.controle_hook_git()
    print()
    print(f"{base.MARQUEUR.get(verdict.statut, verdict.statut)} {verdict.titre} : {verdict.resume}")
    if verdict.statut != "OK" and verdict.detail:
        # Le détail est écrit pour le rapport : sans son balisage, il se lit ici.
        for ligne in verdict.detail.splitlines():
            if not ligne.startswith("```"):
                print(f"    {ligne.replace('**', '').replace('`', '')}".rstrip())
    return verdict.statut


def _poser_le_script() -> tuple[str | None, str]:
    """Copie le hook du paquet dans le projet, exécutable.

    Rend (ce qui a changé, None en échec ; la version qui avait posé la copie).

    ⚠️ Cette étape n'existait pas tant que Lintorn vivait DANS le projet :
    le hook y était déjà, seul `core.hooksPath` manquait. Installé par pip,
    le hook vit dans le paquet — poser le réglage sans copier le fichier
    laissait `core.hooksPath` pointer sur un dossier VIDE, soit exactement
    la panne muette que ce contrôle est censé détecter.
    """
    try:
        cible = config.HOOKS / "pre-push"
        livre = (config.HOOKS_SOURCE / "pre-push").read_bytes()
        avant = cible.read_bytes() if cible.is_file() and not cible.is_symlink() else None
        # Une copie identique n'est pas réécrite : sa date est celle de la pose,
        # d'où le contrôle compte les push. La réécrire effaçait l'alerte « parti
        # SANS Lintorn » sans que sa cause ait changé.
        # Octets pour octets — une réécriture en texte changerait les fins de
        # ligne sous Windows, et `#!/bin/sh\r` n'est plus un interpréteur.
        change = avant != livre
        if change:
            base.ecrire_sortie(cible, livre)
        # La version qui a posé la copie : le hook la compare à celle qu'il lance.
        # Le venv d'un autre projet, activé dans le terminal, faisait tourner sa
        # propre version de Lintorn sous ce hook, sans un mot.
        version = config.HOOKS / "version"
        pose_par = f"lintorn {__version__}\n"
        ancienne = ""
        if version.is_file() and not version.is_symlink():
            ancienne = version.read_text(encoding="utf-8", errors="replace").strip()[:40]
        if ancienne != pose_par.strip():
            base.ecrire_sortie(version, pose_par)
            change = True
        # Sans le bit exécutable, git ignore le hook EN SILENCE. `copyfile` ne
        # transporte pas les permissions : on les pose explicitement plutôt que
        # d'espérer qu'elles aient suivi. (Sous Windows, ce bit n'existe pas.)
        mode = cible.stat().st_mode
        if os.name != "nt" and not mode & 0o111:
            change = True
        cible.chmod(mode | 0o111)
    except OSError as erreur:
        print(f"Echec : impossible d'installer le hook ({erreur})")
        return None, ""
    # Sans `lintorn init` avant, rien n'écartait la copie : un `git add -A` la
    # commitait, en 100644 sous Windows, et le contrôle la déclarait muette.
    dossier_lintorn.poser_gitignore_interne(config.HOOKS.parent)
    if avant is None:
        return _POSE, ancienne
    return (_MIS_A_JOUR if change else _A_JOUR), ancienne


def _cohabiter(autres: hook_git.AutresHooks) -> int:
    """D'autres hooks tiennent la place : poser le script SANS le brancher, et dire quoi ajouter.

    Le script est posé quand même : c'est lui que la ligne à ajouter appelle,
    et le reposer est la façon de le mettre à jour.
    """
    pose, _ = _poser_le_script()
    if pose is None:
        return 1
    voisin = hook_git.lintorn_voisin(autres)
    if voisin is not None:
        return _lance_par_un_voisin(voisin)
    preuve = hook_git.passage()
    if preuve.couvert and not preuve.malgre_refus:
        print(f"{pose} : {config.HOOKS_ATTENDU}/pre-push (lintorn {__version__})")
        print("Ton hook l'appelle deja : Lintorn y a ete vu tourner pendant un push.")
        if pose == _A_JOUR:
            _dire_l_etat()
        return 0

    dossier = chemins.relatif(autres.dossier)
    if preuve.malgre_refus:
        print(f"{pose} : {config.HOOKS_ATTENDU}/pre-push (lintorn {__version__})")
        # Le passage noté prouve que Lintorn a tourné, pas QUI l'a lancé : un
        # refus en mode direct, puis `--no-verify`, ne dit rien de ces hooks-ci.
        print("Lintorn avait refuse ton dernier push, parti malgre son refus : un")
        print("`git push --no-verify`, ou un hook qui l'appelle sans transmettre ce refus.")
    elif autres.noms is None:
        print(f"Lintorn n'a PAS branche son hook : {dossier}/ est illisible.")
        print("Des hooks y tournent peut-etre, et brancher celui de Lintorn les")
        print("rendrait muets, sans le moindre message.")
    else:
        print("Lintorn n'a PAS branche son hook : ce depot a deja des hooks actifs")
        print(f"  dans {dossier}/ : {hook_git.decrire(autres)}")
        print("git ne lit qu'UN dossier de hooks. Brancher celui de Lintorn rendrait")
        print("ceux-la muets, sans le moindre message.")
    print()
    print("Pour garder les deux, ", end="")
    _montrer(hook_git.conseil(autres))
    print(f"Ca lance le hook de Lintorn, pose a l'instant dans {config.HOOKS_ATTENDU}/.")
    print("Pousse ensuite une fois : le controle 'Hook pre-push' ne dit OK qu'apres")
    print("avoir VU Lintorn tourner pendant un push.")
    print()
    print("Pour brancher Lintorn quand meme, en sachant que ces hooks ne")
    print("tourneront plus : lintorn hook --force")
    return 1


def _lance_par_un_voisin(voisin) -> int:
    """Le hook Lintorn d'un autre sous-projet est branché : c'est lui qui lancera celui-ci."""
    nom = f"{hook_git.dans_le_depot(voisin)}/"
    print(f"Hook pose : {config.HOOKS_ATTENDU}/pre-push")
    if not hook_git.lance_ses_voisins(voisin):
        print(f"Le hook Lintorn de {nom} est branche, mais sa copie est d'une version")
        print("precedente : elle ne lance pas celui-ci. Mets-la a jour, depuis le sommet du depot :")
        print(f"    {hook_git.mettre_a_jour_chez(voisin)}")
        return 1
    if not hook_git.visible_des_voisins():
        print(f"Le hook Lintorn de {nom} est branche, mais il ne trouvera pas ce sous-projet :")
        print(f"son {config.DOSSIER_LINTORN.name}/ est ignore par git (un .gitignore du depot l'ecarte).")
        return 1
    print(f"Le hook Lintorn de {nom} est branche : il lance aussi celui-ci a chaque push.")
    print("Rien a ajouter. Pousse une fois : le controle 'Hook pre-push' ne dit OK")
    print("qu'apres avoir VU Lintorn tourner pendant un push.")
    return 0
