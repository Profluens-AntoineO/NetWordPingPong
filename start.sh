#!/bin/bash

# Ce script détecte l'adresse IP locale et la substitue dans le template
# docker-compose avant de lancer les services.

# Détecte l'IP du LAN de manière robuste (fonctionne sur la plupart des systèmes Linux)
# Il cherche la première adresse IP privée (192.168.*, 10.*, 172.16-31.*)
IP=$(hostname -I | awk '{print $1}')

if [ -z "$IP" ]; then
    echo "ERREUR: Impossible de détecter l'adresse IP locale. Veuillez vérifier votre connexion réseau."
    exit 1
fi

echo "======================================================"
echo "Lancement de NetWordPingPong avec l'adresse IP: $IP"
echo "======================================================"

# Utilise 'sed' pour remplacer le placeholder __LAN_IP__ par l'IP détectée
# et pipe le résultat directement à 'docker-compose up'.
# Le '-f -' indique à docker-compose de lire la configuration depuis l'entrée standard (stdin).
sed "s/__LAN_IP__/$IP/g" docker-compose.template.yml | docker-compose -f - up --build
