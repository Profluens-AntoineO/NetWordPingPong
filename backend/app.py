import logging
import os
import threading
import random
import ipaddress
import time
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

# --- Variables d'environnement ---
OWN_HOST = os.getenv("OWN_HOST", "localhost")
NETMASK_CIDR = os.getenv("NETMASK_CIDR", "24")
PORT = 5000
TURN_DURATION = 60.0

# --- Modèles Pydantic ---
class HistoryEntry(BaseModel):
    player: str
    word: str
    response_time_ms: int

class RegisterPayload(BaseModel):
    ip: str
    initialPlayers: Optional[List[str]] = Field(default_factory=list)
    initialTurnCounts: Optional[Dict[str, int]] = Field(default_factory=dict)
    initialReadyPlayers: Optional[List[str]] = Field(default_factory=list)
    initialArchive: Optional[List[List[HistoryEntry]]] = Field(default_factory=list)

class ReadyPayload(BaseModel):
    player_id: str

class BallPayload(BaseModel):
    word: str
    timeout_ms: int
    incomingPlayers: List[str]
    incomingTurnCounts: Dict[str, int]
    incomingReadyPlayers: List[str]
    incomingHistory: List[HistoryEntry]

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
    logging.info("Réinitialisation de l'état du jeu local (sauf le dernier perdant et l'archive).")
    with state_lock:
        if game_state.get("game_timer"):
            game_state["game_timer"].cancel()
        game_state["current_word"] = None
        game_state["game_timer"] = None
        game_state["ready_players"] = []
        game_state["history"] = []
        game_state["turn_start_time"] = None

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
    logging.warning(f"Le minuteur de {TURN_DURATION} secondes a expiré. Le joueur a perdu.")
    broadcast('/api/game-over', {'loser': game_state.get("own_identifier"), 'reason': 'Temps écoulé'})
    reset_local_game_state()

# --- Événement de Démarrage ---
@app.on_event("startup")
def on_startup():
    with state_lock:
        game_state["own_identifier"] = f"{OWN_HOST}:{PORT}"
        game_state["players"] = [game_state["own_identifier"]]
        game_state["turn_counts"] = {game_state["own_identifier"]: 0}
        game_state["ready_players"] = []
        game_state["current_word"] = None
        game_state["game_timer"] = None
        game_state["last_loser"] = None
        game_state["history"] = []
        game_state["archive"] = []
        game_state["turn_start_time"] = None
    logging.info(f"Serveur démarré. Identité: {game_state['own_identifier']}")

# --- Tâches de Fond ---
def send_ball_in_background(player_identifier: str, payload: dict):
    try:
        requests.post(f"http://{player_identifier}/api/receive-ball", json=payload, timeout=2)
    except requests.RequestException as e:
        broadcast('/api/game-over', {'loser': game_state.get("own_identifier"), 'reason': f'Impossible de contacter {player_identifier}'})

def register_back(player_identifier: str):
    try:
        with state_lock:
            payload = {
                "ip": game_state["own_identifier"],
                "initialPlayers": game_state["players"],
                "initialTurnCounts": game_state["turn_counts"],
                "initialReadyPlayers": game_state["ready_players"],
                "initialArchive": game_state["archive"]
            }
        requests.post(f"http://{player_identifier}/api/register", json=payload, timeout=1)
    except requests.RequestException:
        pass

# --- Logique de Démarrage du Jeu ---
def start_game_logic(background_tasks: BackgroundTasks):
    with state_lock:
        if game_state.get("current_word") is not None:
            return

        ready_players = game_state["ready_players"]
        last_loser = game_state.get("last_loser")
        first_player_identifier = None

        if last_loser and last_loser in ready_players:
            first_player_identifier = last_loser
        else:
            if not ready_players: return
            sorted_players = sorted(ready_players)
            seed_string = "".join(sorted_players)
            player_index = hash(seed_string) % len(sorted_players)
            first_player_identifier = sorted_players[player_index]

        start_word = random.choice('abcdefghijklmnopqrstuvwxyz')
        logging.info(f"Premier joueur: {first_player_identifier}, Lettre de départ: '{start_word}'")

        for p_id in ready_players:
            game_state["turn_counts"].setdefault(p_id, 0)
        game_state["turn_counts"][first_player_identifier] += 1

        payload_to_send = BallPayload(
            word=start_word,
            timeout_ms=int(TURN_DURATION * 1000),
            incomingPlayers=game_state["players"],
            incomingTurnCounts=game_state["turn_counts"],
            incomingReadyPlayers=game_state["ready_players"],
            incomingHistory=game_state["history"]
        )
        game_state["current_word"] = "game_starting"

    if first_player_identifier == game_state["own_identifier"]:
        receive_ball(payload_to_send)
    else:
        background_tasks.add_task(send_ball_in_background, first_player_identifier, payload_to_send.dict())

# --- API Endpoints ---

def discover_player(ip_to_try: str):
    if ip_to_try == OWN_HOST: return
    player_identifier = f"{ip_to_try}:{PORT}"
    ping_url = f"http://{player_identifier}/api/ping"
    with state_lock:
        if player_identifier in game_state["players"]: return

    try:
        response_ping = requests.get(ping_url, timeout=0.3)
        if response_ping.status_code == 200 and response_ping.json().get("message") == "pong":
            with state_lock:
                payload_register = {
                    "ip": game_state["own_identifier"],
                    "initialPlayers": game_state["players"],
                    "initialTurnCounts": game_state["turn_counts"],
                    "initialReadyPlayers": game_state["ready_players"],
                    "initialArchive": game_state["archive"]
                }
            response_register = requests.post(f"http://{player_identifier}/api/register", json=payload_register, timeout=0.5)
            if response_register.status_code == 200:
                data = response_register.json()
                with state_lock:
                    game_state["players"] = list(set(game_state["players"]).union(set(data.get("allPlayers", []))))
                    game_state["turn_counts"].update(data.get("allTurnCounts", {}))
                    game_state["ready_players"] = list(set(game_state["ready_players"]).union(set(data.get("allReadyPlayers", []))))
                    game_state["archive"] = data.get("allArchive", [])
    except requests.RequestException:
        pass

@app.post("/api/discover", status_code=202)
def discover():
    try:
        if OWN_HOST == "localhost":
            ips_to_scan = ["localhost"]
        else:
            network = ipaddress.ip_network(f"{OWN_HOST}/{NETMASK_CIDR}", strict=False)
            ips_to_scan = [str(ip) for ip in network.hosts()]
        logging.info(f"Lancement de la découverte réseau sur {len(ips_to_scan)} adresses.")
        executor = ThreadPoolExecutor(max_workers=50)
        threading.Thread(target=lambda: executor.map(discover_player, ips_to_scan)).start()
    except ValueError:
        return {"message": "Erreur de configuration réseau."}
    return {"message": "Découverte réseau lancée en arrière-plan."}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/ping")
def ping_for_discovery():
    with state_lock:
        return {"message": "pong", "identity": game_state.get("own_identifier")}

@app.get("/api/get-ball")
def get_ball():
    with state_lock:
        return {
            "word": game_state.get("current_word"),
            "timeout_ms": game_state.get("current_turn_timeout_ms"),
            "history": game_state.get("history", [])
        }

@app.get("/api/players")
def get_players():
    with state_lock:
        return {
            "self": game_state.get("own_identifier"),
            "players": list(game_state.get("players", [])),
            "turn_counts": dict(game_state.get("turn_counts", {})),
            "ready_players": list(game_state.get("ready_players", []))
        }

@app.get("/api/archive")
def get_archive():
    with state_lock:
        return {"archive": list(game_state.get("archive", []))}

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
        game_state["ready_players"] = list(set(game_state["ready_players"]).union(set(payload.initialReadyPlayers)))
        game_state["archive"] = payload.initialArchive

        return {
            "message": "Enregistré",
            "identity": game_state["own_identifier"],
            "allPlayers": game_state["players"],
            "allTurnCounts": game_state["turn_counts"],
            "allReadyPlayers": game_state["ready_players"],
            "allArchive": game_state["archive"]
        }

# --- MODIFICATION: Logique de l'initiateur ---
@app.post("/api/ready")
def im_ready(background_tasks: BackgroundTasks):
    with state_lock:
        my_id = game_state["own_identifier"]
        if my_id not in game_state["ready_players"]:
            game_state["ready_players"].append(my_id)
            broadcast('/api/notify-ready', {"player_id": my_id})

        known_players = set(game_state["players"])
        ready_players = set(game_state["ready_players"])

        if known_players.issubset(ready_players) and len(known_players) > 0 and game_state.get("current_word") is None:
            initiator = sorted(list(known_players))[0]
            if my_id == initiator:
                logging.info(f"Tous les joueurs sont prêts. En tant qu'initiateur ({my_id}), je démarre la partie.")
                start_game_logic(background_tasks)
            else:
                logging.info(f"Tous les joueurs sont prêts, mais je ne suis pas l'initiateur ({initiator}). J'attends.")

    return {"message": "Vous êtes prêt."}

# --- MODIFICATION: Logique de l'initiateur ---
@app.post("/api/notify-ready")
def notify_ready(payload: ReadyPayload, background_tasks: BackgroundTasks):
    with state_lock:
        player_id = payload.player_id
        if player_id not in game_state["ready_players"]:
            game_state["ready_players"].append(player_id)

        known_players = set(game_state["players"])
        ready_players = set(game_state["ready_players"])

        if known_players.issubset(ready_players) and len(known_players) > 0 and game_state.get("current_word") is None:
            initiator = sorted(list(known_players))[0]
            my_id = game_state["own_identifier"]
            if my_id == initiator:
                logging.info(f"Notification reçue et tous les joueurs sont prêts. En tant qu'initiateur ({my_id}), je démarre la partie.")
                start_game_logic(background_tasks)
            else:
                logging.info(f"Notification reçue et tous les joueurs sont prêts, mais je ne suis pas l'initiateur ({initiator}). J'attends.")

    return {"message": "Notification reçue."}

@app.post("/api/receive-ball")
def receive_ball(payload: BallPayload):
    with state_lock:
        if game_state.get("current_word") is not None and game_state.get("current_word") != "game_starting":
            raise HTTPException(status_code=409, detail="Déjà en train de jouer un tour.")

        game_state["current_word"] = payload.word
        game_state["players"] = list(set(game_state["players"]).union(set(payload.incomingPlayers)))
        game_state["turn_counts"].update(payload.incomingTurnCounts)
        game_state["ready_players"] = list(set(game_state["ready_players"]).union(set(payload.incomingReadyPlayers)))
        game_state["history"] = payload.incomingHistory

        game_state["turn_start_time"] = time.time()
        game_state["current_turn_timeout_ms"] = payload.timeout_ms

        logging.info(f"Nouveau tour. Mot: '{payload.word}'. Timeout: {payload.timeout_ms}ms.")

        game_state["game_timer"] = threading.Timer(payload.timeout_ms / 1000.0, handle_loss)
        game_state["game_timer"].start()
    return {"message": "Balle reçue."}

@app.post("/api/pass-ball")
def pass_ball(payload: PassBallPayload, background_tasks: BackgroundTasks):
    with state_lock:
        current_word = game_state.get("current_word")
        start_time = game_state.get("turn_start_time")

        if current_word is None:
            raise HTTPException(status_code=408, detail="Temps écoulé côté serveur.")
        if not payload.newWord.startswith(current_word) or len(payload.newWord) != len(current_word) + 1:
            raise HTTPException(status_code=400, detail="Mot invalide.")

        if game_state.get("game_timer"):
            game_state["game_timer"].cancel()

        response_time_ms = int((time.time() - start_time) * 1000) if start_time else 0
        history_entry = HistoryEntry(
            player=game_state["own_identifier"],
            word=payload.newWord,
            response_time_ms=response_time_ms
        )
        game_state["history"].append(history_entry)

        other_players = [p_id for p_id in game_state["players"] if p_id != game_state["own_identifier"]]

        next_player_identifier = None
        if other_players:
            candidates = list(other_players)
            while candidates:
                min_turns = min(game_state["turn_counts"].get(p, 0) for p in candidates)
                eligible_players = [p for p in candidates if game_state["turn_counts"].get(p, 0) == min_turns]
                potential_next_player = random.choice(eligible_players)

                try:
                    requests.get(f"http://{potential_next_player}/health", timeout=0.5)
                    next_player_identifier = potential_next_player
                    break
                except requests.RequestException:
                    candidates.remove(potential_next_player)

            if not next_player_identifier:
                next_player_identifier = game_state["own_identifier"]
        else:
            next_player_identifier = game_state["own_identifier"]

        if next_player_identifier != game_state["own_identifier"]:
            game_state["turn_counts"][next_player_identifier] += 1
            next_payload = BallPayload(
                word=payload.newWord,
                timeout_ms=int(TURN_DURATION * 1000),
                incomingPlayers=game_state["players"],
                incomingTurnCounts=game_state["turn_counts"],
                incomingReadyPlayers=game_state["ready_players"],
                incomingHistory=game_state["history"]
            )
            reset_local_game_state()
            background_tasks.add_task(send_ball_in_background, next_player_identifier, next_payload.dict())
        else:
            simulated_word = payload.newWord + random.choice('abcdefghijklmnopqrstuvwxyz')
            game_state["turn_counts"][game_state["own_identifier"]] += 1
            next_payload = BallPayload(
                word=simulated_word,
                timeout_ms=int(TURN_DURATION * 1000),
                incomingPlayers=game_state["players"],
                incomingTurnCounts=game_state["turn_counts"],
                incomingReadyPlayers=game_state["ready_players"],
                incomingHistory=game_state["history"]
            )
            reset_local_game_state()
            receive_ball(next_payload)

    return {"message": "Balle passée avec succès."}

@app.post("/api/game-over")
def game_over(payload: GameOverPayload):
    logging.info(f"Notification de fin de partie reçue. Perdant: {payload.loser}, Raison: {payload.reason}")
    with state_lock:
        game_state["last_loser"] = payload.loser
        if game_state.get("history"):
            logging.info(f"Archivage de la partie terminée avec {len(game_state['history'])} coups.")
            game_state["archive"].append(list(game_state["history"]))

    reset_local_game_state()
    return {"message": "OK"}

# --- Point d'Entrée ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)