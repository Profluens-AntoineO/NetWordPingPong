import logging
import socket
import threading
import random
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional

import requests
import uvicorn
from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = FastAPI()

# Configuration CORS pour autoriser les requêtes du frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permet toutes les origines, à restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PORT = 5000

# --- Modèles de Données (Validation avec Pydantic) ---
class RegisterPayload(BaseModel):
    ip: str
    initialPlayers: Optional[List[str]] = Field(default_factory=list)
    initialTurnCounts: Optional[Dict[str, int]] = Field(default_factory=dict)

class BallPayload(BaseModel):
    word: str
    incomingPlayers: List[str]
    incomingTurnCounts: Dict[str, int]

class PassBallPayload(BaseModel):
    newWord: str

class GameOverPayload(BaseModel):
    loser: str
    reason: Optional[str] = "Raison inconnue"

# --- État du jeu (protégé par un verrou pour la concurrence) ---
game_state = {
    "own_ip": "",
    "players": [],
    "turn_counts": {},
    "current_word": None,
    "game_timer": None
}
state_lock = threading.Lock()

# --- Fonctions Utilitaires (inchangées) ---
def find_own_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def reset_local_game_state():
    logging.info("Réinitialisation de l'état du jeu.")
    with state_lock:
        if game_state["game_timer"]:
            game_state["game_timer"].cancel()
        game_state["current_word"] = None
        game_state["game_timer"] = None

def broadcast(endpoint: str, payload: dict):
    with state_lock:
        players_to_contact = [ip for ip in game_state["players"] if ip != game_state["own_ip"]]

    def post_request(ip):
        try:
            requests.post(f"http://{ip}:{PORT}{endpoint}", json=payload, timeout=1)
        except requests.RequestException:
            logging.warning(f"Impossible de contacter le joueur {ip}")

    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(post_request, players_to_contact)

def handle_loss():
    logging.info("Temps écoulé ! Le joueur a perdu.")
    broadcast('/api/game-over', {'loser': game_state["own_ip"], 'reason': 'Temps écoulé'})
    reset_local_game_state()

# --- Événements de Démarrage ---
@app.on_event("startup")
def on_startup():
    """Initialise l'état du jeu au démarrage du serveur."""
    game_state["own_ip"] = find_own_ip()
    with state_lock:
        game_state["players"].append(game_state["own_ip"])
        game_state["turn_counts"][game_state["own_ip"]] = 0
    logging.info(f"Serveur Backend (FastAPI) démarré sur http://{game_state['own_ip']}:{PORT}")

# --- API Endpoints ---
@app.get("/api/get-ball")
def get_ball():
    with state_lock:
        return {"word": game_state["current_word"]}

@app.post("/api/register")
def register(payload: RegisterPayload):
    with state_lock:
        if payload.ip and payload.ip not in game_state["players"]:
            logging.info(f"Nouveau joueur enregistré: {payload.ip}")
            game_state["players"].append(payload.ip)
            game_state["turn_counts"].setdefault(payload.ip, 0)

        # Fusionner les listes pour la synchronisation
        current_players = set(game_state["players"])
        new_players = set(payload.initialPlayers)
        game_state["players"] = list(current_players.union(new_players))
        game_state["turn_counts"].update(payload.initialTurnCounts)

        return {
            "message": "Enregistré",
            "allPlayers": game_state["players"],
            "allTurnCounts": game_state["turn_counts"]
        }

def discover_player(ip_to_try: str):
    if ip_to_try == game_state["own_ip"]:
        return
    try:
        with state_lock:
            payload = {
                "ip": game_state["own_ip"],
                "initialPlayers": game_state["players"],
                "initialTurnCounts": game_state["turn_counts"]
            }
        response = requests.post(f"http://{ip_to_try}:{PORT}/api/register", json=payload, timeout=0.5)
        if response.status_code == 200:
            logging.info(f"Joueur trouvé et enregistré à l'adresse : {ip_to_try}")
            data = response.json()
            with state_lock:
                game_state["players"] = list(set(game_state["players"]).union(set(data.get("allPlayers", []))))
                game_state["turn_counts"].update(data.get("allTurnCounts", {}))
    except requests.RequestException:
        pass

@app.post("/api/discover", status_code=202)
def discover():
    logging.info("Lancement de la découverte réseau...")
    subnet = game_state["own_ip"].rsplit('.', 1)[0]
    ips_to_scan = [f"{subnet}.{i}" for i in range(1, 255)]

    # Exécute le scan en arrière-plan
    executor = ThreadPoolExecutor(max_workers=50)
    threading.Thread(target=lambda: executor.map(discover_player, ips_to_scan)).start()

    return {"message": "Découverte réseau lancée en arrière-plan."}

@app.post("/api/receive-ball")
def receive_ball(payload: BallPayload):
    with state_lock:
        if game_state["current_word"] is not None:
            raise HTTPException(status_code=409, detail="Déjà en train de jouer un tour.")

        game_state["current_word"] = payload.word
        game_state["players"] = list(set(game_state["players"]).union(set(payload.incomingPlayers)))
        game_state["turn_counts"].update(payload.incomingTurnCounts)
        logging.info(f"Balle reçue avec le mot: {game_state['current_word']}")

        game_state["game_timer"] = threading.Timer(5.0, handle_loss)
        game_state["game_timer"].start()
    return {"message": "Balle reçue."}

@app.post("/api/pass-ball")
def pass_ball(payload: PassBallPayload):
    with state_lock:
        if not game_state["current_word"] or not payload.newWord.startswith(game_state["current_word"]) or len(payload.newWord) != len(game_state["current_word"]) + 1:
            raise HTTPException(status_code=400, detail="Mot invalide.")

        if game_state["game_timer"]:
            game_state["game_timer"].cancel()

        other_players = [p for p in game_state["players"] if p != game_state["own_ip"]]
        if not other_players:
            logging.info("Personne à qui passer la balle. Le jeu s'arrête.")
            reset_local_game_state()
            return {"message": "Vous êtes seul, le jeu est réinitialisé."}

        min_turns = min(game_state["turn_counts"].get(p, 0) for p in other_players)
        eligible_players = [p for p in other_players if game_state["turn_counts"].get(p, 0) == min_turns]
        next_player_ip = random.choice(eligible_players)

        logging.info(f"Envoi de la balle à {next_player_ip}")

        game_state["turn_counts"][next_player_ip] = game_state["turn_counts"].get(next_player_ip, 0) + 1
        next_payload = {
            "word": payload.newWord,
            "incomingPlayers": game_state["players"],
            "incomingTurnCounts": game_state["turn_counts"]
        }

    try:
        requests.post(f"http://{next_player_ip}:{PORT}/api/receive-ball", json=next_payload, timeout=2)
        reset_local_game_state()
        return {"message": "Balle passée avec succès."}
    except requests.RequestException as e:
        logging.error(f"Erreur en passant la balle à {next_player_ip}: {e}")
        broadcast('/api/game-over', {'loser': game_state["own_ip"], 'reason': f'Impossible de contacter {next_player_ip}'})
        reset_local_game_state()
        raise HTTPException(status_code=500, detail="Impossible de contacter le prochain joueur.")

@app.post("/api/start-game")
def start_game():
    with state_lock:
        if len(game_state["players"]) <= 1:
            raise HTTPException(status_code=400, detail="Aucun autre joueur trouvé pour démarrer une partie.")

    logging.info("Tentative de démarrage d'une nouvelle partie...")
    start_word = random.choice('abcdefghijklmnopqrstuvwxyz')

    # On simule un "pass-ball" à partir de rien
    with state_lock:
        game_state["current_word"] = ""

    return pass_ball(PassBallPayload(newWord=start_word))

@app.post("/api/game-over")
def game_over(payload: GameOverPayload):
    logging.info(f"Notification de défaite reçue: {payload.loser} a perdu. Raison: {payload.reason}")
    reset_local_game_state()
    return {"message": "OK"}

# --- Point d'entrée pour Uvicorn ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)