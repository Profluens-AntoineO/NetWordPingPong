## Piste d'amélioration 1 : Script de Lancement Automatisé

Le problème actuel est que chaque utilisateur doit manuellement trouver son adresse IP et modifier le fichier docker-compose.yml. C'est fastidieux et source d'erreurs. Un script de lancement résout ce problème en rendant le démarrage trivial.

**Objectif** : Créer un script (start.sh pour Linux/macOS et start.ps1 pour Windows) qui détecte automatiquement l'adresse IP locale et lance docker-compose avec la bonne configuration.

1. Modifier docker-compose.yml pour qu'il utilise une variable d'environnement qui sera fournie par le script, au lieu d'une valeur en dur.
2. Créer les scripts qui :
   * Trouvent l'adresse IP locale active.
   * Exportent cette IP dans une variable d'environnement.
   * Exécutent la commande docker-compose up

## Piste d'amélioration 2 : Déployer une Registry Docker Privée

**Objectif** : Au lieu de reconstruire les images Docker sur chaque machine (--build), on peut les construire une seule fois, les pousser sur une registry privée sur le réseau local, et les autres joueurs n'auront qu'à les "pull". C'est beaucoup plus rapide et garantit que tout le monde utilise exactement la même version.

1. Lancer un conteneur de registry Docker sur une machine du réseau.
2. Modifier docker-compose.yml pour qu'il utilise des noms d'images préfixés par l'adresse de la registry.
3. Créer des scripts build_and_push.sh et pull_and_run.sh pour simplifier le processus.

## Piste d'amélioration 3 : Tester sur github avec des github action

**Objectif** : Automatiser les tests et la validation du code à chaque modification poussée sur le dépôt GitHub. Cela permet de détecter les régressions et les erreurs le plus tôt possible, sans effort manuel.

Méthode :
1. Créer un workflow GitHub Actions qui se déclenche à chaque push ou pull_request.
2. Définir des "jobs" (tâches) pour le backend :
   * Installer les dépendances Python.
   * Lancer des tests unitaires et d'intégration avec pytest pour valider la logique du serveur.