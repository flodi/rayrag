"""Servizio di ricerca RayRAG: HTTP su localhost, indice in memoria.

    python servizio.py [--indice ~/.rayrag/prova/indice_v2] [--porta 8787]

    GET /cerca?q=contratti+nordvela&n=10   →  JSON con i file più pertinenti
    GET /salute                               →  stato dell'indice

Nessuna dipendenza oltre numpy: il servizio deve restare piccolo in memoria.
Il modello NON viene tenuto caldo di proposito — Ollama lo scarica dopo 5 minuti e
ricaricarlo costa ~1 s, dentro il requisito dei due. Vedi docs/MISURE.md.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "indicizzatore"))

OLLAMA = "http://localhost:11434/api/embed"
MODELLO = "bge-m3"
# Taglio sullo stacco: si scartano i file troppo distanti dal migliore.
# Misurato il 23 agosto sulle sei query di collaudo (prova/esperimento.py): a 0.90
# «contratti nordvela» passa da 4 buoni su 8 a 4 su 4, e nessuna altra query
# perde un risultato. A 0.95 se ne perdeva uno pertinente al quarto posto.
STACCO = 0.90
# L'indicizzatore guarda questo file per farsi da parte mentre si cerca: condividono Ollama.
SEGNALE_QUERY = Path.home() / ".rayrag/ultima_query"


class Indice:
    """Matrice normalizzata più metadati, ricaricata se i file cambiano."""

    def __init__(self, prefisso: Path):
        self.prefisso = prefisso
        self.m = None
        self.meta = []
        self.firma = None
        self.carica()

    def _firma(self):
        f = self.prefisso.with_suffix(".npy")
        return f.stat().st_mtime if f.exists() else None

    def carica(self):
        f = self.prefisso.with_suffix(".npy")
        if not f.exists():
            raise SystemExit(f"indice assente: {f}")
        self.m = np.load(f)
        with open(f"{self.prefisso}.meta.jsonl", encoding="utf-8") as fh:
            self.meta = [json.loads(r) for r in fh]
        self.firma = self._firma()
        if len(self.meta) != self.m.shape[0]:
            raise SystemExit("indice e metadati non allineati")

    def aggiorna_se_serve(self):
        if self._firma() != self.firma:
            self.carica()


class Sorgente:
    """Indice prodotto dall'indicizzatore incrementale (SQLite)."""

    def __init__(self, percorso: Path):
        from deposito import Deposito

        self.percorso = percorso
        self.prefisso = percorso   # stesso nome che espone Indice: /salute non deve sapere quale sorgente è
        self.dep = Deposito(percorso)
        self.firma = None
        self.carica()

    def _firma(self):
        """In modalità WAL le scritture recenti stanno nel file -wal finché SQLite
        non le consolida: guardare solo il file principale le perde per un po'."""
        firma = []
        for f in (self.percorso, self.percorso.with_name(self.percorso.name + "-wal")):
            try:
                s = f.stat()
                firma.append((s.st_mtime, s.st_size))
            except OSError:
                firma.append(None)
        return tuple(firma)

    def carica(self):
        self.m, self.meta = self.dep.carica()
        self.firma = self._firma()

    def aggiorna_se_serve(self):
        if self._firma() != self.firma:
            self.carica()


def incorpora(testo: str, modello: str = MODELLO) -> np.ndarray:
    """Il parametro serve al banco di prova, che confronta modelli diversi."""
    corpo = json.dumps({"model": modello, "input": [testo]}).encode()
    req = urllib.request.Request(
        OLLAMA, data=corpo, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        v = np.array(json.load(r)["embeddings"][0], dtype=np.float32)
    return v / np.linalg.norm(v)


def frammento(testo: str, limite: int = 180) -> str:
    t = " ".join(testo.split())
    return t[:limite] + ("…" if len(t) > limite else "")


def cerca(indice, q: str, quanti: int, stacco: float = STACCO):
    punteggi = indice.m @ incorpora(q)
    # Un file vale quanto il suo chunk migliore: si cercano file, non frammenti.
    migliori = {}
    for i, p in enumerate(punteggi):
        path = indice.meta[i]["path"]
        if path not in migliori or p > migliori[path][0]:
            migliori[path] = (float(p), i)
    ordinati = sorted(migliori.items(), key=lambda kv: -kv[1][0])
    if ordinati:
        limite = ordinati[0][1][0] * stacco
        ordinati = [x for x in ordinati if x[1][0] >= limite]

    # Copie identiche dello stesso documento occupano posti diversi in classifica
    # per nessun motivo: si tiene la prima e si dice quante altre ce ne sono.
    visti, risultati = {}, []
    for path, (p, i) in ordinati:
        chiave = indice.meta[i].get("impronta") or path
        if chiave in visti:
            visti[chiave]["copie"] += 1
            continue
        voce = {
            "path": path,
            "nome": Path(path).name,
            "cartella": str(Path(path).parent),
            "punteggio": round(p, 4),
            "frammento": frammento(indice.meta[i]["testo"]),
            "copie": 0,
        }
        visti[chiave] = voce
        risultati.append(voce)
        if len(risultati) >= quanti:
            break
    return risultati


RADICE = Path(__file__).resolve().parent
PANNELLO = RADICE / "pannello.html"


def stato_completo(indice) -> dict:
    """Tutto ciò che il pannello mostra, in una sola risposta."""
    import configurazione

    dep = getattr(indice, "dep", None)
    base = {"chunk": int(indice.m.shape[0]),
            "file": len({r["path"] for r in indice.meta}),
            "configurazione": configurazione.carica()}
    if dep is None:
        return base | {"solo_lettura": True}
    return base | {
        "conteggi": dep.conteggi(),
        "duplicati": dep.duplicati(),
        "per_estensione": dep.per_estensione(),
        "piu_grandi": dep.piu_grandi(),
        "indicizzatore": dep.stato(),
    }


def crea_handler(indice: Indice):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _rispondi(self, codice, payload):
            corpo = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(codice)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            par = urllib.parse.parse_qs(url.query)

            if url.path == "/salute":
                # Senza ricaricare, /salute descriveva l'indice com'era all'avvio del
                # servizio: a indicizzazione in corso diceva 0 chunk mentre la ricerca,
                # che ricarica, ne vedeva centinaia.
                indice.aggiorna_se_serve()
                return self._rispondi(200, {
                    "stato": "attivo",
                    "chunk": int(indice.m.shape[0]),
                    "file": len({r["path"] for r in indice.meta}),
                    "indice": str(indice.prefisso),
                })

            if url.path in ("/", "/pannello"):
                try:
                    corpo = PANNELLO.read_bytes()
                except OSError:
                    return self._rispondi(500, {"errore": "pannello.html mancante"})
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
                return

            if url.path == "/api/stato":
                indice.aggiorna_se_serve()
                return self._rispondi(200, stato_completo(indice))

            if url.path != "/cerca":
                return self._rispondi(404, {"errore": "usa /cerca?q=…"})

            q = (par.get("q") or [""])[0].strip()
            if not q:
                return self._rispondi(400, {"errore": "parametro q mancante"})
            try:
                quanti = min(int((par.get("n") or ["10"])[0]), 50)
            except ValueError:
                quanti = 10
            try:
                # stacco=0 disattiva il taglio, per diagnosticare
                stacco = float((par.get("stacco") or [STACCO])[0])
            except ValueError:
                stacco = STACCO

            indice.aggiorna_se_serve()
            try:
                SEGNALE_QUERY.parent.mkdir(parents=True, exist_ok=True)
                SEGNALE_QUERY.touch()
            except OSError:
                pass  # il segnale è un'ottimizzazione, non deve far fallire la ricerca
            try:
                risultati = cerca(indice, q, quanti, stacco)
            except urllib.error.URLError as e:
                # Ollama spento: va detto al frontend, non nascosto in una lista vuota.
                return self._rispondi(503, {"errore": f"Ollama non raggiungibile: {e.reason}"})
            self._rispondi(200, {"query": q, "risultati": risultati})

        def _mittente_locale(self) -> bool:
            """Una pagina web qualsiasi può chiamare localhost: si accettano solo
            richieste senza Origin (curl) o con Origin sul servizio stesso."""
            o = self.headers.get("Origin")
            if o is None:
                return True
            return o.rstrip("/") in (f"http://127.0.0.1:{self.server.server_address[1]}",
                                     f"http://localhost:{self.server.server_address[1]}")

        def do_POST(self):
            import configurazione

            if not self._mittente_locale():
                return self._rispondi(403, {"errore": "origine non consentita"})
            url = urllib.parse.urlparse(self.path)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                dati = json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._rispondi(400, {"errore": "corpo non valido"})

            if url.path == "/api/config":
                if not isinstance(dati, dict):
                    return self._rispondi(400, {"errore": "atteso un oggetto"})
                configurazione.salva(dati)
                return self._rispondi(200, {"salvato": True,
                                            "configurazione": configurazione.carica()})

            if url.path == "/api/indicizza":
                c = configurazione.carica()
                script = RADICE.parent / "indicizzatore/indicizza.py"
                py = RADICE.parent / ".venv/bin/python"
                if not script.exists() or not py.exists():
                    return self._rispondi(500, {"errore": "indicizzatore non trovato"})
                # Staccato dal servizio: l'indicizzazione dura minuti, la richiesta no.
                subprocess.Popen(
                    [str(py), str(script), *c["radici"],
                     "--deposito", str(indice.percorso)],
                    stdout=open(Path.home() / ".rayrag/indicizzazione.log", "ab"),
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                return self._rispondi(200, {"avviato": True})

            return self._rispondi(404, {"errore": "rotta sconosciuta"})

        def log_message(self, *a):  # niente rumore su stderr a ogni richiesta
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--indice", help="indice della prova (prefisso .npy/.meta.jsonl)")
    ap.add_argument("--deposito", default="~/.rayrag/indice.sqlite",
                    help="indice dell'indicizzatore incrementale")
    ap.add_argument("--porta", type=int, default=8787)
    a = ap.parse_args()

    if a.indice:
        indice = Indice(Path(a.indice).expanduser())
    else:
        indice = Sorgente(Path(a.deposito).expanduser())
    srv = ThreadingHTTPServer(("127.0.0.1", a.porta), crea_handler(indice))
    print(f"RayRAG in ascolto su http://127.0.0.1:{a.porta}  "
          f"({indice.m.shape[0]} chunk, {len({r['path'] for r in indice.meta})} file)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
