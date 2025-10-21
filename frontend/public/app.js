document.addEventListener('DOMContentLoaded', () => {
    // --- Déterminer l'URL du backend ---
    const urlParams = new URLSearchParams(window.location.search);
    const backendPort = urlParams.get('port') || '5001';
    const backendHost = urlParams.get('host') || 'localhost';
    const backendBaseUrl = `http://${backendHost}:${backendPort}`;

    console.log(`[Init] Connexion au backend sur: ${backendBaseUrl}`);

    // --- Références aux éléments du DOM ---
    const statusEl = document.getElementById('status');
    const timerDisplayEl = document.getElementById('timer-display');
    const wordDisplayEl = document.getElementById('word-display');
    const wordInput = document.getElementById('word-input');
    const sendButton = document.getElementById('send-button');
    const restartButton = document.getElementById('restart-button');
    const startButton = document.getElementById('start-button');
    const discoverButton = document.getElementById('discover-button'); // <-- Récupérer le nouveau bouton

    // --- État du jeu ---
    let currentWord = null;
    let gameTimer = null;
    let countdownInterval = null;
    let pollingInterval = null;

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
        if (pollingInterval) clearInterval(pollingInterval);
        pollingInterval = null;

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

        let timeLeft = 5;
        timerDisplayEl.textContent = `Temps restant : ${timeLeft}s`;

        if (countdownInterval) clearInterval(countdownInterval);
        countdownInterval = setInterval(() => {
            timeLeft--;
            if (timeLeft > 0) {
                timerDisplayEl.textContent = `Temps restant : ${timeLeft}s`;
            }
        }, 1000);

        if (gameTimer) clearTimeout(gameTimer);
        gameTimer = setTimeout(handleLoss, 5000);
    }

    async function passBall() {
        // ... (fonction inchangée)
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

    // --- Fonction de découverte (mise à jour pour un meilleur feedback) ---
    async function discoverAndRegister() {
        console.log('[discoverAndRegister] Lancement de la découverte...');
        statusEl.textContent = "Recherche en cours...";
        discoverButton.disabled = true;
        startButton.disabled = true;

        try {
            await fetch(`${backendBaseUrl}/api/discover`, { method: 'POST' });
            // Le backend étant asynchrone, on donne un feedback immédiat
            statusEl.textContent = "Recherche lancée !";
        } catch (error) {
            statusEl.textContent = "Impossible de lancer la recherche.";
            console.error('[discoverAndRegister] Erreur:', error);
        } finally {
            // On réactive les boutons après un court délai
            setTimeout(() => {
                discoverButton.disabled = false;
                startButton.disabled = false;
                if(statusEl.textContent === "Recherche lancée !") {
                    statusEl.textContent = "Prêt à jouer.";
                }
            }, 2000);
        }
    }

    // --- Initialisation ---
    discoverButton.addEventListener('click', discoverAndRegister); // <-- Lier le bouton

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
        resetUI();
        startPolling();
    });

    // Démarre le processus au chargement de la page
    resetUI();
    startPolling();
});