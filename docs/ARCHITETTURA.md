# Architettura

Tre pezzi separati, ognuno sostituibile senza toccare gli altri. La separazione non è
estetica: viene da un vincolo concreto e da una misura.

## 1. Indicizzatore — `indicizzatore/`

Gira all'avvio del Mac, oppure a comando dal pannello.

**Estrazione.** PDF, Word, Excel, PowerPoint, Numbers, Keynote, email, HTML, testo, immagini.
Quando un PDF non ha livello di testo si passa a Vision di macOS, rasterizzando a 300 dpi.
Vale anche per le immagini, che nella pratica sono quasi sempre scansioni di documenti.

**Chunking.** Blocchi da 2500 caratteri (~600-700 token in italiano) con 400 di
sovrapposizione. Il chunk conserva percorso e posizione.

> Attenzione agli **elenchi**: una rubrica in xlsx ha prodotto da sola 1030 chunk su 1434 —
> il 72% dell'indice — comparendo come rumore in query che non la riguardavano. I fogli di
> calcolo che sono tabelle di dati andrebbero trattati diversamente dalla prosa.

**Incrementalità.** Un file si rifà solo se `mtime` o dimensione sono cambiati. Ogni file è
una transazione a sé: un'interruzione perde al massimo il file in corso. I file spariti dal
disco vengono tolti dall'indice — senza questo, spostare una cartella lascia un indice pieno
di percorsi morti.

**Deduplica sul testo.** L'identità di un documento è il testo che contiene, non i suoi byte:
lo stesso PDF risalvato cambia i metadati e non cambia il contenuto. Si estrae sempre (è la
parte veloce) e si incorpora solo se quel testo non si è già visto (è la parte lenta).

**Due precauzioni misurate.** L'indicizzatore tiene sveglia la macchina con `caffeinate -dims`,
perché a batteria macOS la sospende e il ritmo crolla di venti volte; e si ferma appena arriva
una ricerca, perché ricerca e indicizzazione si contendono Ollama.

## 2. Servizio — `servizio/`

Un processo in ascolto su `127.0.0.1`, che tiene l'indice in memoria e risponde in
millisecondi. Solo libreria standard più numpy: **53 MB residenti**.

```
GET  /cerca?q=…&n=10[&stacco=0]   ricerca
GET  /salute                       stato dell'indice
GET  /                             pannello di gestione
GET  /api/stato                    dati del pannello
POST /api/config                   salva la configurazione
POST /api/indicizza                lancia l'indicizzazione
```

Il modello **non** viene tenuto caldo: ricaricarlo costa un secondo, tenerlo vivo costa un
giga di RAM. Si lascia che Ollama lo scarichi.

Le POST accettano solo richieste senza `Origin` o con origine sul servizio stesso: senza
questo controllo, una qualunque pagina web aperta nel browser potrebbe riconfigurare
l'indicizzatore.

### Perché SQLite e non un database vettoriale

Il piano iniziale prevedeva LanceDB. La misura l'ha smentito: la ricerca a forza bruta costa
**5 ms su 5747 vettori**, quindi l'indice ANN non serve a questa scala. Quello che serve
davvero — sapere cosa è già indicizzato, cancellare i file spariti, riprendere dopo
un'interruzione — è ciò che una tabella SQLite fa senza aggiungere dipendenze.

Il punto in cui cambiare idea, se i chunk diventassero centinaia di migliaia, è **un solo
file**: `indicizzatore/deposito.py`.

### Il taglio sullo stacco

Si scartano i risultati sotto `0,90 × punteggio del primo`. Senza soglia, chiedendo otto
risultati se ne ricevono otto anche quando solo quattro meritano di esserci: il recupero
denso fonde la query in un vettore solo e non può *pretendere* un'entità, quindi esauriti i
documenti giusti i posti successivi li prendono documenti genericamente simili.

## 3. Frontend Raycast — `raycast/`

Un'**estensione locale**, non uno script command. La ragione: uno script command stampa un
blocco di testo, e il requisito è *lista → Invio apre*, che richiede il componente `List`.

L'obiezione classica alle estensioni — «sono processi effimeri, inadatti a mantenere un
indice» — qui non si applica, proprio perché l'indice sta nel servizio e il frontend è solo
un client HTTP.

Non va pubblicata sullo store: si registra in locale con `npm run dev`.

## Il flusso, in una riga

```
file → estrazione (+OCR) → chunk → embedding (Ollama/BGE-M3) → SQLite
                                                                  ↓
query → embedding → coseno → miglior chunk per file → dedup → taglio → JSON → Raycast
```

## Cosa cambierei per primo

- **Elenchi fuori dall'indice**, o spezzati riga per riga anziché come prosa.
- **Riesecuzione su evento**: oggi l'indicizzazione parte all'avvio; agganciarla a FSEvents
  la renderebbe continua.
- **Documenti dentro gli archivi**: uno `.zip` oggi viene saltato e dichiarato. Indicizzarlo
  richiede un localizzatore (`archivio.zip → interno.pdf`) e una decisione su cosa faccia
  Invio, che non può aprire un file che sta dentro una busta.
