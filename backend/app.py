import logging
import os
import random
import requests
import threading
import uvicorn
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Body, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Optional

# --- MODIFICATION: Configuration du logging pour afficher les messages DEBUG ---
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

OWN_HOST = os.getenv("OWN_HOST", "localhost")
OWN_PORT = int(os.getenv("OWN_PORT", "5000"))
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


# --- État du jeu ---
game_state: Dict = {}
state_lock = threading.RLock()


# --- Fonctions Utilitaires ---
def reset_local_game_state():
    logging.debug(f"État AVANT réinitialisation: {game_state}")
    with state_lock:
        if game_state.get("game_timer"):
            game_state["game_timer"].cancel()
        game_state["current_word"] = None
        game_state["game_timer"] = None
    logging.info("État du jeu local réinitialisé (current_word=None).")


def broadcast(endpoint: str, payload: dict):
    with state_lock:
        players_to_contact = [p_id for p_id in game_state.get("players", []) if
                              p_id != game_state.get("own_identifier")]
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
        game_state["own_identifier"] = f"{OWN_HOST}:{OWN_PORT}"
        game_state["players"] = [game_state["own_identifier"]]
        game_state["turn_counts"] = {game_state["own_identifier"]: 0}
        game_state["current_word"] = None
        game_state["game_timer"] = None
    logging.info(f"Serveur démarré. Identité: {game_state['own_identifier']}")
    logging.debug(f"État initial complet: {game_state}")


# --- Tâche de fond ---
def send_ball_in_background(player_identifier: str, payload: dict):
    logging.info(f"Tâche de fond démarrée pour envoyer la balle à {player_identifier}.")
    try:
        requests.post(f"http://{player_identifier}/api/receive-ball", json=payload, timeout=2)
        logging.info(f"Tâche de fond: Balle envoyée avec succès à {player_identifier}.")
    except requests.RequestException as e:
        logging.error(f"Tâche de fond: Erreur en passant la balle à {player_identifier}: {e}")
        broadcast('/api/game-over',
                  {'loser': game_state.get("own_identifier"), 'reason': f'Impossible de contacter {player_identifier}'})


# --- API Endpoints ---
@app.get("/api/get-ball")
def get_ball():
    with state_lock:
        word = game_state.get("current_word")
        logging.debug(f"Requête GET pour la balle. Mot actuel: '{word}'.")
        return {"word": word}


@app.post("/api/register")
def register(payload: RegisterPayload):
    logging.info(f"Requête d'enregistrement reçue de: {payload.ip}")
    logging.debug(f"Payload d'enregistrement complet: {payload}")
    with state_lock:
        if payload.ip and payload.ip not in game_state["players"]:
            logging.info(f"Nouveau joueur ajouté: {payload.ip}")
            game_state["players"].append(payload.ip)
            game_state["turn_counts"].setdefault(payload.ip, 0)

        logging.debug(f"Liste de joueurs avant fusion: {game_state['players']}")
        current_players = set(game_state["players"])
        new_players = set(payload.initialPlayers)
        game_state["players"] = list(current_players.union(new_players))
        game_state["turn_counts"].update(payload.initialTurnCounts)
        logging.debug(f"Liste de joueurs après fusion: {game_state['players']}")

        return {"message": "Enregistré", "allPlayers": game_state["players"],
                "allTurnCounts": game_state["turn_counts"]}


def discover_player(port_to_try: int):
    player_identifier = f"{OWN_HOST}:{port_to_try}"
    if player_identifier == game_state.get("own_identifier"): return
    logging.debug(f"Tentative de découverte sur {player_identifier}...")
    # ... (le reste de la fonction est inchangé)
    try:
        with state_lock:
            payload = {"ip": game_state["own_identifier"], "initialPlayers": game_state["players"],
                       "initialTurnCounts": game_state["turn_counts"]}
        response = requests.post(f"http://{player_identifier}/api/register", json=payload, timeout=0.5)
        if response.status_code == 200:
            logging.info(f"Joueur découvert et enregistré avec succès à l'adresse : {player_identifier}")
            data = response.json()
            with state_lock:
                game_state["players"] = list(set(game_state["players"]).union(set(data.get("allPlayers", []))))
                game_state["turn_counts"].update(data.get("allTurnCounts", {}))
    except requests.RequestException:
        pass


@app.post("/api/discover", status_code=202)
def discover():
    logging.info(f"Lancement de la découverte réseau sur {OWN_HOST}...")
    ports_to_scan = range(5000, 5011)
    executor = ThreadPoolExecutor(max_workers=11)
    threading.Thread(target=lambda: executor.map(discover_player, ports_to_scan)).start()
    return {"message": "Découverte réseau lancée en arrière-plan."}


@app.post("/api/receive-ball")
def receive_ball(payload: BallPayload):
    logging.info(f"Requête pour recevoir la balle avec le mot: '{payload.word}'")
    logging.debug(f"Payload de réception complet: {payload}")
    with state_lock:
        if game_state.get("current_word") is not None:
            logging.warning(
                f"Conflit: Balle reçue alors que le mot actuel est '{game_state.get('current_word')}'. Rejet de la requête.")
            raise HTTPException(status_code=409, detail="Déjà en train de jouer un tour.")

        game_state["current_word"] = payload.word
        game_state["players"] = list(set(game_state["players"]).union(set(payload.incomingPlayers)))
        game_state["turn_counts"].update(payload.incomingTurnCounts)
        logging.info(f"Nouveau tour commencé. Mot: '{game_state['current_word']}'. Démarrage du minuteur de 5s.")

        game_state["game_timer"] = threading.Timer(10.0, handle_loss)
        game_state["game_timer"].start()
    return {"message": "Balle reçue."}


@app.post("/api/pass-ball")
def pass_ball(payload: PassBallPayload, background_tasks: BackgroundTasks):
    logging.info(f"Requête pour passer la balle avec le mot: '{payload.newWord}'")
    with state_lock:
        # --- Validation ---
        current_word = game_state.get("current_word")
        logging.debug(f"Validation: Mot actuel du serveur='{current_word}', Mot soumis='{payload.newWord}'")
        if current_word is None:
            logging.warning("Validation échouée: Le tour a déjà expiré côté serveur (mot actuel is None).")
            raise HTTPException(status_code=408, detail="Temps écoulé côté serveur.")
        if not payload.newWord.startswith(current_word) :
            logging.warning("Validation échouée: Le mot soumis est invalide.")
            raise HTTPException(status_code=400, detail="Mot invalide.")
        if len(payload.newWord) != len(current_word) + 1 :
            logging.warning("Validation échouée: il manque une nouvelle lettre.")
            raise HTTPException(status_code=400, detail="Mot trop court.")

        logging.info("Validation du mot réussie.")

        if game_state.get("game_timer"):
            logging.debug("Annulation du minuteur de 10s.")
            game_state["game_timer"].cancel()

        # --- Sélection du joueur ---
        all_players = game_state["players"]
        min_turns = min(game_state["turn_counts"].get(p_id, 0) for p_id in all_players)
        eligible_players = [p_id for p_id in all_players if game_state["turn_counts"].get(p_id, 0) == min_turns]
        next_player_identifier = random.choice(eligible_players)
        logging.info(
            f"Joueurs éligibles (min tours={min_turns}): {eligible_players}. Joueur choisi: {next_player_identifier}")

        # --- Préparation du payload ---
        game_state["turn_counts"][next_player_identifier] += 1
        next_payload = BallPayload(
            word=payload.newWord,
            incomingPlayers=game_state["players"],
            incomingTurnCounts=game_state["turn_counts"]
        )
        logging.debug(f"Payload préparé pour le prochain joueur: {next_payload}")

        # --- Routage local/distant ---
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
@app.post("/api/start-game")
def start_game(background_tasks: BackgroundTasks):
    logging.info("Requête pour démarrer une nouvelle partie.")

    with state_lock:
        # 1. Générer le mot de départ
        start_word = random.choice('abcdefghijklmnopqrstuvwxyz')
        logging.debug(f"Lettre de départ générée: '{start_word}'")

        # 2. Choisir le premier joueur (logique similaire à pass_ball)
        all_players = game_state["players"]
        if not all_players:
            logging.warning("Impossible de démarrer, aucun joueur n'est enregistré.")
            raise HTTPException(status_code=400, detail="Aucun joueur trouvé pour démarrer une partie.")

        # Pour le tout premier tour, on peut simplement choisir n'importe qui
        first_player_identifier = random.choice(all_players)
        logging.info(f"Premier joueur choisi: {first_player_identifier}")

        # 3. Préparer le payload de la première balle
        game_state["turn_counts"][first_player_identifier] = 1  # C'est le premier tour

        # On met à jour les comptes de tours pour tout le monde au cas où ils ne seraient pas initialisés
        for p_id in all_players:
            game_state["turn_counts"].setdefault(p_id, 0)

        payload_to_send = BallPayload(
            word=start_word,
            incomingPlayers=game_state["players"],
            incomingTurnCounts=game_state["turn_counts"]
        )
        logging.debug(f"Payload de départ préparé: {payload_to_send}")

        # 4. Envoyer la première balle (logique de routage local/distant)
        if first_player_identifier == game_state["own_identifier"]:
            logging.info("Destination LOCALE détectée pour le premier tour. Appel direct de receive_ball.")
            # Pas besoin de réinitialiser l'état, car il est déjà propre
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


# --- Point d'entrée ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=INTERNAL_PORT)
