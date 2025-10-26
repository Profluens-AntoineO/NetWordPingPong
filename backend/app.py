
import logging
import os
import threading
import random
import ipaddress
import time
import json
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Any

import requests
import uvicorn
from fastapi import FastAPI, Body, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
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

# --- Game Constants ---
OWN_HOST = os.getenv("OWN_HOST", "localhost")
NETMASK_CIDR = os.getenv("NETMASK_CIDR", "24")
PORT = 5000

BASE_TIMEOUT_MS = 15000
MIN_TIMEOUT_MS = 3000
MAX_TIMEOUT_MS = 60000

VOWELS = "aeiouy"
VOWEL_POWER_RECHARGE_RATE = 0.25
MAX_VOWEL_POWER = 2.0
CURSE_THRESHOLD = 3
RARE_LETTERS = ['k', 'w', 'x', 'y', 'z']

PAD_CHARGE_THRESHOLD = 3
LETTER_TO_PAD = {
    'a': '2', 'b': '2', 'c': '2',
    'd': '3', 'e': '3', 'f': '3',
    'g': '4', 'h': '4', 'i': '4',
    'j': '5', 'k': '5', 'l': '5',
    'm': '6', 'n': '6', 'o': '6',
    'p': '7', 'q': '7', 'r': '7', 's': '7',
    't': '8', 'u': '8', 'v': '8',
    'w': '9', 'x': '9', 'y': '9', 'z': '9',
}
PAD_COLUMNS = {
    '*': ['7', '4'],       # Purge
    '0': ['2', '5', '8'],       # Recharge
    '#': ['3', '6', '9'],       # Attack
}

# --- WebSocket Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast_state(self):
        with state_lock:
            full_state = {
                "self": game_state.get("own_identifier"),
                "players": list(game_state.get("players", [])),
                "ready_players": list(game_state.get("ready_players", [])),
                "history": [entry.dict() for entry in game_state.get("history", [])],
                "archive": [[entry.dict() for entry in game] for game in game_state.get("archive", [])],
                "word": game_state.get("current_word"),
                "timeout_ms": game_state.get("current_turn_timeout_ms"),
                "player_vowel_powers": game_state.get("player_vowel_powers", {}),
                "cursed_letters": game_state.get("cursed_letters", []),
                "dead_letters": game_state.get("dead_letters", []),
                "player_phone_pads": game_state.get("player_phone_pads", {}),
                "player_max_timeouts": game_state.get("player_max_timeouts", {}),
                "player_inabilities": game_state.get("player_inabilities", {}),
                "active_player": game_state.get("active_player"),
                "active_missions": [m.to_dict() for m in game_state.get("active_missions", [])],
                "completed_missions": [m.to_dict() for m in game_state.get("completed_missions", [])],
                "scramble_ui_for_player": game_state.get("scramble_ui_for_player"),
                "forced_letter": game_state.get("forced_letter"),
            }
        message = json.dumps(full_state)
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()

# --- Mission System ---
class Mission:
    def __init__(self, id: str, name: str, description: str, goal: int, trigger_func: callable, effect_func: callable, progress_func: callable):
        self.id = id
        self.name = name
        self.description = description
        self.goal = goal
        self.trigger_func = trigger_func
        self.effect_func = effect_func
        self.progress_func = progress_func
        self.current_step = 0

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "goal": self.goal,
            "current_step": self.current_step
        }

    def copy(self):
        return Mission(self.id, self.name, self.description, self.goal, self.trigger_func, self.effect_func, self.progress_func)

# --- Pydantic Models ---
class TimeCalculationLog(BaseModel):
    base_timeout: int
    speed_bonus: float
    vowel_bonus: float
    cursed_malus: bool
    pad_combo_malus: bool
    final_timeout: int

class HistoryEntry(BaseModel):
    player: str
    word: str
    response_time_ms: int
    applied_multipliers: List[str] = []
    timeout_log: Optional[TimeCalculationLog] = None

class RegisterPayload(BaseModel):
    ip: str
    initialPlayers: Optional[List[str]] = Field(default_factory=list)
    initialTurnCounts: Optional[Dict[str, int]] = Field(default_factory=dict)
    initialReadyPlayers: Optional[List[str]] = Field(default_factory=list)
    initialArchive: Optional[List[List[HistoryEntry]]] = Field(default_factory=list)
    initialPlayerVowelPowers: Optional[Dict[str, Dict[str, float]]] = Field(default_factory=dict)
    initialCursedLetters: Optional[List[str]] = Field(default_factory=list)
    initialDeadLetters: Optional[List[str]] = Field(default_factory=list)
    initialPlayerPhonePads: Optional[Dict[str, Dict[str, int]]] = Field(default_factory=dict)
    initialPlayerLetterCounts: Optional[Dict[str, Dict[str, int]]] = Field(default_factory=dict)
    initialPlayerMaxTimeouts: Optional[Dict[str, int]] = Field(default_factory=dict)
    initialPlayerInabilities: Optional[Dict[str, List[str]]] = Field(default_factory=dict)
    initialActiveMissions: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    initialCompletedMissions: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    initialLetterCurseCounts: Optional[Dict[str, int]] = Field(default_factory=dict)

class ReadyPayload(BaseModel):
    player_id: str

class ComboPayload(BaseModel):
    combo_key: str

class BallPayload(BaseModel):
    word: str
    timeout_ms: int
    player_vowel_powers: Dict[str, Dict[str, float]]
    cursed_letters: List[str]
    dead_letters: List[str]
    player_phone_pads: Dict[str, Dict[str, int]]
    player_letter_counts: Dict[str, Dict[str, int]]
    player_max_timeouts: Dict[str, int]
    player_inabilities: Dict[str, List[str]]
    active_missions: List[Dict[str, Any]]
    completed_missions: List[Dict[str, Any]]
    letter_curse_counts: Dict[str, int]
    incomingPlayers: List[str]
    incomingTurnCounts: Dict[str, int]
    incomingReadyPlayers: List[str]
    incomingHistory: List[HistoryEntry]
    scramble_ui_for_player: Optional[str] = None
    forced_letter: Optional[str] = None

class PassBallPayload(BaseModel):
    newWord: str
    client_timestamp_ms: int

class GameOverPayload(BaseModel):
    loser: str
    reason: Optional[str] = "Raison inconnue"

# --- Game State ---
game_state: Dict = {}
state_lock = threading.RLock()

# --- Mission Definitions ---
def trigger_suite_harmonique(mission: "Mission", trigger_data: Dict[str, Any]) -> bool:
    return mission.current_step >= mission.goal

async def effect_suite_harmonique(current_player_id: str, background_tasks: BackgroundTasks):
    logging.info(f"Mission triggered: Suite Harmonique by {current_player_id}")
    game_state["opponent_speed_multiplier"][current_player_id] = 1.3

def progress_suite_harmonique(mission: "Mission", player_id: str, new_letter: str):
    if new_letter in VOWELS:
        mission.current_step += 1
    else:
        mission.current_step = 0

def trigger_mur_de_consonnes(mission: "Mission", trigger_data: Dict[str, Any]) -> bool:
    return mission.current_step >= mission.goal

async def effect_mur_de_consonnes(current_player_id: str, background_tasks: BackgroundTasks):
    logging.info(f"Mission triggered: Mur de Consonnes by {current_player_id}")
    game_state["player_max_timeouts"][current_player_id] = int(game_state["player_max_timeouts"].get(current_player_id, BASE_TIMEOUT_MS) * 1.5)

def progress_mur_de_consonnes(mission: "Mission", player_id: str, new_letter: str):
    if new_letter not in VOWELS:
        mission.current_step += 1
    else:
        mission.current_step = 0

def trigger_echo_parfait(mission: "Mission", trigger_data: Dict[str, Any]) -> bool:
    history = trigger_data["history"]
    if len(history) < 2: return False
    return history[-1].word[-1] == history[-2].word[-1]

async def effect_echo_parfait(current_player_id: str, background_tasks: BackgroundTasks):
    logging.info(f"Mission triggered: Écho Parfait by {current_player_id}")
    # This effect is handled in pass_ball by re-assigning the turn to the opponent

def progress_echo_parfait(mission: "Mission", player_id: str, new_letter: str):
    pass # No progress, instant trigger

def trigger_progression_alphabetique(mission: "Mission", trigger_data: Dict[str, Any]) -> bool:
    new_word = trigger_data["new_word"]
    if len(new_word) < 2: return False
    return ord(new_word[-1]) == ord(new_word[-2]) + 1

async def effect_progression_alphabetique(current_player_id: str, background_tasks: BackgroundTasks):
    logging.info(f"Mission triggered: Progression Alphabétique by {current_player_id}")
    opponent_id = [p for p in game_state["players"] if p != current_player_id][0]
    game_state["scramble_ui_for_player"] = opponent_id

def progress_progression_alphabetique(mission: "Mission", player_id: str, new_letter: str):
    pass

def trigger_symetrie_inversee(mission: "Mission", trigger_data: Dict[str, Any]) -> bool:
    new_word = trigger_data["new_word"]
    return len(new_word) > 1 and new_word == new_word[::-1]

async def effect_symetrie_inversee(current_player_id: str, background_tasks: BackgroundTasks):
    logging.info(f"Mission triggered: Symétrie Inversée by {current_player_id}")
    # Effect handled in pass_ball

def progress_symetrie_inversee(mission: "Mission", player_id: str, new_letter: str):
    pass

def trigger_frappe_eclair(mission: "Mission", trigger_data: Dict[str, Any]) -> bool:
    return mission.current_step >= mission.goal

async def effect_frappe_eclair(current_player_id: str, background_tasks: BackgroundTasks):
    logging.info(f"Mission triggered: Frappe Éclair by {current_player_id}")
    game_state["opponent_speed_multiplier"][current_player_id] = 1.2

def progress_frappe_eclair(mission: "Mission", player_id: str, new_letter: str):
    response_time = game_state["history"][-1].response_time_ms
    timeout = game_state["player_max_timeouts"].get(player_id, BASE_TIMEOUT_MS)
    if response_time < timeout * 0.25:
        mission.current_step += 1
    else:
        mission.current_step = 0

def trigger_au_bord_du_precipice(mission: "Mission", trigger_data: Dict[str, Any]) -> bool:
    response_time = trigger_data["response_time_ms"]
    timeout = trigger_data["timeout_ms"]
    return response_time > timeout * 0.9

async def effect_au_bord_du_precipice(current_player_id: str, background_tasks: BackgroundTasks):
    logging.info(f"Mission triggered: Au Bord du Précipice by {current_player_id}")
    game_state["player_max_timeouts"][current_player_id] = MAX_TIMEOUT_MS

def progress_au_bord_du_precipice(mission: "Mission", player_id: str, new_letter: str):
    pass

def trigger_pression_constante(mission: "Mission", trigger_data: Dict[str, Any]) -> bool:
    return len(trigger_data["history"]) % 10 == 0

async def effect_pression_constante(current_player_id: str, background_tasks: BackgroundTasks):
    logging.info(f"Mission triggered: Pression Constante")
    game_state["base_timeout_modifier"] = 0.5

def progress_pression_constante(mission: "Mission", player_id: str, new_letter: str):
    pass

def trigger_coup_du_dictionnaire(mission: "Mission", trigger_data: Dict[str, Any]) -> bool:
    return trigger_data["new_letter"] in RARE_LETTERS

async def effect_coup_du_dictionnaire(current_player_id: str, background_tasks: BackgroundTasks):
    logging.info(f"Mission triggered: Le Coup du Dictionnaire by {current_player_id}")
    # Penalty handled in pass_ball of the opponent

def progress_coup_du_dictionnaire(mission: "Mission", player_id: str, new_letter: str):
    pass

def trigger_union_forcee(mission: "Mission", trigger_data: Dict[str, Any]) -> bool:
    return trigger_data["new_letter"] == 'q'

async def effect_union_forcee(current_player_id: str, background_tasks: BackgroundTasks):
    logging.info(f"Mission triggered: Union Forcée by {current_player_id}")
    game_state["forced_letter"] = 'u'

def progress_union_forcee(mission: "Mission", player_id: str, new_letter: str):
    pass

ALL_MISSIONS = [
    Mission("suite_harmonique", "Suite Harmonique", "Jouer 3 voyelles consécutives. Réduit le temps du prochain adversaire de 30%.", goal=3, trigger_func=trigger_suite_harmonique, effect_func=effect_suite_harmonique, progress_func=progress_suite_harmonique),
    Mission("mur_de_consonnes", "Mur de Consonnes", "Jouer 4 consonnes consécutives. Augmente votre temps pour le prochain tour de 50%.", goal=4, trigger_func=trigger_mur_de_consonnes, effect_func=effect_mur_de_consonnes, progress_func=progress_mur_de_consonnes),
    Mission("echo_parfait", "Écho Parfait", "Jouer la même lettre que l'adversaire. Renvoie la balle instantanément.", goal=1, trigger_func=trigger_echo_parfait, effect_func=effect_echo_parfait, progress_func=progress_echo_parfait),
    Mission("progression_alphabetique", "Progression Alphabétique", "Jouer une lettre qui suit la précédente dans l'alphabet. Brouille le clavier de l'adversaire.", goal=1, trigger_func=trigger_progression_alphabetique, effect_func=effect_progression_alphabetique, progress_func=progress_progression_alphabetique),
    Mission("symetrie_inversee", "Symétrie Inversée", "Compléter un palindrome. Annule le dernier coup de l'adversaire.", goal=1, trigger_func=trigger_symetrie_inversee, effect_func=effect_symetrie_inversee, progress_func=progress_symetrie_inversee),
    Mission("frappe_eclair", "Frappe Éclair", "Jouer 3 fois de suite en moins de 25% du temps. Accélère le temps de l'adversaire.", goal=3, trigger_func=trigger_frappe_eclair, effect_func=effect_frappe_eclair, progress_func=progress_frappe_eclair),
    Mission("au_bord_du_precipice", "Au Bord du Précipice", "Jouer avec moins de 10% de temps restant. Récupère tout votre temps.", goal=1, trigger_func=trigger_au_bord_du_precipice, effect_func=effect_au_bord_du_precipice, progress_func=progress_au_bord_du_precipice),
    Mission("pression_constante", "Pression Constante", "Échanger la balle 10 fois. Réduit le temps de base de 50%.", goal=1, trigger_func=trigger_pression_constante, effect_func=effect_pression_constante, progress_func=progress_pression_constante),
    Mission("coup_du_dictionnaire", "Le Coup du Dictionnaire", "Jouer une lettre rare (K, W, X, Y, Z). Pénalise l'adversaire s'il ne joue pas une voyelle.", goal=1, trigger_func=trigger_coup_du_dictionnaire, effect_func=effect_coup_du_dictionnaire, progress_func=progress_coup_du_dictionnaire),
    Mission("union_forcee", "Union Forcée", "Jouer la lettre 'Q'. Force l'adversaire à jouer 'U'.", goal=1, trigger_func=trigger_union_forcee, effect_func=effect_union_forcee, progress_func=progress_union_forcee),
]

def find_mission_template_by_id(mission_id: str) -> Optional[Mission]:
    for mission in ALL_MISSIONS:
        if mission.id == mission_id:
            return mission
    return None

def select_initial_missions():
    with state_lock:
        game_state["active_missions"] = [m.copy() for m in random.sample(ALL_MISSIONS, min(3, len(ALL_MISSIONS)))]

def replace_triggered_mission(triggered_mission: Mission):
    with state_lock:
        game_state["active_missions"] = [m for m in game_state["active_missions"] if m.id != triggered_mission.id]
        game_state["completed_missions"].append(triggered_mission)

        current_mission_ids = {m.id for m in game_state["active_missions"]}.union({m.id for m in game_state["completed_missions"]})
        available_missions = [m for m in ALL_MISSIONS if m.id not in current_mission_ids]

        if available_missions:
            new_mission_template = random.choice(available_missions)
            game_state["active_missions"].append(new_mission_template.copy())

# --- State Reset Functions ---
def get_new_phone_pad():
    return {str(i): 0 for i in range(2, 10)}

def reset_local_game_state():
    with state_lock:
        if game_state.get("game_timer"):
            game_state["game_timer"].cancel()
        game_state["current_word"] = None
        game_state["game_timer"] = None
        game_state["current_turn_timeout_ms"] = None
        game_state["active_player"] = None
        game_state["forced_letter"] = None
        game_state["scramble_ui_for_player"] = None
        game_state["opponent_speed_multiplier"] = {}
        game_state["base_timeout_modifier"] = 1.0
    logging.info("Local game state (turn) reset.")

async def reset_full_game_state_and_broadcast():
    with state_lock:
        reset_local_game_state()
        game_state["ready_players"] = []
        game_state["history"] = []
        game_state["player_vowel_powers"] = {p_id: {v: 1.0 for v in VOWELS} for p_id in game_state.get("players", [])}
        game_state["cursed_letters"] = []
        game_state["dead_letters"] = []
        game_state["player_phone_pads"] = {p_id: get_new_phone_pad() for p_id in game_state.get("players", [])}
        game_state["player_letter_counts"] = {p_id: {} for p_id in game_state.get("players", [])}
        game_state["player_max_timeouts"] = {p_id: BASE_TIMEOUT_MS for p_id in game_state.get("players", [])}
        game_state["player_inabilities"] = {p_id: [] for p_id in game_state.get("players", [])}
        game_state["active_missions"] = []
        game_state["completed_missions"] = []
        game_state["forced_letter"] = None
        game_state["scramble_ui_for_player"] = None
        game_state["opponent_speed_multiplier"] = {}
        game_state["base_timeout_modifier"] = 1.0
        game_state["letter_curse_counts"] = {}
    await manager.broadcast_state()

def broadcast_sync(endpoint: str, payload: dict):
    with state_lock:
        players_to_contact = [p_id for p_id in game_state.get("players", []) if p_id != game_state.get("own_identifier")]
    def post_request(player_identifier):
        try:
            requests.post(f"http://{player_identifier}{endpoint}", json=payload, timeout=1)
        except requests.RequestException:
            pass
    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(post_request, players_to_contact)

def register_back(player_id_to_register_with: str):
    '''Posts this node's state to the other player's /register endpoint.'''
    with state_lock:
        my_id = game_state["own_identifier"]
        payload = {
            "ip": my_id,
            "initialPlayers": game_state["players"],
            "initialTurnCounts": game_state["turn_counts"],
            "initialReadyPlayers": game_state["ready_players"],
            "initialArchive": [[e.dict() for e in game] for game in game_state["archive"]],
            "initialPlayerVowelPowers": game_state["player_vowel_powers"],
            "initialCursedLetters": game_state["cursed_letters"],
            "initialDeadLetters": game_state["dead_letters"],
            "initialPlayerPhonePads": game_state["player_phone_pads"],
            "initialPlayerLetterCounts": game_state["player_letter_counts"],
            "initialPlayerMaxTimeouts": game_state["player_max_timeouts"],
            "initialPlayerInabilities": game_state["player_inabilities"],
            "initialActiveMissions": [m.to_dict() for m in game_state.get("active_missions", [])],
            "initialCompletedMissions": [m.to_dict() for m in game_state.get("completed_missions", [])],
            "initialLetterCurseCounts": game_state["letter_curse_counts"],
        }
    try:
        requests.post(f"http://{player_id_to_register_with}/api/register", json=payload, timeout=1)
        logging.info(f"Registered back with {player_id_to_register_with}")
    except requests.RequestException:
        logging.warning(f"Failed to register back with {player_id_to_register_with}")

def discover_peers():
    '''Scans the network for other players and registers with them.'''
    with state_lock:
        my_id = game_state["own_identifier"]
        own_ip = my_id.split(':')[0]
        try:
            network = ipaddress.ip_network(f'{own_ip}/{NETMASK_CIDR}', strict=False)
        except ValueError:
            logging.error(f"Invalid OWN_HOST/NETMASK_CIDR: {own_ip}/{NETMASK_CIDR}")
            return

    def ping_and_initiate_register(ip):
        if str(ip) == own_ip:
            return
        
        target_id = f"{ip}:{PORT}"
        with state_lock:
            if target_id in game_state["players"]:
                return # Already know this player

        try:
            ping_response = requests.get(f"http://{target_id}/api/ping", timeout=0.5)
            if ping_response.status_code == 200:
                logging.info(f"Found potential peer: {target_id}")
                register_back(target_id)

        except requests.RequestException:
            pass  # Ignore nodes that don't respond

    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(ping_and_initiate_register, network.hosts())
    
    asyncio.run(manager.broadcast_state())

def calculate_next_timeout(response_time_ms: int, new_word: str, player_vowel_power: Dict[str, float], cursed_malus: bool = False, pad_combo_malus: bool = False) -> (int, List[str], Dict[str, float], TimeCalculationLog):
    speed_bonus = (5000 - response_time_ms) * 1.5
    new_letter = new_word[-1]
    vowel_bonus = 0
    applied_multipliers = []
    new_player_vowel_power = player_vowel_power.copy()

    if new_letter in VOWELS:
        power_before_use = new_player_vowel_power.get(new_letter, 1.0)
        vowel_bonus = -7500 * power_before_use # Negative bonus for opponent
        new_player_vowel_power[new_letter] = power_before_use / 2
        if vowel_bonus < 0: applied_multipliers.append(f"voyelle ({power_before_use:.0%})")
    else:
        recharged = False
        for v in VOWELS:
            if new_player_vowel_power.get(v, 1.0) < MAX_VOWEL_POWER:
                recharged = True
                new_player_vowel_power[v] = min(MAX_VOWEL_POWER, new_player_vowel_power.get(v, 1.0) + VOWEL_POWER_RECHARGE_RATE)
        if recharged: applied_multipliers.append("recharge")

    final_timeout = BASE_TIMEOUT_MS + speed_bonus + vowel_bonus
    if cursed_malus: final_timeout *= 0.25; applied_multipliers.append("maudite")
    if pad_combo_malus: final_timeout *= 0.5; applied_multipliers.append("combo #")
    if speed_bonus > 0: applied_multipliers.append("vitesse")

    final_timeout = max(MIN_TIMEOUT_MS, min(final_timeout, MAX_TIMEOUT_MS))
    
    log = TimeCalculationLog(
        base_timeout=BASE_TIMEOUT_MS,
        speed_bonus=speed_bonus,
        vowel_bonus=vowel_bonus,
        cursed_malus=cursed_malus,
        pad_combo_malus=pad_combo_malus,
        final_timeout=int(final_timeout)
    )

    return int(final_timeout), applied_multipliers, new_player_vowel_power, log

# --- Core Logic ---

@app.on_event("startup")
def on_startup():
    with state_lock:
        my_id = f"{OWN_HOST}:{PORT}"
        game_state["own_identifier"] = my_id
        game_state["players"] = [my_id]
        game_state["turn_counts"] = {my_id: 0}
        game_state["ready_players"] = []
        game_state["archive"] = []
        game_state["player_vowel_powers"] = {my_id: {v: 1.0 for v in VOWELS}}
        game_state["cursed_letters"] = []
        game_state["dead_letters"] = []
        game_state["player_phone_pads"] = {my_id: get_new_phone_pad()}
        game_state["player_letter_counts"] = {my_id: {}}
        game_state["player_max_timeouts"] = {my_id: BASE_TIMEOUT_MS}
        game_state["player_inabilities"] = {my_id: []}
        game_state["last_loser"] = None
        game_state["attack_combo_player"] = None
        game_state["active_player"] = None
        game_state["active_missions"] = []
        game_state["completed_missions"] = []
        game_state["forced_letter"] = None
        game_state["scramble_ui_for_player"] = None
        game_state["opponent_speed_multiplier"] = {}
        game_state["base_timeout_modifier"] = 1.0
        game_state["letter_curse_counts"] = {}
    logging.info(f"Server started. Identity: {my_id}")

async def handle_loss():
    with state_lock:
        loser_id = game_state.get("own_identifier")
        current_word = game_state.get("current_word")
        if not (loser_id and current_word and current_word != "game_starting"):
            return

        logging.info(f"Player {loser_id} lost due to timeout on word {current_word}")
        broadcast_sync("/api/game-over", {"loser": loser_id, "reason": "timeout"})
        await game_over(GameOverPayload(loser=loser_id, reason="timeout"))

def start_game_logic(background_tasks: BackgroundTasks):
    with state_lock:
        if game_state.get("current_word") is not None: return
        
        ready_players = game_state["ready_players"]
        game_state["player_vowel_powers"] = {p_id: {v: 1.0 for v in VOWELS} for p_id in ready_players}
        game_state["cursed_letters"] = []
        game_state["dead_letters"] = []
        game_state["player_phone_pads"] = {p_id: get_new_phone_pad() for p_id in ready_players}
        game_state["player_letter_counts"] = {p_id: {} for p_id in ready_players}
        game_state["player_max_timeouts"] = {p_id: BASE_TIMEOUT_MS for p_id in ready_players}
        game_state["player_inabilities"] = {p_id: [] for p_id in ready_players}
        game_state["letter_curse_counts"] = {}
        select_initial_missions()
        background_tasks.add_task(manager.broadcast_state)

        first_player_identifier = sorted(ready_players)[0]
        start_word = random.choice('abcdefghijklmnopqrstuvwxyz')
        
        for p_id in ready_players: game_state["turn_counts"].setdefault(p_id, 0)
        game_state["turn_counts"][first_player_identifier] += 1
        game_state["active_player"] = first_player_identifier

        payload_to_send = BallPayload(
            word=start_word, timeout_ms=BASE_TIMEOUT_MS, 
            player_vowel_powers=game_state["player_vowel_powers"],
            cursed_letters=game_state["cursed_letters"],
            dead_letters=game_state["dead_letters"],
            player_phone_pads=game_state["player_phone_pads"],
            player_letter_counts=game_state["player_letter_counts"],
            player_max_timeouts=game_state["player_max_timeouts"],
            player_inabilities=game_state["player_inabilities"],
            active_missions=[m.to_dict() for m in game_state["active_missions"]],
            completed_missions=[m.to_dict() for m in game_state["completed_missions"]],
            letter_curse_counts=game_state["letter_curse_counts"],
            incomingPlayers=game_state["players"], 
            incomingTurnCounts=game_state["turn_counts"],
            incomingReadyPlayers=game_state["ready_players"], 
            incomingHistory=[]
        )

        if first_player_identifier == game_state["own_identifier"]:
            background_tasks.add_task(receive_ball, payload_to_send)
        else:
            background_tasks.add_task(send_ball_in_background, first_player_identifier, payload_to_send.dict())

async def play_computer_turn_and_return(ball_from_human: BallPayload):
    '''Computer plays a turn by adding a random letter and passes the ball back to the human.'''
    await asyncio.sleep(1)  # Simulate thinking

    with state_lock:
        computer_id = "computer"
        human_player_id = game_state["own_identifier"]
        base_word = ball_from_human.word

        new_letter = random.choice('abcdefghijklmnopqrstuvwxyz')
        computer_new_word = base_word + new_letter

        logging.info(f"Computer chose letter '{new_letter}' to form '{computer_new_word}'")

        response_time_ms = random.randint(300, 900)
        computer_vowel_power = game_state["player_vowel_powers"].get(computer_id, {v: 1.0 for v in VOWELS})
        
        next_timeout_for_human, computer_modifiers, next_computer_vowel_power, timeout_log = calculate_next_timeout(
            response_time_ms, computer_new_word, computer_vowel_power
        )
        game_state["player_vowel_powers"][computer_id] = next_computer_vowel_power
        game_state["player_max_timeouts"][human_player_id] = next_timeout_for_human

        history_entry = HistoryEntry(
            player=computer_id,
            word=computer_new_word,
            response_time_ms=response_time_ms,
            applied_multipliers=computer_modifiers,
            timeout_log=timeout_log
        )
        game_state["history"].append(history_entry)
        game_state["turn_counts"].setdefault(computer_id, 0)
        game_state["turn_counts"][computer_id] += 1
        game_state["active_player"] = human_player_id

        ball_for_human = BallPayload(
            word=computer_new_word,
            timeout_ms=next_timeout_for_human,
            player_vowel_powers=game_state["player_vowel_powers"],
            cursed_letters=game_state["cursed_letters"],
            dead_letters=game_state["dead_letters"],
            player_phone_pads=game_state["player_phone_pads"],
            player_letter_counts=game_state["player_letter_counts"],
            player_max_timeouts=game_state["player_max_timeouts"],
            player_inabilities=game_state["player_inabilities"],
            active_missions=[m.to_dict() for m in game_state["active_missions"]],
            completed_missions=[m.to_dict() for m in game_state["completed_missions"]],
            letter_curse_counts=game_state["letter_curse_counts"],
            incomingPlayers=game_state["players"],
            incomingTurnCounts=game_state["turn_counts"],
            incomingReadyPlayers=game_state["ready_players"],
            incomingHistory=game_state["history"]
        )

        await receive_ball(ball_for_human)

async def initiate_rematch_logic(background_tasks: BackgroundTasks):
    with state_lock:
        if game_state.get("history"):
            if game_state["history"]:
                game_state["archive"].append(list(game_state["history"]))
        
        reset_local_game_state()
        game_state["history"] = []
        game_state["last_loser"] = None
        game_state["attack_combo_player"] = None
        
        current_players = game_state.get("players", [])
        game_state["ready_players"] = list(current_players)
        
        game_state["player_vowel_powers"] = {p_id: {v: 1.0 for v in VOWELS} for p_id in current_players}
        game_state["cursed_letters"] = []
        game_state["dead_letters"] = []
        game_state["player_phone_pads"] = {p_id: get_new_phone_pad() for p_id in current_players}
        game_state["player_letter_counts"] = {p_id: {} for p_id in current_players}
        game_state["player_max_timeouts"] = {p_id: BASE_TIMEOUT_MS for p_id in current_players}
        game_state["player_inabilities"] = {p_id: [] for p_id in current_players}
        game_state["letter_curse_counts"] = {}
        select_initial_missions()

        initiator = sorted(current_players)[0]
        my_id = game_state["own_identifier"]
        if my_id == initiator:
            start_game_logic(background_tasks)

    await manager.broadcast_state()

async def end_turn(background_tasks: BackgroundTasks, current_player_id: str, timeout_for_next_player: int, new_inabilities: List[str] = [], applied_modifiers: List[str] = [], ricochet: bool = False, mirror_move: bool = False):
    with state_lock:
        if mirror_move:
            if len(game_state["history"]) > 1:
                game_state["history"].pop()
                last_word = game_state["history"][-1].word
                game_state["current_word"] = last_word
                next_player_identifier = game_state["history"][-1].player
            else: # Should not happen in a real game
                next_player_identifier = current_player_id
        elif ricochet:
            next_player_identifier = [p for p in game_state["players"] if p != current_player_id][0]
        else:
            other_players = [p_id for p_id in game_state.get("players", []) if p_id != current_player_id]
            next_player_identifier = None

            if "computer" in other_players:
                next_player_identifier = "computer"
            elif other_players:
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
                    next_player_identifier = current_player_id
            else:
                next_player_identifier = current_player_id

        game_state["turn_counts"].setdefault(next_player_identifier, 0)
        game_state["turn_counts"][next_player_identifier] += 1
        game_state["active_player"] = next_player_identifier
        game_state["player_max_timeouts"][next_player_identifier] = timeout_for_next_player

        current_player_inabilities = game_state["player_inabilities"].get(current_player_id, [])
        next_player_inabilities = game_state["player_inabilities"].get(next_player_identifier, [])
        
        game_state["player_inabilities"][next_player_identifier] = list(set(next_player_inabilities + new_inabilities))
        game_state["player_inabilities"][current_player_id] = []

        if applied_modifiers:
            last_history = game_state["history"][-1]
            last_history.applied_multipliers.extend(applied_modifiers)

        next_payload = BallPayload(
            word=game_state["history"][-1].word, 
            timeout_ms=timeout_for_next_player, 
            player_vowel_powers=game_state["player_vowel_powers"],
            cursed_letters=game_state["cursed_letters"],
            dead_letters=game_state["dead_letters"],
            player_phone_pads=game_state["player_phone_pads"],
            player_letter_counts=game_state["player_letter_counts"],
            player_max_timeouts=game_state["player_max_timeouts"],
            player_inabilities=game_state["player_inabilities"],
            active_missions=[m.to_dict() for m in game_state["active_missions"]],
            completed_missions=[m.to_dict() for m in game_state["completed_missions"]],
            letter_curse_counts=game_state["letter_curse_counts"],
            incomingPlayers=game_state["players"], 
            incomingTurnCounts=game_state["turn_counts"],
            incomingReadyPlayers=game_state["ready_players"], 
            incomingHistory=game_state["history"],
            scramble_ui_for_player=game_state.get("scramble_ui_for_player"),
            forced_letter=game_state.get("forced_letter"),
        )
        
        reset_local_game_state()

        if next_player_identifier == "computer":
            background_tasks.add_task(play_computer_turn_and_return, next_payload)
        elif next_player_identifier != current_player_id:
            background_tasks.add_task(send_ball_in_background, next_player_identifier, next_payload.dict())
        else:
            background_tasks.add_task(receive_ball, next_payload)

# --- API Endpoints ---

@app.post("/api/discover")
async def discover(background_tasks: BackgroundTasks):
    background_tasks.add_task(discover_peers)
    return {"message": "Discovery process started."}

@app.post("/api/power-up")
async def power_up(background_tasks: BackgroundTasks):
    with state_lock:
        my_id = game_state["own_identifier"]
        my_pad = game_state["player_phone_pads"].get(my_id)
        if not my_pad:
            raise HTTPException(status_code=404, detail="Player pad not found.")

        is_ready = all(my_pad.get(str(num), 0) >= 1 for num in range(2, 10))
        if not is_ready:
            raise HTTPException(status_code=400, detail="Power-up not ready.")

        logging.info(f"Player {my_id} triggered Power-Up!")
        
        for player_id in game_state["players"]:
            if player_id != my_id:
                game_state["player_phone_pads"][player_id] = get_new_phone_pad()

        game_state["player_phone_pads"][my_id] = get_new_phone_pad()
        
        await end_turn(background_tasks, my_id, BASE_TIMEOUT_MS, new_inabilities=[], applied_modifiers=["power-up"])

    return {"message": "Power-up activated and turn passed."}

@app.post("/api/combo")
async def trigger_combo(payload: ComboPayload, background_tasks: BackgroundTasks):
    with state_lock:
        my_id = game_state["own_identifier"]
        combo_key = payload.combo_key
        
        if combo_key not in PAD_COLUMNS:
            raise HTTPException(status_code=400, detail="Invalid combo key.")

        my_pad = game_state["player_phone_pads"].get(my_id)
        if not my_pad:
            raise HTTPException(status_code=404, detail="Player pad not found.")

        column_nums = PAD_COLUMNS[combo_key]
        is_combo_ready = all(my_pad.get(num, 0) >= 1 for num in column_nums)

        if not is_combo_ready:
            raise HTTPException(status_code=400, detail="Combo not ready.")

        logging.info(f"Player {my_id} triggered combo '{combo_key}'!")
        
        new_inabilities_for_next_player = []
        if combo_key == '*': # Purge
            game_state["cursed_letters"] = []
        elif combo_key == '0': # Recharge
            for v in VOWELS:
                game_state["player_vowel_powers"][my_id][v] = MAX_VOWEL_POWER
        elif combo_key == '#': # Attack
            for num in column_nums:
                for letter, pad_num in LETTER_TO_PAD.items():
                    if pad_num == num and letter not in new_inabilities_for_next_player:
                        new_inabilities_for_next_player.append(letter)
        
        for num in column_nums:
            if num in my_pad:
                my_pad[num] = 0
        
        await end_turn(background_tasks, my_id, BASE_TIMEOUT_MS, new_inabilities=new_inabilities_for_next_player, applied_modifiers=[f"combo {combo_key}"])

    return {"message": f"Combo {combo_key} activated and turn passed."}

@app.post("/api/register")
async def register(payload: RegisterPayload, background_tasks: BackgroundTasks):
    with state_lock:
        new_player_id = payload.ip
        if new_player_id and new_player_id not in game_state["players"]:
            game_state["players"].append(new_player_id)
            game_state["turn_counts"].setdefault(new_player_id, 0)
            game_state["player_vowel_powers"][new_player_id] = {v: 1.0 for v in VOWELS}
            game_state["player_phone_pads"][new_player_id] = get_new_phone_pad()
            game_state["player_letter_counts"][new_player_id] = {}
            game_state["player_max_timeouts"][new_player_id] = BASE_TIMEOUT_MS
            game_state["player_inabilities"][new_player_id] = []
            background_tasks.add_task(register_back, new_player_id)
        
        game_state["players"] = list(set(game_state["players"]).union(set(payload.initialPlayers)))
        game_state["turn_counts"].update(payload.initialTurnCounts)
        game_state["ready_players"] = list(set(game_state["ready_players"]).union(set(payload.initialReadyPlayers)))
        if len(payload.initialArchive) > len(game_state["archive"]):
            game_state["archive"] = payload.initialArchive
        
        game_state["player_vowel_powers"].update(payload.initialPlayerVowelPowers)
        game_state["cursed_letters"] = list(set(game_state["cursed_letters"]).union(set(payload.initialCursedLetters)))
        game_state["dead_letters"] = list(set(game_state["dead_letters"]).union(set(payload.initialDeadLetters)))
        game_state["player_phone_pads"].update(payload.initialPlayerPhonePads)
        game_state["player_letter_counts"].update(payload.initialPlayerLetterCounts)
        game_state["player_max_timeouts"].update(payload.initialPlayerMaxTimeouts)
        game_state["player_inabilities"].update(payload.initialPlayerInabilities)
        
        if payload.initialActiveMissions:
            reconstructed_active_missions = []
            for m_dict in payload.initialActiveMissions:
                template = find_mission_template_by_id(m_dict["id"])
                if template:
                    mission_instance = template.copy()
                    mission_instance.current_step = m_dict.get("current_step", 0)
                    reconstructed_active_missions.append(mission_instance)
            game_state["active_missions"] = reconstructed_active_missions

        if payload.initialCompletedMissions:
            reconstructed_completed_missions = []
            for m_dict in payload.initialCompletedMissions:
                template = find_mission_template_by_id(m_dict["id"])
                if template:
                    reconstructed_completed_missions.append(template.copy())
            game_state["completed_missions"] = reconstructed_completed_missions
            
        game_state["letter_curse_counts"].update(payload.initialLetterCurseCounts)

    await manager.broadcast_state()
    return {"message": "Registered"}

@app.post("/api/ready")
async def im_ready(background_tasks: BackgroundTasks):
    with state_lock:
        my_id = game_state["own_identifier"]
        if my_id not in game_state["ready_players"]:
            game_state["ready_players"].append(my_id)

        if len(game_state["players"]) == 1 and game_state["players"][0] == my_id:
            computer_id = "computer"
            if computer_id not in game_state["players"]:
                game_state["players"].append(computer_id)
                game_state["turn_counts"][computer_id] = 0
                game_state["player_vowel_powers"][computer_id] = {v: 1.0 for v in VOWELS}
                game_state["player_phone_pads"][computer_id] = get_new_phone_pad()
                game_state["player_letter_counts"][computer_id] = {}
                game_state["player_max_timeouts"][computer_id] = BASE_TIMEOUT_MS
                game_state["player_inabilities"][computer_id] = []
            if computer_id not in game_state["ready_players"]:
                game_state["ready_players"].append(computer_id)
        else:
            broadcast_sync('/api/notify-ready', {"player_id": my_id})

        known_players = set(game_state["players"])
        ready_players = set(game_state["ready_players"])
        
        if known_players.issubset(ready_players) and len(ready_players) >= 1 and game_state.get("current_word") is None:
            initiator = sorted(list(known_players))[0]
            if my_id == initiator or "computer" in known_players:
                start_game_logic(background_tasks)
            
    await manager.broadcast_state()
    return {"message": "You are ready."}

@app.post("/api/notify-ready")
async def notify_ready(payload: ReadyPayload, background_tasks: BackgroundTasks):
    with state_lock:
        player_id = payload.player_id
        if player_id not in game_state["ready_players"]:
            game_state["ready_players"].append(player_id)
        
        known_players = set(game_state["players"])
        ready_players = set(game_state["ready_players"])
        if known_players.issubset(ready_players) and len(ready_players) >= 1 and game_state.get("current_word") is None:
            initiator = sorted(list(known_players))[0]
            my_id = game_state["own_identifier"]
            if my_id == initiator:
                start_game_logic(background_tasks)

    await manager.broadcast_state()
    return {"message": "Notification received."}

@app.post("/api/receive-ball")
async def receive_ball(payload: BallPayload):
    with state_lock:
        reset_local_game_state()

        reconstructed_active_missions = []
        for m_dict in payload.active_missions:
            template = find_mission_template_by_id(m_dict["id"])
            if template:
                mission_instance = template.copy()
                mission_instance.current_step = m_dict.get("current_step", 0)
                reconstructed_active_missions.append(mission_instance)
        
        reconstructed_completed_missions = []
        for m_dict in payload.completed_missions:
            template = find_mission_template_by_id(m_dict["id"])
            if template:
                reconstructed_completed_missions.append(template.copy())

        game_state.update({
            "current_word": payload.word,
            "players": list(set(game_state.get("players", [])).union(set(payload.incomingPlayers))),
            "ready_players": list(set(game_state.get("ready_players", [])).union(set(payload.incomingReadyPlayers))),
            "player_vowel_powers": payload.player_vowel_powers,
            "cursed_letters": payload.cursed_letters,
            "dead_letters": payload.dead_letters,
            "player_phone_pads": payload.player_phone_pads,
            "player_letter_counts": payload.player_letter_counts,
            "player_max_timeouts": payload.player_max_timeouts,
            "player_inabilities": payload.player_inabilities,
            "active_missions": reconstructed_active_missions,
            "completed_missions": reconstructed_completed_missions,
            "letter_curse_counts": payload.letter_curse_counts,
            "history": payload.incomingHistory,
            "turn_start_time": time.time(),
            "current_turn_timeout_ms": payload.timeout_ms,
            "active_player": game_state["own_identifier"],
            "scramble_ui_for_player": payload.scramble_ui_for_player,
            "forced_letter": payload.forced_letter,
        })
        
        game_state["game_timer"] = threading.Timer(payload.timeout_ms / 1000.0, lambda: asyncio.run(handle_loss()))
        game_state["game_timer"].start()

    await manager.broadcast_state()
    return {"message": "Ball received."}

@app.post("/api/pass-ball")
async def pass_ball(payload: PassBallPayload, background_tasks: BackgroundTasks):
    with state_lock:
        my_id = game_state["own_identifier"]
        current_word = game_state.get("current_word")
        turn_start_time = game_state.get("turn_start_time")

        if current_word is None:
            raise HTTPException(status_code=408, detail="Server-side timeout or not your turn.")
        if not payload.newWord.startswith(current_word) or len(payload.newWord) != len(current_word) + 1:
            raise HTTPException(status_code=400, detail="Invalid word.")
        
        if game_state.get("game_timer"): 
            game_state["game_timer"].cancel()

        new_letter = payload.newWord[-1]

        if game_state.get("forced_letter") and new_letter != game_state["forced_letter"]:
            raise HTTPException(status_code=400, detail=f"Forced to play '{game_state['forced_letter']}'.")
        game_state["forced_letter"] = None

        if new_letter in game_state.get("dead_letters", []):
            logging.info(f"Player {my_id} played a dead letter '{new_letter}' and loses instantly.")
            broadcast_sync("/api/game-over", {"loser": my_id, "reason": f"Played dead letter {new_letter}"})
            await game_over(GameOverPayload(loser=my_id, reason=f"Played dead letter {new_letter}"))
            return {"message": "You played a dead letter and lost."}

        if new_letter in game_state.get("player_inabilities", {}).get(my_id, []):
            raise HTTPException(status_code=403, detail=f"Letter {new_letter} is blocked for you this turn.")

        game_state["player_inabilities"][my_id] = []

        if turn_start_time is None:
            turn_start_time = time.time() - (game_state.get("current_turn_timeout_ms", BASE_TIMEOUT_MS) / 1000.0)
            logging.warning("turn_start_time was None; using fallback.")
        response_time_ms = int((payload.client_timestamp_ms / 1000 - turn_start_time) * 1000)

        cursed_malus = new_letter in game_state["cursed_letters"]
        if cursed_malus:
            game_state["cursed_letters"].remove(new_letter)
            game_state["player_phone_pads"][my_id] = get_new_phone_pad()
            logging.info(f"Player {my_id} played cursed letter '{new_letter}'. Curse lifted for all, pad reset for player.")
            for player_id in game_state["player_letter_counts"]:
                if new_letter in game_state["player_letter_counts"][player_id]:
                    game_state["player_letter_counts"][player_id][new_letter] = 0

        pad_number = LETTER_TO_PAD.get(new_letter)
        if pad_number:
            my_pad = game_state["player_phone_pads"].setdefault(my_id, get_new_phone_pad())
            if my_pad[pad_number] < PAD_CHARGE_THRESHOLD:
                my_pad[pad_number] += 1

        pad_combo_malus = False
        if game_state.get("attack_combo_player") == my_id:
            pad_combo_malus = True
            game_state["attack_combo_player"] = None
            logging.info(f"Player {my_id} consumes their Attack combo.")

        my_vowel_power = game_state["player_vowel_powers"].get(my_id, {v: 1.0 for v in VOWELS})
        next_timeout, modifiers, next_vowel_power, timeout_log = calculate_next_timeout(response_time_ms, payload.newWord, my_vowel_power, cursed_malus, pad_combo_malus)
        game_state["player_vowel_powers"][my_id] = next_vowel_power
        history_entry = HistoryEntry(player=my_id, word=payload.newWord, response_time_ms=response_time_ms, applied_multipliers=modifiers, timeout_log=timeout_log)
        game_state["history"].append(history_entry)

        my_counts = game_state["player_letter_counts"].setdefault(my_id, {})
        my_counts[new_letter] = my_counts.get(new_letter, 0) + 1
        if my_counts[new_letter] >= CURSE_THRESHOLD:
            curse_count = game_state["letter_curse_counts"].get(new_letter, 0)
            if curse_count == 0:
                if new_letter not in game_state["cursed_letters"]:
                    game_state["cursed_letters"].append(new_letter)
                game_state["letter_curse_counts"][new_letter] = 1
                logging.info(f"Letter '{new_letter}' is now globally cursed.")
            elif curse_count == 1:
                if new_letter in game_state["cursed_letters"]:
                    game_state["cursed_letters"].remove(new_letter)
                if new_letter not in game_state["dead_letters"]:
                    game_state["dead_letters"].append(new_letter)
                game_state["letter_curse_counts"][new_letter] = 2
                logging.info(f"Letter '{new_letter}' is now in a DEAD STATE.")
            my_counts[new_letter] = 0

        for mission in game_state["active_missions"]:
            mission.progress_func(mission, my_id, new_letter)

        ricochet = False
        mirror_move = False
        triggered_missions = []
        for mission in list(game_state["active_missions"]):
            trigger_data = {
                "player_id": my_id,
                "new_letter": new_letter,
                "new_word": payload.newWord,
                "response_time_ms": response_time_ms,
                "timeout_ms": game_state.get("current_turn_timeout_ms", BASE_TIMEOUT_MS),
                "history": game_state["history"],
                "player_letter_counts": game_state["player_letter_counts"].get(my_id, {}),
            }
            if mission.trigger_func(mission, trigger_data):
                triggered_missions.append(mission)
        
        for mission in triggered_missions:
            await mission.effect_func(my_id, background_tasks)
            replace_triggered_mission(mission)
            modifiers.append(f"mission:{mission.name}")
            if mission.id == "echo_parfait": ricochet = True
            if mission.id == "symetrie_inversee": mirror_move = True

        if game_state["opponent_speed_multiplier"].get(my_id):
            next_timeout = int(next_timeout / game_state["opponent_speed_multiplier"][my_id])
            del game_state["opponent_speed_multiplier"][my_id]

        next_timeout = int(next_timeout * game_state["base_timeout_modifier"])

        await end_turn(background_tasks, my_id, next_timeout, applied_modifiers=modifiers, ricochet=ricochet, mirror_move=mirror_move)

    return {"message": "Ball passed successfully."}

@app.post("/api/game-over")
async def game_over(payload: GameOverPayload):
    with state_lock:
        if game_state.get("current_word") is None and not game_state.get("history"):
            return {"message": "Game already over."}

        game_state["last_loser"] = payload.loser
        if game_state.get("history"):
            game_state["archive"].append(list(game_state["history"]))
    
    await reset_full_game_state_and_broadcast()
    return {"message": "OK"}

@app.post("/api/rematch")
async def rematch(background_tasks: BackgroundTasks):
    broadcast_sync("/api/rematch-broadcast", {})
    await initiate_rematch_logic(background_tasks)
    return {"message": "Rematch proposed."}

@app.post("/api/rematch-broadcast")
async def rematch_broadcast(background_tasks: BackgroundTasks):
    await initiate_rematch_logic(background_tasks)
    return {"message": "OK"}

@app.get("/health")
def health_check(): return {"status": "ok"}

@app.get("/api/ping")
def ping_for_discovery():
    with state_lock:
        return {"message": "pong", "identity": game_state.get("own_identifier")}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    await manager.broadcast_state()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
