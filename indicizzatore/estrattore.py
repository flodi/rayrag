"""Estrazione del testo dai formati che vale la pena indicizzare.

Scelte fatte guardando il corpus reale (vedi docs/MISURE.md):
  - documenti Office e PDF, con OCR di ripiego per i PDF scansionati;
  - email `.eml` e `.msg`: 25 file di corrispondenza, fra cui ricevute PEC allegate
    a una citazione;
  - immagini: 44 file, quasi tutti scansioni di documenti — si passano a Vision;
  - `.html` e `.doc`: via `textutil`, che macOS ha già;
  - `.numbers`: i dati stanno in protobuf compresso, serve numbers-parser.

Restano deliberatamente fuori: archivi (.zip, .gz), modelli 3D (.stp), diagrammi
(.drawio, .graffle, .orct), configurazioni (.json). Non sono documenti da ritrovare.
"""

import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

DIM_CHUNK = 2500
SOVRAPPOSIZIONE = 400
DPI_OCR = 300
TIMEOUT_ESTERNO = 120


def _pdf(p: Path) -> str:
    import pymupdf

    with pymupdf.open(p) as doc:
        return "\n".join(pagina.get_text() for pagina in doc)


def _docx(p: Path) -> str:
    import docx

    d = docx.Document(str(p))
    parti = [par.text for par in d.paragraphs]
    for tabella in d.tables:
        for riga in tabella.rows:
            parti.append(" | ".join(cella.text for cella in riga.cells))
    return "\n".join(parti)


def _xlsx(p: Path) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(str(p), data_only=True, read_only=True)
    parti = []
    for foglio in wb.worksheets:
        parti.append(f"# foglio: {foglio.title}")
        for riga in foglio.iter_rows(values_only=True):
            celle = [str(c) for c in riga if c is not None]
            if celle:
                parti.append(" | ".join(celle))
    wb.close()
    return "\n".join(parti)


def _pptx(p: Path) -> str:
    from pptx import Presentation

    parti = []
    for slide in Presentation(str(p)).slides:
        for forma in slide.shapes:
            if forma.has_text_frame:
                parti.append(forma.text_frame.text)
    return "\n".join(parti)


def _numbers(p: Path) -> str:
    from numbers_parser import Document

    parti = []
    for foglio in Document(str(p)).sheets:
        parti.append(f"# foglio: {foglio.name}")
        for tab in foglio.tables:
            for riga in tab.rows(values_only=True):
                celle = [str(c) for c in riga if c is not None]
                if celle:
                    parti.append(" | ".join(celle))
    return "\n".join(parti)


def _textutil(p: Path) -> str:
    """`.doc` e `.html`: macOS converte già, senza aggiungere dipendenze."""
    r = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(p)],
        capture_output=True, text=True, timeout=TIMEOUT_ESTERNO,
    )
    return r.stdout


def _eml(p: Path) -> str:
    import email
    from email import policy

    m = email.message_from_bytes(p.read_bytes(), policy=policy.default)
    intestazione = "\n".join(
        f"{k}: {m[k]}" for k in ("From", "To", "Cc", "Subject", "Date") if m[k]
    )
    corpo = ""
    try:
        parte = m.get_body(preferencelist=("plain", "html"))
        if parte is not None:
            corpo = parte.get_content()
            if parte.get_content_type() == "text/html":
                corpo = _strip_html(corpo)
    except Exception:
        corpo = ""
    allegati = [a.get_filename() for a in m.iter_attachments() if a.get_filename()]
    # I nomi degli allegati vanno nel testo: spesso sono l'unica traccia
    # ricercabile di un documento che sta dentro l'email.
    coda = ("\nallegati: " + ", ".join(allegati)) if allegati else ""
    return f"{intestazione}\n\n{corpo}{coda}"


def _msg(p: Path) -> str:
    import extract_msg

    with extract_msg.Message(str(p)) as m:
        campi = [
            f"From: {m.sender}" if m.sender else "",
            f"To: {m.to}" if m.to else "",
            f"Subject: {m.subject}" if m.subject else "",
            f"Date: {m.date}" if m.date else "",
        ]
        allegati = [a.longFilename or a.shortFilename for a in (m.attachments or [])]
        coda = ("\nallegati: " + ", ".join(x for x in allegati if x)) if allegati else ""
        return "\n".join(x for x in campi if x) + "\n\n" + (m.body or "") + coda


def _strip_html(t: str) -> str:
    import re

    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    import html as _html

    return _html.unescape(t)


def _testo(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _xml(p: Path) -> str:
    """Solo il testo, senza tag.

    Nell'archivio reale gli XML che contano sono fatture elettroniche e i
    datiatto.xml del deposito telematico: letti come testo grezzo finivano
    nell'indice come markup, e un chunk di tag non somiglia a nessuna domanda.
    """
    import xml.etree.ElementTree as ET

    try:
        radice = ET.parse(p).getroot()
        pezzi = (s.strip() for s in radice.itertext())
        return "\n".join(s for s in pezzi if s)
    except ET.ParseError:
        # XML malformato: si tolgono i tag a mano piuttosto che perdere il file.
        return _strip_html(p.read_text(encoding="utf-8", errors="replace"))


ESTRATTORI = {
    ".pdf": _pdf, ".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx,
    ".numbers": _numbers, ".doc": _textutil, ".html": _textutil, ".htm": _textutil,
    ".eml": _eml, ".msg": _msg,
    ".txt": _testo, ".md": _testo, ".xml": _xml, ".csv": _testo,
}

# Versione dell'estrattore per estensione. Va incrementata quando un estrattore
# cambia in modo da produrre testo diverso: l'indicizzatore rifà da solo i file di
# quell'estensione, invece di tenerli com'erano finché qualcuno non li modifica.
VERSIONI = {".xml": "2"}


def versione(suffisso: str) -> str:
    return VERSIONI.get(suffisso.lower(), "1")


# Riconosciute con Vision: nel corpus sono quasi tutte scansioni di documenti.
IMMAGINI = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".heic"}

ESTENSIONI = set(ESTRATTORI) | IMMAGINI


def normalizza(t: str) -> str:
    t = unicodedata.normalize("NFC", t)
    return "\n".join(r for r in (x.strip() for x in t.splitlines()) if r)


def spezza(t: str) -> list[str]:
    if len(t) <= DIM_CHUNK:
        return [t] if t else []
    pezzi, i = [], 0
    while i < len(t):
        pezzi.append(t[i : i + DIM_CHUNK])
        i += DIM_CHUNK - SOVRAPPOSIZIONE
    return pezzi


def _vision(percorsi: list[str], vocr: str) -> str:
    r = subprocess.run([vocr, *percorsi], capture_output=True, text=True,
                       timeout=TIMEOUT_ESTERNO)
    return r.stdout


def ocr_pdf(p: Path, vocr: str) -> str:
    import pymupdf

    parti = []
    with tempfile.TemporaryDirectory() as tmp, pymupdf.open(p) as doc:
        for n, pagina in enumerate(doc):
            png = Path(tmp) / f"{n}.png"
            pagina.get_pixmap(dpi=DPI_OCR).save(png)
            parti.append(_vision([str(png)], vocr))
    return "\n".join(parti)


def estrai(p: Path, vocr: str | None = None) -> tuple[list[str], bool]:
    """Restituisce (chunk, da_ocr). Solleva se il file è illeggibile."""
    suffisso = p.suffix.lower()

    if suffisso in IMMAGINI:
        if not vocr:
            return [], False
        # Vision legge il file direttamente: niente rasterizzazione di mezzo.
        testo = normalizza(_vision([str(p)], vocr))
        return spezza(testo), bool(testo)

    estrattore = ESTRATTORI.get(suffisso)
    if estrattore is None:
        return [], False

    testo = normalizza(estrattore(p))
    da_ocr = False
    if not testo and suffisso == ".pdf" and vocr:
        testo = normalizza(ocr_pdf(p, vocr))
        da_ocr = bool(testo)
    return spezza(testo), da_ocr


_IDENTIFICATORE = re.compile(r"^[A-Za-z]+(\.[A-Za-z0-9]+)+$")   # TSP.ArchiveInfo
_CAMEL = re.compile(r"^[A-Z][A-Za-z0-9]*$")                     # IgnoreAndPreserveUntilModified


def _prosa(s: str) -> bool:
    """Distingue il contenuto dalla struttura dentro un archivio IWA.

    Misurato su un pacchetto reale: 81402 stringhe grezze, 130 di contenuto.
    Il criterio che fa quasi tutto il lavoro è lo spazio — la prosa ne ha,
    i nomi di tipo protobuf no.
    """
    if len(s) < 4 or len(s) > 5000:
        return False
    if " " not in s:
        return False
    if not any(c.isalpha() for c in s):
        return False
    if _IDENTIFICATORE.match(s) or _CAMEL.match(s):
        return False
    return s.count("-") < 4


def _stringhe_iwa(d, fuori):
    """Raccoglie ricorsivamente le stringhe di prosa da un archivio IWA."""
    if isinstance(d, dict):
        for v in d.values():
            _stringhe_iwa(v, fuori)
    elif isinstance(d, list):
        for v in d:
            _stringhe_iwa(v, fuori)
    elif isinstance(d, str):
        s = d.strip()
        if _prosa(s):
            fuori.append(s)


def _keynote(p: Path) -> str:
    """Keynote: la meccanica di lettura degli archivi IWA è verificata, la resa
    su un vero .key no — nel corpus di sviluppo non ce n'erano.

    Se la lettura degli archivi non produce nulla, si ripiega sull'anteprima
    JPEG che il pacchetto contiene sempre, riconosciuta con Vision.
    """
    import zipfile

    from keynote_parser.codec import IWAFile

    pezzi: list[str] = []
    with zipfile.ZipFile(p) as z:
        for nome in z.namelist():
            if not nome.endswith(".iwa"):
                continue
            try:
                d = IWAFile.from_buffer(z.read(nome), nome).to_dict()
            except Exception:
                continue
            _stringhe_iwa(d, pezzi)
    visti, unici = set(), []
    for s in pezzi:
        if s not in visti:
            visti.add(s)
            unici.append(s)
    return "\n".join(unici)


ESTRATTORI[".key"] = _keynote
ESTENSIONI.add(".key")
