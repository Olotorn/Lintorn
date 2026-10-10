# Lintorn
"""Les contrôles qui surveillent LINTORN lui-même : sa config, son hook, son python, sa fraîcheur.

A-t-il pu LIRE ses propres consignes ? Son hook pre-push est-il branché ? Ses
outils lents ont-ils tourné ? Avec quel python a-t-il lancé les outils ?

    configuration.py   la config du projet a-t-elle été lue ?
    python_projet.py   quel python audite ?
    hook_git.py        le hook est-il branché, exécutable, à jour ?
    audit_complet.py   les outils lents ont-ils tourné récemment ?

⚠️ Ils ne regardent NI le code NI la documentation du projet. Ils peuvent donc
être verts là où rien d'autre n'a tourné — et ne doivent jamais, à eux seuls,
faire croire à un audit réussi. D'où `TITRES_OUTILLAGE`, que le verdict global
met de côté.
"""

# Ces contrôles ne regardent NI le code NI la documentation : ils
# surveillent Lintorn lui-même (son hook, la date de son dernier passage
# complet, le python avec lequel il a lancé les outils). Ils peuvent donc
# être verts sur un projet où rien d'autre n'a tourné — et ne doivent
# jamais, à eux seuls, faire croire à un audit réussi.
TITRES_OUTILLAGE = ("Configuration (Lintorn)", "Hook pre-push (Lintorn)",
                    "Audit complet (outils lents)", "Python du projet (venv)")


from . import audit_complet, configuration, hook_git, python_projet  # noqa: E402 — après ce qu'ils lisent ici

__all__ = ['audit_complet', 'configuration', 'hook_git', 'python_projet']
