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

# --- Variables d'environnement et Constantes de Jeu ---
OWN_HOST = os.getenv("OWN_HOST", "localhost")
NETMASK_CIDR = os.getenv("NETMASK_CIDR", "24")
PORT = 5000

BASE_TIMEOUT_MS = 60000
MIN_TIMEOUT_MS = 2000
RESPONSE_REFERENCE_MS = 10000
FAST_RESPONSE_THRESHOLD_MS = 3000

FAST_RESPONSE_MULTIPLIER = 1.5
NOVELTY_MULTIPLIER = 1.2
PROXIMITY_MULTIPLIER = 1.2

# --- Modèles Pydantic ---
class HistoryEntry(BaseModel):
    player: str
    word: str
    response_time_ms: int
    applied_multipliers: List[str] = []

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
    combo_counter: int
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
    with state_lock:
        if game_state.get("game_timer"):
            game_state["game_timer"].cancel()
        game_state["current_word"] = None
        game_state["game_timer"] = None
        game_state["ready_players"] = []
        game_state["history"] = []
        game_state["turn_start_time"] = None
        game_state["combo_counter"] = 1

def broadcast(endpoint: str, payload: dict):
    with state_lock:
        players_to_contact = [p_id for p_id in game_state.get("players", []) if p_id != game_state.get("own_identifier")]
    def post_request(player_identifier):
        try:
            requests.post(f"http://{player_identifier}{endpoint}", json=payload, timeout=1)
        except requests.RequestException:
            pass
    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(post_request, players_to_contact)

def handle_loss():
    timeout = game_state.get("current_turn_timeout_ms", BASE_TIMEOUT_MS) / 1000.0
    broadcast('/api/game-over', {'loser': game_state.get("own_identifier"), 'reason': f'Temps écoulé ({timeout}s)'})
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
        game_state["combo_counter"] = 1
    logging.info(f"Serveur démarré. Identité: {game_state['own_identifier']}")

# --- Tâches de Fond ---
def send_ball_in_background(player_identifier: str, payload: dict):
    try:
        requests.post(f"http://{player_identifier}/api/receive-ball", json=payload, timeout=2)
    except requests.RequestException:
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

# --- Logique de Calcul du Timeout ---
def calculate_next_timeout(response_time_ms: int, previous_word: str, new_word: str, incoming_combo: int) -> (int, List[str], int):
    applied_multipliers = []
    is_special_move = False

    speed_delta = RESPONSE_REFERENCE_MS - response_time_ms

    if speed_delta > 0:
        if response_time_ms < FAST_RESPONSE_THRESHOLD_MS:
            is_special_move = True
            applied_multipliers.append("vitesse")

        new_letter = new_word[-1]

        if previous_word and new_letter not in previous_word:
            is_special_move = True
            applied_multipliers.append("nouveauté")

        if previous_word:
            last_letter = previous_word[-1]
            if abs(ord(new_letter) - ord(last_letter)) == 1:
                is_special_move = True
                applied_multipliers.append("proximité")

    new_combo = 1
    if is_special_move:
        new_combo = incoming_combo + 1
        if incoming_combo > 1:
            speed_delta *= incoming_combo
            applied_multipliers.append(f"combo x{incoming_combo}")

    total_delta = -speed_delta
    final_timeout = BASE_TIMEOUT_MS + total_delta
    final_timeout = max(MIN_TIMEOUT_MS, final_timeout)

    return int(final_timeout), applied_multipliers, new_combo

# --- Logique de Démarrage du Jeu ---
def start_game_logic(background_tasks: BackgroundTasks):
    with state_lock:
        if game_state.get("current_word") is not None: return

        ready_players = game_state["ready_players"]
        last_loser = game_state.get("last_loser")
        first_player_identifier = None

        if last_loser and last_loser in ready_players:
            first_player_identifier = last_loser
        else:
            if not ready_players: return
            first_player_identifier = sorted(ready_players)[0]

        start_word = random.choice('abcdefghijklmnopqrstuvwxyz')

        for p_id in ready_players:
            game_state["turn_counts"].setdefault(p_id, 0)
        game_state["turn_counts"][first_player_identifier] += 1

        payload_to_send = BallPayload(
            word=start_word,
            timeout_ms=BASE_TIMEOUT_MS,
            combo_counter=1,
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
                    "ip": game_state["own_identifier"], "initialPlayers": game_state["players"],
                    "initialTurnCounts": game_state["turn_counts"], "initialReadyPlayers": game_state["ready_players"],
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
        executor = ThreadPoolExecutor(max_workers=50)
        threading.Thread(target=lambda: executor.map(discover_player, ips_to_scan)).start()
    except ValueError:
        return {"message": "Erreur de configuration réseau."}
    return {"message": "Découverte réseau lancée en arrière-plan."}

@app.get("/health")
def health_check(): return {"status": "ok"}

@app.get("/api/ping")
def ping_for_discovery():
    with state_lock:
        return {"message": "pong", "identity": game_state.get("own_identifier")}

# --- MODIFICATION: get-ball ne renvoie plus l'historique ---
@app.get("/api/get-ball")
def get_ball():
    with state_lock:
        return {
            "word": game_state.get("current_word"),
            "timeout_ms": game_state.get("current_turn_timeout_ms"),
        }

# --- MODIFICATION: players renvoie maintenant l'historique et l'archive ---
@app.get("/api/players")
def get_players():
    with state_lock:
        return {
            "self": game_state.get("own_identifier"),
            "players": list(game_state.get("players", [])),
            "turn_counts": dict(game_state.get("turn_counts", {})),
            "ready_players": list(game_state.get("ready_players", [])),
            "history": list(game_state.get("history", [])),
            "archive": list(game_state.get("archive", [])),
        }

@app.post("/api/register")
def register(payload: RegisterPayload, background_tasks: BackgroundTasks):
    with state_lock:
        is_new_player = payload.ip and payload.ip not in game_state["players"]
        if is_new_player:
            game_state["players"].append(payload.ip)
            game_state["turn_counts"].setdefault(payload.ip, 0)
            background_tasks.add_task(register_back, payload.ip)

        game_state["players"] = list(set(game_state["players"]).union(set(payload.initialPlayers)))
        game_state["turn_counts"].update(payload.initialTurnCounts)
        game_state["ready_players"] = list(set(game_state["ready_players"]).union(set(payload.initialReadyPlayers)))
        game_state["archive"] = payload.initialArchive

        return {
            "message": "Enregistré", "identity": game_state["own_identifier"],
            "allPlayers": game_state["players"], "allTurnCounts": game_state["turn_counts"],
            "allReadyPlayers": game_state["ready_players"], "allArchive": game_state["archive"]
        }

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
                start_game_logic(background_tasks)

    return {"message": "Vous êtes prêt."}

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
                start_game_logic(background_tasks)

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
        game_state["combo_counter"] = payload.combo_counter

        game_state["turn_start_time"] = time.time()
        game_state["current_turn_timeout_ms"] = payload.timeout_ms

        game_state["game_timer"] = threading.Timer(payload.timeout_ms / 1000.0, handle_loss)
        game_state["game_timer"].start()
    return {"message": "Balle reçue."}

@app.post("/api/pass-ball")
def pass_ball(payload: PassBallPayload, background_tasks: BackgroundTasks):
    with state_lock:
        current_word = game_state.get("current_word")
        start_time = game_state.get("turn_start_time")
        incoming_combo = game_state.get("combo_counter", 1)

        if current_word is None:
            raise HTTPException(status_code=408, detail="Temps écoulé côté serveur.")
        if not payload.newWord.startswith(current_word) or len(payload.newWord) != len(current_word) + 1:
            raise HTTPException(status_code=400, detail="Mot invalide.")

        if game_state.get("game_timer"):
            game_state["game_timer"].cancel()

        response_time_ms = int((time.time() - start_time) * 1000) if start_time else 0

        next_timeout, multipliers, next_combo = calculate_next_timeout(response_time_ms, current_word, payload.newWord, incoming_combo)

        history_entry = HistoryEntry(
            player=game_state["own_identifier"], word=payload.newWord,
            response_time_ms=response_time_ms, applied_multipliers=multipliers
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
                word=payload.newWord, timeout_ms=next_timeout, combo_counter=next_combo,
                incomingPlayers=game_state["players"], incomingTurnCounts=game_state["turn_counts"],
                incomingReadyPlayers=game_state["ready_players"], incomingHistory=game_state["history"]
            )
            reset_local_game_state()
            background_tasks.add_task(send_ball_in_background, next_player_identifier, next_payload.dict())
        else:
            simulated_word = payload.newWord + random.choice('abcdefghijklmnopqrstuvwxyz')
            game_state["turn_counts"][game_state["own_identifier"]] += 1
            ia_next_timeout, _, ia_next_combo = calculate_next_timeout(50, payload.newWord, simulated_word, next_combo)
            next_payload = BallPayload(
                word=simulated_word, timeout_ms=ia_next_timeout, combo_counter=ia_next_combo,
                incomingPlayers=game_state["players"], incomingTurnCounts=game_state["turn_counts"],
                incomingReadyPlayers=game_state["ready_players"], incomingHistory=game_state["history"]
            )
            reset_local_game_state()
            receive_ball(next_payload)

    return {"message": "Balle passée avec succès."}

@app.post("/api/game-over")
def game_over(payload: GameOverPayload):
    with state_lock:
        game_state["last_loser"] = payload.loser
        if game_state.get("history"):
            game_state["archive"].append(list(game_state["history"]))

    reset_local_game_state()
    return {"message": "OK"}

# --- Point d'Entrée ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)