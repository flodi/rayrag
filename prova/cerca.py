"""Interroga l'indice: densa, lessicale (BM25) e ibrida (RRF).

Uso: python cerca.py <prefisso> "query" [modello]
     python cerca.py <prefisso> --collaudo [modello]
"""

import json
import math
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "servizio"))
from servizio import incorpora  # noqa: E402

# Da adattare ai TUOI documenti: sono le query con cui si giudica se la ricerca
# funziona, e i frammenti di nome file che una buona risposta deve portare in alto.
# Vanno scelte in modo che le loro parole NON compaiano nei documenti bersaglio:
# è l'unico modo di distinguere la semantica dalla coincidenza lessicale.
QUERY_COLLAUDO = [
    {
        "q": "contratti nordvela",
        "attesi": ["nordvela", "nord vela"],
        "nota": "nome proprio; la variante staccata è quella che il lessicale non prende",
    },
    {
        "q": "documenti della mia automobile",
        "attesi": ["libretto", "assicurazione", "proprieta"],
        "nota": "'automobile' non compare: i documenti dicono veicolo, targa, marca",
    },
    {
        "q": "cosa devo pagare al fisco",
        "attesi": ["f24", "unico", "730", "iva"],
        "nota": "né 'fisco' né 'pagare' sono nel testo di un F24",
    },
    {
        "q": "permesso di soggiorno per lavoro",
        "attesi": ["residence permit", "permesso"],
        "nota": "prova il recupero crosslingua se il documento è in inglese",
    },
]


def parole(t):
    return re.findall(r"\w+", t.lower())


class BM25:
    """Lessicale classico: serve da termine di paragone e da metà dell'ibrido."""

    def __init__(self, documenti, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.doc = [Counter(parole(d)) for d in documenti]
        self.lunghezze = np.array([sum(c.values()) for c in self.doc], dtype=np.float32)
        self.media = float(self.lunghezze.mean())
        df = Counter()
        for c in self.doc:
            df.update(c.keys())
        n = len(self.doc)
        self.idf = {
            t: math.log(1 + (n - v + 0.5) / (v + 0.5)) for t, v in df.items()
        }

    def punteggi(self, query):
        s = np.zeros(len(self.doc), dtype=np.float32)
        for t in parole(query):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, c in enumerate(self.doc):
                f = c.get(t, 0)
                if f:
                    denom = f + self.k1 * (
                        1 - self.b + self.b * self.lunghezze[i] / self.media
                    )
                    s[i] += idf * f * (self.k1 + 1) / denom
        return s


def per_file(punteggi, meta, quanti=5):
    """Il chunk migliore rappresenta il suo file: l'utente cerca file, non chunk."""
    migliori = {}
    for i, p in enumerate(punteggi):
        path = meta[i]["path"]
        if path not in migliori or p > migliori[path][0]:
            migliori[path] = (float(p), i)
    # Punteggio nullo significa "nessuna corrispondenza": per BM25 non è un risultato
    # in fondo alla lista, è un risultato che non c'è.
    ordinati = sorted(migliori.items(), key=lambda kv: -kv[1][0])[:quanti]
    return [(path, p, i) for path, (p, i) in ordinati if p > 0]


def rrf(*classifiche, k=60):
    """Reciprocal Rank Fusion: fonde graduatorie senza dover scalare i punteggi."""
    punti = {}
    for classifica in classifiche:
        for rango, (path, _, idx) in enumerate(classifica):
            voce = punti.setdefault(path, [0.0, idx])
            voce[0] += 1 / (k + rango + 1)
    ordinati = sorted(punti.items(), key=lambda kv: -kv[1][0])
    return [(path, p, idx) for path, (p, idx) in ordinati]


def pertinente(path, attesi):
    nome = Path(path).name.lower()
    return any(a.lower() in nome for a in attesi)


def mostra(titolo, risultati, meta, attesi, quanti=5):
    if attesi:
        ranghi = [n for n, r in enumerate(risultati, 1) if pertinente(r[0], attesi)]
        primo = f"primo pertinente al posto {ranghi[0]}" if ranghi else "NESSUN pertinente"
        in_cima = sum(1 for n in ranghi if n <= quanti)
        esito = f"→ {primo}; {in_cima} nei primi {quanti}"
    else:
        esito = ""
    print(f"\n  {titolo}  {esito}")
    for n, (path, punteggio, idx) in enumerate(risultati[:quanti], 1):
        segno = "✓" if attesi and pertinente(path, attesi) else " "
        frammento = " ".join(meta[idx]["testo"].split())[:100]
        print(f"    {segno} {n}. [{punteggio:.3f}] {Path(path).name}")
        print(f"         …{frammento}…")


def main(prefisso, query, modello="bge-m3"):
    m = np.load(f"{prefisso}.npy")
    meta = [json.loads(r) for r in open(f"{prefisso}.meta.jsonl", encoding="utf-8")]
    bm25 = BM25([r["testo"] + " " + r["nome"] for r in meta])

    if query == "--collaudo":
        casi = QUERY_COLLAUDO
    else:
        casi = [{"q": query, "attesi": [], "nota": ""}]

    for caso in casi:
        q = caso["q"]
        t0 = time.time()
        v = incorpora(q)
        t_emb = time.time() - t0

        # Le classifiche vanno calcolate per intero: il rango del primo documento
        # pertinente è il numero che interessa, e può stare oltre i primi cinque.
        densa = per_file(m @ v, meta, quanti=len(meta))
        lessicale = per_file(bm25.punteggi(q), meta, quanti=len(meta))
        ibrida = rrf(densa, lessicale)
        t_tot = time.time() - t0

        print(f"\n{'=' * 74}\nQUERY: «{q}»   ({t_emb * 1000:.0f} ms embedding, "
              f"{t_tot * 1000:.0f} ms totale)")
        if caso["nota"]:
            print(f"  ({caso['nota']})")
        mostra("DENSA (semantica)", densa, meta, caso["attesi"])
        mostra("LESSICALE (BM25)", lessicale, meta, caso["attesi"])
        mostra("IBRIDA (RRF)", ibrida, meta, caso["attesi"])


if __name__ == "__main__":
    main(*sys.argv[1:])
