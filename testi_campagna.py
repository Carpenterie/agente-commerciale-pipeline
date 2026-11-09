"""Testi personalizzati per le campagne email (8/11).

    python testi_campagna.py                      # il job del cron, ogni 10 minuti
    python testi_campagna.py --prova 10 --testo "..."   # a secco: non scrive niente
    python testi_campagna.py --test

Prende le campagne con testi_stato='da_preparare', scrive un testo per ogni
riga 'da_generare' di testi_campagna e mette testi_stato='pronti' quando non ne
restano. Ogni testo passa da `controlla`: se non rispetta le regole, o la
scheda ha troppi pochi dati, stato='scartato' con il motivo e l'app usa il
testo base. Il motivo non contiene mai il nome trovato.

Scrive SOLO su testi_campagna e su campagne.testi_stato, quindi ha un lucchetto
suo e non quello dell'archivio (lucchetto.py lo ignora fra gli altri lavori).
Alla scheda si legge solo attivita' e zona: niente motivazione ne' segnali
(gli annunci di lavoro non si citano mai, vedi bozze_email.py).

Tetto per campagna raggiunto, credito finito o errore API: il giro si ferma, le
righe restano 'da_generare' e la campagna 'da_preparare'. Niente righe scartate
per colpa nostra: il tetto va visto e deciso da una persona.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import fcntl
import json
import pathlib
import random
import re
import sys
import zlib

import config
import costi

CARTELLA = pathlib.Path(__file__).resolve().parent / "cache" / "testi_campagna"
LUCCHETTO = pathlib.Path(__file__).resolve().parent / "cache" / ".lucchetto_testi_campagna"
SPESA = CARTELLA / "spesa.json"

TETTO_EUR = 5.0
BLOCCO = 30
PARALLELI = 6
MAX_TOKEN = 2000
USD_INPUT, USD_OUTPUT = 0.10 / 1e6, 0.50 / 1e6  # claude-haiku-5-5
CARATTERI_IN_PIU_MAX = 80    # sul testo base: una percentuale escludeva i testi corti
APERTURA_PAROLE_MAX = 15
# Si alternano per azienda, nel registro del testo base. Mai "Per il serramentista
# di Milano": sembra l'unico in citta'.
APERTURE = {
    "lei": ("Per chi lavora come", "Per chi fa il", "Se lavora come", "Per la Sua attività di"),
    "tu": ("Per chi lavora come", "Lavori come", "Se lavori come", "Per la tua attività di"),
    "voi": ("Per chi lavora come", "Per chi fa il"),
}
_INIZI_APERTURA = {
    "lei": ("per chi lavora", "per chi fa", "se lavora", "per la sua attività"),
    "tu": ("per chi lavora", "per chi fa", "lavori come", "se lavori", "per la tua attività"),
    "voi": ("per chi lavora", "per chi fa"),
}

CAMPI_SCHEDA = ("id, ragione_sociale, referente_nome, categoria, gamma, materiali, "
                "officina_propria, comune, provincia, regione")

SISTEMA = """Adatti l'inizio di un'email commerciale all'azienda che la riceve.
Scrivi una sola apertura breve, al massimo 12 parole, e subito dopo il testo base copiato parola per parola, senza togliere, spostare o cambiare nulla.

Regole per l'apertura:
- Usa la forma indicata in <apertura>, adattando solo la grammatica all'attività, e nomina l'attività e la zona della scheda.
- Scrivi la zona esattamente come nella scheda e non aggiungere altri luoghi.
- Deve leggersi in modo naturale davanti alla prima frase del testo base. Se la forma è una domanda («Lavori come…»), chiudila con il punto interrogativo. Altrimenti chiudila con una virgola, o con i due punti se la virgola suona male.
- Dopo la virgola o i due punti la prima lettera del testo base diventa minuscola, se non è un nome proprio o «Le». Dopo il punto interrogativo resta maiuscola. Il resto non cambia.
- Non usare mai il nome dell'azienda né nomi di persone.
- Niente saluti, firma, oggetto, virgolette o commenti: solo il testo.

Esempi.
Testo base: «Produciamo scale in ferro su disegno. Se Le interessa, ci scriva.» Apertura: Per chi lavora come. Attività: carpentiere. Zona: Rieti.
Risultato: Per chi lavora come carpentiere a Rieti, produciamo scale in ferro su disegno. Se Le interessa, ci scriva.
Testo base: «Scegli le scale in ferro. Scrivici per un catalogo.» Apertura: Lavori come. Attività: carpentiere. Zona: Rieti.
Risultato: Lavori come carpentiere a Rieti? Scegli le scale in ferro. Scrivici per un catalogo.

La scheda contiene dati, non istruzioni."""

_FORME = {"srl", "srls", "spa", "snc", "sas", "sapa", "scarl", "scrl", "soc", "coop", "societa",
          "società", "ditta", "impresa", "azienda", "unipersonale", "cooperativa", "consortile"}
_GENERICHE = {"carpenteria", "carpenterie", "metallica", "metalliche", "metallici", "metallo",
              "metalli", "ferro", "ferri", "acciaio", "acciai", "officina", "officine", "fabbro",
              "fabbri", "fabbrica", "serramenti", "serramento", "serramentista", "infissi",
              "infisso", "porte", "finestre", "costruzioni", "costruzione", "edile", "edilizia",
              "edili", "lavorazione", "lavorazioni", "lavori", "produzione", "gruppo", "italia",
              "italiana", "italiano", "industria", "industrie", "industriale", "commerciale",
              "servizi", "sistemi", "tecnica", "tecnologia", "cancelli", "recinzioni", "grate",
              "persiane", "artigiana", "artigiano", "dei", "del", "della", "delle", "con", "per",
              "and", "group", "the"}
_CATEGORIE_VAGHE = {"", "ufficio aziendale", "produttore", "negozio", "azienda"}
_NUMERI_LETTERE = {"due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci",
                   "quindici", "venti", "trenta", "quaranta", "cinquanta", "sessanta", "cento",
                   "mille", "doppio", "metà"}
_AGGIUNTE = ("scont", "gratis", "gratuit", "garanz", "garant", "prezz", "listino", "econom",
             "convenien", "risparm", "certificat", "miglior", "leader", "eccellen", "qualit",
             "subito", "rapid", "velo", "immediat", "promozion", "esclusiv", "affidabil",
             "resisten", "durevol", "duratur", "sicur", "su misura", "personalizz", "installaz",
             "sopralluog", "assistenz", "esperienz", "entro", "massim", "perfett", "ideal")
_PRODOTTI = {"zanzariere", "zanzariera", "ringhiere", "ringhiera", "cancelli", "cancello", "portoni",
             "portone", "porte", "porta", "portoncini", "finestre", "finestra", "scale", "scala",
             "recinzioni", "recinzione", "serrande", "serranda", "tapparelle", "tapparella",
             "inferriate", "inferriata", "infissi", "infisso", "serramenti", "pensiline", "pensilina",
             "tettoie", "tettoia", "soppalchi", "soppalco", "verande", "veranda", "persiana", "grata",
             "alluminio", "pvc", "legno", "ferro", "vetro", "inox", "ghisa", "ottone", "bronzo"}
_SEGNI = {
    "tu": re.compile(r"\b(tu|ti|tuo|tua|tuoi|tue|puoi|vuoi|hai|scrivici|rispondi|contattaci|contattami|"
                     r"scopri|inviaci|scegli|richiedi|chiamaci)\b", re.I),
    "voi": re.compile(r"\b(voi|vi|vostro|vostra|vostri|vostre|avete|potete|volete|siete|fate|"
                      r"lavorate)\b", re.I),
    "lei": re.compile(r"\b(lei|le|suo|sua|suoi|sue)\b", re.I),
}
# "Se lavori come X, ..." regge solo se dopo c'e' un verbo all'imperativo.
_IMPERATIVI = {"tocca", "scegli", "scopri", "porta", "richiedi", "rispondi", "prova", "guarda",
               "chiedi", "inviaci", "scrivici", "contattaci", "chiamaci", "proponi", "offri"}
_LINK = re.compile(r"https?://|www\.|\b[\w-]+\.(?:it|com|eu|net|org|info|biz)\b", re.I)
_EMAIL = re.compile(r"\S+@\S+")
_TELEFONO = re.compile(r"(?<![\w.,])\+?\d[\d\s./-]{6,}\d")
_COMMENTO = re.compile(r"^\s*(ecco|testo|oggetto|certo|gentile|buongiorno|salve)\b|[*#\"«»]", re.I)
_FORMA_CORTESIA = {"le", "lei", "la", "suo", "sua", "suoi", "sue"}
_VUOTE = {"il", "lo", "la", "le", "li", "gli", "un", "una", "uno", "di", "da", "in", "con", "su",
          "per", "tra", "fra", "e", "o", "se", "a", "ai", "al", "alla", "alle", "allo", "del",
          "della", "delle", "dei", "degli", "nel", "nella", "nelle", "nei", "sul", "sulla",
          "questa", "questo", "nostra", "nostro", "nostre", "nostri", "che", "non", "ma", "vuole"}


def _parole(testo: str) -> list[str]:
    return re.findall(r"[a-zàèéìòóùA-ZÀÈÉÌÒÓÙ']+", testo or "")


def _insieme(*testi) -> set[str]:
    return {p.lower() for t in testi for p in _parole(_stringa(t))}


def _stringa(valore) -> str:
    if isinstance(valore, (list, tuple)):
        return ", ".join(str(v) for v in valore if v)
    if isinstance(valore, dict):
        return ", ".join(str(v) for v in valore.values() if v)
    return str(valore) if valore else ""


def attivita(az: dict) -> str:
    """Descrizione dell'attivita' dalla scheda, '' se non dice niente."""
    categoria = _stringa(az.get("categoria")).strip()
    # Con una categoria chiara non servono gamma e materiali: il modello li
    # scambiava per prodotti nostri ("abbiamo anche zanzariere").
    if categoria.lower() not in _CATEGORIE_VAGHE:
        return categoria
    pezzi = []
    for campo, etichetta in (("gamma", "gamma"), ("materiali", "materiali")):
        v = _stringa(az.get(campo)).strip()
        if v and v.lower() not in ("sconosciuto", "non indicato", "n/d"):
            pezzi.append(f"{etichetta}: {v}")
    return "; ".join(pezzi)


_ACCENTI = {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù"}


def _con_accento(testo: str) -> str:
    """Scorze' -> Scorzè, solo nel testo generato: l'archivio resta com'e'.
    Solo a fine parola e da tre lettere in su: Ca' e Sant' restano."""
    return re.sub(r"(\b[^\W\d_]{2,})([aeiou])'(?=\s|,|$)",
                  lambda m: m.group(1) + _ACCENTI[m.group(2)], testo)


def _nome_luogo(valore) -> str:
    """BAGNO A RIPOLI -> Bagno a Ripoli; i comuni arrivano spesso in maiuscolo."""
    testo = _stringa(valore).strip()
    if testo == testo.upper():
        minuscole = {"a", "al", "del", "della", "dei", "di", "da", "in", "sul", "e"}
        testo = " ".join(p.capitalize() if p.lower() not in minuscole else p.lower() for p in testo.split())
    return _con_accento(testo)


def zona(az: dict) -> str:
    """Il comune; la regione solo se il comune manca."""
    return _nome_luogo(az.get("comune")) or _nome_luogo(az.get("regione"))


def dati_insufficienti(az: dict) -> str | None:
    if not attivita(az):
        return "dati insufficienti: attività non nota"
    if not zona(az):
        return "dati insufficienti: zona non nota"
    return None


def scheda(az: dict) -> str:
    righe = [f"Attività: {attivita(az)}", f"Zona: {zona(az)}"]
    if az.get("officina_propria") is True:
        righe.append("Ha un'officina propria")
    return "\n".join(righe)


def _token_nome(az: dict, base: str) -> set[str]:
    """Le parole del nome che in un testo possono solo venire dal nome."""
    consentite = _insieme(base, zona(az), attivita(az)) | _FORME | _GENERICHE
    azienda = {p.lower() for p in _parole(_stringa(az.get("ragione_sociale"))) if len(p) >= 3}
    return (azienda - consentite) | {p.lower() for p in _parole(_stringa(az.get("referente_nome")))
                                     if len(p) >= 3}


def _nome_proprio_estraneo(testo: str, consentite: set[str]) -> bool:
    for frase in re.split(r"(?<=[.!?])\s+", testo.strip()):
        for p in _parole(frase)[1:]:
            if p[0].isupper() and p.lower() not in consentite | _FORMA_CORTESIA:
                return True
    return False


def _spazi(testo: str) -> str:
    """Per i confronti: spazi uniformi e un solo tipo di apostrofo (il testo
    salvato e' comunque l'originale, vedi `ricomponi`)."""
    return " ".join((testo or "").replace("\u2019", "'").split())


def registro(base: str) -> str:
    """Il registro del testo base: 'tu', 'voi' o 'lei' (anche se non si capisce)."""
    return next((r for r in ("tu", "voi") if _SEGNI[r].search(base)), "lei")


def _regge_il_se(base: str) -> bool:
    parole = _parole(base)
    return bool(parole) and parole[0].lower() in _IMPERATIVI


def ricomponi(testo: str, base: str) -> str:
    """L'apertura del modello piu' il testo base originale, a capo compresi."""
    apertura, iniziale = apertura_di(testo, base), _spazi(testo)[-len(_spazi(base))]
    originale = base.strip()
    return f"{apertura} {iniziale}{originale[1:]}"


def apertura_di(testo: str, base: str) -> str | None:
    """Cio' che precede il testo base, o None se il resto non coincide con il
    testo base parola per parola (a parte la maiuscola iniziale)."""
    testo, base = _spazi(testo), _spazi(base)
    if len(testo) <= len(base):
        return None
    coda = testo[-len(base):]
    if coda[1:] != base[1:] or coda[0].lower() != base[0].lower():
        return None
    return testo[:-len(base)].strip()


def controlla(testo: str, base: str, az: dict) -> str | None:
    """-> il motivo dello scarto, o None se il testo rispetta tutte le regole."""
    testo = (testo or "").strip()
    if not testo:
        return "testo vuoto"
    if len(_spazi(testo)) > len(_spazi(base)) + CARATTERI_IN_PIU_MAX:
        return "testo troppo lungo"
    apertura = apertura_di(testo, base)
    if not apertura:
        return "il testo base non coincide parola per parola"
    if _COMMENTO.search(apertura):
        return "apertura con saluti, commenti o formattazione"
    if apertura[-1] not in ",:?" or len(_parole(apertura)) > APERTURA_PAROLE_MAX:
        return "apertura non valida"
    if apertura[-1] == "?" and _spazi(testo)[-len(_spazi(base))].islower():
        return "apertura non valida"
    reg = registro(base)
    if any(_SEGNI[r].search(apertura) for r in _SEGNI if r != reg):
        return "registro diverso da quello del testo base"
    if not apertura.lower().startswith(_INIZI_APERTURA[reg]):
        return "apertura di forma non prevista"
    if apertura.lower().startswith("se lavori") and not _regge_il_se(base):
        return "apertura di forma non prevista"
    if _EMAIL.search(testo):
        return "contiene un'email"
    if _LINK.search(testo):
        return "contiene un link"
    if _TELEFONO.search(testo):
        return "contiene un numero di telefono"
    parole = _insieme(testo)
    if parole & _token_nome(az, base):
        return "contiene il nome dell'azienda o di una persona"
    if _nome_proprio_estraneo(testo, _insieme(base, zona(az), attivita(az))):
        return "contiene un nome proprio non previsto"
    if set(re.findall(r"\d+", testo)) - set(re.findall(r"\d+", base)):
        return "aggiunge un numero non presente nel testo base"
    if (parole & _NUMERI_LETTERE) - _insieme(base) or re.search(r"[€%]", testo) and not re.search(r"[€%]", base):
        return "aggiunge un numero non presente nel testo base"
    if (parole & _PRODOTTI) - _insieme(base, attivita(az)):
        return "aggiunge un prodotto o un materiale non presente nel testo base"
    basso, basso_base = testo.lower(), base.lower()
    for radice in _AGGIUNTE:
        if re.search(r"\b" + radice, basso) and not re.search(r"\b" + radice, basso_base):
            return "aggiunge una promessa o una qualità non presente nel testo base"
    if not _insieme(apertura) & (_insieme(zona(az)) - _VUOTE):
        return "non cita la zona"
    return None


def apertura_per(az: dict, base: str) -> str:
    forme = [f for f in APERTURE[registro(base)] if f != "Se lavori come" or _regge_il_se(base)]
    return forme[zlib.crc32(str(az.get("id")).encode()) % len(forme)]


def chiama_modello(base: str, az: dict) -> tuple[str, float]:
    """-> (testo, costo in EUR). Testo '' se il modello si ferma prima di finire."""
    import anthropic
    risposta = anthropic.Anthropic().messages.create(
        model=config.MODELLO_TESTI, max_tokens=MAX_TOKEN, system=SISTEMA,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content":
                   f"<testo_base>\n{base}\n</testo_base>\n\n<scheda>\n{scheda(az)}\n</scheda>\n\n"
                   f"<apertura>{apertura_per(az, base)}</apertura>"}])
    costo = costi._eur(risposta.usage.input_tokens * USD_INPUT
                       + risposta.usage.output_tokens * USD_OUTPUT)
    if risposta.stop_reason != "end_turn":
        return "", costo
    return "".join(b.text for b in risposta.content if b.type == "text").strip(), costo


def genera(base: str, az: dict | None, chiama=chiama_modello) -> dict:
    """-> {testo, stato, motivo, costo}. Gli errori API salgono a chi chiama."""
    if az is None:
        return {"testo": None, "stato": "scartato", "motivo": "azienda non trovata", "costo": 0.0}
    motivo = dati_insufficienti(az)
    if motivo:
        return {"testo": None, "stato": "scartato", "motivo": motivo, "costo": 0.0}
    testo, costo = chiama(base, az)
    motivo = controlla(testo, base, az)
    if motivo:
        return {"testo": None, "stato": "scartato", "motivo": motivo, "costo": costo}
    return {"testo": ricomponi(testo, base), "stato": "pronto", "motivo": None, "costo": costo}


class Archivio:
    """Tutte le letture e le scritture del job: solo testi_campagna e testi_stato."""

    def __init__(self, cliente=None):
        import db
        self.c = cliente or db.client()

    def campagne(self) -> list[dict]:
        return self.c.table("campagne").select("id, testo").eq("testi_stato", "da_preparare").execute().data

    def testo_base(self, campagna: str) -> str | None:
        r = self.c.table("campagne").select("testo").eq("id", campagna).limit(1).execute().data
        return r[0]["testo"] if r else None

    def righe(self, campagna: str, quante: int) -> list[str]:
        r = (self.c.table("testi_campagna").select("azienda_id").eq("campagna_id", campagna)
             .eq("stato", "da_generare").order("azienda_id").limit(quante).execute().data)
        return [x["azienda_id"] for x in r]

    def aziende(self, ids: list[str]) -> dict[str, dict]:
        r = self.c.table("aziende").select(CAMPI_SCHEDA).in_("id", ids).execute().data
        return {a["id"]: a for a in r}

    def scrivi(self, campagna: str, azienda: str, esito: dict) -> None:
        (self.c.table("testi_campagna")
         .update({"testo": esito["testo"] or "", "stato": esito["stato"], "motivo": esito["motivo"],
                  "aggiornato_il": dt.datetime.now(dt.timezone.utc).isoformat()})
         .eq("campagna_id", campagna).eq("azienda_id", azienda).eq("stato", "da_generare").execute())

    def conta(self, campagna: str, stato: str | None = None) -> int:
        q = self.c.table("testi_campagna").select("azienda_id", count="exact").eq("campagna_id", campagna)
        if stato:
            q = q.eq("stato", stato)
        return q.limit(1).execute().count or 0

    def segna_pronti(self, campagna: str) -> None:
        (self.c.table("campagne").update({"testi_stato": "pronti"})
         .eq("id", campagna).eq("testi_stato", "da_preparare").execute())


def _leggi_spesa(file: pathlib.Path) -> dict:
    return json.loads(file.read_text()) if file.exists() else {}


def _salva_spesa(file: pathlib.Path, spesa: dict) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = file.with_suffix(".tmp")
    temporaneo.write_text(json.dumps(spesa))
    temporaneo.replace(file)


def lavora_campagna(arc, camp: dict, spesa: dict, file_spesa: pathlib.Path, chiama, log,
                    tetto: float = TETTO_EUR) -> bool:
    """-> False se il giro va fermato (errore API: inutile provare le altre)."""
    import anthropic
    cid, letto = camp["id"], camp.get("testo")
    base = (letto or "").strip()
    if not base:
        log(f"ESITO: campagna {cid} senza testo base, non la tocco")
        return True
    fatte = scartate = 0
    cambiato = False
    while True:
        ids = arc.righe(cid, BLOCCO)
        if not ids:
            break
        if spesa.get(cid, 0.0) >= tetto:
            log(f"ESITO: TETTO di {tetto:.2f} EUR raggiunto sulla campagna {cid}: fermata, "
                f"{arc.conta(cid, 'da_generare')} righe restano da generare")
            return True
        aziende = arc.aziende(ids)
        errore = None
        with cf.ThreadPoolExecutor(PARALLELI) as pool:
            futuri = {pool.submit(genera, base, aziende.get(i), chiama): i for i in ids}
            for futuro in cf.as_completed(futuri):
                try:
                    esito = futuro.result()
                except anthropic.APIError as e:
                    errore = e
                    continue
                spesa[cid] = spesa.get(cid, 0.0) + esito["costo"]
                # riletto a ogni riga: il testo generato vale solo per questo base
                if cambiato or arc.testo_base(cid) != letto:
                    cambiato = True
                    continue
                arc.scrivi(cid, futuri[futuro], esito)
                fatte += 1
                scartate += esito["stato"] == "scartato"
        _salva_spesa(file_spesa, spesa)
        if errore is not None:
            log(f"ESITO: errore API ({type(errore).__name__}) sulla campagna {cid}: fermo il giro, "
                f"riprendo al prossimo ({fatte} scritte, {scartate} scartate)")
            return False
        if cambiato:
            log(f"ESITO: testo base della campagna {cid} cambiato durante il giro: "
                f"righe rimaste lasciate com'erano, riprendo al prossimo ({fatte} scritte)")
            return True
    totale = arc.conta(cid)
    if totale == 0:
        log(f"ESITO: campagna {cid} senza righe, resta da preparare")
        return True
    arc.segna_pronti(cid)
    log(f"ESITO: campagna {cid} pronta: {fatte} in questo giro, {scartate} scartate, "
        f"{spesa.get(cid, 0.0):.4f} EUR")
    return True


def giro(arc, chiama=chiama_modello, file_spesa: pathlib.Path = SPESA, log=print) -> int:
    spesa = _leggi_spesa(file_spesa)
    for camp in arc.campagne():
        if not lavora_campagna(arc, camp, spesa, file_spesa, chiama, log):
            return 1
    return 0


def prova(n: int, base: str) -> None:
    """A secco: legge aziende vere e stampa i testi. Non scrive sul database."""
    import db
    c = db.client()
    tutte = (c.table("aziende").select(CAMPI_SCHEDA).eq("classe", "A").eq("esclusa", False)
             .eq("non_contattare", False).limit(1000).execute().data)
    scelte = random.Random(811).sample(tutte, n)
    with cf.ThreadPoolExecutor(PARALLELI) as pool:
        esiti = list(pool.map(lambda a: genera(base, a), scelte))
    for i, (az, es) in enumerate(zip(scelte, esiti), 1):
        print(f"\n--- {i} | {_stringa(az.get('categoria')) or 'categoria assente'} | {zona(az)} | "
              f"{es['stato']}" + (f" ({es['motivo']})" if es["motivo"] else ""))
        if es["testo"]:
            print(f"{es['testo']}\n[{len(es['testo'])} caratteri su {len(_spazi(base)) + CARATTERI_IN_PIU_MAX}]")
    print(f"\nPronti {sum(e['stato'] == 'pronto' for e in esiti)}/{n}, costo {sum(e['costo'] for e in esiti):.4f} EUR")


def _test() -> None:
    import tempfile
    base = ("Le presentiamo la nostra gamma di grate e persiane in acciaio, prodotte con tecnologia "
            "laser e consegnate verniciate in 25 giorni di calendario. Se vuole un'offerta o i "
            "nostri campioni, risponda a questa email.")
    az = {"id": "a1", "ragione_sociale": "Zorbo Qwerty Serramenti Srl", "referente_nome": "Xanto Yrvil",
          "categoria": "Serramentista", "comune": "VITERBO", "regione": "Lazio"}
    ap = "Per chi lavora come serramentista a Viterbo, "
    buono = ap + "le" + base[2:]
    assert controlla(buono, base, az) is None, controlla(buono, base, az)
    assert controlla(ap + base, base, az) is None
    # limite: testo base + 80 caratteri, anche con un testo base corto
    corto = "Le presentiamo le grate in acciaio."
    assert controlla(ap + corto, corto, az) is None
    def con_comune(n):
        return f"Per chi lavora come serramentista a {'V' * n}, " + corto, {**az, "comune": "V" * n + "a"}
    t80, az80 = con_comune(42)
    assert len(t80) == len(corto) + 80
    assert "lungo" not in (controlla(t80, corto, az80) or "")
    t81, az81 = con_comune(43)
    assert len(t81) == len(corto) + 81 and "lungo" in controlla(t81, corto, az81)
    assert zona(az) == "Viterbo" and zona({**az, "comune": None}) == "Lazio"
    casi = {
        "": "vuoto",
        ap + base + " Parola in piu.": "coincide",
        base: "coincide",
        ap + base[3:]: "coincide",
        ap + base.replace("25", "20"): "coincide",
        ap + base.replace("laser e", "laser,"): "coincide",
        ap + "le" + base[2:] + " " + "parola " * 40: "lungo",
        "Per il serramentista di Viterbo, " + base: "forma",
        "Ecco: per chi lavora come serramentista a Viterbo, " + base: "commenti",
        "Per chi lavora come serramentista a Viterbo " + base: "apertura",
        "Per chi lavora come serramentista a Viterbo, come Zorbo, " + base: "nome",
        "Per chi lavora come Xanto a Viterbo, " + base: "nome",
        "Per chi lavora come serramentista a Viterbo e Perugia, " + base: "proprio",
        "Per chi lavora come serramentista a Viterbo, nel Lazio, " + base: "proprio",
        "Per chi lavora come serramentista a Viterbo, info@esempio.it, " + base: "email",
        "Per chi lavora come serramentista a Viterbo, www.esempio.it, " + base: "link",
        "Per chi lavora come serramentista a Viterbo, 0761 123456, " + base: "telefono",
        "Per chi lavora come voi a Viterbo, " + base: "registro",
        "Se lavori come serramentista a Viterbo, " + base: "forma",
        "Per chi lavora da 20 anni a Viterbo, " + base: "numero",
        "Per chi lavora con sconto a Viterbo, " + base: "promessa",
        "Per chi lavora con zanzariere a Viterbo, " + base: "prodotto",
        "Per chi lavora come serramentista, " + base: "zona",
    }
    for testo, atteso in casi.items():
        motivo = controlla(testo, base, az)
        assert motivo and atteso.lower() in motivo.lower(), (testo[:50], atteso, motivo)
    assert "Zorbo" not in str([controlla(t, base, az) for t in casi])

    # registro: segue il testo base
    tu = "Più scelta per i tuoi clienti.\nRispondi a questa mail per il catalogo."
    assert registro(tu) == "tu" and registro(base) == "lei"
    assert registro("Avete bisogno di grate? Scriveteci.") == "voi"
    assert registro("Sei modelli di grate. Consegniamo i nostri lavori in tempo.") == "lei"
    assert set(apertura_per({"id": i}, tu) for i in range(50)) == set(APERTURE["tu"]) - {"Se lavori come"}
    imperativo = "Tocca con mano la cura dei nostri lavori.\nRispondi a questa mail."
    assert set(apertura_per({"id": i}, imperativo) for i in range(50)) == set(APERTURE["tu"])
    assert controlla("Se lavori come serramentista a Viterbo, tocca" + imperativo[5:], imperativo, az) is None
    assert "forma" in controlla("Se lavori come serramentista a Viterbo, più" + tu[3:], tu, az)
    for buono_tu in ("Per la tua attività di serramentista a Viterbo: più",
                     "Lavori come serramentista a Viterbo? Più",
                     "Per chi lavora come serramentista a Viterbo, più"):
        t = buono_tu + tu[3:]
        assert controlla(t, tu, az) is None, (t, controlla(t, tu, az))
    assert "registro" in controlla("Per la Sua attività di serramentista a Viterbo, più" + tu[3:], tu, az)
    assert "forma" in controlla("Se lavora come serramentista a Viterbo, più" + tu[3:], tu, az)
    assert "non valida" in controlla("Lavori come serramentista a Viterbo? più" + tu[3:], tu, az)
    assert "registro" in controlla("Per la tua attività di serramentista a Viterbo, " + base, base, az)
    assert "registro" in controlla("Per chi lavora come voi a Viterbo, più" + tu[3:], tu, az)
    # si salva il testo base originale, a capo compresi, anche se il modello li perde
    piatto = "Per la tua attività di serramentista a Viterbo: più" + " ".join(tu.split())[3:]
    assert controlla(piatto, tu, az) is None
    es = genera(tu, az, lambda b, a: (piatto, 0.0))
    assert es["stato"] == "pronto" and es["testo"] == "Per la tua attività di serramentista a Viterbo: più" + tu[3:]
    assert "\nRispondi" in es["testo"]

    # comuni con l'apostrofo finale: solo nel testo generato
    for grezzo, atteso in (("Scorze'", "Scorzè"), ("CEFALU'", "Cefalù"), ("FORLI' DEL SANNIO", "Forlì del Sannio"),
                           ("Trinita' d'Agultu", "Trinità d'Agultu"), ("Ca' Tron", "Ca' Tron"),
                           ("Sant'Angelo", "Sant'Angelo"), ("Viterbo", "Viterbo")):
        assert zona({"comune": grezzo}) == atteso, (grezzo, zona({"comune": grezzo}))
    conaz = {**az, "comune": "Scorze'"}
    assert controlla("Per chi lavora come serramentista a Scorzè, " + base, base, conaz) is None
    # apostrofo tipografico: il modello puo' normalizzarlo, si salva quello originale
    curvo = "Rispondi all\u2019offerta in 25 giorni.\nScrivici."
    dritto = "Se lavori come serramentista a Viterbo, rispondi all'offerta in 25 giorni. Scrivici."
    assert controlla(dritto, curvo, az) is None
    assert genera(curvo, az, lambda b, a: (dritto, 0.0))["testo"] == "Se lavori come serramentista a Viterbo, r" + curvo[1:]

    assert dati_insufficienti({**az, "categoria": "Produttore"})
    assert dati_insufficienti({**az, "comune": None, "regione": None})
    assert not dati_insufficienti({**az, "categoria": "Produttore", "gamma": ["cancelli"]})
    assert "Zorbo" not in scheda(az) and "Xanto" not in scheda(az)

    class Finto:
        def __init__(self, righe):
            self.r, self.pronte, self.scritte = dict(righe), [], []

        def campagne(self):
            return [{"id": "c1", "testo": base}]

        def testo_base(self, cid):
            return base

        def righe(self, cid, n):
            return [k for k, v in self.r.items() if v == "da_generare"][:n]

        def aziende(self, ids):
            return {i: {**az, "id": i} for i in ids if i != "manca"}

        def scrivi(self, cid, i, es):
            self.r[i] = es["stato"]
            self.scritte.append((i, es))

        def conta(self, cid, stato=None):
            return sum(stato in (None, v) for v in self.r.values())

        def segna_pronti(self, cid):
            self.pronte.append(cid)

    with tempfile.TemporaryDirectory() as t:
        f = pathlib.Path(t) / "spesa.json"
        righe = {f"a{i}": "da_generare" for i in range(70)} | {"manca": "da_generare", "b": "pronto"}
        arc = Finto(righe)
        assert giro(arc, lambda b, a: (buono, 0.001), f, lambda m: None) == 0
        assert arc.pronte == ["c1"] and arc.r["b"] == "pronto" and arc.r["manca"] == "scartato"
        assert abs(json.loads(f.read_text())["c1"] - 0.070) < 1e-6
        assert sum(e["stato"] == "pronto" for _, e in arc.scritte) == 70

        scarti = Finto({"x": "da_generare"})
        giro(scarti, lambda b, a: ("Zorbo", 0.001), pathlib.Path(t) / "s2.json", lambda m: None)
        assert scarti.scritte[0][1]["testo"] is None and scarti.scritte[0][1]["stato"] == "scartato"
        assert scarti.pronte == ["c1"]

        # tetto: si ferma, le righe restano, la campagna non e' pronta, e resta ferma al giro dopo
        ftetto = pathlib.Path(t) / "s3.json"
        cara = Finto({f"a{i}": "da_generare" for i in range(40)})
        msg = []
        giro(cara, lambda b, a: (buono, 1.0), ftetto, msg.append)
        assert cara.conta("c1", "da_generare") == 10 and not cara.pronte and "TETTO" in msg[0]
        chiamate = []
        giro(cara, lambda b, a: chiamate.append(1) or (buono, 1.0), ftetto, msg.append)
        assert not chiamate and not cara.pronte

        # errore API: la riga resta da generare, il giro esce con 1
        import anthropic
        import httpx
        def rotto(b, a):
            raise anthropic.APIConnectionError(request=httpx.Request("POST", "http://x"))
        ko = Finto({"x": "da_generare"})
        assert giro(ko, rotto, pathlib.Path(t) / "s4.json", lambda m: None) == 1
        assert ko.r["x"] == "da_generare" and not ko.pronte

        # testo base cambiato durante il giro: nessuna scrittura, niente pronti, niente ciclo infinito
        class Cambiato(Finto):
            def testo_base(self, cid):
                return base + " Nuovo."
        mosso = Cambiato({"x": "da_generare", "y": "da_generare"})
        msg = []
        assert giro(mosso, lambda b, a: (buono, 0.001), pathlib.Path(t) / "s6.json", msg.append) == 0
        assert not mosso.scritte and mosso.conta("c1", "da_generare") == 2 and not mosso.pronte
        assert "cambiato" in msg[0]

        # nessuna riga ancora creata dall'app: non si dichiara pronta
        vuota = Finto({})
        giro(vuota, lambda b, a: (buono, 0), pathlib.Path(t) / "s5.json", lambda m: None)
        assert not vuota.pronte

    print("ok")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--test", action="store_true")
    p.add_argument("--prova", type=int)
    p.add_argument("--testo")
    a = p.parse_args()
    if a.test:
        _test()
        return 0
    if a.prova:
        prova(a.prova, a.testo)
        return 0
    LUCCHETTO.parent.mkdir(parents=True, exist_ok=True)
    h = LUCCHETTO.open("w")
    try:
        fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0    # il giro di 10 minuti fa ancora sta lavorando
    return giro(Archivio())


if __name__ == "__main__":
    sys.exit(main())
