# Utilise l'image Nginx officielle et très légère
FROM nginx:alpine

# Copie les fichiers statiques de notre application dans le dossier par défaut de Nginx
COPY ./public /usr/share/nginx/html

# Remplace la configuration par défaut de Nginx par la nôtre
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose le port 80 (le port HTTP standard)
EXPOSE 80