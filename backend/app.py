import logging
import os
import threading
import random
import ipaddress  # Pour la manipulation d'IP
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional

import requests
import uvicorn
from fastapi import FastAPI, Body, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# --- Configuration du Logging ---
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s'
)

# --- Initialisation de FastAPI ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Variables d'environnement ---
OWN_HOST = os.getenv("OWN_HOST", "localhost")
NETMASK_CIDR = os.getenv("NETMASK_CIDR", "24")
PORT = 5000  # Le port du jeu est maintenant fixe

# --- Modèles de Données Pydantic ---
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
            requests.post(f"http://{player_identifier}{endpoint}", json=payload, timeout=1)
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
        game_state["own_identifier"] = f"{OWN_HOST}:{PORT}"
        game_state["players"] = [game_state["own_identifier"]]
        game_state["turn_counts"] = {game_state["own_identifier"]: 0}
        game_state["current_word"] = None
        game_state["game_timer"] = None
    logging.info(f"Serveur démarré. Identité: {game_state['own_identifier']}")

# --- Tâches de Fond ---
def send_ball_in_background(player_identifier: str, payload: dict):
    logging.info(f"Tâche de fond: Envoi de la balle à {player_identifier}.")
    try:
        requests.post(f"http://{player_identifier}/api/receive-ball", json=payload, timeout=2)
        logging.info(f"Tâche de fond: Balle envoyée avec succès à {player_identifier}.")
    except requests.RequestException as e:
        logging.error(f"Tâche de fond: Erreur en passant la balle à {player_identifier}: {e}")
        broadcast('/api/game-over', {'loser': game_state.get("own_identifier"), 'reason': f'Impossible de contacter {player_identifier}'})

def register_back(player_identifier: str):
    logging.info(f"Handshake: Enregistrement en retour auprès de {player_identifier}.")
    try:
        with state_lock:
            payload = {"ip": game_state["own_identifier"], "initialPlayers": game_state["players"], "initialTurnCounts": game_state["turn_counts"]}
        requests.post(f"http://{player_identifier}/api/register", json=payload, timeout=1)
    except requests.RequestException:
        logging.warning(f"Handshake: Impossible de s'enregistrer en retour auprès de {player_identifier}.")

# --- API Endpoints ---

def discover_player(ip_to_try: str):
    """Tente de contacter un joueur sur une IP donnée sur le port standard du jeu."""
    if ip_to_try == OWN_HOST:
        return

    player_identifier = f"{ip_to_try}:{PORT}"
    logging.debug(f"Tentative de découverte sur {player_identifier}...")
    try:
        with state_lock:
            if player_identifier in game_state["players"]:
                return
            payload = {"ip": game_state["own_identifier"], "initialPlayers": game_state["players"], "initialTurnCounts": game_state["turn_counts"]}

        response = requests.post(f"http://{player_identifier}/api/register", json=payload, timeout=0.5)

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
    """Calcule la plage d'IP à partir du masque réseau et lance le scan."""
    try:
        network = ipaddress.ip_network(f"{OWN_HOST}/{NETMASK_CIDR}", strict=False)
        ips_to_scan = [str(ip) for ip in network.hosts()]
        logging.info(f"Lancement de la découverte réseau sur {len(ips_to_scan)} adresses ({network.network_address} à {network.broadcast_address}).")
    except ValueError:
        logging.error(f"Erreur: L'IP '{OWN_HOST}' ou le masque '{NETMASK_CIDR}' est invalide.")
        return {"message": "Erreur de configuration réseau."}

    executor = ThreadPoolExecutor(max_workers=50)
    threading.Thread(target=lambda: executor.map(discover_player, ips_to_scan)).start()

    return {"message": "Découverte réseau lancée en arrière-plan."}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/get-ball")
def get_ball():
    with state_lock:
        word = game_state.get("current_word")
        return {"word": word}

@app.get("/api/players")
def get_players():
    with state_lock:
        players_list = list(game_state.get("players", []))
        turn_counts_dict = dict(game_state.get("turn_counts", {}))
        return {"players": players_list, "turn_counts": turn_counts_dict}

@app.post("/api/register")
def register(payload: RegisterPayload, background_tasks: BackgroundTasks):
    with state_lock:
        is_new_player = payload.ip and payload.ip not in game_state["players"]

        if is_new_player:
            logging.info(f"NOUVEAU JOUEUR TROUVÉ ET AJOUTÉ: {payload.ip}")
            game_state["players"].append(payload.ip)
            game_state["turn_counts"].setdefault(payload.ip, 0)
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

@app.post("/api/receive-ball")
def receive_ball(payload: BallPayload):
    with state_lock:
        if game_state.get("current_word") is not None:
            raise HTTPException(status_code=409, detail="Déjà en train de jouer un tour.")

        game_state["current_word"] = payload.word
        game_state["players"] = list(set(game_state["players"]).union(set(payload.incomingPlayers)))
        game_state["turn_counts"].update(payload.incomingTurnCounts)
        logging.info(f"Nouveau tour commencé. Mot: '{game_state['current_word']}'. Démarrage du minuteur de 5s.")

        game_state["game_timer"] = threading.Timer(5.0, handle_loss)
        game_state["game_timer"].start()
    return {"message": "Balle reçue."}

@app.post("/api/pass-ball")
def pass_ball(payload: PassBallPayload, background_tasks: BackgroundTasks):
    with state_lock:
        current_word = game_state.get("current_word")
        if current_word is None:
            raise HTTPException(status_code=408, detail="Temps écoulé côté serveur.")
        if not payload.newWord.startswith(current_word) or len(payload.newWord) != len(current_word) + 1:
            raise HTTPException(status_code=400, detail="Mot invalide.")

        if game_state.get("game_timer"):
            game_state["game_timer"].cancel()

        all_players = game_state["players"]
        min_turns = min(game_state["turn_counts"].get(p_id, 0) for p_id in all_players)
        eligible_players = [p_id for p_id in all_players if game_state["turn_counts"].get(p_id, 0) == min_turns]
        next_player_identifier = random.choice(eligible_players)

        game_state["turn_counts"][next_player_identifier] += 1
        next_payload = BallPayload(
            word=payload.newWord,
            incomingPlayers=game_state["players"],
            incomingTurnCounts=game_state["turn_counts"]
        )

        if next_player_identifier == game_state["own_identifier"]:
            reset_local_game_state()
            receive_ball(next_payload)
        else:
            reset_local_game_state()
            background_tasks.add_task(
                send_ball_in_background,
                player_identifier=next_player_identifier,
                payload=next_payload.dict()
            )
    return {"message": "Balle passée avec succès."}

@app.post("/api/start-game")
def start_game(background_tasks: BackgroundTasks):
    with state_lock:
        start_word = random.choice('abcdefghijklmnopqrstuvwxyz')
        all_players = game_state["players"]
        if not all_players:
            raise HTTPException(status_code=400, detail="Aucun joueur trouvé.")

        first_player_identifier = random.choice(all_players)
        for p_id in all_players:
            game_state["turn_counts"].setdefault(p_id, 0)
        game_state["turn_counts"][first_player_identifier] += 1

        payload_to_send = BallPayload(
            word=start_word,
            incomingPlayers=game_state["players"],
            incomingTurnCounts=game_state["turn_counts"]
        )

        if first_player_identifier == game_state["own_identifier"]:
            receive_ball(payload_to_send)
        else:
            background_tasks.add_task(
                send_ball_in_background,
                player_identifier=first_player_identifier,
                payload=payload_to_send.dict()
            )

    return {"message": "Partie démarrée, première balle envoyée."}

@app.post("/api/game-over")
def game_over(payload: GameOverPayload):
    logging.info(f"Notification de fin de partie reçue. Perdant: {payload.loser}, Raison: {payload.reason}")
    reset_local_game_state()
    return {"message": "OK"}

# --- Point d'Entrée ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)