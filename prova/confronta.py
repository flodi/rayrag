"""Confronta due indici sulle stesse query: solo similarità densa.

Uso: python confronta.py
Serve a rispondere a una domanda sola: il modello inglese sarebbe bastato?
"""

import json
from pathlib import Path

import numpy as np

from cerca import QUERY_COLLAUDO, incorpora, per_file, pertinente

DATI = Path("~/.rayrag/prova").expanduser()
INDICI = [
    ("BGE-M3", DATI / "indice", "bge-m3"),
    ("all-MiniLM-L6-v2", DATI / "indice_minilm", "all-minilm"),
]


def carica(prefisso):
    m = np.load(f"{prefisso}.npy")
    meta = [json.loads(r) for r in open(f"{prefisso}.meta.jsonl", encoding="utf-8")]
    return m, meta


def main():
    tabella = []
    for caso in QUERY_COLLAUDO:
        riga = {"query": caso["q"]}
        for etichetta, prefisso, modello in INDICI:
            m, meta = carica(prefisso)
            v = incorpora(caso["q"], modello)
            classifica = per_file(m @ v, meta, quanti=len(meta))
            ranghi = [
                n for n, r in enumerate(classifica, 1) if pertinente(r[0], caso["attesi"])
            ]
            riga[etichetta] = {
                "primo": ranghi[0] if ranghi else None,
                "nei_primi_5": sum(1 for n in ranghi if n <= 5),
                "top3": [Path(r[0]).name for r in classifica[:3]],
            }
        tabella.append(riga)

    print(f"\n{'query':44s} {'BGE-M3':>12s} {'MiniLM':>12s}")
    print("-" * 70)
    for r in tabella:
        def cella(e):
            d = r[e]
            return f"{d['primo']}" if d["primo"] else "assente"
        print(f"{r['query'][:44]:44s} {cella('BGE-M3'):>12s} {cella('all-MiniLM-L6-v2'):>12s}")
    print("\n(numero = posizione del primo documento pertinente; più basso è meglio)")

    for r in tabella:
        print(f"\n### {r['query']}")
        for e, _, _ in INDICI:
            d = r[e]
            print(f"  {e:18s} primo pertinente: {d['primo'] or 'assente':>7}   "
                  f"nei primi 5: {d['nei_primi_5']}")
            for n, nome in enumerate(d["top3"], 1):
                print(f"       {n}. {nome}")


if __name__ == "__main__":
    main()
