# Le misure

Ogni scelta di RayRAG viene da una misura su un archivio vero: 762 file fra contratti,
fatture, buste paga, cartelle fiscali e corrispondenza, in italiano. Le tabelle qui sotto
sono i numeri effettivi; i nomi di clienti, dipendenti e società sono stati sostituiti con
segnaposto, ma i risultati non sono ritoccati.

Il caso di prova ricorrente è la query `contratti nordvela`, dove **NordVela** sta per un
cliente reale il cui nome ha la stessa proprietà utile: è **una parola sola**, e in un
documento dell'archivio compare **staccata in due**. È la differenza fra trovare per
significato e trovare per corrispondenza di stringhe.

---

## 1. Il modello conta più di tutto il resto

Cinque query scelte perché le loro parole **non compaiono** nei documenti bersaglio: è
l'unico modo di distinguere la semantica dalla coincidenza lessicale. Il numero è la
posizione del primo documento pertinente.

| query | BGE-M3 | all-MiniLM-L6-v2 |
|---|---|---|
| contratti nordvela | **1** | 5 |
| documenti della mia automobile | **1** | 5 |
| cosa devo pagare al fisco | **1** | 17 |
| permesso di soggiorno per lavoro | **1** | 43 |
| crescita professionale di un collaboratore | **1** | 11 |

BGE-M3 è primo su tutte e cinque. Casi che vale la pena guardare:

- **`documenti della mia automobile`** → certificato di proprietà, libretto e assicurazione.
  La parola «automobile» non compare in nessuno dei tre.
- **`cosa devo pagare al fisco`** → i modelli F24. Un F24 non contiene né «fisco» né «pagare».
- **`permesso di soggiorno per lavoro`** → primo un documento **in inglese**. Il recupero
  crosslingua funziona senza fare nulla di speciale.
- **`contratti nordvela`** → i sei documenti del cliente ai primi sei posti, compreso quello
  che nel nome ha il termine **staccato in due parole**: nessuna corrispondenza lessicale è
  possibile lì.

Con `all-MiniLM-L6-v2` — modello addestrato essenzialmente su inglese, spesso proposto come
opzione «leggera» — la stessa query mette al primo posto **un contratto che non c'entra**:
il concetto «contratto» domina e l'entità cercata non influenza il ranking. È il fallimento
tipico della ricerca semantica in italiano fatta con un modello inglese.

## 2. La ricerca ibrida, fatta ingenuamente, peggiora

L'idea corrente è che combinare denso e lessicale (BM25) aiuti sui nomi propri. Misurata:

| query | densa | lessicale | ibrida (RRF) |
|---|---|---|---|
| contratti nordvela | 1 | 1 | 1 |
| documenti della mia automobile | 1 | 3 | 1 |
| cosa devo pagare al fisco | **1** | 22 | **13** |
| permesso di soggiorno per lavoro | **1** | assente | **43** |
| crescita professionale | 1 | 1 | 1 |

Sulle query concettuali la fusione RRF **affossa** risultati che il denso aveva al primo
posto, perché fa entrare il rumore del lessicale a pari dignità.

Un secondo tentativo, più mirato — bonus ai soli token **rari** della query, lasciando fuori
le parole comuni — è andato peggio:

| query | senza bonus | bonus 0,05 | bonus 0,10 |
|---|---|---|---|
| contratti nordvela | 4/8 | 4/8 | **6/8** |
| il bilancio della società | **4/8 (1°)** | 1/8 (7°) | 0/8 (10°) |
| permesso di soggiorno | **1/8 (1°)** | 1/8 (1°) | 1/8 (4°) |

Aiuta solo il nome proprio e rovina il resto. Il crollo sulla query del bilancio spiega il
meccanismo: **i bilanci sono scansioni**, e il loro testo OCR non contiene necessariamente
la parola «bilancio», mentre decine di altri documenti la nominano di sfuggita. La spinta
lessicale premia i documenti che *parlano di* una cosa sopra quelli che *sono* quella cosa.

**Conclusione: solo denso.** Due tentativi, due bocciature, stessa causa.

## 3. Un terzo dei PDF non ha testo

**12 PDF su 41** nel nucleo dell'archivio non hanno livello di testo: sono scansioni, e in
gran parte proprio i documenti fiscali e contabili. Per la ricerca **non esistono**, con
qualunque modello.

Erano **18 pagine in tutto**: il problema sembrava grosso e non lo era.

### Vision di macOS contro Tesseract italiano

| pagina | caratteri Vision | caratteri Tesseract | secondi Vision | secondi Tesseract |
|---|---|---|---|---|
| scansione da fotocopiatrice | 1974 | 2373 | **1,19** | 1,81 |
| bilancio | 4703 | 4377 | **1,04** | 3,85 |
| situazione contabile | 1748 | 1836 | **0,62** | 1,51 |

Quantità equivalente, Vision da 1,5 a 3,7 volte più veloce. Contate le parole di almeno
quattro lettere: **116 Vision, 118 Tesseract**. Ma Tesseract le sporca — `Èmichilizzazioni`
per «Immobilizzazioni», `pisponibilità` per «Disponibilità».

Le due differenze reali:

- **Tesseract conserva la disposizione**, quindi ogni importo resta accanto alla sua voce.
  Vision legge **per colonne**: le parole ci sono tutte, l'accostamento riga per riga no.
  Per la ricerca semantica è ininfluente; per leggere un importo lo sarebbe.
- **Vision non richiede installazioni.** Tesseract senza il pacchetto lingua italiana
  riconosce testo italiano col modello inglese e sbaglia in modo silenzioso e plausibile.

**Scelto Vision.** Le 18 pagine costano **19 secondi** in tutto.

### Serve davvero?

Stesso indice, prima e dopo l'aggiunta dei documenti riconosciuti:

| query | senza OCR | con OCR |
|---|---|---|
| il bilancio della mia società | buste paga ✗ | **i tre documenti contabili** ✓ |
| situazione contabile e patrimonio netto | buste paga ✗ | **situazione contabile e bilanci** ✓ |
| delega di pagamento F24 | comunicazioni generiche (0,61) | **i tre F24 scansionati** (0,66) ✓ |
| quanto devo di IVA | invariato | invariato |

Prima dell'OCR la domanda sul bilancio non aveva **nessun bilancio da trovare**, e il modello
ripiegava sulla cosa più vicina. L'ultima riga è altrettanto istruttiva: l'OCR non migliora
tutto, chiude un buco preciso.

## 4. Tempi e memoria

| misura | valore |
|---|---|
| query a modello caricato | **52-68 ms** |
| query a modello scaricato (incluso il caricamento) | **1,0-1,7 s** |
| ricerca a forza bruta su 5747 vettori | ~5 ms |
| memoria del servizio a riposo | **53 MB** |
| memoria del modello quando è caricato | 664 MB – 1,24 GB |
| indicizzazione | 1,6-3 chunk/s |

Conseguenze di progetto:

- **Il modello non va tenuto caldo.** Ricaricarlo costa un secondo: si lascia che Ollama lo
  scarichi dopo cinque minuti di inattività, e il servizio a riposo resta a 53 MB.
- **L'indice ANN non serve** a questa scala: 5 ms in forza bruta. SQLite basta, e in cambio
  dà transazioni, ripartenza e ispezionabilità.
- **Ricerca e indicizzazione si contendono Ollama**: con l'indicizzazione in corso le query
  passano da 150 ms a **5,5-6,4 s**. Per questo l'indicizzatore si ferma appena arriva una
  ricerca.

## 5. Indicizzare a batteria non funziona

Un giro da 4429 chunk ha richiesto **12968 secondi** invece dei ~26 minuti previsti.
`pmset -g log` mostra la causa: a batteria il Mac entra in *Maintenance Sleep* ogni 10-15
minuti e il lavoro procede solo durante i brevi risvegli — **0,1 chunk/s invece di 2,8**.

`caffeinate -i` **non basta**: tiene `PreventUserIdleSystemSleep`, che non copre quella
sospensione. RayRAG usa `caffeinate -dims` e avvisa quando sei a batteria.

Corollario: un indicizzatore che non sa riprendere è inservibile. Qui ogni file è una
transazione a sé.

## 6. Due difetti dell'archivio che l'indice deve gestire

**Duplicati — sul testo, non sui byte.** Un hash del contenuto binario ne trovava 5; uno del
**testo estratto** ne trova **26**. Lo stesso PDF risalvato ha byte diversi e testo identico:
per chi cerca è lo stesso documento. Il caso opposto conferma la regola — due file con lo
stesso nome ma testo diverso (9 e 7 chunk) sono due versioni, e vanno mostrate entrambe.

**Un file solo può occupare l'indice.** Una rubrica in xlsx produceva **1030 chunk su 1434**
— il 72% — e compariva come rumore in query che non la riguardavano. Gli elenchi non sono
prosa e non vanno spezzati come tale.

**Cartelle che non c'entrano.** Un backup completo di WordPress dentro l'archivio valeva
oltre 1200 file di codice e boilerplate. Da qui `.rayragignore`.

## 7. Il rumore in fondo alla classifica

Cercando `contratti nordvela` compariva al quinto posto un preventivo di un altro cliente,
che con NordVela non c'entra nulla (zero occorrenze del nome nel testo). Non superava i
documenti giusti: li seguiva.

Sui 762 file, i documenti sopra 0,50 erano **esattamente quattro: i quattro giusti**. La
mediana del corpus per quella query era 0,341. Mancava una soglia: chiedi 8 risultati,
ne ricevi 8, qualunque sia il punteggio.

Il rimedio adottato è il **taglio sullo stacco**: si scartano i file sotto
`0,90 × punteggio del primo`.

| query | senza taglio | α=0,90 | α=0,95 |
|---|---|---|---|
| contratti nordvela | 4 buoni su 8 | **4 su 4** | 3 su 3 (ne perde uno) |
| cosa devo pagare al fisco | 7/8 | 7/8 | 7/8 |
| documenti automobile | 3/8 | 3/8 | 0/8 |
| il bilancio della società | 4/8 | 4/8 | 0/6 |

A 0,90 nessuna query perde un risultato buono. A 0,95 sì: per questo il valore è 0,90 e non
un compromesso arbitrario. Si disattiva per singola ricerca con `&stacco=0`.

## 8. Prodotti già pronti, valutati

- **Un'app commerciale di ricerca documentale** (licenza acquistata): il suo modello leggero
  è `all-MiniLM-L6-v2`, con il fallimento della tabella 1; l'alternativa multilingue era un
  modello visuale che ha reso il Mac inutilizzabile per ore; e la schermata di ricerca
  esponeva solo modalità lessicali, quindi l'indice vettoriale calcolato non era nemmeno
  raggiungibile.
- **Un'app di ricerca semantica locale, open source e molto vicina a questo progetto**:
  indice persistente, nessun LLM, embedding multilingue, OCR. Provata sull'archivio reale,
  su `contratti nordvela` ha restituito i documenti che contengono «contratto» **oppure** il
  nome del cliente. In più indicizza per impostazione predefinita tutto ciò che trova —
  compreso il backup WordPress di cui sopra.
- **Un'app con backend FastAPI**, gratuita: calcola gli embedding con un servizio cloud, cioè
  **manda il testo di ogni documento a un fornitore esterno**. Su contratti, buste paga e
  cartelle fiscali chiude il discorso da sola.
- **Assistenti AI con RAG integrata**: la loro ricerca serve a dare contesto a un modello
  generativo, non a restituire file. Categoria diversa.

## Rifare le misure

Gli script sono in [`prova/`](../prova). Servono un archivio di documenti e Ollama con
`bge-m3`. Il banco di prova va adattato ai tuoi documenti: le query di collaudo e i file
attesi stanno in cima a `prova/cerca.py`.


## 9. Cercare un nome proprio: il limite del denso, e la regola che lo chiude

Cercando `overace` — un progetto citato **una sola volta** in tutto l'archivio, in un
inciso dentro un dossier legale — la ricerca restituiva documenti senza alcun rapporto.
Il documento giusto stava al **posto 45 su 652**, con 0,387 contro lo 0,462 del primo.

È il recupero denso nella sua forma più sfavorevole: una parola rara **da sola**, senza
concetto intorno. Il vettore non somiglia a niente, e il chunk che la contiene parla
d'altro. Quando non c'è nulla da somigliare il denso ordina lo stesso tutti i file, e in
cima finisce il meno dissimile — cioè rumore.

### Perché non basta premiare i token rari

Primo tentativo: portare in cima i file che contengono un token presente in meno dell'1%
dei file. Misurato:

| query | denso | con il ripescaggio |
|---|---|---|
| overace | 45 | **1** |
| cosa devo pagare al fisco | 1 | **2** |
| documenti della mia automobile | 1 | **4** |
| permesso di soggiorno per lavoro | 1 | **3** |

Aiuta il nome proprio e peggiora tre query su sette. Il motivo: in *questo* archivio
«fisco» compare in un file, «automobile» in tre, «soggiorno» in due. Sono parole italiane
comuni che qui sono rare, e trattarle da identificatori ripesca file che non c'entrano.
È la stessa patologia di agosto, innescata in modo diverso: **raro ≠ nome proprio**.

### La regola che funziona

Il ripescaggio scatta solo se **ogni** termine della query è raro — cioè se l'utente ha
scritto un identificatore e non una domanda — e al più tre termini. In quel caso si
risponde con i soli file che contengono il termine, perché la coda densa sarebbe rumore.

| query | denso | regola stretta | scatta? |
|---|---|---|---|
| overace | 45 | **1** | sì |
| bomi | 116 | **3** | sì |
| contratti profondoblu | 1 | 1 | no |
| cosa devo pagare al fisco | 1 | 1 | no |
| documenti della mia automobile | 1 | 1 | no |
| il bilancio della mia società | 1 | 1 | no |
| permesso di soggiorno per lavoro | 1 | 1 | no |
| crescita professionale | 2 | 2 | no |

Nessuna query concettuale cambia di una posizione. Il controllo si fa al momento con una
scansione del testo invece di tenere un indice lessicale in memoria: su questa scala costa
pochi millisecondi e il servizio resta a 53 MB.

Nota su cosa questo **non** smentisce: resta vero che fondere denso e lessicale in modo
indiscriminato peggiora le query concettuali, misurato due volte. Quello che le due misure
di agosto non coprivano era la query fatta di solo nome proprio — un regime diverso, dove
il denso non ha nulla su cui lavorare.
