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
BASE_TIMEOUT_MS = 60000
MIN_TIMEOUT_MS = 2000
RESPONSE_REFERENCE_MS = 10000
FAST_RESPONSE_THRESHOLD_MS = 3000

FAST_RESPONSE_MULTIPLIER = 1.5
NOVELTY_MULTIPLIER = 1.2
PROXIMITY_MULTIPLIER = 1.2


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

