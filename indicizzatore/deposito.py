"""Deposito dell'indice: SQLite per i metadati, vettori come BLOB.

Perché non LanceDB, come diceva docs/ARCHITETTURA.md: la ricerca a forza bruta impiega
5 ms su 5747 vettori (vedi docs/MISURE.md), quindi l'indice ANN non serve a
questa scala. Quello che serve davvero — sapere cosa è già stato indicizzato,
cancellare i file spariti, riprendere dopo un'interruzione — è esattamente ciò che
una tabella SQLite fa bene e senza dipendenze. Se un giorno i chunk diventassero
centinaia di migliaia, il punto in cui cambiare è questo file soltanto.
"""

import hashlib
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS file (
    percorso    TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    dimensione  INTEGER NOT NULL,
    impronta    TEXT NOT NULL,          -- sha256 dei byte: dice se il file è cambiato
    n_chunk     INTEGER NOT NULL DEFAULT 0,
    ocr         INTEGER NOT NULL DEFAULT 0,
    visto_a     REAL NOT NULL           -- ultima volta che il file è stato trovato su disco
);
CREATE INDEX IF NOT EXISTS idx_file_impronta ON file(impronta);

CREATE TABLE IF NOT EXISTS chunk (
    id        INTEGER PRIMARY KEY,
    percorso  TEXT NOT NULL REFERENCES file(percorso) ON DELETE CASCADE,
    n         INTEGER NOT NULL,
    testo     TEXT NOT NULL,
    vettore   BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunk_percorso ON chunk(percorso);

CREATE TABLE IF NOT EXISTS stato (chiave TEXT PRIMARY KEY, valore TEXT NOT NULL);
"""


class Deposito:
    def __init__(self, percorso: Path):
        percorso = Path(percorso).expanduser()
        percorso.parent.mkdir(parents=True, exist_ok=True)
        # Il servizio HTTP è multi-thread: senza check_same_thread=False SQLite
        # rifiuta la connessione appena una richiesta arriva su un thread diverso
        # da quello che l'ha aperta. Il lucchetto serializza gli accessi dentro al
        # processo; fra processi diversi (servizio e indicizzatore) ci pensa il WAL.
        self._lucchetto = threading.RLock()
        self.db = sqlite3.connect(percorso, isolation_level=None, timeout=30,
                                  check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        colonne = {r[1] for r in self.db.execute("PRAGMA table_info(file)")}
        if "impronta_testo" not in colonne:  # deposito creato prima del 24 agosto
            self.db.execute(
                "ALTER TABLE file ADD COLUMN impronta_testo TEXT NOT NULL DEFAULT ''")
        if "versione" not in colonne:  # deposito creato prima del 15 settembre
            # I file già indicizzati valgono come versione "1": altrimenti l'aggiunta
            # della colonna farebbe rifare l'intero indice, OCR ed embedding compresi.
            self.db.execute(
                "ALTER TABLE file ADD COLUMN versione TEXT NOT NULL DEFAULT '1'")
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_file_impronta_testo ON file(impronta_testo)")

    # --- interrogazioni usate dall'indicizzatore -------------------------------

    def da_rifare(self, percorso: str, mtime: float, dimensione: int,
                  versione: str = "1") -> bool:
        """Un file va rifatto se non c'è, o se mtime/dimensione non combaciano.

        L'impronta non si calcola qui: leggere ogni file per intero a ogni giro
        costerebbe più di quel che fa risparmiare.
        """
        with self._lucchetto:
            r = self.db.execute(
                "SELECT mtime, dimensione, versione FROM file WHERE percorso=?", (percorso,)
            ).fetchone()
        if r is None:
            return True
        return abs(r[0] - mtime) > 1e-6 or r[1] != dimensione or r[2] != versione

    def gemello(self, impronta_testo: str, escluso: str) -> str | None:
        """Un altro file già indicizzato con lo STESSO TESTO, se esiste.

        Sul testo e non sui byte: nel corpus di prova lo stesso PDF esisteva in due
        cartelle con byte diversi (metadati PDF) e testo identico. Per la ricerca
        è lo stesso documento; per un hash dei byte sono due file distinti.
        """
        with self._lucchetto:
            r = self.db.execute(
                "SELECT percorso FROM file WHERE impronta_testo=? AND impronta_testo<>''"
                " AND percorso<>? AND n_chunk>0 LIMIT 1",
                (impronta_testo, escluso),
            ).fetchone()
        return r[0] if r else None

    def segna_visto(self, percorso: str) -> None:
        with self._lucchetto:
            self.db.execute(
                "UPDATE file SET visto_a=? WHERE percorso=?", (time.time(), percorso))

    # --- scrittura ------------------------------------------------------------

    def salva(self, percorso, mtime, dimensione, impronta, chunk, vettori,
              ocr=False, impronta_testo="", versione="1"):
        """Sostituisce in blocco i chunk di un file. Transazione unica: o tutto o niente."""
        m = np.asarray(vettori, dtype=np.float32)
        if m.size:
            m /= np.linalg.norm(m, axis=1, keepdims=True)
        with self._lucchetto, self.db:
            self.db.execute("BEGIN")
            self.db.execute("DELETE FROM chunk WHERE percorso=?", (percorso,))
            self.db.execute(
                "INSERT INTO file(percorso, mtime, dimensione, impronta, impronta_testo,"
                " n_chunk, ocr, visto_a, versione) VALUES(?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(percorso) DO UPDATE SET"
                " mtime=excluded.mtime, dimensione=excluded.dimensione,"
                " impronta=excluded.impronta, impronta_testo=excluded.impronta_testo,"
                " n_chunk=excluded.n_chunk, ocr=excluded.ocr, visto_a=excluded.visto_a,"
                " versione=excluded.versione",
                (percorso, mtime, dimensione, impronta, impronta_testo,
                 len(chunk), int(ocr), time.time(), versione),
            )
            self.db.executemany(
                "INSERT INTO chunk(percorso, n, testo, vettore) VALUES(?,?,?,?)",
                [(percorso, i, t, m[i].tobytes()) for i, t in enumerate(chunk)],
            )

    def rimuovi_spariti(self, visti: set[str]) -> list[str]:
        """Cancella dall'indice i file che non esistono più su disco.

        È il pezzo che è mancato quando i documenti sono usciti da iCloud e
        l'indice ha continuato a puntare a percorsi morti.
        """
        with self._lucchetto:
            tutti = {r[0] for r in self.db.execute("SELECT percorso FROM file")}
            spariti = sorted(tutti - visti)
            with self.db:
                self.db.executemany(
                    "DELETE FROM file WHERE percorso=?", [(p,) for p in spariti])
        return spariti

    def riempi_impronte_testo(self) -> int:
        """Calcola l'impronta del testo per i file indicizzati prima che esistesse.

        Non richiede di reincorporare nulla: il testo è già nel deposito.
        """
        with self._lucchetto:
            da_fare = [r[0] for r in self.db.execute(
                "SELECT percorso FROM file WHERE impronta_testo='' AND n_chunk>0")]
            for percorso in da_fare:
                testo = "".join(r[0] for r in self.db.execute(
                    "SELECT testo FROM chunk WHERE percorso=? ORDER BY n", (percorso,)))
                self.db.execute("UPDATE file SET impronta_testo=? WHERE percorso=?",
                                (hashlib.sha256(testo.encode()).hexdigest(), percorso))
        return len(da_fare)

    # --- lettura per il servizio ----------------------------------------------

    def carica(self):
        """Restituisce (matrice normalizzata, metadati allineati)."""
        with self._lucchetto:
            righe = self.db.execute(
                "SELECT c.percorso, c.n, c.testo, c.vettore,"
                " CASE WHEN f.impronta_testo<>'' THEN f.impronta_testo ELSE f.impronta END"
                " FROM chunk c JOIN file f ON f.percorso=c.percorso ORDER BY c.id"
            ).fetchall()
        if not righe:
            return np.zeros((0, 1024), dtype=np.float32), []
        m = np.frombuffer(b"".join(r[3] for r in righe), dtype=np.float32)
        m = m.reshape(len(righe), -1)
        meta = [
            {"path": r[0], "chunk": r[1], "testo": r[2], "impronta": r[4]} for r in righe
        ]
        return m, meta

    def conteggi(self):
        with self._lucchetto:
            f = self.db.execute("SELECT COUNT(*) FROM file").fetchone()[0]
            c = self.db.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
            o = self.db.execute("SELECT COUNT(*) FROM file WHERE ocr=1").fetchone()[0]
        return {"file": f, "chunk": c, "da_ocr": o}

    # --- stato per il pannello di gestione -------------------------------------

    def imposta_stato(self, **valori) -> None:
        with self._lucchetto:
            self.db.executemany(
                "INSERT INTO stato(chiave, valore) VALUES(?,?)"
                " ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore",
                [(k, str(v)) for k, v in valori.items()],
            )

    def stato(self) -> dict:
        with self._lucchetto:
            return {k: v for k, v in self.db.execute("SELECT chiave, valore FROM stato")}

    def per_estensione(self):
        """Quanti file e chunk per estensione: è la vista che serve al pannello
        per decidere cosa vale la pena indicizzare e cosa no."""
        with self._lucchetto:
            righe = self.db.execute("SELECT percorso, n_chunk, ocr FROM file").fetchall()
        file_per, chunk_per, ocr_per = Counter(), Counter(), Counter()
        for percorso, n, ocr in righe:
            e = ("." + percorso.rsplit(".", 1)[-1].lower()) if "." in percorso else "(nessuna)"
            file_per[e] += 1
            chunk_per[e] += n
            ocr_per[e] += 1 if ocr else 0
        return sorted(
            ({"estensione": e, "file": c, "chunk": chunk_per[e], "ocr": ocr_per[e]}
             for e, c in file_per.items()),
            key=lambda x: -x["file"],
        )

    def piu_grandi(self, quanti=8):
        with self._lucchetto:
            righe = self.db.execute(
                "SELECT percorso, n_chunk FROM file ORDER BY n_chunk DESC LIMIT ?",
                (quanti,),
            ).fetchall()
        return [{"percorso": p, "chunk": n} for p, n in righe]

    def duplicati(self) -> int:
        with self._lucchetto:
            return self.db.execute(
                "SELECT COUNT(*) FROM (SELECT impronta_testo FROM file"
                " WHERE n_chunk>0 AND impronta_testo<>'' GROUP BY impronta_testo"
                " HAVING COUNT(*)>1)"
            ).fetchone()[0]
