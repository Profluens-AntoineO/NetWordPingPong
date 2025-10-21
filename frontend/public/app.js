document.addEventListener('DOMContentLoaded', () => {
    // --- Détermination de l'URL du backend ---
    const backendBaseUrl = `http://${window.location.hostname}:5000`;
    console.log(`[Init] Connexion au backend sur: ${backendBaseUrl}`);

    // --- Références aux éléments du DOM ---
    const statusEl = document.getElementById('status');
    const timerDisplayEl = document.getElementById('timer-display');
    const wordDisplayEl = document.getElementById('word-display');
    const wordInput = document.getElementById('word-input');
    const sendButton = document.getElementById('send-button');
    const restartButton = document.getElementById('restart-button');
    const readyButton = document.getElementById('ready-button'); // Nouveau bouton
    const discoverButton = document.getElementById('discover-button');
    const playerListEl = document.getElementById('player-list');

    // --- État du jeu ---
    let currentWord = null;
    let gameTimer = null;
    let countdownInterval = null;
    let pollingInterval = null;
    let playerListInterval = null;

    // --- Fonctions de jeu ---

    function stopPolling() {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    }

    function startPolling() {
        stopPolling();
        pollingInterval = setInterval(checkForBall, 1000);
    }

    function resetUI() {
        wordDisplayEl.textContent = '';
        wordInput.value = '';
        wordInput.disabled = true;

        sendButton.classList.add('hidden');
        restartButton.classList.add('hidden');
        readyButton.classList.remove('hidden');
        readyButton.disabled = false; // Réactiver le bouton "Prêt"
        discoverButton.classList.remove('hidden');

        statusEl.textContent = "Cliquez sur 'Rechercher' puis sur 'Je suis prêt'.";
        currentWord = null;

        if (gameTimer) clearTimeout(gameTimer);
        if (countdownInterval) clearInterval(countdownInterval);
        timerDisplayEl.textContent = '';

        stopPolling();
    }

    function handleLoss() {
        if (countdownInterval) clearInterval(countdownInterval);
        timerDisplayEl.textContent = 'Temps écoulé !';
        clearTimeout(gameTimer);
        statusEl.textContent = "Trop tard ! Vous avez perdu.";
        wordInput.disabled = true;

        sendButton.classList.add('hidden');
        readyButton.classList.add('hidden');
        discoverButton.classList.add('hidden');
        restartButton.classList.remove('hidden');

        stopPolling();
    }

    function startTurn(word) {
        stopPolling();
        currentWord = word;
        statusEl.textContent = "À vous de jouer !";
        wordDisplayEl.textContent = word;
        wordInput.disabled = false;
        wordInput.focus();

        readyButton.classList.add('hidden');
        restartButton.classList.add('hidden');
        discoverButton.classList.add('hidden');
        sendButton.classList.remove('hidden');
        sendButton.disabled = false;

        let timeLeft = 60;
        timerDisplayEl.textContent = `Temps restant : ${timeLeft}s`;

        if (countdownInterval) clearInterval(countdownInterval);
        countdownInterval = setInterval(() => {
            timeLeft--;
            if (timeLeft > 0) {
                timerDisplayEl.textContent = `Temps restant : ${timeLeft}s`;
            }
        }, 1000);

        if (gameTimer) clearTimeout(gameTimer);
        gameTimer = setTimeout(handleLoss, 60000);
    }

    async function passBall() {
        const newWord = wordInput.value.trim().toLowerCase();
        const expectedPattern = new RegExp(`^${currentWord}[a-z]$`);

        if (!expectedPattern.test(newWord)) {
            statusEl.textContent = "Mot incorrect ! Réessayez.";
            return;
        }

        clearTimeout(gameTimer);
        if (countdownInterval) clearInterval(countdownInterval);
        timerDisplayEl.textContent = '';
        wordInput.disabled = true;
        sendButton.disabled = true;
        statusEl.textContent = "Envoi en cours...";

        try {
            const response = await fetch(`${backendBaseUrl}/api/pass-ball`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ newWord: newWord }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Erreur lors de l\'envoi.');
            }

            resetUI();
            startPolling();
        } catch (error) {
            statusEl.textContent = error.message;
            wordInput.disabled = false;
            sendButton.disabled = false;
        }
    }

    async function checkForBall() {
        try {
            const response = await fetch(`${backendBaseUrl}/api/get-ball`);
            const data = await response.json();
            if (data && data.word && data.word !== currentWord) {
                if (data.word === "game_starting") {
                    statusEl.textContent = "La partie commence !";
                } else {
                    startTurn(data.word);
                }
            }
        } catch (error) {
            // Silence
        }
    }

    async function updatePlayerList() {
        try {
            const response = await fetch(`${backendBaseUrl}/api/players`);
            if (!response.ok) return;

            const data = await response.json();
            playerListEl.innerHTML = '';

            if (data.players && data.players.length > 0) {
                data.players.sort().forEach(playerIdentifier => {
                    const li = document.createElement('li');
                    const isReady = data.ready_players.includes(playerIdentifier);

                    li.textContent = `${playerIdentifier}`;

                    const statusSpan = document.createElement('span');
                    statusSpan.textContent = isReady ? ' (Prêt !)' : ' (En attente)';
                    statusSpan.className = isReady ? 'text-green-400' : 'text-amber-400';
                    li.appendChild(statusSpan);

                    if (playerIdentifier.endsWith(`:${backendPort}`)) {
                        li.classList.add('text-cyan-400', 'font-bold');
                    }

                    playerListEl.appendChild(li);
                });
            } else {
                playerListEl.innerHTML = '<li>Aucun joueur détecté.</li>';
            }
        } catch (error) {
            // Silence
        }
    }

    function startPlayerListPolling() {
        if (playerListInterval) clearInterval(playerListInterval);
        updatePlayerList();
        playerListInterval = setInterval(updatePlayerList, 1000);
    }

    async function discoverAndRegister() {
        statusEl.textContent = "Recherche en cours...";
        discoverButton.disabled = true;
        try {
            await fetch(`${backendBaseUrl}/api/discover`, { method: 'POST' });
            statusEl.textContent = "Recherche lancée !";
        } catch (error) {
            statusEl.textContent = "Impossible de lancer la recherche.";
        } finally {
            setTimeout(() => {
                discoverButton.disabled = false;
                if(statusEl.textContent === "Recherche lancée !") {
                    statusEl.textContent = "Prêt à jouer.";
                }
            }, 2000);
        }
    }

    // --- Initialisation ---
    discoverButton.addEventListener('click', discoverAndRegister);

    readyButton.addEventListener('click', () => {
        statusEl.textContent = "Vous êtes prêt ! En attente des autres joueurs...";
        readyButton.disabled = true;
        discoverButton.disabled = true; // On ne peut plus chercher une fois prêt

        fetch(`${backendBaseUrl}/api/ready`, { method: 'POST' })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => { throw new Error(err.detail); });
                }
                // Le backend gère le démarrage, on se met en attente
                startPolling();
            })
            .catch(error => {
                statusEl.textContent = error.message;
                readyButton.disabled = false; // Réactiver en cas d'erreur
                discoverButton.disabled = false;
            });
    });

    sendButton.addEventListener('click', passBall);
    wordInput.addEventListener('keyup', (event) => {
        if (event.key === 'Enter' && !sendButton.disabled) passBall();
    });
    restartButton.addEventListener('click', () => {
        resetUI();
    });

    // Démarre le processus au chargement de la page
    resetUI();
    startPlayerListPolling();
});