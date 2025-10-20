# Utilise une image Python officielle et légère
FROM python:3.10-slim

WORKDIR /app

# Installe les dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie le code de l'application
COPY app.py .

# Commande pour démarrer le serveur avec Uvicorn
# app:app -> le fichier app.py, et l'objet app = FastAPI() à l'intérieur
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000"]