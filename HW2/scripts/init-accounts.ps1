<#
.SYNOPSIS
    Založí vlastníka v n8n, aby se po `docker compose up` nemuselo nic proklikávat.

.DESCRIPTION
    n8n si od verze 2 vlastníka vynucuje — bez něj první načtení UI skončí na
    registračním formuláři. Ruční proklikání je nepříjemné hlavně proto, že se
    po každém `docker compose down -v` opakuje a že ho nikdo jiný nezreprodukuje.

    Skript je idempotentní: když vlastník existuje, jen to oznámí a skončí.
    Údaje bere z `.env` vedle `docker-compose.yml`.

    LangFlow se neřeší — běží s LANGFLOW_AUTO_LOGIN=true a přihlášení nemá.

.EXAMPLE
    .\scripts\init-accounts.ps1
#>
[CmdletBinding()]
param(
    [string] $EnvFile = (Join-Path $PSScriptRoot '..\.env'),
    [string] $N8nUrl  = 'http://localhost:5678'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $EnvFile)) {
    throw "Chybí $EnvFile. Vytvoř ho příkazem: Copy-Item .env.example .env"
}

# Načtení .env — komentáře a prázdné řádky pryč, zbytek na hashtable.
$cfg = @{}
foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $key, $value = $line -split '=', 2
    $cfg[$key.Trim()] = $value.Trim()
}

foreach ($required in 'N8N_OWNER_EMAIL', 'N8N_OWNER_PASSWORD') {
    if (-not $cfg[$required]) { throw "V $EnvFile chybí $required." }
}

# Běží vůbec n8n?
try {
    $null = Invoke-RestMethod -Uri "$N8nUrl/healthz" -TimeoutSec 10
}
catch {
    throw "n8n na $N8nUrl neodpovídá. Nastartuj stack: docker compose up -d"
}

$settings = Invoke-RestMethod -Uri "$N8nUrl/rest/settings" -TimeoutSec 10
if (-not $settings.data.userManagement.showSetupOnFirstLoad) {
    Write-Host "Vlastník už v n8n existuje — není co dělat." -ForegroundColor Yellow
    Write-Host "Přihlas se jako $($cfg['N8N_OWNER_EMAIL']) na $N8nUrl"
    exit 0
}

$body = @{
    email     = $cfg['N8N_OWNER_EMAIL']
    firstName = if ($cfg['N8N_OWNER_FIRST_NAME']) { $cfg['N8N_OWNER_FIRST_NAME'] } else { 'Admin' }
    lastName  = if ($cfg['N8N_OWNER_LAST_NAME'])  { $cfg['N8N_OWNER_LAST_NAME'] }  else { 'Local' }
    password  = $cfg['N8N_OWNER_PASSWORD']
} | ConvertTo-Json

try {
    $null = Invoke-RestMethod -Uri "$N8nUrl/rest/owner/setup" -Method Post `
        -ContentType 'application/json' -Body $body -TimeoutSec 20
}
catch {
    # n8n chce heslo aspoň 8 znaků, jedno velké písmeno a jednu číslici.
    throw "Založení vlastníka selhalo: $($_.Exception.Message)"
}

Write-Host "Vlastník založen." -ForegroundColor Green
Write-Host "  $N8nUrl  ->  $($cfg['N8N_OWNER_EMAIL'])"
Write-Host "  http://localhost:7860  ->  LangFlow, bez přihlášení"
