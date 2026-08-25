#!/bin/bash
# Avvia il servizio di ricerca RayRAG.
#   ./servizio/avvia.sh                         usa il deposito predefinito
#   ./servizio/avvia.sh ~/.rayrag/altro.sqlite  usa un altro deposito
set -euo pipefail
RADICE="$(cd "$(dirname "$0")/.." && pwd)"
DEPOSITO="${1:-$HOME/.rayrag/indice.sqlite}"

if [ ! -f "$DEPOSITO" ]; then
  echo "deposito assente: $DEPOSITO — costruiscilo con indicizzatore/indicizza.py" >&2
  exit 1
fi
# Ollama serve solo al momento della query, non all'avvio: se non c'è ancora
# (tipico al login, prima che parta il suo agent) si avvisa e si prosegue.
# Uscire qui farebbe entrare launchd in un ciclo di riavvii.
if ! curl -s --max-time 2 localhost:11434/api/tags > /dev/null; then
  echo "attenzione: Ollama non risponde su localhost:11434; le query falliranno finché non parte" >&2
fi

exec "$RADICE/.venv/bin/python" "$RADICE/servizio/servizio.py" --deposito "$DEPOSITO"
