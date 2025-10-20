document.addEventListener('DOMContentLoaded', () => {
    // --- Références aux éléments du DOM ---
    const statusEl = document.getElementById('status');
    const wordDisplayEl = document.getElementById('word-display');
    const wordInput = document.getElementById('word-input');
    const sendButton = document.getElementById('send-button');
    const restartButton = document.getElementById('restart-button');
    const startButton = document.getElementById('start-button'); // <-- 1. Récupérer le bouton

    // --- État du jeu ---
    let currentWord = null;
    let gameTimer = null;
    let pollingInterval = null;

    // --- Fonctions de jeu ---

    /**
     * Réinitialise l'interface à l'état d'attente.
     */
    function resetUI() {
        wordDisplayEl.textContent = '';
        wordInput.value = '';
        wordInput.disabled = true;
        sendButton.disabled = true;
        restartButton.style.display = 'none';

        // Affiche le bouton "Commencer" si le jeu est inactif
        startButton.style.display = 'block'; // <-- 3. Afficher le bouton

        statusEl.textContent = "Prêt à jouer. Cliquez sur 'Commencer' ou attendez la balle.";
        currentWord = null;
        if (gameTimer) clearTimeout(gameTimer);
    }

    /**
     * Gère la condition de défaite lorsque le temps est écoulé.
     */
    function handleLoss() {
        clearTimeout(gameTimer);
        statusEl.textContent = "Trop tard ! Vous avez perdu.";
        wordInput.disabled = true;
        sendButton.disabled = true;
        startButton.style.display = 'none';
        restartButton.style.display = 'block';
    }

    /**
     * Déclenche le tour du joueur.
     * @param {string} word Le mot à afficher.
     */
    function startTurn(word) {
        if (pollingInterval) clearInterval(pollingInterval);
        pollingInterval = null;

        currentWord = word;
        statusEl.textContent = "À vous de jouer !";
        wordDisplayEl.textContent = word;
        wordInput.disabled = false;
        sendButton.disabled = false;
        wordInput.focus();

        // Masque le bouton "Commencer" pendant un tour
        startButton.style.display = 'none'; // <-- 3. Masquer le bouton

        if (gameTimer) clearTimeout(gameTimer);
        gameTimer = setTimeout(handleLoss, 5000);
    }

    /**
     * Appelle l'API pour renvoyer la balle.
     */
    async function passBall() {
        const newWord = wordInput.value.trim().toLowerCase();
        const expectedPattern = new RegExp(`^${currentWord}[a-z]$`);

        if (!expectedPattern.test(newWord)) {
            statusEl.textContent = "Mot incorrect ! Réessayez.";
            return;
        }

        clearTimeout(gameTimer);
        wordInput.disabled = true;
        sendButton.disabled = true;
        statusEl.textContent = "Envoi en cours...";

        try {
            const response = await fetch('http://localhost:5000/api/pass-ball', {
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

    /**
     * Appelle l'API pour démarrer une nouvelle partie.
     */
    async function startGame() { // <-- 2. Nouvelle fonction
        statusEl.textContent = "Démarrage d'une nouvelle partie...";
        startButton.style.display = 'none'; // Masque le bouton pour éviter les doubles clics

        try {
            const response = await fetch('http://localhost:5000/api/start-game', {
                method: 'POST',
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Impossible de démarrer la partie.');
            }

            statusEl.textContent = "Partie démarrée ! En attente de la balle...";
            // Le polling va automatiquement détecter le début du jeu
            if (!pollingInterval) {
                startPolling();
            }

        } catch (error) {
            statusEl.textContent = error.message;
            startButton.style.display = 'block'; // Réaffiche le bouton en cas d'erreur
        }
    }

    /**
     * Interroge le backend toutes les secondes pour savoir si c'est notre tour.
     */
    async function checkForBall() {
        try {
            const response = await fetch('http://localhost:5000/api/get-ball');
            const data = await response.json();

            if (data && data.word && data.word !== currentWord) {
                startTurn(data.word);
            }
        } catch (error) {
            console.error("Erreur de polling:", error);
            statusEl.textContent = "Erreur de connexion au serveur.";
            if(pollingInterval) clearInterval(pollingInterval);
        }
    }

    function startPolling() {
        if (pollingInterval) clearInterval(pollingInterval);
        pollingInterval = setInterval(checkForBall, 1000);
    }

    /**
     * Tente de s'inscrire sur le réseau (la logique est côté backend).
     */
    async function discoverAndRegister() {
        try {
            statusEl.textContent = "Recherche d'autres joueurs sur le réseau...";
            await fetch('http://localhost:5000/api/discover', { method: 'POST' });
            // Le message de resetUI sera affiché après
        } catch (error) {
            statusEl.textContent = "Impossible de contacter le serveur pour la découverte.";
        }
    }

    // --- Initialisation ---
    sendButton.addEventListener('click', passBall);
    startButton.addEventListener('click', startGame); // <-- 2. Ajouter l'événement

    wordInput.addEventListener('keyup', (event) => {
        if (event.key === 'Enter' && !sendButton.disabled) passBall();
    });

    restartButton.addEventListener('click', () => {
        resetUI();
        startPolling();
    });

    // Démarre le processus
    discoverAndRegister().then(() => {
        resetUI();
        startPolling();
    });
});