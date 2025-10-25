# Script PowerShell pour lancer NetWord Ping Pong en détectant automatiquement l'IP locale.
#
# Utilisation :
# 1. Ouvrez une console PowerShell.
# 2. Si nécessaire, autorisez l'exécution de scripts : Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
# 3. Exécutez le script : .\start.ps1

Write-Host "🔍 Recherche de l'adresse IP locale..."

# Tente de trouver une adresse IPv4 active sur une interface Wi-Fi ou Ethernet.
# On filtre par AddressState 'Preferred' pour obtenir l'IP principale et non une IP temporaire.
$localIp = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceType Ethernet, WiFi | Where-Object { $_.AddressState -eq 'Preferred' } | Select-Object -First 1).IPAddress

if (-not $localIp) {
    Write-Host "❌ Impossible de détecter une adresse IP locale active. Veuillez la configurer manuellement dans le fichier docker-compose.yml."
    exit 1
}

Write-Host "✅ Adresse IP détectée : $localIp"
Write-Host "🚀 Lancement des conteneurs Docker..."

$env:OWN_HOST = $localIp
docker-compose up --build