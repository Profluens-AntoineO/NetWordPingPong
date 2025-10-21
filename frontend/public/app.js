document.addEventListener('DOMContentLoaded', () => {
    // --- Déterminer l'URL du backend ---
    const backendBaseUrl = `http://${window.location.hostname}:5000`;

    console.log(`[Init] Connexion au backend sur: ${backendBaseUrl}`);


    console.log(`[Init] Connexion au backend sur: ${backendBaseUrl}`);

    // --- Références aux éléments du DOM ---
    const statusEl = document.getElementById('status');
    const timerDisplayEl = document.getElementById('timer-display');
    const wordDisplayEl = document.getElementById('word-display');
    const wordInput = document.getElementById('word-input');
    const sendButton = document.getElementById('send-button');
    const restartButton = document.getElementById('restart-button');
    const startButton = document.getElementById('start-button');
    const discoverButton = document.getElementById('discover-button');
    const playerListEl = document.getElementById('player-list');

    // --- État du jeu ---
    let currentWord = null;
    let gameTimer = null;
    let countdownInterval = null;
    let pollingInterval = null;
    let playerListInterval = null;

    // --- Fonctions de jeu ---

    function resetUI() {
        wordDisplayEl.textContent = '';
        wordInput.value = '';
        wordInput.disabled = true;

        sendButton.classList.add('hidden');
        restartButton.classList.add('hidden');
        startButton.classList.remove('hidden');
        discoverButton.classList.remove('hidden');

        statusEl.textContent = "Cliquez sur 'Rechercher' ou 'Commencer'.";
        currentWord = null;
        if (gameTimer) clearTimeout(gameTimer);
        if (countdownInterval) clearInterval(countdownInterval);
        timerDisplayEl.textContent = '';
    }

    function handleLoss() {
        console.warn('[handleLoss] Le temps est écoulé côté client.');
        if (countdownInterval) clearInterval(countdownInterval);
        timerDisplayEl.textContent = 'Temps écoulé !';
        clearTimeout(gameTimer);
        statusEl.textContent = "Trop tard ! Vous avez perdu.";
        wordInput.disabled = true;

        sendButton.classList.add('hidden');
        startButton.classList.add('hidden');
        discoverButton.classList.add('hidden');
        restartButton.classList.remove('hidden');
    }
    function startTurn(word) {
        console.log(`%c[startTurn] Nouveau tour commencé avec le mot : "${word}"`, 'color: #61dafb; font-weight: bold;');
        stopPolling();

        currentWord = word;
        statusEl.textContent = "À vous de jouer !";
        wordDisplayEl.textContent = word;
        wordInput.disabled = false;
        wordInput.focus();

        startButton.classList.add('hidden');
        restartButton.classList.add('hidden');
        discoverButton.classList.add('hidden');
        sendButton.classList.remove('hidden');
        sendButton.disabled = false;

        // --- MODIFICATION: Temps du tour augmenté à 60 secondes ---
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
        gameTimer = setTimeout(handleLoss, 60000); // 60000 millisecondes
    }

    async function passBall() {
        console.log('[passBall] Tentative de soumission déclenchée.');
        const newWord = wordInput.value.trim().toLowerCase();
        const expectedPattern = new RegExp(`^${currentWord}[a-z]$`);

        console.log(`[passBall] Mot soumis: "${newWord}", Mot attendu: "${currentWord}"`);
        if (!expectedPattern.test(newWord)) {
            statusEl.textContent = "Mot incorrect ! Réessayez.";
            console.error('[passBall] ÉCHEC de la validation locale.');
            return;
        }

        console.log('%c[passBall] SUCCÈS de la validation locale.', 'color: lightgreen;');
        clearTimeout(gameTimer);
        if (countdownInterval) clearInterval(countdownInterval);
        timerDisplayEl.textContent = '';
        wordInput.disabled = true;
        sendButton.disabled = true;
        statusEl.textContent = "Envoi en cours...";

        try {
            console.log(`[passBall] Envoi de la requête POST à ${backendBaseUrl}/api/pass-ball`);
            const response = await fetch(`${backendBaseUrl}/api/pass-ball`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ newWord: newWord }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                console.error('[passBall] Erreur reçue du serveur:', errorData);
                throw new Error(errorData.detail || 'Erreur lors de l\'envoi.');
            }

            console.log('%c[passBall] Réponse positive (200 OK) reçue du serveur.', 'color: lightgreen;');
            resetUI();
            startPolling();
        } catch (error) {
            statusEl.textContent = error.message;
            console.error('[passBall] Erreur dans le bloc try/catch:', error);
            wordInput.disabled = false;
            sendButton.disabled = false;
        }
    }

    async function checkForBall() {
        try {
            const response = await fetch(`${backendBaseUrl}/api/get-ball`);
            const data = await response.json();
            if (data && data.word && data.word !== currentWord) {
                console.log(`[checkForBall] Nouvelle balle détectée ! Mot reçu : "${data.word}"`);
                startTurn(data.word);
            }
        } catch (error) {
            // On évite de spammer la console pour les erreurs de polling
        }
    }

    function startPolling() {
        if (pollingInterval) clearInterval(pollingInterval);
        pollingInterval = setInterval(checkForBall, 1000);
    }

    // --- NOUVELLE FONCTION: Mise à jour de la liste des joueurs (AVEC LOGS) ---
    async function updatePlayerList() {
        try {
            // console.debug('[updatePlayerList] Interrogation de /api/players...');
            const response = await fetch(`${backendBaseUrl}/api/players`);
            if (!response.ok) {
                // console.warn('[updatePlayerList] La requête a échoué, le serveur n\'est peut-être pas prêt.');
                return;
            }

            const data = await response.json();
            console.log('[updatePlayerList] Données reçues:', data);

            playerListEl.innerHTML = '';

            if (data.players && data.players.length > 0) {
                console.log(`[updatePlayerList] ${data.players.length} joueur(s) trouvé(s). Mise à jour de l'affichage.`);
                data.players.sort().forEach(playerIdentifier => {
                    const li = document.createElement('li');
                    const turnCount = data.turn_counts[playerIdentifier] || 0;

                    let playerText = `${playerIdentifier} (Tours: ${turnCount})`;

                    if (`http://${playerIdentifier}` === backendBaseUrl) {
                        li.classList.add('text-cyan-400', 'font-bold');
                        playerText += ' (Vous)';
                    }

                    li.textContent = playerText;
                    playerListEl.appendChild(li);
                });
            } else {
                console.log('[updatePlayerList] Aucun joueur détecté. Affichage du message par défaut.');
                playerListEl.innerHTML = '<li>Aucun joueur détecté.</li>';
            }
        } catch (error) {
            console.error('[updatePlayerList] Erreur lors de la récupération ou de la mise à jour de la liste des joueurs:', error);
        }
    }

    function startPlayerListPolling() {
        if (playerListInterval) clearInterval(playerListInterval);
        updatePlayerList();
        playerListInterval = setInterval(updatePlayerList, 1000);
    }

    async function discoverAndRegister() {
        console.log('[discoverAndRegister] Lancement de la découverte...');
        statusEl.textContent = "Recherche en cours...";
        discoverButton.disabled = true;
        startButton.disabled = true;

        try {
            await fetch(`${backendBaseUrl}/api/discover`, { method: 'POST' });
            statusEl.textContent = "Recherche lancée !";
        } catch (error) {
            statusEl.textContent = "Impossible de lancer la recherche.";
            console.error('[discoverAndRegister] Erreur:', error);
        } finally {
            setTimeout(() => {
                discoverButton.disabled = false;
                startButton.disabled = false;
                if(statusEl.textContent === "Recherche lancée !") {
                    statusEl.textContent = "Prêt à jouer.";
                }
            }, 2000);
        }
    }
    function resetUI() {
        wordDisplayEl.textContent = '';
        wordInput.value = '';
        wordInput.disabled = true;

        sendButton.classList.add('hidden');
        restartButton.classList.add('hidden');
        startButton.classList.remove('hidden'); // Afficher le bouton "Commencer"
        discoverButton.classList.remove('hidden'); // Afficher le bouton "Rechercher"

        statusEl.textContent = "Cliquez sur 'Rechercher' ou 'Commencer'."; // Message de départ
        currentWord = null;

        if (gameTimer) clearTimeout(gameTimer);
        if (countdownInterval) clearInterval(countdownInterval);
        timerDisplayEl.textContent = '';
    }
    // --- Initialisation ---
    discoverButton.addEventListener('click', discoverAndRegister);

    startButton.addEventListener('click', () => {
        console.log('[startButton] Clic sur "Commencer la partie".');
        statusEl.textContent = "Démarrage de la partie...";
        startButton.disabled = true;
        discoverButton.disabled = true;

        fetch(`${backendBaseUrl}/api/start-game`, { method: 'POST' })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(err => { throw new Error(err.detail); });
                }
                console.log('[startButton] Requête de démarrage envoyée avec succès.');
                statusEl.textContent = "Partie démarrée ! En attente de la balle...";
            })
            .catch(error => {
                statusEl.textContent = error.message;
                console.error('[startButton] Erreur:', error);
            })
            .finally(() => {
                // Ne pas réactiver les boutons ici, car le jeu est censé commencer
            });
    });

    sendButton.addEventListener('click', passBall);
    wordInput.addEventListener('keyup', (event) => {
        if (event.key === 'Enter' && !sendButton.disabled) passBall();
    });
    restartButton.addEventListener('click', () => {
        console.log('[restartButton] Clic sur "Recommencer".');
        // On réinitialise l'interface
        resetUI();
        // On relance le polling pour la balle (au cas où un autre joueur nous enverrait une balle)
        startPolling();
        // On relance le polling pour la liste des joueurs
        startPlayerListPolling();
    });

    // Démarre le processus au chargement de la page
    resetUI();
    startPolling();
    startPlayerListPolling();
});