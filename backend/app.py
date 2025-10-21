import logging
import os
import threading
import random
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional

import requests
import uvicorn
from fastapi import FastAPI, Body, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# --- Configuration ---
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s'
)
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Variables d'environnement Docker ---
CONTAINER_NAME = os.getenv("CONTAINER_NAME", "localhost")
PUBLIC_PORT = int(os.getenv("PUBLIC_PORT", "5000"))
INTERNAL_PORT = 5000

# --- Modèles Pydantic (inchangés) ---
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

# --- État du Jeu ---
game_state: Dict = {}
state_lock = threading.RLock()

# --- Fonctions Utilitaires ---
def reset_local_game_state():
    logging.info("État du jeu local réinitialisé.")
    with state_lock:
        if game_state.get("game_timer"):
            game_state["game_timer"].cancel()
        game_state["current_word"] = None
        game_state["game_timer"] = None

def broadcast(endpoint: str, payload: dict):
    with state_lock:
        players_to_contact = [p_id for p_id in game_state.get("players", []) if p_id != game_state.get("own_identifier")]
    logging.info(f"Diffusion du message sur '{endpoint}' à {len(players_to_contact)} joueur(s).")
    def post_request(player_identifier):
        try:
            container_name = player_identifier.split(":")[0]
            internal_url = f"http://{container_name}:{INTERNAL_PORT}{endpoint}"
            requests.post(internal_url, json=payload, timeout=1)
        except requests.RequestException:
            logging.warning(f"Impossible de contacter le joueur {player_identifier} lors de la diffusion.")
    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(post_request, players_to_contact)

def handle_loss():
    logging.warning("Le minuteur de 5 secondes a expiré. Le joueur a perdu.")
    broadcast('/api/game-over', {'loser': game_state.get("own_identifier"), 'reason': 'Temps écoulé'})
    reset_local_game_state()

# --- Événement de Démarrage ---
@app.on_event("startup")
def on_startup():
    with state_lock:
        game_state["own_identifier"] = f"{CONTAINER_NAME}:{PUBLIC_PORT}"
        game_state["players"] = [game_state["own_identifier"]]
        game_state["turn_counts"] = {game_state["own_identifier"]: 0}
        game_state["current_word"] = None
        game_state["game_timer"] = None
    logging.info(f"Serveur démarré. Identité: {game_state['own_identifier']}")

# --- Tâches de Fond ---
def send_ball_in_background(player_identifier: str, payload: dict):
    logging.info(f"Tâche de fond: Envoi de la balle à {player_identifier}.")
    try:
        container_name = player_identifier.split(":")[0]
        internal_url = f"http://{container_name}:{INTERNAL_PORT}/api/receive-ball"
        requests.post(internal_url, json=payload, timeout=2)
        logging.info(f"Tâche de fond: Balle envoyée avec succès à {player_identifier}.")
    except requests.RequestException as e:
        logging.error(f"Tâche de fond: Erreur en passant la balle à {player_identifier}: {e}")
        broadcast('/api/game-over', {'loser': game_state.get("own_identifier"), 'reason': f'Impossible de contacter {player_identifier}'})

# --- MODIFICATION: Nouvelle tâche de fond pour le handshake ---
def register_back(player_identifier: str):
    """Contacte un joueur pour s'enregistrer en retour."""
    logging.info(f"Handshake: Enregistrement en retour auprès de {player_identifier}.")
    try:
        container_name = player_identifier.split(":")[0]
        internal_url = f"http://{container_name}:{INTERNAL_PORT}/api/register"
        with state_lock:
            payload = {"ip": game_state["own_identifier"], "initialPlayers": game_state["players"], "initialTurnCounts": game_state["turn_counts"]}
        requests.post(internal_url, json=payload, timeout=1)
    except requests.RequestException:
        logging.warning(f"Handshake: Impossible de s'enregistrer en retour auprès de {player_identifier}.")

# --- API Endpoints ---

def discover_player(service_name: str):
    internal_url = f"http://{service_name}:{INTERNAL_PORT}/api/register"
    logging.debug(f"Tentative de découverte sur {service_name}...")
    try:
        with state_lock:
            if service_name == CONTAINER_NAME: return
            if any(p.startswith(f"{service_name}:") for p in game_state["players"]): return
            payload = {"ip": game_state["own_identifier"], "initialPlayers": game_state["players"], "initialTurnCounts": game_state["turn_counts"]}

        response = requests.post(internal_url, json=payload, timeout=0.5)

        if response.status_code == 200:
            data = response.json()
            logging.info(f"Joueur découvert avec succès : {data.get('identity')}")
            with state_lock:
                game_state["players"] = list(set(game_state["players"]).union(set(data.get("allPlayers", []))))
                game_state["turn_counts"].update(data.get("allTurnCounts", {}))
    except requests.RequestException:
        pass

@app.post("/api/discover", status_code=202)
def discover():
    services_to_scan = ["backend1", "backend2", "backend3"]
    logging.info(f"Lancement de la découverte sur les services: {services_to_scan}")
    executor = ThreadPoolExecutor(max_workers=len(services_to_scan))
    threading.Thread(target=lambda: executor.map(discover_player, services_to_scan)).start()
    return {"message": "Découverte réseau lancée en arrière-plan."}

@app.get("/api/players")
def get_players():
    logging.debug("Requête pour obtenir la liste des joueurs.")
    with state_lock:
        players_list = list(game_state.get("players", []))
        turn_counts_dict = dict(game_state.get("turn_counts", {}))
        return {"players": players_list, "turn_counts": turn_counts_dict}

# --- MODIFICATION: La fonction register devient active ---
@app.post("/api/register")
def register(payload: RegisterPayload, background_tasks: BackgroundTasks):
    logging.info(f"Requête d'enregistrement reçue de: {payload.ip}")
    with state_lock:
        is_new_player = payload.ip and payload.ip not in game_state["players"]

        if is_new_player:
            logging.info(f"NOUVEAU JOUEUR TROUVÉ ET AJOUTÉ: {payload.ip}")
            game_state["players"].append(payload.ip)
            game_state["turn_counts"].setdefault(payload.ip, 0)
            # --- Logique du Handshake ---
            # On s'enregistre en retour auprès du nouveau joueur.
            background_tasks.add_task(register_back, payload.ip)

        current_players = set(game_state["players"])
        new_players = set(payload.initialPlayers)
        game_state["players"] = list(current_players.union(new_players))
        game_state["turn_counts"].update(payload.initialTurnCounts)

        return {
            "message": "Enregistré",
            "identity": game_state["own_identifier"],
            "allPlayers": game_state["players"],
            "allTurnCounts": game_state["turn_counts"]
        }

# ... (Le reste des endpoints : receive_ball, pass_ball, start_game, game_over sont INCHANGÉS) ...
# ... (Collez ici le reste des endpoints de la version précédente) ...

# --- Point d'entrée ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=INTERNAL_PORT)