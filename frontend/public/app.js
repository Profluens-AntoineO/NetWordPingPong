document.addEventListener('DOMContentLoaded', () => {
    // --- Déterminer l'URL du backend ---
    const urlParams = new URLSearchParams(window.location.search);
    const backendPort = urlParams.get('port') || '5000';
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
        sendButton.disabled = true;
        restartButton.style.display = 'none';
        startButton.style.display = 'block';
        statusEl.textContent = "Prêt à jouer. Cliquez sur 'Commencer' ou attendez la balle.";
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
        sendButton.disabled = true;
        startButton.style.display = 'none';
        restartButton.style.display = 'block';
    }

    function startTurn(word) {
        console.log(`%c[startTurn] Nouveau tour commencé avec le mot : "${word}"`, 'color: #61dafb; font-weight: bold;');
        if (pollingInterval) clearInterval(pollingInterval);
        pollingInterval = null;

        currentWord = word;
        statusEl.textContent = "À vous de jouer !";
        wordDisplayEl.textContent = word;
        wordInput.disabled = false;
        sendButton.disabled = false;
        wordInput.focus();
        startButton.style.display = 'none';

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
        console.log('[passBall] Tentative de soumission déclenchée.');

        const newWord = wordInput.value.trim().toLowerCase();

        // --- LOGS DE COMPARAISON ---
        console.log(`[passBall] Mot soumis par l'utilisateur : "${newWord}"`);
        console.log(`[passBall] Mot de base attendu (currentWord) : "${currentWord}"`);
        console.log(`[passBall] Test de la condition: Le mot "${newWord}" correspond-il au à ${currentWord} ? -> ${currentWord === newWord}`);
        // --- FIN DES LOGS DE COMPARAISON ---

        if (newWord.startsWith(currentWord) && newWord.length !== currentWord.length + 1) {
            statusEl.textContent = "Mot incorrect ! Réessayez.";
            console.error('[passBall] ÉCHEC de la validation locale : le mot soumis ne correspond pas au format attendu.');
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
            console.log(`[passBall] Envoi de la requête POST à ${backendBaseUrl}/api/pass-ball avec le payload: { "newWord": "${newWord}" }`);
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
            console.error('[passBall] Erreur dans le bloc try/catch de la requête fetch:', error);
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
            console.error("[checkForBall] Erreur de polling:", error);
            statusEl.textContent = "Erreur de connexion au serveur.";
            if (pollingInterval) clearInterval(pollingInterval);
        }
    }

    function startPolling() {
        if (pollingInterval) clearInterval(pollingInterval);
        pollingInterval = setInterval(checkForBall, 1000);
    }

    async function discoverAndRegister() {
        try {
            console.log('[discoverAndRegister] Lancement de la découverte côté serveur...');
            statusEl.textContent = "Recherche d'autres joueurs sur le réseau...";
            await fetch(`${backendBaseUrl}/api/discover`, { method: 'POST' });
        } catch (error) {
            statusEl.textContent = "Impossible de contacter le serveur pour la découverte.";
            console.error('[discoverAndRegister] Erreur:', error);
        }
    }

    // --- Initialisation ---
    sendButton.addEventListener('click', passBall);
    startButton.addEventListener('click', () => {
        console.log('[startButton] Clic sur "Commencer la partie".');
        // On passe l'objet backgroundTasks vide, car il n'est utilisé que côté serveur
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
                console.error('[startButton] Erreur lors du démarrage de la partie:', error);
            });
    });

    wordInput.addEventListener('keyup', (event) => {
        if (event.key === 'Enter' && !sendButton.disabled) {
            passBall();
        }
    });

    restartButton.addEventListener('click', () => {
        console.log('[restartButton] Clic sur "Recommencer".');
        resetUI();
        startPolling();
    });

    // Démarre le processus
    discoverAndRegister().then(() => {
        resetUI();
        startPolling();
    });
});