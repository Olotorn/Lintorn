# Contribuer à Lintorn

Merci de ton intérêt. Lis ceci avant d'ouvrir une merge request.

## Où en est le projet

**Lintorn n'est pas encore ouvert aux contributions de code extérieures.** Le projet est
jeune, et son intérieur bouge encore vite. Pour l'instant, les merge requests seront
poliment refusées.

Ce qui est bienvenu, et vraiment utile :

- **Les rapports de bug**, surtout sur un contrôle qui se trompe en silence. Un contrôle qui
  affiche `OK` sans rien vérifier est la pire panne que connaisse ce projet, et la plus
  dure à repérer de l'intérieur.
- **Les idées de fonctionnalités**, en ticket (*issue*).
- **Les retours d'autres environnements** : Lintorn est né sur un projet Django + React.
  Si sa détection se trompe sur l'organisation de ton projet, c'est une information
  précieuse.

## Quand les contributions ouvriront : le CLA

Pour contribuer du code, il faudra signer un **CLA** (*Contributor License Agreement*,
l'accord de licence du contributeur) avant que ta merge request puisse être fusionnée.
Sans exception, même pour une modification d'une ligne.

### Pourquoi

Lintorn est publié sous **AGPL-3.0**. Il existe aussi sous licence commerciale, pour les
organisations qui ne peuvent pas respecter l'obligation de l'AGPL de publier leur code
source.

Cette double licence ne tient que tant qu'**un seul détenteur possède les droits sur tout
le code**. Par défaut, un contributeur garde le copyright du code qu'il écrit : une seule
merge request fusionnée sans CLA rendrait donc juridiquement impossible, définitivement et
rétroactivement, d'accorder une licence commerciale qui couvre ce code.

Le CLA n'est pas une formalité : c'est ce qui permet au projet de durer.

### Ce qu'il contiendra

L'accord suivra le modèle, très répandu, de
l'[Apache Individual CLA](https://www.apache.org/licenses/icla.pdf) :

- tu **gardes** le copyright de ta contribution ;
- tu accordes une licence perpétuelle, mondiale et irrévocable pour l'utiliser, la
  modifier, la sous-licencier et la placer sous une autre licence (c'est ce qui rend la
  licence commerciale possible) ;
- tu confirmes avoir le droit de proposer ce code : il est à toi, et aucun employeur ni
  client n'a de droit dessus.

La signature devrait se faire automatiquement, à chaque merge request.

### Si tu contribues sur ton temps de travail

Demande d'abord à ton employeur. Dans beaucoup de pays, le code écrit pendant les heures
de travail appartient à l'employeur, et tu ne peux pas accorder ces droits seul. C'est la
raison la plus courante pour laquelle un CLA ne peut pas être signé : mieux vaut le savoir
avant d'écrire le code.

## Si tu préfères forker

Tu es libre de forker Lintorn sous AGPL-3.0. Deux obligations viennent avec : garder la
même licence, et publier ton code source, y compris quand tu proposes le logiciel à
travers un réseau. C'est précisément ce que l'AGPL ajoute à la GPL.

Tu ne peux pas utiliser le nom **Lintorn** pour un fork d'une manière qui laisserait croire
que c'est ce projet, ou que ce projet l'approuve.

## Développer

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .          # `-e` : ton code local, pas la version publiée
pip install ruff pytest

pytest -q                 # les tests
ruff check .              # le lint
lintorn rapide            # Lintorn s'audite lui-même
```

Lintorn n'a aucune dépendance, et ne doit jamais en avoir : il tourne dans un hook git,
avec le python qu'il trouve sur la machine. Bibliothèque standard uniquement.

## Questions

Ouvre un ticket (*issue*). Pour une licence commerciale, contacte le détenteur du
copyright : **Olotorn**.
