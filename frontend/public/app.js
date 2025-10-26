
document.addEventListener('DOMContentLoaded', () => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.hostname}:5000/ws`;
    const backendBaseUrl = `http://${window.location.hostname}:5000`;

    const statusEl = document.getElementById('status');
    const timerDisplayEl = document.getElementById('timer-display');
    const wordPrefixDisplayEl = document.getElementById('word-prefix-display');
    const wordDisplayEl = document.getElementById('word-display');
    const restartButton = document.getElementById('restart-button');
    const readyButton = document.getElementById('ready-button');
    const discoverButton = document.getElementById('discover-button');
    const playerListEl = document.getElementById('player-list');
    const historyListEl = document.getElementById('history-list');
    const archiveListEl = document.getElementById('archive-list');
    const vowelPowerDisplayEl = document.getElementById('vowel-power-display');
    const cursedLettersDisplayEl = document.getElementById('cursed-letters-display');
    const deadLettersDisplayEl = document.getElementById('dead-letters-display');
    const phonePadDisplayEl = document.getElementById('phone-pad-display');
    const activePlayerDisplayEl = document.getElementById('active-player-display');
    const inabilityDisplayEl = document.getElementById('inability-display');
    const missionsDisplayEl = document.getElementById('missions-display');

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
        activePlayerDisplayEl.innerHTML = '';
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
        readyButton.classList.add('hidden');
        restartButton.classList.add('hidden');
        discoverButton.classList.add('hidden');
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
        activePlayerDisplayEl.innerHTML = '';
        statusEl.textContent = "Partie terminée !";
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
        const historyList = document.getElementById('panel-history').querySelector('ul');
        historyList.innerHTML = '';
        if (history && history.length > 0) {
            history.forEach(entry => {
                const li = document.createElement('li');
                li.className = 'flex items-center gap-2 flex-wrap';
                const textContainer = document.createElement('div');
                textContainer.innerHTML = `<span class="font-mono">${entry.word}</span> <span class="text-slate-500">par</span> <span class="font-semibold">${entry.player}</span> <span class="text-slate-500">en</span> <span class="text-cyan-400">${entry.response_time_ms} ms</span>`;
                li.appendChild(textContainer);

                if (entry.timeout_log) {
                    const log = entry.timeout_log;
                    const logDetails = `(Base: ${log.base_timeout}, Speed: ${log.speed_bonus.toFixed(0)}, Vowel: ${log.vowel_bonus.toFixed(0)}, Cursed: ${log.cursed_malus}, Combo: ${log.pad_combo_malus}) -> Final: ${log.final_timeout}`;
                    const logEl = document.createElement('span');
                    logEl.className = 'text-xs text-slate-500';
                    logEl.textContent = logDetails;
                    li.appendChild(logEl);
                }

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
                historyList.appendChild(li);
            });
            historyList.scrollTop = historyList.scrollHeight;
        } else {
            historyList.innerHTML = '<li>En attente du premier coup...</li>';
        }
    }

    function updateArchiveList(archive) {
        const archiveList = document.getElementById('panel-archives').querySelector('div');
        if (!archiveList) return;
        archiveList.innerHTML = '';
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
                archiveList.appendChild(gameContainer);
            });
        } else {
            archiveList.innerHTML = '<span>Aucune partie archivée.</span>';
        }
    }

    function updatePlayerList(data) {
        playerListEl.innerHTML = '';
        playerListEl.className = 'flex flex-wrap gap-4 justify-center'; // Use flex-wrap for card layout

        if (data.players && data.players.length > 0) {
            myIdentifier = data.self;
            let sortedPlayers = [...data.players].sort();
            if (data.active_player) {
                sortedPlayers = sortedPlayers.filter(p => p !== data.active_player);
                sortedPlayers.unshift(data.active_player);
            }

            sortedPlayers.forEach(playerIdentifier => {
                const isReady = data.ready_players.includes(playerIdentifier);
                const isActive = playerIdentifier === data.active_player;
                const isSelf = playerIdentifier === myIdentifier;

                let cardClasses = 'p-3 rounded-lg flex flex-col justify-between items-center transition-all duration-300 w-36 h-24 border-2 ';
                if (isActive) {
                    cardClasses += 'bg-amber-500/20 border-amber-400';
                } else if (isReady) {
                    cardClasses += 'bg-green-500/10 border-green-500';
                } else {
                    cardClasses += 'bg-slate-700/50 border-slate-600';
                }

                const playerCard = document.createElement('div');
                playerCard.className = cardClasses;

                let playerText = playerIdentifier;
                if (isSelf) {
                    playerText = `(Vous) ${playerText.split(':')[0]}`;
                }

                const maxTimeout = data.player_max_timeouts ? data.player_max_timeouts[playerIdentifier] / 1000 : 'N/A';
                
                const nameSpan = document.createElement('span');
                nameSpan.className = `font-semibold text-sm truncate ${isSelf ? 'text-cyan-400' : ''}`;
                nameSpan.textContent = playerText;

                const timeoutSpan = document.createElement('span');
                timeoutSpan.className = 'text-xs text-slate-400';
                timeoutSpan.textContent = `Max: ${maxTimeout}s`;

                const statusSpan = document.createElement('span');
                statusSpan.className = `text-xs font-bold px-2 py-0.5 rounded-full ${isReady ? 'bg-green-500/50 text-green-300' : 'bg-slate-600 text-slate-300'}`;
                statusSpan.textContent = isReady ? 'Prêt' : 'Attente';

                playerCard.appendChild(nameSpan);
                playerCard.appendChild(timeoutSpan);
                playerCard.appendChild(statusSpan);
                playerListEl.appendChild(playerCard);
            });
        } else {
            playerListEl.innerHTML = '<li>Aucun joueur détecté.</li>';
        }
    }

    function getVowelPowerColor(power) {
        const percentage = power * 100;
        if (percentage >= 150) return 'text-green-400';
        if (percentage >= 100) return 'text-cyan-400';
        if (percentage >= 50) return 'text-blue-400';
        if (percentage > 0) return 'text-slate-400';
        return 'text-red-600';
    }

    function updateVowelPowerDisplay(playerVowelPowers) {
        if (!vowelPowerDisplayEl || !myIdentifier || !playerVowelPowers[myIdentifier]) return;
        const myVowelPower = playerVowelPowers[myIdentifier];
        vowelPowerDisplayEl.innerHTML = '';
        const vowels = ['a', 'e', 'i', 'o', 'u', 'y'];
        vowels.forEach(vowel => {
            const power = myVowelPower[vowel] || 0;
            const colorClass = getVowelPowerColor(power);
            const div = document.createElement('div');
            div.className = 'p-2 rounded-md bg-slate-800/50';
            div.innerHTML = `<div class="text-2xl font-bold ${colorClass}">${vowel.toUpperCase()}</div><div class="text-sm ${colorClass}">${(power * 100).toFixed(0)}%</div>`;
            vowelPowerDisplayEl.appendChild(div);
        });
    }

    function updateCursedLettersDisplay(cursedLetters) {
        const section = cursedLettersDisplayEl.parentElement;
        if (!cursedLettersDisplayEl || !section) return;
        if (!cursedLetters || cursedLetters.length === 0) {
            section.classList.add('hidden');
            return;
        }
        section.classList.remove('hidden');
        cursedLettersDisplayEl.innerHTML = '';
        cursedLetters.forEach(letter => {
            const div = document.createElement('div');
            div.className = `p-2 rounded-md flex items-center gap-2 bg-red-900`;
            div.innerHTML = `<span class="text-2xl font-bold">${letter.toUpperCase()}</span>`;
            cursedLettersDisplayEl.appendChild(div);
        });
    }

    function updateDeadLettersDisplay(deadLetters) {
        const section = deadLettersDisplayEl.parentElement;
        if (!deadLettersDisplayEl || !section) return;
        if (!deadLetters || deadLetters.length === 0) {
            section.classList.add('hidden');
            return;
        }
        section.classList.remove('hidden');
        deadLettersDisplayEl.innerHTML = '';
        deadLetters.forEach(letter => {
            const div = document.createElement('div');
            div.className = `p-2 rounded-md flex items-center gap-2 bg-black`;
            div.innerHTML = `<span class="text-2xl font-bold text-red-600">${letter.toUpperCase()}</span>`;
            deadLettersDisplayEl.appendChild(div);
        });
    }

    function updateInabilityDisplay(inabilities) {
        const section = inabilityDisplayEl.parentElement;
        if (!inabilityDisplayEl || !section) return;
        if (!inabilities || inabilities.length === 0) {
            section.classList.add('hidden');
            return;
        }
        section.classList.remove('hidden');
        inabilityDisplayEl.innerHTML = '';
        inabilities.forEach(letter => {
            const div = document.createElement('div');
            div.className = `p-2 rounded-md flex items-center gap-2 bg-yellow-900`;
            div.innerHTML = `<span class="text-2xl font-bold">${letter.toUpperCase()}</span>`;
            inabilityDisplayEl.appendChild(div);
        });
    }

    function updateMissionsDisplay(missions) {
        const section = missionsDisplayEl.parentElement;
        if (!missionsDisplayEl || !section) return;
        if (!missions || missions.length === 0) {
            section.classList.add('hidden');
            return;
        }
        section.classList.remove('hidden');
        missionsDisplayEl.innerHTML = '';
        missions.forEach(mission => {
            const div = document.createElement('div');
            const progressValue = mission.current_step || 0;
            const goal = mission.goal;
            const isCompleted = progressValue >= goal;
            const progressPercentage = goal > 0 ? Math.min(100, (progressValue / goal) * 100) : (isCompleted ? 100 : 0);
            div.className = `p-2 rounded-md ${isCompleted ? 'bg-green-800' : 'bg-slate-700'}`;
            div.innerHTML = `
                <h3 class="font-bold text-cyan-400">${mission.name} ${isCompleted ? '(Terminée !)' : ''}</h3>
                <p class="text-xs text-slate-400">${mission.description}</p>
                <div class="w-full bg-slate-600 rounded-full h-2.5 mt-2">
                    <div class="bg-cyan-400 h-2.5 rounded-full" style="width: ${progressPercentage}%"></div>
                </div>
            `;
            missionsDisplayEl.appendChild(div);
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

        const chargeColors = [
            'bg-slate-700/50', 
            'bg-teal-800', 
            'bg-teal-700', 
            'bg-green-600'
        ];

        padGrid.flat().forEach(key => {
            const div = document.createElement('div');
            const isSpecial = ['*', '0', '#'].includes(key);
            const isNumeric = !isNaN(parseInt(key)) && !isSpecial;

            let bgColor = 'bg-slate-700/50';
            let content = '';

            if (key === '1') {
                const isReady = isPowerUpReady(myPad);
                bgColor = isReady ? 'bg-red-500' : 'bg-slate-900/50';
                content = `<div class="text-2xl font-bold text-slate-900">1</div>`;
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
                content = `<div class="text-2xl font-bold">${key}</div><div class="text-xs">${comboName}</div>`;
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
                bgColor = chargeColors[charge] || 'bg-slate-700/50';
                content = `<div class="text-2xl font-bold">${key}</div><div class="text-xs">${keyToLetters[key]}</div>`;
            }
            
            div.className = `p-2 rounded-md ${bgColor}`;
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
            updateDeadLettersDisplay(data.dead_letters);
            updatePhonePadDisplay(data.player_phone_pads);
            updateInabilityDisplay(data.player_inabilities ? data.player_inabilities[myIdentifier] : []);
            updateMissionsDisplay(data.active_missions);

            if (data.active_player && data.active_player === myIdentifier) {
                setInTurnState(data);
            } else if (data.active_player) {
                setWaitingState();
                statusEl.textContent = `Au tour de ${data.active_player}...`;
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
        // setWaitingState(); // Removed to prevent UI flashing
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

    // Tab switching logic
    const tabs = ['game', 'history', 'archives'];
    tabs.forEach(tabId => {
        const tabButton = document.getElementById(`tab-${tabId}`);
        if (tabButton) {
            tabButton.addEventListener('click', () => {
                // Hide all panels
                tabs.forEach(id => {
                    const panel = document.getElementById(`panel-${id}`);
                    const tab = document.getElementById(`tab-${id}`);
                    if (panel) panel.classList.add('hidden');
                    if (tab) tab.classList.remove('active-tab');
                });
                // Show the selected panel
                const selectedPanel = document.getElementById(`panel-${tabId}`);
                const selectedTab = document.getElementById(`tab-${tabId}`);
                if (selectedPanel) selectedPanel.classList.remove('hidden');
                if (selectedTab) selectedTab.classList.add('active-tab');
            });
        }
    });

    connect();
});
