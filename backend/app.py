import logging
import os
import threading
import random
import ipaddress  # Importation pour la manipulation d'IP
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
OWN_PORT = int(os.getenv("OWN_PORT", "5000"))
NETMASK_CIDR = os.getenv("NETMASK_CIDR", "24")  # Défaut à /24 (255.255.255.0)
INTERNAL_PORT = 5000  # Le port interne du conteneur est toujours 5000

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
    """Réinitialise l'état du jeu localement."""
    logging.info("État du jeu local réinitialisé.")
    with state_lock:
        if game_state.get("game_timer"):
            game_state["game_timer"].cancel()
        game_state["current_word"] = None
        game_state["game_timer"] = None

def broadcast(endpoint: str, payload: dict):
    """Diffuse un message à tous les autres joueurs."""
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
    """Gère la défaite du joueur lorsque le temps est écoulé."""
    logging.warning("Le minuteur de 5 secondes a expiré. Le joueur a perdu.")
    broadcast('/api/game-over', {'loser': game_state.get("own_identifier"), 'reason': 'Temps écoulé'})
    reset_local_game_state()

# --- Événement de Démarrage ---
@app.on_event("startup")
def on_startup():
    """Initialise l'état du jeu au démarrage du serveur."""
    with state_lock:
        game_state["own_identifier"] = f"{OWN_HOST}:{OWN_PORT}"
        game_state["players"] = [game_state["own_identifier"]]
        game_state["turn_counts"] = {game_state["own_identifier"]: 0}
        game_state["current_word"] = None
        game_state["game_timer"] = None
    logging.info(f"Serveur démarré. Identité: {game_state['own_identifier']}")

# --- Tâche de Fond pour l'envoi de la balle ---
def send_ball_in_background(player_identifier: str, payload: dict):
    """Envoie la balle dans un thread séparé pour éviter les deadlocks."""
    logging.info(f"Tâche de fond démarrée pour envoyer la balle à {player_identifier}.")
    try:
        requests.post(f"http://{player_identifier}/api/receive-ball", json=payload, timeout=2)
        logging.info(f"Tâche de fond: Balle envoyée avec succès à {player_identifier}.")
    except requests.RequestException as e:
        logging.error(f"Tâche de fond: Erreur en passant la balle à {player_identifier}: {e}")
        broadcast('/api/game-over', {'loser': game_state.get("own_identifier"), 'reason': f'Impossible de contacter {player_identifier}'})

# --- API Endpoints ---

def discover_player(ip_to_try: str):
    """Tente de contacter un joueur sur une IP donnée et sur les ports publics connus."""
    if ip_to_try == OWN_HOST:
        return

    # On teste tous les ports publics définis dans docker-compose.yml
    for port in [INTERNAL_PORT]:
        player_identifier = f"{ip_to_try}:{port}"
        logging.debug(f"Tentative de découverte sur {player_identifier}...")
        try:
            with state_lock:
                if player_identifier in game_state["players"]:
                    continue
                payload = {"ip": game_state["own_identifier"], "initialPlayers": game_state["players"], "initialTurnCounts": game_state["turn_counts"]}

            response = requests.post(f"http://{player_identifier}/api/register", json=payload, timeout=0.5)

            if response.status_code == 200:
                logging.info(f"Joueur découvert et enregistré avec succès à l'adresse : {player_identifier}")
                data = response.json()
                with state_lock:
                    game_state["players"] = list(set(game_state["players"]).union(set(data.get("allPlayers", []))))
                    game_state["turn_counts"].update(data.get("allTurnCounts", {}))
        except requests.RequestException:
            pass  # C'est normal que la plupart des requêtes échouent

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

@app.get("/api/get-ball")
def get_ball():
    with state_lock:
        word = game_state.get("current_word")
        return {"word": word}

@app.post("/api/register")
def register(payload: RegisterPayload):
    logging.info(f"Requête d'enregistrement reçue de: {payload.ip}")
    with state_lock:
        if payload.ip and payload.ip not in game_state["players"]:
            game_state["players"].append(payload.ip)
            game_state["turn_counts"].setdefault(payload.ip, 0)

        current_players = set(game_state["players"])
        new_players = set(payload.initialPlayers)
        game_state["players"] = list(current_players.union(new_players))
        game_state["turn_counts"].update(payload.initialTurnCounts)

        return {"message": "Enregistré", "allPlayers": game_state["players"], "allTurnCounts": game_state["turn_counts"]}

@app.post("/api/receive-ball")
def receive_ball(payload: BallPayload):
    logging.info(f"Requête pour recevoir la balle avec le mot: '{payload.word}'")
    with state_lock:
        if game_state.get("current_word") is not None:
            logging.warning(f"Conflit: Balle reçue alors que le mot actuel est '{game_state.get('current_word')}'. Rejet.")
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
    logging.info(f"Requête pour passer la balle avec le mot: '{payload.newWord}'")
    with state_lock:
        current_word = game_state.get("current_word")
        logging.debug(f"Validation: Mot actuel du serveur='{current_word}', Mot soumis='{payload.newWord}'")
        if current_word is None:
            logging.warning("Validation échouée: Le tour a déjà expiré côté serveur.")
            raise HTTPException(status_code=408, detail="Temps écoulé côté serveur.")
        if not payload.newWord.startswith(current_word) or len(payload.newWord) != len(current_word) + 1:
            logging.warning("Validation échouée: Le mot soumis est invalide.")
            raise HTTPException(status_code=400, detail="Mot invalide.")

        logging.info("Validation du mot réussie.")
        if game_state.get("game_timer"):
            game_state["game_timer"].cancel()

        all_players = game_state["players"]
        min_turns = min(game_state["turn_counts"].get(p_id, 0) for p_id in all_players)
        eligible_players = [p_id for p_id in all_players if game_state["turn_counts"].get(p_id, 0) == min_turns]
        next_player_identifier = random.choice(eligible_players)
        logging.info(f"Joueur choisi pour le prochain tour: {next_player_identifier}")

        game_state["turn_counts"][next_player_identifier] += 1
        next_payload = BallPayload(
            word=payload.newWord,
            incomingPlayers=game_state["players"],
            incomingTurnCounts=game_state["turn_counts"]
        )

        if next_player_identifier == game_state["own_identifier"]:
            logging.info("Destination LOCALE détectée. Appel direct de la fonction receive_ball.")
            reset_local_game_state()
            receive_ball(next_payload)
        else:
            logging.info("Destination DISTANTE détectée. Planification de la tâche de fond.")
            reset_local_game_state()
            background_tasks.add_task(
                send_ball_in_background,
                player_identifier=next_player_identifier,
                payload=next_payload.dict()
            )
    return {"message": "Balle passée avec succès."}

@app.post("/api/start-game")
def start_game(background_tasks: BackgroundTasks):
    logging.info("Requête pour démarrer une nouvelle partie.")
    with state_lock:
        start_word = random.choice('abcdefghijklmnopqrstuvwxyz')
        logging.debug(f"Lettre de départ générée: '{start_word}'")

        all_players = game_state["players"]
        if not all_players:
            raise HTTPException(status_code=400, detail="Aucun joueur trouvé pour démarrer une partie.")

        first_player_identifier = random.choice(all_players)
        logging.info(f"Premier joueur choisi: {first_player_identifier}")

        for p_id in all_players:
            game_state["turn_counts"].setdefault(p_id, 0)
        game_state["turn_counts"][first_player_identifier] += 1

        payload_to_send = BallPayload(
            word=start_word,
            incomingPlayers=game_state["players"],
            incomingTurnCounts=game_state["turn_counts"]
        )
        logging.debug(f"Payload de départ préparé: {payload_to_send}")

        if first_player_identifier == game_state["own_identifier"]:
            logging.info("Destination LOCALE détectée pour le premier tour. Appel direct de receive_ball.")
            receive_ball(payload_to_send)
        else:
            logging.info("Destination DISTANTE détectée pour le premier tour. Tâche de fond planifiée.")
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
    uvicorn.run(app, host="0.0.0.0", port=INTERNAL_PORT)


@app.get("/api/players")
def get_players():
    """Retourne la liste actuelle des joueurs et leurs comptes de tours."""
    logging.debug("Requête pour obtenir la liste des joueurs.")
    with state_lock:
        # On retourne une copie pour la sécurité des threads, même si c'est pour de la lecture
        players_list = list(game_state.get("players", []))
        turn_counts_dict = dict(game_state.get("turn_counts", {}))

        return {
            "players": players_list,
            "turn_counts": turn_counts_dict
        }