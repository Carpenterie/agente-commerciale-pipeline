#!/usr/bin/env bash
# Deploy su Hetzner (PRD §11.9). Da lanciare DAL MAC, non dal server.
#
#   ./deploy.sh utente@indirizzo-server
#
# Copia il repo via rsync ESCLUDENDO .env, cache, venv e file locali.
# Il .env sul server si crea a mano UNA VOLTA (vedi README): non viaggia
# mai né in git né in rsync.
set -euo pipefail

SERVER="${1:?uso: ./deploy.sh utente@server}"
REMOTA="${2:-/opt/agente-commerciale-pipeline}"

echo "==> gitleaks prima di copiare (obbligo di consegna)"
if command -v gitleaks >/dev/null; then
    gitleaks detect --no-git --source . --redact || {
        echo "!! gitleaks ha trovato qualcosa: NON procedo"; exit 1; }
else
    echo "   gitleaks non installato: scaricalo prima del deploy definitivo"
fi

echo "==> rsync verso $SERVER:$REMOTA"
rsync -az --delete \
    --exclude '.env' \
    --exclude '.venv/' \
    --exclude 'cache/' \
    --exclude '__pycache__/' \
    --exclude '.DS_Store' \
    --exclude 'tests/campione_26/cache/' \
    ./ "$SERVER:$REMOTA/"

echo "==> setup remoto (venv e dipendenze)"
ssh "$SERVER" "cd $REMOTA && python3 -m venv .venv 2>/dev/null || true; \
    .venv/bin/pip install -q -r requirements.txt && \
    .venv/bin/python -m playwright install --with-deps chromium"

echo "==> verifica: il .env deve esistere sul server ed essere solo tuo"
ssh "$SERVER" "cd $REMOTA && \
    if [ -f .env ]; then chmod 600 .env; echo '   .env presente (chmod 600)'; \
    else echo '   !! .env MANCANTE: crealo a mano, vedi README'; fi"

echo "==> fatto. Cron: vedi README, sezione Deploy."
