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
# scansione git-aware: guarda i file TRACCIATI, che sono quelli che rsync
# copia. Con --no-git vedrebbe anche .env (non tracciato, escluso dal
# rsync) e bloccherebbe ogni deploy per un falso positivo.
if command -v gitleaks >/dev/null; then
    gitleaks detect --source . --redact || {
        echo "!! gitleaks ha trovato qualcosa nei file versionati: NON procedo"
        exit 1; }
else
    echo "!! gitleaks non installato: NON procedo (e' un obbligo di consegna)"
    exit 1
fi

echo "==> rsync verso $SERVER:$REMOTA"
rsync -az --delete \
    --exclude '.env' \
    --exclude '.venv/' \
    --exclude '/cache/' \
    --exclude '__pycache__/' \
    --exclude '.DS_Store' \
    ./ "$SERVER:$REMOTA/"

echo "==> prerequisiti di sistema sul server"
# Ubuntu minimale non ha ensurepip: senza python3-venv il venv si crea
# vuoto e pip non esiste
ssh "$SERVER" "export DEBIAN_FRONTEND=noninteractive; \
    dpkg -s python3-venv >/dev/null 2>&1 || apt-get install -y -qq python3-venv || \
    apt-get install -y -qq python3.12-venv"

echo "==> setup remoto (venv e dipendenze)"
ssh "$SERVER" "cd $REMOTA && python3 -m venv .venv 2>/dev/null || true; \
    .venv/bin/pip install -q -r requirements.txt && \
    .venv/bin/python -m playwright install --with-deps chromium"

echo "==> verifica: il .env deve esistere sul server ed essere solo tuo"
ssh "$SERVER" "cd $REMOTA && \
    if [ -f .env ]; then chmod 600 .env; echo '   .env presente (chmod 600)'; \
    else echo '   !! .env MANCANTE: crealo a mano, vedi README'; fi"

echo "==> fatto. Cron: vedi README, sezione Deploy."
