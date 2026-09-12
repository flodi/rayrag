#!/bin/bash
# Installazione di RayRAG. Idempotente: si può rilanciare senza danni.
set -euo pipefail
RADICE="$(cd "$(dirname "$0")" && pwd)"
DATI="$HOME/.rayrag"

dimmi() { printf '\n\033[1m%s\033[0m\n' "$1"; }

dimmi "1/5  Requisiti"
[ "$(uname)" = "Darwin" ] || { echo "Serve macOS: l'OCR usa Vision." >&2; exit 1; }
command -v python3 >/dev/null || { echo "Serve python3." >&2; exit 1; }
command -v ollama  >/dev/null || { echo "Serve Ollama: https://ollama.com" >&2; exit 1; }
command -v swiftc  >/dev/null || echo "  swiftc assente: niente OCR (installa gli strumenti da riga di comando di Xcode)"

dimmi "2/5  Ambiente Python"
# Un venv NON è spostabile: gli script in bin/ hanno il percorso assoluto nello
# shebang, quindi se la cartella del progetto viene spostata pip smette di funzionare
# mentre python sembra a posto. Si verifica invece di fidarsi dell'esistenza.
if [ -d "$RADICE/.venv" ] && ! "$RADICE/.venv/bin/pip" --version >/dev/null 2>&1; then
  echo "  il venv esistente è rotto (progetto spostato?): lo ricreo"
  rm -rf "$RADICE/.venv"
fi
[ -d "$RADICE/.venv" ] || python3 -m venv "$RADICE/.venv"
"$RADICE/.venv/bin/pip" install -q --upgrade pip
"$RADICE/.venv/bin/pip" install -q -r "$RADICE/requirements.txt"
echo "  dipendenze a posto"

dimmi "3/5  Modello di embedding"
if ollama list 2>/dev/null | grep -q '^bge-m3'; then
  echo "  bge-m3 già presente"
else
  echo "  scarico bge-m3 (~1,2 GB, ci vuole qualche minuto)"
  ollama pull bge-m3
fi

dimmi "4/5  OCR"
if command -v swiftc >/dev/null; then
  swiftc -O -o "$RADICE/indicizzatore/vocr" "$RADICE/indicizzatore/vocr.swift"
  echo "  vocr compilato"
fi

dimmi "5/5  Avvio automatico"
mkdir -p "$DATI" "$HOME/Library/LaunchAgents"
for m in "$RADICE"/servizio/io.rayrag.plist.modello "$RADICE"/indicizzatore/io.rayrag-indicizzatore.plist.modello; do
  nome="$(basename "$m" .modello)"
  sed -e "s|__RADICE__|$RADICE|g" -e "s|__CASA__|$HOME|g" "$m" > "$HOME/Library/LaunchAgents/$nome"
  launchctl unload "$HOME/Library/LaunchAgents/$nome" 2>/dev/null || true
  launchctl load "$HOME/Library/LaunchAgents/$nome"
  echo "  caricato $nome"
done

cat <<FINE

Fatto. Il servizio ascolta su http://localhost:8787
  · pannello di gestione: apri quell'indirizzo nel browser
  · scegli le cartelle da indicizzare e premi «Indicizza ora»
  · per la scorciatoia da tastiera: cd raycast && npm install && npm run dev

L'indice sta in $DATI e non esce mai da questa macchina.
FINE
