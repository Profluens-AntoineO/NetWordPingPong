import pytest
from httpx import AsyncClient

# On importe l'application et les outils de gestion d'état depuis le fichier principal
from .app import app, game_state, state_lock, reset_local_game_state


@pytest.fixture(autouse=True)
def run_before_and_after_tests():
    """
    Fixture pour garantir que l'état du jeu est propre avant chaque test.
    'autouse=True' signifie qu'elle s'exécute pour chaque test sans avoir à l'appeler.
    """
    reset_local_game_state()
    yield  # C'est ici que le test s'exécute
    reset_local_game_state()


@pytest.mark.asyncio
async def test_get_ball_when_no_game_is_running():
    """Vérifie que l'API renvoie bien `word: null` quand aucune partie n'est en cours."""
    # AsyncClient permet de faire des requêtes HTTP vers une application ASGI comme FastAPI
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/api/get-ball")

    assert response.status_code == 200
    assert response.json() == {"word": None}