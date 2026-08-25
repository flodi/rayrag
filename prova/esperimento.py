"""Misura due interventi sulla classifica: taglio sullo stacco e spinta lessicale mirata.

Domanda a cui deve rispondere: togliere la coda di rumore (documenti solo vagamente
simili, doppioni) senza
perdere risultati buoni sulle altre query.

Verità di riferimento: frammenti di nome file. È approssimata — un file pertinente
con un nome che non contiene la parola attesa conta come sbagliato — ma è la stessa
usata da tutte le misure precedenti, quindi i confronti restano validi.
"""

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "servizio"))
from servizio import incorpora  # noqa: E402

D = Path.home() / ".rayrag/prova"

# Stessi casi di cerca.py: da adattare ai propri documenti.
CASI = [
    ("contratti nordvela", ["nordvela", "nord vela"]),
    ("cosa devo pagare al fisco", ["f24", "unico", "730", "iva"]),
    ("documenti della mia automobile", ["libretto", "assicurazione", "proprieta"]),
    ("permesso di soggiorno per lavoro", ["residence permit", "permesso"]),
]


def parole(t):
    return re.findall(r"\w+", t.lower())


def pertinente(path, attesi):
    n = Path(path).name.lower()
    return any(a in n for a in attesi)


def carica():
    m = np.load(D / "indice_totale.npy")
    meta = [json.loads(r) for r in open(D / "indice_totale.meta.jsonl", encoding="utf-8")]
    return m, meta


def indice_lessicale(meta):
    """token → insieme dei file che lo contengono, più l'idf."""
    per_file = {}
    for r in meta:
        per_file.setdefault(r["path"], []).append(r["testo"])
    documenti = {p: set(parole(" ".join(t) + " " + Path(p).name)) for p, t in per_file.items()}
    df = Counter()
    for s in documenti.values():
        df.update(s)
    n = len(documenti)
    idf = {t: math.log(n / v) for t, v in df.items()}
    return documenti, idf, n


def classifica_densa(m, meta, v):
    punteggi = m @ v
    best = {}
    for i, p in enumerate(punteggi):
        path = meta[i]["path"]
        if path not in best or p > best[path][0]:
            best[path] = (float(p), i)
    return sorted(best.items(), key=lambda kv: -kv[1][0])


def con_spinta(ordinati, query, documenti, idf, n, beta, soglia_raro=0.05):
    """Bonus ai file che contengono davvero i token RARI della query.

    Solo i rari: 'contratti' compare ovunque e spingerebbe qualunque contratto,
    che è esattamente l'errore da evitare. 'nordvela' invece identifica.
    """
    rari = [t for t in parole(query)
            if t in idf and math.exp(-idf[t]) <= soglia_raro]
    if not rari:
        return ordinati, rari
    max_idf = max(idf[t] for t in rari)
    nuovo = []
    for path, (p, i) in ordinati:
        presenti = sum(idf[t] for t in rari if t in documenti.get(path, ()))
        nuovo.append((path, (p + beta * presenti / max_idf, i)))
    return sorted(nuovo, key=lambda kv: -kv[1][0]), rari


def taglia(ordinati, alfa):
    if not ordinati:
        return ordinati
    limite = ordinati[0][1][0] * alfa
    return [x for x in ordinati if x[1][0] >= limite]


def valuta(ordinati, attesi, quanti=8):
    primi = ordinati[:quanti]
    ranghi = [i for i, (path, _) in enumerate(primi, 1) if pertinente(path, attesi)]
    tutti = [i for i, (path, _) in enumerate(ordinati, 1) if pertinente(path, attesi)]
    return {
        "primo": tutti[0] if tutti else None,
        "buoni": len(ranghi),
        "restituiti": len(primi),
        "rumore": len(primi) - len(ranghi),
    }


def main():
    m, meta = carica()
    documenti, idf, n = indice_lessicale(meta)
    print(f"corpus: {len(documenti)} file, {len(meta)} chunk\n")

    ALFA = [1.0, 0.95, 0.90, 0.85]
    BETA = [0.0, 0.05, 0.10]

    intestazione = f"{'query':34s} " + " ".join(
        f"β{b:.2f}".ljust(7) for b in BETA)
    for alfa in ALFA:
        print(f"=== taglio α={alfa:.2f} " + ("(nessun taglio)" if alfa == 1.0 else "") + " ===")
        print(intestazione + "   (buoni/restituiti, primo pertinente)")
        for query, attesi in CASI:
            v = incorpora(query)
            base = classifica_densa(m, meta, v)
            celle = []
            for beta in BETA:
                ord2, rari = con_spinta(base, query, documenti, idf, n, beta)
                ord3 = taglia(ord2, alfa) if alfa < 1.0 else ord2
                e = valuta(ord3, attesi)
                celle.append(f"{e['buoni']}/{e['restituiti']}·{e['primo'] or '-'}".ljust(7))
            print(f"{query[:34]:34s} " + " ".join(celle))
        print()


if __name__ == "__main__":
    main()
