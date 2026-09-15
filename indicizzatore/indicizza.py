"""Indicizzatore incrementale di RayRAG.

    python indicizza.py ~/Documents ~/Scrivania/Archivio

Fa quattro cose che gli script della prova non facevano:
  1. riprende — ogni file è una transazione, un'interruzione non butta via il resto;
  2. salta ciò che non è cambiato (mtime + dimensione);
  3. toglie dall'indice i file spariti dal disco;
  4. non reincorpora i duplicati: stesso contenuto, un solo calcolo.

E due precauzioni misurate sul campo:
  - tiene sveglia la macchina, altrimenti il ritmo crolla da 2,8 a 0,1 chunk/s;
  - si ferma mentre l'utente cerca, perché ricerca e indicizzazione si contendono Ollama.
"""

import argparse
import fnmatch
import hashlib
from collections import Counter
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import configurazione
from deposito import Deposito
from estrattore import ESTENSIONI, IMMAGINI, estrai, versione

OLLAMA = "http://localhost:11434/api/embed"
MODELLO = "bge-m3"
LOTTO = 8
SEGNALE_QUERY = Path.home() / ".rayrag/ultima_query"
PAUSA_DOPO_QUERY = 5.0  # secondi di silenzio prima di riprendere a indicizzare

fermare = False


def _ferma(*_):
    global fermare
    fermare = True
    print("\ninterruzione richiesta: chiudo dopo il file in corso…", flush=True)


class Esclusioni:
    def __init__(self, percorso: Path):
        self.regole = []
        if percorso.exists():
            for riga in percorso.read_text(encoding="utf-8").splitlines():
                riga = riga.strip()
                if riga and not riga.startswith("#"):
                    self.regole.append(riga)

    def esclusa_cartella(self, nome: str) -> bool:
        for r in self.regole:
            if r.endswith("/") and fnmatch.fnmatch(nome, r[:-1]):
                return True
        return False

    def escluso_file(self, nome: str) -> bool:
        for r in self.regole:
            if not r.endswith("/") and fnmatch.fnmatch(nome, r):
                return True
        return False


def impronta(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blocco in iter(lambda: f.read(1 << 20), b""):
            h.update(blocco)
    return h.hexdigest()


def incorpora(testi: list[str]) -> list[list[float]]:
    corpo = json.dumps({"model": MODELLO, "input": testi}).encode()
    req = urllib.request.Request(
        OLLAMA, data=corpo, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["embeddings"]


def attendi_se_si_cerca() -> None:
    """Le query hanno la precedenza: condividono Ollama con noi."""
    while SEGNALE_QUERY.exists():
        eta = time.time() - SEGNALE_QUERY.stat().st_mtime
        if eta >= PAUSA_DOPO_QUERY:
            return
        time.sleep(PAUSA_DOPO_QUERY - eta)


def tieni_sveglio() -> subprocess.Popen | None:
    """caffeinate muore con noi (-w sul nostro pid).

    Attenzione: a batteria non basta. Misurato il 20 agosto: con `caffeinate -i` il
    Mac entrava comunque in Maintenance Sleep e il ritmo restava a 0,1 chunk/s.
    """
    try:
        return subprocess.Popen(
            ["caffeinate", "-dims", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return None


def attendi_ollama(secondi: int = 180) -> bool:
    """All'avvio del Mac l'indicizzatore può partire prima di Ollama.

    Senza questa attesa ogni file fallirebbe con un errore di connessione e il
    giro si concluderebbe "riuscito" con zero lavoro fatto.
    """
    scadenza = time.time() + secondi
    while time.time() < scadenza:
        try:
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
            return True
        except Exception:
            time.sleep(5)
    return False


def a_batteria() -> bool:
    try:
        r = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True)
        return "Battery Power" in r.stdout
    except Exception:
        return False


# Firma di un documento Office (.docx, .xlsx, .pptx) aperto come cartella.
FIRMA_OFFICE = "[Content_Types].xml"


def candidati(radici, escl: Esclusioni, saltati=None, attive=None, pacchetti=None):
    """`saltati` raccoglie le estensioni non gestite: vanno dette, non nascoste.

    Uno zip che sparisce dall'indice senza una riga di resoconto è indistinguibile
    da un file che non esiste.
    """
    for radice in radici:
        radice = Path(radice).expanduser()
        for cartella, sottocartelle, file in os.walk(radice):
            if FIRMA_OFFICE in file:
                # Un PowerPoint scompattato ha prodotto due slide XML da 5000 chunk,
                # il 52% dell'indice, fatte di solo markup. Il documento vero, se c'è,
                # è il .pptx: la sua carcassa non va indicizzata. Criterio sul contenuto
                # e non sul nome, perché "ppt/" o "word/" possono essere cartelle vere.
                sottocartelle[:] = []
                if pacchetti is not None:
                    pacchetti.append(cartella)
                continue
            sottocartelle[:] = [
                d for d in sottocartelle
                if not d.startswith(".") and not escl.esclusa_cartella(d)
            ]
            for nome in file:
                if nome.startswith(".") or escl.escluso_file(nome):
                    continue
                p = Path(cartella) / nome
                if p.suffix.lower() in (attive if attive is not None else ESTENSIONI):
                    yield p
                elif saltati is not None:
                    saltati[p.suffix.lower() or "(senza estensione)"] += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("radici", nargs="*")
    ap.add_argument("--deposito", default="~/.rayrag/indice.sqlite")
    ap.add_argument("--vocr", default=str(Path(__file__).parent / "vocr"))
    ap.add_argument("--esclusioni", default=str(Path(__file__).parent / ".rayragignore"))
    ap.add_argument("--attendi-ollama", type=int, default=0,
                    help="secondi di attesa perché Ollama risponda (per l'avvio automatico)")
    a = ap.parse_args()

    conf = configurazione.carica()
    radici = a.radici or conf["radici"]
    # L'estrattore sa leggere più formati di quanti se ne vogliano indicizzare:
    # quali sono attivi lo decide il pannello, non il codice.
    attive = set(conf["estensioni_attive"]) & ESTENSIONI

    if a.attendi_ollama and not attendi_ollama(a.attendi_ollama):
        print(f"Ollama non ha risposto entro {a.attendi_ollama}s: non indicizzo.",
              file=sys.stderr)
        return

    signal.signal(signal.SIGINT, _ferma)
    signal.signal(signal.SIGTERM, _ferma)

    if a_batteria():
        print("ATTENZIONE: la macchina è a batteria. Misurato: il ritmo può crollare\n"
              "da 2,8 a 0,1 chunk/s perché macOS sospende comunque. Collega l'alimentazione.",
              file=sys.stderr)

    guardiano = tieni_sveglio()
    dep = Deposito(Path(a.deposito))
    escl = Esclusioni(Path(a.esclusioni))
    escl.regole = list(dict.fromkeys(escl.regole + list(conf["esclusioni"])))
    vocr = a.vocr if Path(a.vocr).exists() else None
    if vocr is None:
        print("nota: vocr non compilato, i PDF scansionati verranno saltati", file=sys.stderr)

    visti, nuovi, invariati, copie, errori, n_chunk = set(), 0, 0, 0, 0, 0
    rimandati = 0
    pacchetti_office = []
    tipi_saltati = Counter()
    dep.imposta_stato(in_corso=1, avviato_a=time.strftime("%Y-%m-%d %H:%M"),
                      file_fatti=0, ultimo_file="")
    inizio = time.time()

    for p in candidati(radici, escl, tipi_saltati, attive, pacchetti_office):
        if fermare:
            break
        percorso = str(p)
        visti.add(percorso)
        try:
            st = p.stat()
        except OSError:
            continue

        ver = versione(p.suffix)
        if not dep.da_rifare(percorso, st.st_mtime, st.st_size, ver):
            dep.segna_visto(percorso)
            invariati += 1
            continue

        try:
            imp = impronta(p)
            chunk, da_ocr = estrai(p, vocr)
            if not chunk:
                if vocr is None and (p.suffix.lower() in IMMAGINI or p.suffix.lower() == ".pdf"):
                    # Senza OCR non si può dire se il file è vuoto o se è una scansione.
                    # Registrarlo lo segnerebbe come fatto, e non verrebbe mai più
                    # riprovato nemmeno dopo aver compilato vocr: meglio rimandarlo.
                    rimandati += 1
                    continue
                dep.salva(percorso, st.st_mtime, st.st_size, imp, [], [], versione=ver)
                continue

            # L'identità del documento è il suo testo, non i suoi byte: lo stesso PDF
            # risalvato ha byte diversi e testo identico. Si estrae sempre (costa poco),
            # si incorpora solo se il testo non si è già visto (costa molto).
            imp_testo = hashlib.sha256("".join(chunk).encode()).hexdigest()
            if dep.gemello(imp_testo, percorso):
                dep.salva(percorso, st.st_mtime, st.st_size, imp, [], [],
                          impronta_testo=imp_testo, versione=ver)
                copie += 1
                continue

            attendi_se_si_cerca()
            vettori = []
            for i in range(0, len(chunk), LOTTO):
                vettori.extend(incorpora(chunk[i : i + LOTTO]))
                attendi_se_si_cerca()

            dep.salva(percorso, st.st_mtime, st.st_size, imp, chunk, vettori, da_ocr,
                      impronta_testo=imp_testo, versione=ver)
            nuovi += 1
            n_chunk += len(chunk)
            dep.imposta_stato(file_fatti=nuovi, ultimo_file=p.name[:80], chunk_fatti=n_chunk)
            trascorso = time.time() - inizio
            print(f"  {nuovi:5d} file · {n_chunk:6d} chunk · "
                  f"{n_chunk / max(trascorso, 1):.1f} chunk/s · "
                  f"{'OCR ' if da_ocr else ''}{p.name[:48]}", flush=True)
        except Exception as e:
            errori += 1
            print(f"  errore su {p.name}: {type(e).__name__}: {e}", file=sys.stderr)

    spariti = dep.rimuovi_spariti(visti) if not fermare else []
    dep.imposta_stato(in_corso=0, completato_a=time.strftime("%Y-%m-%d %H:%M"),
                      file_fatti=nuovi, chunk_fatti=n_chunk,
                      interrotto=int(bool(fermare)))
    if guardiano:
        guardiano.terminate()

    c = dep.conteggi()
    print(f"\nfatto in {time.time() - inizio:.0f}s")
    print(f"  nuovi o aggiornati : {nuovi} file, {n_chunk} chunk")
    print(f"  già a posto        : {invariati}")
    print(f"  duplicati          : {copie}")
    print(f"  spariti dal disco  : {len(spariti)}")
    for s in spariti[:10]:
        print(f"      {s}")
    print(f"  errori             : {errori}")
    if pacchetti_office:
        print(f"  pacchetti Office aperti saltati: {len(pacchetti_office)}")
        for cartella in pacchetti_office[:5]:
            print(f"      {cartella}")
    if rimandati:
        print(f"  rimandati (serve OCR, vocr assente): {rimandati}")
    if tipi_saltati:
        n = sum(tipi_saltati.values())
        print(f"  tipo non gestito   : {n} file — " + ", ".join(
            f"{e}×{c}" for e, c in tipi_saltati.most_common(8)))
    print(f"  indice             : {c['file']} file, {c['chunk']} chunk, {c['da_ocr']} da OCR")


if __name__ == "__main__":
    main()
