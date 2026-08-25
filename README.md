# RayRAG

Ricerca semantica sui tuoi documenti, in italiano, richiamabile da Raycast con una
scorciatoia. Tutto in locale: nessun documento lascia il Mac.

```
⌘ + tasto  →  "contratti nordvela"  →  lista di file  →  Invio apre
```

Cerchi **per significato**, non per parole esatte: «cosa devo pagare al fisco» trova i
modelli F24, che la parola «fisco» non la contengono.

---

## Cosa lo distingue

**Nessun LLM.** Non serve che qualcosa *risponda*, serve che *trovi*. Togliere il modello
generativo elimina il pezzo più pesante e più lento, e con esso diversi GB di RAM. Il
risultato è un elenco di file ordinati per pertinenza — e a quel punto **150 millisecondi**
bastano.

**Pensato per l'italiano.** Il modello di embedding è [BGE-M3](https://huggingface.co/BAAI/bge-m3),
multilingue. È la scelta che conta più di ogni altra: con `all-MiniLM-L6-v2` — spesso
proposto come opzione leggera, ma addestrato su inglese — la stessa ricerca sullo stesso
archivio restituisce documenti sbagliati. I numeri sono in [docs/MISURE.md](docs/MISURE.md).

**Legge anche le scansioni.** Un terzo dei PDF di un archivio reale non ha livello di testo:
bilanci, cartelle fiscali, roba passata dalla fotocopiatrice. RayRAG li riconosce con Vision
di macOS, senza installare nulla e senza toccare gli originali.

**Ogni scelta è misurata.** La ricerca ibrida densa+lessicale è stata provata due volte e
scartata due volte perché peggiorava i risultati. La soglia di taglio vale 0,90 perché a 0,95
si perdeva un documento pertinente. Tutte le misure sono pubblicate, comprese quelle che
hanno smentito il progetto iniziale.

## Come è fatto

```
┌─────────────────┐   indicizza   ┌──────────────┐
│  INDICIZZATORE  │ ────────────► │   SQLite     │   testo + vettori, solo qui
│  (all'avvio)    │               │  ~/.rayrag   │
└─────────────────┘               └──────┬───────┘
                                         │
                                  ┌──────▼───────┐
                                  │  SERVIZIO    │   HTTP su localhost, 53 MB
                                  │  + pannello  │
                                  └──────┬───────┘
                                         │ JSON
                                  ┌──────▼───────┐
                                  │   RAYCAST    │   ⏎ apre il file
                                  └──────────────┘
```

L'**indicizzatore** è incrementale: rifà solo i file cambiati, toglie quelli spariti, riprende
dopo un'interruzione, riconosce i duplicati dal testo e non li reincorpora. Il **servizio**
tiene l'indice in memoria e risponde in millisecondi. L'**estensione Raycast** è un client
HTTP di un centinaio di righe.

Formati letti: PDF (con OCR se serve), Word, Excel, PowerPoint, Numbers, Keynote, email
`.eml` e `.msg`, HTML, testo, e immagini via OCR.

## Installazione

Serve **macOS su Apple silicon**, [Ollama](https://ollama.com), Python 3.11+ e, per l'OCR,
gli strumenti da riga di comando di Xcode.

```bash
git clone https://github.com/flodi/rayrag.git
cd rayrag
./installa.sh
```

Lo script prepara l'ambiente Python, scarica il modello (~1,2 GB), compila l'OCR e installa
due LaunchAgent: il servizio di ricerca e l'indicizzazione all'avvio del Mac.

Poi apri **http://localhost:8787**, indica le cartelle da indicizzare e premi «Indicizza ora».

Per la scorciatoia da tastiera:

```bash
cd raycast && npm install && npm run dev
```

e in Raycast assegna una hotkey al comando **Cerca Documenti**.

## Il pannello

Su `http://localhost:8787` trovi quanti file e chunk contiene l'indice, quanti sono stati
letti con OCR, quanti documenti esistono in più copie, l'avanzamento dell'indicizzazione, e
la configurazione: **quali estensioni indicizzare** e quali cartelle escludere (sintassi
`.gitignore`).

## Interrogarlo da fuori

```bash
curl -G --data-urlencode "q=contratti nordvela" --data "n=5" localhost:8787/cerca
curl localhost:8787/salute
```

Risposta: percorso, punteggio, un frammento e il numero di copie identiche trovate.

## Cosa NON fa

- **Non risponde a domande.** Trova file. Se vuoi una risposta in prosa serve un LLM, ed è
  esattamente il pezzo che questo progetto ha tolto.
- **Non indicizza archivi** (`.zip`, `.tar.gz`), modelli 3D, diagrammi o file di
  configurazione. I tipi saltati vengono elencati a fine indicizzazione, non spariscono in
  silenzio.
- **Non è un indice ANN.** La ricerca è a forza bruta perché su decine di migliaia di chunk
  costa 5 ms. Oltre quella scala il punto da cambiare è un file solo, `deposito.py`.
- **Non gira su Linux o Windows**: l'OCR usa Vision di macOS.

## Privacy

L'indice contiene **il testo integrale** dei documenti indicizzati. Sta in `~/.rayrag/` e non
esce di lì: nessuna chiamata di rete a parte Ollama in locale. Se sincronizzi la cartella
home fra più macchine, tieni `~/.rayrag/` fuori dalla sincronizzazione.

## Documentazione

| | |
|---|---|
| [docs/MISURE.md](docs/MISURE.md) | tutti i numeri: modelli a confronto, OCR, tempi, i due tentativi falliti |
| [docs/ARCHITETTURA.md](docs/ARCHITETTURA.md) | perché i tre pezzi sono separati, e cosa cambiare per far crescere l'indice |

## Licenza

MIT — vedi [LICENSE](LICENSE).
