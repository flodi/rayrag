# Estensione Raycast

Frontend di RayRAG: interroga il servizio su `localhost` e mostra i file trovati.
**Non è pensata per il negozio Raycast** — vive in locale.

## Avvio

```bash
# 1. il servizio di ricerca (in un terminale a parte)
../servizio/avvia.sh

# 2. l'estensione, la prima volta
cd raycast && npm install && npm run dev
```

`npm run dev` la registra in Raycast: da lì cerca **Cerca Documenti** e assegnale una
scorciatoia (Impostazioni → Extensions → RayRAG → Record Hotkey). È quella scorciatoia il
requisito del progetto, non l'estensione in sé.

## Uso

| tasto | azione |
|---|---|
| ⏎ | apre il file |
| ⌘⏎ | mostra nel Finder |
| ⌘⇧C | copia il percorso |
| ⌘O | apri con… |

Si cerca **per significato**: «cosa devo pagare al fisco» trova gli F24 anche se non
contengono quelle parole. Vedi [../docs/MISURE.md](../docs/MISURE.md).

## Preferenze

| preferenza | predefinito | a cosa serve |
|---|---|---|
| Servizio di ricerca | `http://127.0.0.1:8787` | dove ascolta `servizio.py` |
| Risultati | `12` | quanti file mostrare |

## Se non trova nulla

L'estensione distingue i due casi: se il servizio non risponde lo dice esplicitamente
(«Servizio di ricerca non raggiungibile»), invece di mostrare una lista vuota che
sembrerebbe «nessun documento pertinente». Controlla nell'ordine:

```bash
curl localhost:8787/salute      # il servizio e quanti chunk ha in pancia
curl localhost:11434/api/tags   # Ollama, che calcola l'embedding della query
```
