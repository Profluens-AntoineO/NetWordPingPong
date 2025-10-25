
document.addEventListener('DOMContentLoaded', () => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.hostname}:5000/ws`;
    const backendBaseUrl = `http://${window.location.hostname}:5000`;

    const statusEl = document.getElementById('status');
    const timerDisplayEl = document.getElementById('timer-display');
    const wordPrefixDisplayEl = document.getElementById('word-prefix-display');
    const wordDisplayEl = document.getElementById('word-display');
    const wordInput = document.getElementById('word-input');
    const sendButton = document.getElementById('send-button');
    const restartButton = document.getElementById('restart-button');
    const readyButton = document.getElementById('ready-button');
    const discoverButton = document.getElementById('discover-button');
    const playerListEl = document.getElementById('player-list');
    const historyListEl = document.getElementById('history-list');
    const archiveListEl = document.getElementById('archive-list');
    const vowelPowerDisplayEl = document.getElementById('vowel-power-display');
    const cursedLettersDisplayEl = document.getElementById('cursed-letters-display');
    const phonePadDisplayEl = document.getElementById('phone-pad-display');

    let localCurrentWord = null;
    let gameTimer = null;
    let countdownInterval = null;
    let lastKeyPressTime = 0;
    let myIdentifier = null;
    let isMyTurn = false;
    let gameState = {}; // To store the latest state from the server

    // Global PAD_COLUMNS and isColumnCharged for consistent use
    const PAD_COLUMNS = {
        '*': ['7', '4'],
        '0': ['2', '5', '8'],
        '#': ['3', '6', '9'],
    };

    const isColumnCharged = (colKey, myPad) => {
        if (!PAD_COLUMNS[colKey] || !myPad) return false;
        const columnNums = PAD_COLUMNS[colKey];
        return columnNums.every(num => (myPad[num] || 0) >= 1);
    };

    const isPowerUpReady = (myPad) => {
        if (!myPad) return false;
        for (let i = 2; i <= 9; i++) {
            if ((myPad[String(i)] || 0) < 1) {
                return false;
            }
        }
        return true;
    };

    function setLobbyState() {
        isMyTurn = false;
        statusEl.textContent = "Cliquez sur 'Rechercher' puis sur 'Je suis prêt'.";
        wordDisplayEl.textContent = '';
        wordPrefixDisplayEl.textContent = '';
        timerDisplayEl.textContent = '';
        wordInput.value = '';
        wordInput.disabled = true;
        sendButton.classList.add('hidden');
        restartButton.classList.add('hidden');
        readyButton.classList.remove('hidden');
        readyButton.disabled = false;
        discoverButton.classList.remove('hidden');
        discoverButton.disabled = false;
        localCurrentWord = null;
        if (gameTimer) clearTimeout(gameTimer);
        if (countdownInterval) clearInterval(countdownInterval);
    }

    function setWaitingState() {
        isMyTurn = false;
        statusEl.textContent = "Balle envoyée ! En attente du prochain tour...";
        wordDisplayEl.textContent = '';
        wordPrefixDisplayEl.textContent = '';
        timerDisplayEl.textContent = '';
        wordInput.value = '';
        wordInput.disabled = true;
        sendButton.classList.add('hidden');
        restartButton.classList.add('hidden');
        readyButton.classList.add('hidden');
        discoverButton.classList.add('hidden');
    }

    function setInTurnState(turnData) {
        isMyTurn = true;
        const { word, timeout_ms } = turnData;
        localCurrentWord = word;
        statusEl.textContent = "À vous de jouer !";
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
        wordInput.disabled = false;
        wordInput.value = localCurrentWord;
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
        gameTimer = setTimeout(() => handleLoss(word), timeout_ms);
    }

    function setGameOverState() {
        isMyTurn = false;
        if (countdownInterval) clearInterval(countdownInterval);
        timerDisplayEl.textContent = '';
        statusEl.textContent = "Partie terminée !";
        wordInput.disabled = true;
        sendButton.classList.add('hidden');
        readyButton.classList.add('hidden');
        discoverButton.classList.add('hidden');
        restartButton.classList.remove('hidden');
        restartButton.disabled = false;
    }

    function handleLoss(wordAtTimeout) {
        if (localCurrentWord === wordAtTimeout) {
            statusEl.textContent = "Trop tard ! Vous avez perdu.";
        }
    }

    function updateHistoryList(history) {
        historyListEl.innerHTML = '';
        if (history && history.length > 0) {
            history.forEach(entry => {
                const li = document.createElement('li');
                li.className = 'flex items-center gap-2 flex-wrap';
                const textContainer = document.createElement('div');
                textContainer.innerHTML = `<span class="font-mono">${entry.word}</span> <span class="text-slate-500">par</span> <span class="font-semibold">${entry.player}</span> <span class="text-slate-500">en</span> <span class="text-cyan-400">${entry.response_time_ms} ms</span>`;
                li.appendChild(textContainer);
                if (entry.applied_multipliers && entry.applied_multipliers.length > 0) {
                    const tagsContainer = document.createElement('div');
                    tagsContainer.className = 'flex gap-1';
                    entry.applied_multipliers.forEach(modifier => {
                        const tag = document.createElement('span');
                        tag.textContent = modifier;
                        tag.className = 'bg-purple-600 text-white text-xs font-semibold px-2 py-0.5 rounded-full';
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
            archive.slice().reverse().forEach((gameHistory, index) => {
                const gameContainer = document.createElement('div');
                const gameTitle = document.createElement('h3');
                gameTitle.textContent = `Partie Précédente #${archive.length - index}`;
                gameTitle.className = 'font-bold text-slate-200 mt-2';
                gameContainer.appendChild(gameTitle);
                const gameUl = document.createElement('ul');
                gameUl.className = 'pl-4 text-sm border-l border-slate-700 ml-2';
                gameHistory.forEach(entry => {
                    const li = document.createElement('li');
                    li.innerHTML = `<span class="font-mono">${entry.word}</span> par <span class="font-semibold">${entry.player}</span>`;
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
            myIdentifier = data.self;
            data.players.sort().forEach(playerIdentifier => {
                const li = document.createElement('li');
                const isReady = data.ready_players.includes(playerIdentifier);
                let playerText = `${playerIdentifier}`;
                if (playerIdentifier === myIdentifier) {
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

    function updateVowelPowerDisplay(playerVowelPowers) {
        if (!vowelPowerDisplayEl || !myIdentifier || !playerVowelPowers[myIdentifier]) return;
        const myVowelPower = playerVowelPowers[myIdentifier];
        vowelPowerDisplayEl.innerHTML = '';
        const vowels = ['a', 'e', 'i', 'o', 'u', 'y'];
        vowels.forEach(vowel => {
            const power = myVowelPower[vowel] || 0;
            const div = document.createElement('div');
            div.className = 'p-2 rounded-md bg-slate-700';
            div.innerHTML = `<div class="text-2xl font-bold text-cyan-400">${vowel.toUpperCase()}</div><div class="text-sm text-slate-400">${(power * 100).toFixed(0)}%</div>`;
            vowelPowerDisplayEl.appendChild(div);
        });
    }

    function updateCursedLettersDisplay(cursedLetters) {
        if (!cursedLettersDisplayEl) return;
        cursedLettersDisplayEl.innerHTML = '';
        if (cursedLetters.length === 0) {
            cursedLettersDisplayEl.innerHTML = '<span>Aucune lettre maudite.</span>';
            return;
        }
        cursedLetters.forEach(letter => {
            const div = document.createElement('div');
            div.className = `p-2 rounded-md flex items-center gap-2 bg-red-900`;
            div.innerHTML = `<span class="text-2xl font-bold">${letter.toUpperCase()}</span>`;
            cursedLettersDisplayEl.appendChild(div);
        });
    }

    function updatePhonePadDisplay(playerPhonePads) {
        if (!phonePadDisplayEl || !myIdentifier || !playerPhonePads[myIdentifier]) return;
        const myPad = playerPhonePads[myIdentifier];
        phonePadDisplayEl.innerHTML = '';
        
        const padGrid = [
            ['1', '2', '3'],
            ['4', '5', '6'],
            ['7', '8', '9'],
            ['*', '0', '#']
        ];

        const keyToLetters = {
            '2': "ABC", '3': "DEF", '4': "GHI", '5': "JKL", 
            '6': "MNO", '7': "PQRS", '8': "TUV", '9': "WXYZ"
        };

        padGrid.flat().forEach(key => {
            const div = document.createElement('div');
            const isSpecial = ['*', '0', '#'].includes(key);
            const isNumeric = !isNaN(parseInt(key)) && !isSpecial;

            let bgColor = 'bg-slate-700';
            let content = '';

            if (key === '1') {
                const isReady = isPowerUpReady(myPad);
                bgColor = isReady ? 'bg-red-500' : 'bg-slate-900';
                content = `<div class="text-3xl font-bold text-slate-900">1</div>`;
                div.addEventListener('click', () => {
                    if (isReady) {
                        fetch(`${backendBaseUrl}/api/power-up`, { method: 'POST' });
                    }
                });

            } else if (isSpecial) {
                const isColCharged = isColumnCharged(key, myPad);
                if (isColCharged) bgColor = 'bg-purple-600';
                let comboName = '';
                if (key === '*') comboName = 'Purge';
                if (key === '0') comboName = 'Recharge';
                if (key === '#') comboName = 'Attaque';
                content = `<div class="text-3xl font-bold">${key}</div><div class="text-xs">${comboName}</div>`;
                 div.addEventListener('click', () => {
                    if (isColumnCharged(key, myPad)) {
                        fetch(`${backendBaseUrl}/api/combo`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ combo_key: key }),
                        });
                    }
                });
            } else if (isNumeric) {
                const charge = myPad[key] || 0;
                const isCharged = charge >= 1;
                if (isCharged) bgColor = 'bg-green-600';
                content = `<div class="text-3xl font-bold">${key}</div><div class="text-xs">${keyToLetters[key]}</div><div class="text-xs">${charge}/3</div>`;
            }
            
            div.className = `p-3 rounded-md ${bgColor}`;
            div.innerHTML = content;
            phonePadDisplayEl.appendChild(div);
        });
    }

    let socket;
    function connect() {
        socket = new WebSocket(wsUrl);
        socket.onopen = () => {
            console.log("[WebSocket] Connexion établie.");
            statusEl.textContent = "Connecté ! Prêt à jouer.";
            setLobbyState();
        };
        socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            gameState = data; // Store the latest game state
            console.log("[WebSocket] Message d'état reçu:", data);
            updatePlayerList(data);
            updateHistoryList(data.history);
            updateArchiveList(data.archive);
            updateVowelPowerDisplay(data.player_vowel_powers);
            updateCursedLettersDisplay(data.cursed_letters);
            updatePhonePadDisplay(data.player_phone_pads);
            if (data.word && data.word !== localCurrentWord) {
                if (data.word === "game_starting") {
                    statusEl.textContent = "La partie commence !";
                } else {
                    setInTurnState(data);
                }
            } else if (!data.word && localCurrentWord) {
                setGameOverState();
            }
        };
        socket.onclose = () => {
            console.warn("[WebSocket] Connexion perdue. Tentative de reconnexion dans 3s...");
            statusEl.textContent = "Déconnecté. Tentative de reconnexion...";
            setTimeout(connect, 3000);
        };
        socket.onerror = (error) => {
            console.error("[WebSocket] Erreur:", error);
            socket.close();
        };
    }

    async function passBall(newLetter) {
        if (!isMyTurn || !newLetter) return;
        const newWord = localCurrentWord + newLetter.toLowerCase();
        lastKeyPressTime = new Date().getTime();
        
        isMyTurn = false;
        clearTimeout(gameTimer);
        if (countdownInterval) clearInterval(countdownInterval);
        setWaitingState();
        try {
            const response = await fetch(`${backendBaseUrl}/api/pass-ball`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    newWord: newWord,
                    client_timestamp_ms: lastKeyPressTime
                }),
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Erreur lors de l\'envoi.');
            }
        } catch (error) {
            statusEl.textContent = error.message;
            setInTurnState({ word: localCurrentWord, timeout_ms: 10000 });
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
            }, 1500);
        }
    }

    discoverButton.addEventListener('click', discoverAndRegister);
    readyButton.addEventListener('click', () => {
        statusEl.textContent = "Vous êtes prêt ! En attente des autres joueurs...";
        readyButton.disabled = true;
        discoverButton.disabled = true;
        fetch(`${backendBaseUrl}/api/ready`, { method: 'POST' })
            .catch(error => {
                statusEl.textContent = error.message;
                readyButton.disabled = false;
                discoverButton.disabled = false;
            });
    });
    sendButton.addEventListener('click', () => passBall(wordInput.value.slice(-1)));
    document.addEventListener('keydown', (event) => {
        const key = event.key.toLowerCase();
        const myPad = gameState.player_phone_pads ? gameState.player_phone_pads[myIdentifier] : {};

        // Handle alphanumeric keys for word input (only if it's my turn)
        if (key.length === 1 && key.match(/[a-z]/i)) {
            if (isMyTurn) { // Only allow letter input on my turn
                passBall(key);
            }
        // Handle special pad keys for combos (*, 0, #) - can be pressed anytime if combo is charged
        } else if (['*', '0', '#'].includes(key)) {
            if (isColumnCharged(key, myPad)) {
                fetch(`${backendBaseUrl}/api/combo`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ combo_key: key }),
                });
            }
        // Handle number keys (2-9) for combos
        } else if (key.match(/[2-9]/)) {
            // Do nothing - pad charges are handled by letter input
        // Handle power-up key (1) - can be pressed anytime
        } else if (key === '1') {
            if (isPowerUpReady(myPad)) {
                fetch(`${backendBaseUrl}/api/power-up`, { method: 'POST' });
            }
        }
    });
    restartButton.addEventListener('click', () => {
        restartButton.disabled = true;
        statusEl.textContent = "Proposition de revanche envoyée...";
        fetch(`${backendBaseUrl}/api/rematch`, { method: 'POST' })
            .catch(error => {
                console.error('Erreur lors de la proposition de revanche:', error)
                restartButton.disabled = false;
                statusEl.textContent = "Erreur lors de la proposition.";
            });
    });

    connect();
});
