document.addEventListener('DOMContentLoaded', () => {
    // --- Détermination de l'URL du backend ---
    const backendBaseUrl = `http://${window.location.hostname}:5000`;
    console.log(`[Init] Connexion au backend sur: ${backendBaseUrl}`);

    // --- Références aux éléments du DOM ---
    const statusEl = document.getElementById('status');
    const timerDisplayEl = document.getElementById('timer-display');
    const wordPrefixDisplayEl = document.getElementById('word-prefix-display'); // <-- Nouvel élément
    const wordDisplayEl = document.getElementById('word-display');
    const wordInput = document.getElementById('word-input');
    const sendButton = document.getElementById('send-button');
    const restartButton = document.getElementById('restart-button');
    const readyButton = document.getElementById('ready-button');
    const discoverButton = document.getElementById('discover-button');
    const playerListEl = document.getElementById('player-list');
    const historyListEl = document.getElementById('history-list');
    const archiveListEl = document.getElementById('archive-list');

    // --- État du jeu ---
    let currentWord = null;
    let gameTimer = null;
    let countdownInterval = null;
    let pollingInterval = null;
    let playerListInterval = null;

    // --- Fonctions de gestion des états de l'UI ---

    function setLobbyState() {
        statusEl.textContent = "Cliquez sur 'Rechercher' puis sur 'Je suis prêt'.";
        wordDisplayEl.textContent = '';
        wordPrefixDisplayEl.textContent = ''; // <-- Vider le préfixe
        timerDisplayEl.textContent = '';
        wordInput.value = '';
        wordInput.disabled = true;

        sendButton.classList.add('hidden');
        restartButton.classList.add('hidden');

        readyButton.classList.remove('hidden');
        readyButton.disabled = false;
        discoverButton.classList.remove('hidden');
        discoverButton.disabled = false;

        currentWord = null;
        if (gameTimer) clearTimeout(gameTimer);
        if (countdownInterval) clearInterval(countdownInterval);

        stopPolling();
    }

    function setWaitingState() {
        statusEl.textContent = "Balle envoyée ! En attente du prochain tour...";
        wordDisplayEl.textContent = '';
        wordPrefixDisplayEl.textContent = ''; // <-- Vider le préfixe
        timerDisplayEl.textContent = '';
        wordInput.value = '';
        wordInput.disabled = true;

        sendButton.classList.add('hidden');
        restartButton.classList.add('hidden');
        readyButton.classList.add('hidden');
        discoverButton.classList.add('hidden');
    }

    function setInTurnState(turnData) {
        const { word, timeout_ms } = turnData;

        stopPolling();
        currentWord = word;
        statusEl.textContent = "À vous de jouer !";

        // --- MODIFICATION: Logique d'affichage du mot ---
        const displayThreshold = 10;
        if (word.length > displayThreshold) {
            const prefix = word.substring(0, word.length - displayThreshold);
            const suffix = word.substring(word.length - displayThreshold);
            wordPrefixDisplayEl.textContent = prefix;
            wordDisplayEl.textContent = suffix;
        } else {
            wordPrefixDisplayEl.textContent = '';
            wordDisplayEl.textContent = word;
        }
        // --- FIN DE LA MODIFICATION ---

        wordInput.disabled = false;
        wordInput.focus();

        readyButton.classList.add('hidden');
        restartButton.classList.add('hidden');
        discoverButton.classList.add('hidden');
        sendButton.classList.remove('hidden');
        sendButton.disabled = false;

        let timeLeft = Math.round(timeout_ms / 1000);
        timerDisplayEl.textContent = `Temps restant : ${timeLeft}s`;

        if (countdownInterval) clearInterval(countdownInterval);
        countdownInterval = setInterval(() => {
            timeLeft--;
            if (timeLeft >= 0) {
                timerDisplayEl.textContent = `Temps restant : ${timeLeft}s`;
            } else {
                clearInterval(countdownInterval);
            }
        }, 1000);

        if (gameTimer) clearTimeout(gameTimer);
        gameTimer = setTimeout(handleLoss, timeout_ms);
    }

    function setGameOverState() {
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

    // --- Fonctions de logique de jeu ---

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

    function handleLoss() {
        setGameOverState();
    }

    function startTurn(turnData) {
        if (typeof turnData.timeout_ms !== 'number' || turnData.timeout_ms <= 0) {
            return;
        }
        setInTurnState(turnData);
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

        setWaitingState();

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

            startPolling();
        } catch (error) {
            statusEl.textContent = error.message;
            setInTurnState({ word: currentWord, timeout_ms: 10000 });
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
                    startTurn(data);
                }
            }
        } catch (error) { /* Silence */ }
    }

    function updateHistoryList(history) {
        historyListEl.innerHTML = '';
        if (history && history.length > 0) {
            history.forEach(entry => {
                const li = document.createElement('li');
                li.className = 'flex items-center gap-2 flex-wrap';

                const textContainer = document.createElement('div');
                textContainer.innerHTML = `
                    <span class="font-mono">${entry.word}</span>
                    <span class="text-slate-500"> par </span>
                    <span class="font-semibold">${entry.player}</span>
                    <span class="text-slate-500"> en </span>
                    <span class="text-cyan-400">${entry.response_time_ms} ms</span>
                `;
                li.appendChild(textContainer);

                if (entry.applied_multipliers && entry.applied_multipliers.length > 0) {
                    const tagsContainer = document.createElement('div');
                    tagsContainer.className = 'flex gap-1';

                    entry.applied_multipliers.forEach(modifier => {
                        const tag = document.createElement('span');
                        tag.textContent = modifier;

                        if (modifier.startsWith('combo')) {
                            tag.className = 'bg-purple-600 text-white text-xs font-semibold px-2 py-0.5 rounded-full';
                        } else if (modifier === 'maudite') {
                            tag.className = 'bg-emerald-600 text-white text-xs font-semibold px-2 py-0.5 rounded-full';
                        } else {
                            tag.className = 'bg-red-600 text-white text-xs font-semibold px-2 py-0.5 rounded-full';
                        }
                        tagsContainer.appendChild(tag);
                    });
                    li.appendChild(tagsContainer);
                }

                historyListEl.appendChild(li);
            });
            historyListEl.scrollTop = historyListEl.scrollHeight;
        } else {
            historyListEl.innerHTML = '<li>En attente du premier coup...</li>';
        }
    }

    function updateArchiveList(archive) {
        if (!archiveListEl) return;
        archiveListEl.innerHTML = '';
        if (archive && archive.length > 0) {
            archive.forEach((gameHistory, index) => {
                const gameContainer = document.createElement('div');
                const gameTitle = document.createElement('h3');
                gameTitle.textContent = `Partie ${index + 1}`;
                gameTitle.className = 'font-bold text-slate-200 mt-2';
                gameContainer.appendChild(gameTitle);

                const gameUl = document.createElement('ul');
                gameUl.className = 'pl-4 text-sm border-l border-slate-700 ml-2';

                gameHistory.forEach(entry => {
                    const li = document.createElement('li');
                    li.innerHTML = `
                        <span class="font-mono">${entry.word}</span>
                        <span class="text-slate-500"> par </span>
                        <span class="font-semibold">${entry.player}</span>
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

    function updatePlayerList(data) {
        playerListEl.innerHTML = '';
        if (data.players && data.players.length > 0) {
            const selfIdentifier = data.self;
            data.players.sort().forEach(playerIdentifier => {
                const li = document.createElement('li');
                const isReady = data.ready_players.includes(playerIdentifier);

                let playerText = `${playerIdentifier}`;
                if (playerIdentifier === selfIdentifier) {
                    playerText = `(Vous) ${playerText}`;
                    li.classList.add('text-cyan-400', 'font-bold');
                }

                li.textContent = playerText;

                const statusSpan = document.createElement('span');
                statusSpan.textContent = isReady ? ' (Prêt !)' : ' (En attente)';
                statusSpan.className = isReady ? 'text-green-400' : 'text-amber-400';
                li.appendChild(statusSpan);

                playerListEl.appendChild(li);
            });
        } else {
            playerListEl.innerHTML = '<li>Aucun joueur détecté.</li>';
        }
    }

    function startPlayerListPolling() {
        if (playerListInterval) clearInterval(playerListInterval);

        const updateAllStatus = () => {
            fetch(`${backendBaseUrl}/api/players`)
                .then(res => res.json())
                .then(data => {
                    if (data) {
                        updatePlayerList(data);
                        updateHistoryList(data.history);
                        if (archiveListEl) {
                            updateArchiveList(data.archive);
                        }
                    }
                })
                .catch(() => {});
        };

        updateAllStatus();
        playerListInterval = setInterval(updateAllStatus, 2000);
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
        setLobbyState();
    });

    // --- DÉMARRAGE DU PROCESSUS ---
    setLobbyState();
    startPlayerListPolling();
});