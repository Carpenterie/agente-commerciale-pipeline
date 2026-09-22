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
# Se gitleaks non e' sul PATH si scarica da solo, UNA volta, in una cache
# fuori dal repo: versione PINNATA e checksum verificato contro il file
# ufficiale della release. Prima viveva nello scratchpad di sessione, che
# si ripulisce tra un riavvio e l'altro, e il riscarico era un rito a mano.
GITLEAKS_VER="8.30.1"
GITLEAKS_CACHE="$HOME/.cache/carpenterie-gitleaks"
GITLEAKS_BIN="$GITLEAKS_CACHE/gitleaks-$GITLEAKS_VER"
if ! command -v gitleaks >/dev/null && [ ! -x "$GITLEAKS_BIN" ]; then
    case "$(uname -s)-$(uname -m)" in
        Darwin-x86_64) GITLEAKS_PIATTAFORMA="darwin_x64" ;;
        Darwin-arm64)  GITLEAKS_PIATTAFORMA="darwin_arm64" ;;
        Linux-x86_64)  GITLEAKS_PIATTAFORMA="linux_x64" ;;
        *) echo "!! piattaforma non prevista: installa gitleaks a mano"; exit 1 ;;
    esac
    echo "==> scarico gitleaks v$GITLEAKS_VER ($GITLEAKS_PIATTAFORMA) nella cache"
    mkdir -p "$GITLEAKS_CACHE"
    BASE_URL="https://github.com/gitleaks/gitleaks/releases/download/v$GITLEAKS_VER"
    curl -sL -o "$GITLEAKS_CACHE/gl.tar.gz" \
        "$BASE_URL/gitleaks_${GITLEAKS_VER}_${GITLEAKS_PIATTAFORMA}.tar.gz"
    curl -sL -o "$GITLEAKS_CACHE/sums.txt" \
        "$BASE_URL/gitleaks_${GITLEAKS_VER}_checksums.txt"
    ATTESO=$(grep "_${GITLEAKS_PIATTAFORMA}.tar.gz" "$GITLEAKS_CACHE/sums.txt" | cut -d' ' -f1)
    REALE=$(shasum -a 256 "$GITLEAKS_CACHE/gl.tar.gz" | cut -d' ' -f1)
    if [ -z "$ATTESO" ] || [ "$ATTESO" != "$REALE" ]; then
        echo "!! checksum di gitleaks NON corrisponde: NON procedo"
        rm -f "$GITLEAKS_CACHE/gl.tar.gz"
        exit 1
    fi
    tar xzf "$GITLEAKS_CACHE/gl.tar.gz" -C "$GITLEAKS_CACHE" gitleaks
    mv "$GITLEAKS_CACHE/gitleaks" "$GITLEAKS_BIN"
    chmod +x "$GITLEAKS_BIN"
    rm -f "$GITLEAKS_CACHE/gl.tar.gz" "$GITLEAKS_CACHE/sums.txt"
fi
if command -v gitleaks >/dev/null; then
    GITLEAKS=gitleaks
else
    GITLEAKS="$GITLEAKS_BIN"
fi
"$GITLEAKS" version >/dev/null || { echo "!! gitleaks non eseguibile"; exit 1; }
"$GITLEAKS" detect --source . --redact || {
    echo "!! gitleaks ha trovato qualcosa nei file versionati: NON procedo"
    exit 1; }

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
