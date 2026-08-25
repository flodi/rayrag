"""Configurazione condivisa fra indicizzatore e pannello web.

Sta in ~/.rayrag/configurazione.json, fuori dal progetto: è stato dell'utente,
non codice, e non va sincronizzata fra le macchine.
"""

import json
from pathlib import Path

PERCORSO = Path.home() / ".rayrag/configurazione.json"

# Tutto ciò che l'estrattore sa leggere. Quali di questi indicizzare davvero
# è una scelta dell'utente, modificabile dal pannello.
PREDEFINITA = {
    # Da cambiare dal pannello web: qui sta solo un punto di partenza sensato.
    "radici": [str(Path.home() / "Documents")],
    "estensioni_attive": [
        ".pdf", ".docx", ".xlsx", ".pptx", ".numbers", ".doc", ".html", ".htm",
        ".eml", ".msg", ".txt", ".md", ".xml", ".csv",
        ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".heic",
    ],
    "esclusioni": [
        "wp-admin/", "wp-includes/", "wp-content/", "public_html/", "public_html 2/",
        "node_modules/", "vendor/", ".venv/", "venv/", "__pycache__/", ".build/",
        "DerivedData/", "Pods/", ".git/", ".svn/", ".hg/", ".cache/", "Caches/",
        ".Trash/", "Library/", "*.app/",
    ],
}


def carica() -> dict:
    c = dict(PREDEFINITA)
    if PERCORSO.exists():
        try:
            salvata = json.loads(PERCORSO.read_text(encoding="utf-8"))
            for k in PREDEFINITA:
                if k in salvata:
                    c[k] = salvata[k]
        except (json.JSONDecodeError, OSError):
            pass  # configurazione illeggibile: si prosegue con i valori predefiniti
    return c


def salva(c: dict) -> None:
    """Scrittura atomica: un pannello che salva mentre l'indicizzatore legge
    non deve poter produrre un file mezzo scritto."""
    PERCORSO.parent.mkdir(parents=True, exist_ok=True)
    tmp = PERCORSO.with_suffix(".json.tmp")
    ripulita = {k: c.get(k, v) for k, v in PREDEFINITA.items()}
    tmp.write_text(json.dumps(ripulita, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PERCORSO)
