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
    const readyButton = document.getElementById('ready-button');
    const discoverButton = document.getElementById('discover-button');
    const playerListEl = document.getElementById('player-list');
    const historyListEl = document.getElementById('history-list');

    // --- État du jeu ---
    let currentWord = null;
    let gameTimer = null;
    let countdownInterval = null;
    let pollingInterval = null; // Pour la balle
    let playerListInterval = null; // Pour la liste des joueurs

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
        readyButton.disabled = false;
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

    function startTurn(turnData) {
        const { word, timeout_ms } = turnData;
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

        let timeLeft = timeout_ms / 1000;
        timerDisplayEl.textContent = `Temps restant : ${timeLeft}s`;

        if (countdownInterval) clearInterval(countdownInterval);
        countdownInterval = setInterval(() => {
            timeLeft--;
            if (timeLeft > 0) {
                timerDisplayEl.textContent = `Temps restant : ${timeLeft}s`;
            }
        }, 1000);

        if (gameTimer) clearTimeout(gameTimer);
        gameTimer = setTimeout(handleLoss, timeout_ms);
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

            // Mise à jour de l'historique
            if (data.history) {
                updateHistoryList(data.history);
            }

            if (data && data.word && data.word !== currentWord) {
                if (data.word === "game_starting") {
                    statusEl.textContent = "La partie commence !";
                } else {
                    // On passe l'objet complet
                    startTurn(data);
                }
            }
        } catch (error) { /* Silence */ }
    }

    // --- NOUVELLE FONCTION: Mise à jour de l'historique ---
    function updateHistoryList(history) {
        historyListEl.innerHTML = '';
        if (history && history.length > 0) {
            history.forEach(entry => {
                const li = document.createElement('li');
                li.innerHTML = `
                <span class="font-mono">${entry.word}</span>
                <span class="text-slate-500"> par </span>
                <span class="font-semibold">${entry.player}</span>
                <span class="text-slate-500"> en </span>
                <span class="text-cyan-400">${entry.response_time_ms} ms</span>
            `;
                historyListEl.appendChild(li);
            });
            // Scroll vers le bas
            historyListEl.scrollTop = historyListEl.scrollHeight;
        } else {
            historyListEl.innerHTML = '<li>En attente du premier coup...</li>';
        }
    }

    async function updatePlayerList() {
        try {
            const response = await fetch(`${backendBaseUrl}/api/players`);
            if (!response.ok) return;

            const data = await response.json();
            playerListEl.innerHTML = '';

            if (data.players && data.players.length > 0) {
                // --- CORRECTION: On récupère notre identité depuis le backend ---
                const selfIdentifier = data.self;

                data.players.sort().forEach(playerIdentifier => {
                    const li = document.createElement('li');
                    const isReady = data.ready_players.includes(playerIdentifier);

                    li.textContent = `${playerIdentifier}`;

                    const statusSpan = document.createElement('span');
                    statusSpan.textContent = isReady ? ' (Prêt !)' : ' (En attente)';
                    statusSpan.className = isReady ? 'text-green-400' : 'text-amber-400';
                    li.appendChild(statusSpan);

                    // --- CORRECTION: La comparaison est maintenant simple et fiable ---
                    if (playerIdentifier === selfIdentifier) {
                        li.classList.add('text-cyan-400', 'font-bold');
                        // On ajoute la mention "(Vous)" au début pour une meilleure visibilité
                        li.textContent = `(Vous) ${li.textContent}`;
                    }

                    playerListEl.appendChild(li);
                });
            } else {
                playerListEl.innerHTML = '<li>Aucun joueur détecté.</li>';
            }
        } catch (error) {
            // Silence pour ne pas spammer la console
        }
    }

    function startPlayerListPolling() {
        if (playerListInterval) clearInterval(playerListInterval);

        const updateAllStatus = () => {
            updatePlayerList();
            // On ajoute la mise à jour de l'archive ici
            fetch(`${backendBaseUrl}/api/archive`)
                .then(res => res.json())
                .then(data => {
                    if (data.archive) {
                        updateArchiveList(data.archive);
                    }
                })
                .catch(() => {}); // Silence pour les erreurs de polling
        };

        updateAllStatus();
        playerListInterval = setInterval(updateAllStatus, 2000); // On peut ralentir ce polling
    }
    function updateArchiveList(archive) {
        archiveListEl.innerHTML = '';
        if (archive && archive.length > 0) {
            archive.forEach((gameHistory, index) => {
                const gameContainer = document.createElement('div');
                const gameTitle = document.createElement('h3');
                gameTitle.textContent = `Partie ${index + 1}`;
                gameTitle.className = 'font-bold text-slate-200';
                gameContainer.appendChild(gameTitle);

                const gameUl = document.createElement('ul');
                gameUl.className = 'pl-4 text-sm';

                gameHistory.forEach(entry => {
                    const li = document.createElement('li');
                    li.innerHTML = `
                        <span class="font-mono">${entry.word}</span>
                        <span class="text-slate-500"> par </span>
                        <span class="font-semibold">${entry.player}</span>
                        <span class="text-slate-500"> en </span>
                        <span class="text-cyan-400">${entry.response_time_ms} ms</span>
                    `;
                    gameUl.appendChild(li);
                });

                gameContainer.appendChild(gameUl);
                archiveListEl.appendChild(gameContainer);
            });
        } else {
            archiveListEl.innerHTML = '<span>Aucune partie archivée.</span>';
        }
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
        discoverButton.disabled = true;

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
                readyButton.disabled = false;
                discoverButton.disabled = false;
            });
    });
    
    sendButton.addEventListener('click', passBall);
    wordInput.addEventListener('keyup', (event) => {
        if (event.key === 'Enter' && !sendButton.disabled) passBall();
    });
    restartButton.addEventListener('click', () => {
        console.log('[restartButton] Clic sur "Recommencer". Le joueur est à nouveau prêt.');
        // On appelle directement la logique du bouton "Prêt"
        readyButton.click();
    });

    // --- DÉMARRAGE DU PROCESSUS ---
    resetUI();
    // On lance le polling de la liste des joueurs dès le début.
    startPlayerListPolling();
});
