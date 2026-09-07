#!/usr/bin/env bash
# Založí vlastníka v n8n — linuxová varianta pro nasazení na VM.
# Windows verze: scripts/init-accounts.ps1 (viz docs/instalace.md).
# Idempotentní: když vlastník existuje, jen to oznámí.
set -euo pipefail

ENV_FILE="${ENV_FILE:-$(dirname "$0")/../.env}"
N8N_URL="${N8N_URL:-http://localhost:5678}"

[ -f "$ENV_FILE" ] || { echo "Chybí $ENV_FILE — vytvoř ho z .env.vm.example." >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

: "${N8N_OWNER_EMAIL:?chybí v .env}"
: "${N8N_OWNER_PASSWORD:?chybí v .env}"

curl -sf "$N8N_URL/healthz" >/dev/null \
  || { echo "n8n na $N8N_URL neodpovídá — spusť: docker compose up -d" >&2; exit 1; }

if ! curl -s "$N8N_URL/rest/settings" | grep -q '"showSetupOnFirstLoad":true'; then
  echo "Vlastník už v n8n existuje — není co dělat."
  echo "Přihlas se jako $N8N_OWNER_EMAIL na $N8N_URL"
  exit 0
fi

curl -sf -X POST "$N8N_URL/rest/owner/setup" \
  -H 'Content-Type: application/json' \
  -d "$(printf '{"email":"%s","firstName":"%s","lastName":"%s","password":"%s"}' \
        "$N8N_OWNER_EMAIL" "${N8N_OWNER_FIRST_NAME:-Admin}" \
        "${N8N_OWNER_LAST_NAME:-Local}" "$N8N_OWNER_PASSWORD")" >/dev/null

echo "Vlastník založen: $N8N_OWNER_EMAIL na $N8N_URL"
