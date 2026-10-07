#!/usr/bin/env bash
# Aggiorna OPENAPI_TOKEN nel .env del Mac e del server. Da lanciare a mano
# in una finestra del Terminale: il token si digita (o incolla) senza che
# compaia, non finisce nella cronologia della shell, non passa mai come
# argomento di un comando (si vedrebbe in `ps`) e non viene stampato.
#
#   ./strumenti/aggiorna_token_openapi.sh
set -euo pipefail
SERVER="${1:-root@91.99.52.118}"
REMOTA="/opt/agente-commerciale-pipeline"
cd "$(dirname "$0")/.."

read -r -s -p "Nuovo token Openapi (non viene mostrato): " TOKEN
echo
if [ -z "$TOKEN" ]; then echo "nessun token: niente modificato"; exit 1; fi

# printf e' un comando interno di bash: il token resta in memoria e arriva
# allo script Python solo da stdin (sul server, dentro la connessione ssh)
printf '%s' "$TOKEN" | python3 strumenti/scrivi_env.py OPENAPI_TOKEN .env
printf '%s' "$TOKEN" | ssh "$SERVER" "cd $REMOTA && python3 strumenti/scrivi_env.py OPENAPI_TOKEN .env"
unset TOKEN
echo "fatto: il token e' nel .env del Mac e del server. Ora la verifica (senza mostrarlo)."
