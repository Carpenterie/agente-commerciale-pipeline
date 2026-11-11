"""Sentinella (11/11): si accorge di cio' che altrimenti si ferma in silenzio.

    python sentinella.py            # il job del cron, ogni 30 minuti, sempre
    python sentinella.py --secco    # legge e stampa il verdetto: non scrive, non chiama
    python sentinella.py --test

LEGGE soltanto; scrive solo tre righe sue in stato_sistema, che l'app mostra in
alto a chi la usa (rosso = 'esaurito', giallo = 'sotto_soglia'). Le righe si
aggiornano sul posto quando il problema cambia o finisce: mai cancellate. Non
tocca l'archivio, quindi e' esente dal lucchetto (lucchetto.ESENTI).

Sempre, a ogni ora:
- il database risponde.

Solo in orario di invio (lunedi'-venerdi' non festivi, fra orario_inizio_locale
e orario_fine_locale della configurazione, ora di Roma) e con gli invii accesi:
- sentinella_invii
    * invii fermi: il motore ha una riga che potrebbe partire adesso, il tetto
      del giorno non e' raggiunto, e da 20 minuti non prende nessuna riga dalla
      coda (ne' per mandarla ne' per rinviarla);
    * righe rimaste 'in_invio' da piu' di 10 minuti (esito sconosciuto);
- sentinella_campagne
    * campagna 'in_preparazione' ferma da piu' di 20 minuti;
    * campagna 'programmata' con la data di partenza arrivata e non partita
      alle 10:00;
- sentinella_testi
    * testi di una campagna fermi da piu' di 2 ore;
    * testi non pronti il giorno lavorativo prima della partenza.

Niente falsi allarmi sugli invii. "Una riga che potrebbe partire" la decide il
motore stesso: e' la funzione del database prossima_riga_automatica() (in
attesa, ora arrivata, azienda non esclusa, campagna attiva, nessuna risposta da
verificare). Finche' la funzione non esiste si applicano qui le stesse
condizioni; se non si riesce a stabilirlo non si da' l'allarme. Le righe ferme
per le regole di distanza hanno l'ora nel futuro e non contano; quelle che il
motore rinvia al momento dell'invio aggiornano `ultimo_tentativo`, che qui vale
come segno di vita: il segnale e' "il motore non tocca la coda", non "non parte
niente".

Segnale esterno: se nel .env c'e' HEARTBEAT_URL lo si chiama quando e' tutto a
posto, e con /fail in fondo quando c'e' un problema (anche il database che non
risponde). Al massimo 10 secondi; un errore della chiamata non ferma niente e
non cambia il codice di uscita. Senza la variabile si salta. Chi riceve il
segnale avvisa quando smette di arrivare: copre anche il server spento.

Fuori orario le tre righe non si toccano: il verdetto resta quello dell'ultimo
controllo fatto in orario (un problema di ieri sera e' ancora un problema).
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import urllib.request
from zoneinfo import ZoneInfo

ROMA = ZoneInfo("Europe/Rome")
INVII, CAMPAGNE, TESTI = "sentinella_invii", "sentinella_campagne", "sentinella_testi"
SERVIZI = (INVII, CAMPAGNE, TESTI)
ROSSO, GIALLO, OK = "esaurito", "sotto_soglia", "ok"
# stato_sistema.fonte_lettura e' obbligatoria e accetta solo i valori di crediti.py
FONTE_LETTURA = "controllo_pre_giro"
A_POSTO = {INVII: "Invii automatici: nessun problema rilevato",
           CAMPAGNE: "Campagne: nessun problema rilevato",
           TESTI: "Testi delle campagne: nessun problema rilevato"}
SOSPESI = "controlli sospesi, invii automatici spenti"

MIN_FERMI = 20            # il motore non tocca la coda da cosi' tanti minuti
MIN_IN_INVIO = 10
MIN_PREPARAZIONE = 20
ORA_PARTENZA = 10 * 60    # minuti dalla mezzanotte: alle 10:00 una campagna di oggi deve essere partita
ORE_TESTI = 2
MIN_TESTI_VIVI = 30       # la vigilia: testi in preparazione che avanzano non sono un problema
MODELLO_PANNELLO = "pannello"
LETTE_MAX = 200           # righe in attesa guardate quando la funzione del database non c'e'
TEMPO_BATTITO_S = 10


# ------------------------------------------------------------------ tempo ---

def _quando(iso) -> dt.datetime | None:
    if not iso:
        return None
    try:
        t = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def pasqua(anno: int) -> dt.date:
    a, b, c = anno % 19, anno // 100, anno % 100
    d, e, f = b // 4, b % 4, (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    return dt.date(anno, (h + l - 7 * m + 114) // 31, (h + l - 7 * m + 114) % 31 + 1)


def festivo(giorno: dt.date) -> bool:
    """Gli stessi festivi nazionali dell'app (regole.ts: isFestivo)."""
    fissi = {(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)}
    if giorno.year >= 2026:
        fissi.add((10, 4))
    return (giorno.month, giorno.day) in fissi or giorno == pasqua(giorno.year) + dt.timedelta(days=1)


def lavorativo(giorno: dt.date) -> bool:
    return giorno.weekday() < 5 and not festivo(giorno)


def _minuti(ora: str | None, predefinito: int) -> int:
    try:
        h, m = str(ora).split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return predefinito


def fuori_orario(adesso: dt.datetime, cfg: dict) -> str | None:
    """-> None se il motore oggi a quest'ora manda; altrimenti il perche'."""
    r = adesso.astimezone(ROMA)
    if r.weekday() >= 5:
        return "fine settimana"
    if festivo(r.date()):
        return "festivo"
    minuti = r.hour * 60 + r.minute
    if minuti < _minuti(cfg.get("orario_inizio_locale"), 9 * 60) or \
            minuti >= _minuti(cfg.get("orario_fine_locale"), 18 * 60):
        return "fuori orario"
    return None


def mezzanotte_roma(adesso: dt.datetime) -> dt.datetime:
    r = adesso.astimezone(ROMA)
    return r.replace(hour=0, minute=0, second=0, microsecond=0)


def _ora(t: dt.datetime, adesso: dt.datetime) -> str:
    """Per i messaggi: 'alle 10:42', o 'del 09/11 alle 13:00' se non e' oggi."""
    r = t.astimezone(ROMA)
    if r.date() == adesso.astimezone(ROMA).date():
        return f"alle {r:%H:%M}"
    return f"del {r:%d/%m} alle {r:%H:%M}"


def _giorno(data_iso: str) -> str:
    return f"{data_iso[8:10]}/{data_iso[5:7]}"


# --------------------------------------------------------------- verdetto ---

def valuta(dati: dict, adesso: dt.datetime) -> dict | None:
    """Regole pure. `dati` e' la fotografia letta dal database (vedi `leggi`).
    -> {servizio: (stato, messaggio)} oppure None se e' fuori orario: in quel
    caso le righe di stato_sistema non si toccano."""
    cfg = dati["cfg"]
    if fuori_orario(adesso, cfg):
        return None
    if not cfg.get("attivo"):
        return {s: (OK, f"{A_POSTO[s].split(':')[0]}: {SOSPESI}") for s in SERVIZI}
    r = adesso.astimezone(ROMA)
    oggi, minuti = r.date().isoformat(), r.hour * 60 + r.minute
    eta = lambda t: (adesso - t).total_seconds() / 60 if t else None     # noqa: E731

    # --- invii
    invii, grave = [], False
    aperto_da = minuti - _minuti(cfg.get("orario_inizio_locale"), 9 * 60)
    limite = cfg.get("limite_giornaliero") or 0
    mosso = _quando(dati.get("ultimo_movimento"))
    if dati.get("dovuta") is True and dati.get("inviate_oggi", 0) < limite and aperto_da >= MIN_FERMI \
            and (mosso is None or eta(mosso) > MIN_FERMI):
        da = (f"l'ultima attività sulla coda è {_ora(mosso, adesso)}"
              if mosso and mosso >= mezzanotte_roma(adesso) else "oggi il motore non ha ancora toccato la coda")
        invii.append(f"Invii automatici fermi: in coda ci sono email pronte a partire e il tetto di oggi non è "
                     f"raggiunto ({dati.get('inviate_oggi', 0)} su {limite}), ma {da}. Controllare in Automazioni "
                     f"il collegamento a Outlook; se è in ordine, avvisare chi gestisce il sistema.")
        grave = True
    ferme = sorted(t for t in (_quando(x) for x in dati.get("in_invio", []))
                   if t and eta(t) > MIN_IN_INVIO)
    senza_data = sum(1 for x in dati.get("in_invio", []) if not _quando(x))
    if ferme or senza_data:
        n = len(ferme) + senza_data
        piu_vecchia = f" (la più vecchia è {_ora(ferme[0], adesso)})" if ferme else ""
        invii.append(f"{'1 email è rimasta' if n == 1 else f'{n} email sono rimaste'} «in invio» da più di "
                     f"{MIN_IN_INVIO} minuti{piu_vecchia}: non si sa se {'è partita' if n == 1 else 'sono partite'}. "
                     f"Verificarne l'esito in Automazioni.")

    # --- campagne
    campagne = []
    for c in dati.get("campagne", []):
        nome = c.get("nome") or "senza nome"
        if c.get("stato") == "in_preparazione":
            viva = max((t for t in (_quando(c.get("aggiornato_il")), _quando(c.get("avvio_blocco_il"))) if t),
                       default=None)
            if viva is None or eta(viva) > MIN_PREPARAZIONE:
                da = f" Ultimo avanzamento {_ora(viva, adesso)}." if viva else ""
                campagne.append(f"La campagna «{nome}» è ferma in preparazione: l'avvio non si è concluso.{da} "
                                f"Aprire Automazioni e premere «Avvia» sulla campagna; se resta ferma, avvisare "
                                f"chi gestisce il sistema.")
        elif c.get("stato") == "programmata" and c.get("data_partenza") and c["data_partenza"] <= oggi \
                and minuti >= ORA_PARTENZA:
            if c["data_partenza"] == oggi and c.get("testi_stato") == "da_preparare":
                campagne.append(f"La campagna «{nome}» doveva partire oggi ma aspetta i testi personalizzati, che non "
                                f"sono pronti: partirà domani, con il testo base per chi non ha un testo pronto.")
            else:
                quando = "oggi" if c["data_partenza"] == oggi else f"il {_giorno(c['data_partenza'])}"
                campagne.append(f"La campagna «{nome}» doveva partire {quando} e non è ancora partita. "
                                f"Avvisare chi gestisce il sistema.")

    # --- testi
    testi = []
    for c in dati.get("campagne", []):
        nome, cid = c.get("nome") or "senza nome", c.get("id")
        t = dati.get("testi", {}).get(cid) or {}
        ultimo = max((x for x in (_quando(t.get("ultimo")), _quando(c.get("testi_programmati_il"))) if x),
                     default=_quando(c.get("aggiornato_il")))
        vigilia = (c.get("stato") == "programmata" and c.get("modello_email") == MODELLO_PANNELLO
                   and c.get("data_partenza") and c["data_partenza"] > oggi
                   and c.get("testi_stato") != "pronti"
                   and _lavorativo_prima(dt.date.fromisoformat(c["data_partenza"])) <= r.date())
        if vigilia and (c.get("testi_stato") != "da_preparare" or ultimo is None or eta(ultimo) > MIN_TESTI_VIVI):
            testi.append(f"La campagna «{nome}» parte il {_giorno(c['data_partenza'])} e i testi personalizzati non "
                         f"sono pronti: se restano così partirà con il testo base. Aprire la campagna e premere "
                         f"«Riprepara i testi»; se non avanzano, avvisare chi gestisce il sistema.")
        elif c.get("testi_stato") == "da_preparare" and not dati.get("avviso_testi") \
                and c.get("stato") not in ("completata", "archiviata") \
                and (ultimo is None or eta(ultimo) > ORE_TESTI * 60):
            resto = f": restano {t['da_generare']} testi da preparare" if t.get("da_generare") else ""
            da = f" {_ora(ultimo, adesso)}" if ultimo else ""
            testi.append(f"I testi personalizzati della campagna «{nome}» sono fermi da più di {ORE_TESTI} ore"
                         f"{resto}. Ultimo avanzamento{da or ' non noto'}. Avvisare chi gestisce il sistema.")

    return {INVII: ((ROSSO if grave else GIALLO), " ".join(invii)) if invii else (OK, A_POSTO[INVII]),
            CAMPAGNE: (ROSSO, " ".join(campagne)) if campagne else (OK, A_POSTO[CAMPAGNE]),
            TESTI: (GIALLO, " ".join(testi)) if testi else (OK, A_POSTO[TESTI])}


def _lavorativo_prima(giorno: dt.date) -> dt.date:
    """L'ultimo giorno lavorativo prima di `giorno`."""
    g = giorno - dt.timedelta(days=1)
    while not lavorativo(g):
        g -= dt.timedelta(days=1)
    return g


# --------------------------------------------------------------- database ---

class Archivio:
    """Tutte le letture, e l'unica scrittura: le tre righe di stato_sistema."""

    def __init__(self, cliente=None):
        import db
        self.c = cliente or db.client()

    def config(self) -> dict:
        return self.c.table("config_invii_automatici").select("*").eq("id", 1).single().execute().data

    def inviate_oggi(self, adesso: dt.datetime) -> int:
        return (self.c.table("attivita").select("id", count="exact").eq("tipo", "email_inviata")
                .eq("esito", "inviata").gte("creato_il", mezzanotte_roma(adesso).isoformat())
                .limit(1).execute().count or 0)

    def dovuta(self, adesso: dt.datetime) -> bool | None:
        """C'e' una riga che il motore potrebbe mandare adesso? None = non si sa."""
        try:
            return bool(self.c.rpc("prossima_riga_automatica").execute().data)
        except Exception as e:  # noqa: BLE001
            if "PGRST202" not in f"{getattr(e, 'code', '')} {e}":
                raise
        # La funzione non c'e' ancora: stesse condizioni, sulle prime righe per priorita'.
        righe = (self.c.table("coda_invii_automatici").select("id,azienda_id,campagna_id")
                 .eq("stato", "in_attesa").lte("programmato_per", adesso.isoformat())
                 .order("priorita").order("creato_il").limit(LETTE_MAX).execute().data)
        if not righe:
            return False
        attive = {c["id"] for c in self.c.table("campagne").select("id").eq("stato", "attiva").execute().data}
        buone = [r for r in righe if not r["campagna_id"] or r["campagna_id"] in attive]
        ids = sorted({r["azienda_id"] for r in buone})
        escluse, con_risposta = set(), set()
        for k in range(0, len(ids), 100):
            pezzo = ids[k:k + 100]
            escluse |= {a["id"] for a in self.c.table("aziende").select("id").in_("id", pezzo)
                        .eq("esclusa", True).execute().data}
            con_risposta |= {x["azienda_id"] for x in self.c.table("log_risposte_rilevate").select("azienda_id")
                             .in_("azienda_id", pezzo).eq("gestita", False)
                             .eq("classificazione", "risposta_da_verificare").is_("esito_avviso", "null")
                             .execute().data}
        if any(r["azienda_id"] not in escluse and not (r["campagna_id"] and r["azienda_id"] in con_risposta)
               for r in buone):
            return True
        return None if len(righe) >= LETTE_MAX else False

    def ultimo_movimento(self) -> str | None:
        """L'ultima volta che il motore ha preso una riga dalla coda, o l'ultimo invio."""
        visti = []
        for campo in ("ultimo_tentativo", "inviato_il"):
            r = (self.c.table("coda_invii_automatici").select(campo).not_.is_(campo, "null")
                 .order(campo, desc=True).limit(1).execute().data)
            if r:
                visti.append(r[0][campo])
        return max(visti, key=_quando) if visti else None

    def in_invio(self) -> list:
        return [r["ultimo_tentativo"] for r in self.c.table("coda_invii_automatici").select("ultimo_tentativo")
                .eq("stato", "in_invio").execute().data]

    def campagne(self) -> list[dict]:
        colonne = "*"
        return [{k: v for k, v in c.items() if k != "testo"}
                for c in self.c.table("campagne").select(colonne).execute().data]

    def testi(self, campagna: str) -> dict:
        q = lambda: self.c.table("testi_campagna").select("aggiornato_il", count="exact").eq("campagna_id", campagna)  # noqa: E731
        ultimo = q().order("aggiornato_il", desc=True).limit(1).execute()
        return {"totale": ultimo.count or 0,
                "ultimo": ultimo.data[0]["aggiornato_il"] if ultimo.data else None,
                "da_generare": q().eq("stato", "da_generare").limit(1).execute().count or 0}

    def righe_stato(self) -> dict[str, dict]:
        r = (self.c.table("stato_sistema").select("servizio,stato,messaggio")
             .in_("servizio", [*SERVIZI, "testi_campagna"]).execute().data)
        return {x["servizio"]: x for x in r}

    def scrivi_stato(self, servizio: str, stato: str, messaggio: str) -> None:
        riga = {"servizio": servizio, "stato": stato, "messaggio": messaggio,
                "letto_il": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "fonte_lettura": FONTE_LETTURA}
        if not self.c.table("stato_sistema").update(riga).eq("servizio", servizio).execute().data:
            self.c.table("stato_sistema").insert(riga).execute()


def leggi(arc, adesso: dt.datetime) -> dict:
    """La fotografia per `valuta`. Fuori orario o a invii spenti bastano configurazione e righe di stato."""
    cfg = arc.config()
    righe = arc.righe_stato()
    dati = {"cfg": cfg, "righe": righe,
            "avviso_testi": (righe.get("testi_campagna") or {}).get("stato") in (ROSSO, GIALLO)}
    if fuori_orario(adesso, cfg) or not cfg.get("attivo"):
        return dati
    campagne = arc.campagne()
    dati.update(inviate_oggi=arc.inviate_oggi(adesso), dovuta=arc.dovuta(adesso),
                ultimo_movimento=arc.ultimo_movimento(), in_invio=arc.in_invio(), campagne=campagne,
                testi={c["id"]: arc.testi(c["id"]) for c in campagne if c.get("testi_stato") == "da_preparare"})
    return dati


# ------------------------------------------------------------------ giro ---

def battito(url: str | None, a_posto: bool, log=print, apri=urllib.request.urlopen) -> None:
    """Il segnale esterno. Non solleva mai e non scrive l'indirizzo nel log."""
    url = (url or "").strip()
    if not url:
        return
    try:
        apri(url if a_posto else url.rstrip("/") + "/fail", timeout=TEMPO_BATTITO_S).close()
    except Exception as e:  # noqa: BLE001
        log(f"segnale esterno non riuscito ({type(e).__name__}): si riprova al prossimo giro")


def giro(arc, adesso: dt.datetime, log=print, scrivi: bool = True) -> bool:
    """-> True se e' tutto a posto. Scrive in stato_sistema solo cio' che cambia."""
    dati = leggi(arc, adesso)
    attuali = dati["righe"]
    verdetto = valuta(dati, adesso)
    if verdetto is None:
        # fuori orario: vale l'ultimo controllo fatto in orario
        return not any((attuali.get(s) or {}).get("stato") in (ROSSO, GIALLO) for s in SERVIZI)
    for servizio, (stato, messaggio) in verdetto.items():
        prima = attuali.get(servizio)
        if prima and prima.get("stato") == stato and prima.get("messaggio") == messaggio:
            continue
        if scrivi:
            arc.scrivi_stato(servizio, stato, messaggio)
        if stato != OK:
            log(f"ESITO: {servizio} {stato}: {messaggio}")
        elif prima and prima.get("stato") != OK:
            log(f"ESITO: {servizio} tornato a posto")
    return all(stato == OK for stato, _ in verdetto.values())


def main() -> int:
    if "--test" in sys.argv:
        _test()
        return 0
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    secco = "--secco" in sys.argv
    adesso = dt.datetime.now(dt.timezone.utc)
    log = lambda m: print(f"{adesso.astimezone(ROMA):%Y-%m-%d %H:%M} {m}", flush=True)  # noqa: E731
    a_posto, errore = False, None
    for tentativo in (1, 2):                     # un inciampo di rete non e' un database fermo
        try:
            a_posto = giro(Archivio(), adesso, log, scrivi=not secco)
            errore = None
            break
        except Exception as e:  # noqa: BLE001
            errore = e
            if tentativo == 1:
                import time
                time.sleep(20)
    if errore is not None:
        log(f"ESITO: database non raggiungibile o lettura fallita ({type(errore).__name__})")
    if secco:
        dati = leggi(Archivio(), adesso) if errore is None else {}
        print("verdetto:", "a posto" if a_posto else "PROBLEMA", "|",
              valuta(dati, adesso) if dati else "nessuna lettura")
        return 0
    battito(os.environ.get("HEARTBEAT_URL"), a_posto, log)
    return 0 if errore is None else 1


def _test() -> None:
    utc = dt.timezone.utc
    mer = dt.datetime(2026, 11, 11, 9, 30, tzinfo=utc)          # mercoledi' 10:30 a Roma
    cfg = {"attivo": True, "limite_giornaliero": 300, "orario_inizio_locale": "09:00:00",
           "orario_fine_locale": "18:00:00"}
    fa = lambda minuti, da=mer: (da - dt.timedelta(minutes=minuti)).isoformat()      # noqa: E731

    # orario: gli stessi giorni dell'app
    assert fuori_orario(mer, cfg) is None
    assert fuori_orario(dt.datetime(2026, 11, 11, 7, 59, tzinfo=utc), cfg) == "fuori orario"       # 8:59
    assert fuori_orario(dt.datetime(2026, 11, 11, 8, 0, tzinfo=utc), cfg) is None                  # 9:00
    assert fuori_orario(dt.datetime(2026, 11, 11, 17, 0, tzinfo=utc), cfg) == "fuori orario"       # 18:00
    assert fuori_orario(dt.datetime(2026, 7, 15, 7, 0, tzinfo=utc), cfg) is None                   # 9:00 ora legale
    assert fuori_orario(dt.datetime(2026, 11, 14, 9, 30, tzinfo=utc), cfg) == "fine settimana"
    assert fuori_orario(dt.datetime(2026, 12, 8, 9, 30, tzinfo=utc), cfg) == "festivo"
    assert pasqua(2026) == dt.date(2026, 4, 5) and pasqua(2027) == dt.date(2027, 3, 28)
    assert festivo(dt.date(2026, 4, 6)) and festivo(dt.date(2027, 3, 29)) and festivo(dt.date(2026, 10, 4))
    assert not festivo(dt.date(2025, 10, 4)) and not festivo(dt.date(2026, 11, 11))
    assert _lavorativo_prima(dt.date(2026, 11, 16)) == dt.date(2026, 11, 13)       # lunedi' -> venerdi'
    assert _lavorativo_prima(dt.date(2026, 12, 9)) == dt.date(2026, 12, 7)         # salta l'8 dicembre
    assert _lavorativo_prima(dt.date(2027, 1, 7)) == dt.date(2027, 1, 5)           # salta l'Epifania

    def foto(**k):
        return {"cfg": cfg, "inviate_oggi": 50, "dovuta": True, "ultimo_movimento": fa(2), "in_invio": [],
                "campagne": [], "testi": {}, "avviso_testi": False, "righe": {}, **k}

    def stati(v):
        return {s: v[s][0] for s in SERVIZI}

    tutto_ok = {INVII: OK, CAMPAGNE: OK, TESTI: OK}
    assert stati(valuta(foto(), mer)) == tutto_ok
    # fuori orario non si giudica; a invii spenti tutto a posto, e lo si dice
    assert valuta(foto(ultimo_movimento=fa(600)), dt.datetime(2026, 11, 11, 19, 0, tzinfo=utc)) is None
    assert valuta(foto(ultimo_movimento=fa(600)), dt.datetime(2026, 11, 14, 9, 30, tzinfo=utc)) is None
    spento = valuta({"cfg": {**cfg, "attivo": False}}, mer)
    assert stati(spento) == tutto_ok and all(SOSPESI in m for _, m in spento.values())

    # --- invii fermi: SOLO se una riga potrebbe partire, il tetto non c'e' e il motore non tocca la coda
    v = valuta(foto(ultimo_movimento=fa(25)), mer)
    assert v[INVII][0] == ROSSO and "fermi" in v[INVII][1] and "50 su 300" in v[INVII][1]
    assert "alle 10:05" in v[INVII][1], v[INVII][1]
    assert valuta(foto(ultimo_movimento=fa(19)), mer)[INVII][0] == OK                 # pausa fra due invii
    assert valuta(foto(ultimo_movimento=fa(900), dovuta=False), mer)[INVII][0] == OK  # coda vuota, o tutte rinviate
    assert valuta(foto(ultimo_movimento=fa(900), dovuta=None), mer)[INVII][0] == OK   # non si sa: niente allarme
    assert valuta(foto(ultimo_movimento=fa(900), inviate_oggi=300), mer)[INVII][0] == OK   # tetto raggiunto
    # il motore rinvia righe per le regole di distanza: non manda niente ma tocca la coda -> non e' un guasto
    assert valuta(foto(ultimo_movimento=fa(1)), mer)[INVII][0] == OK
    # appena aperto (9:10) non si giudica; alle 9:30 si', e l'ultima attivita' di ieri si dice cosi'
    apertura = dt.datetime(2026, 11, 11, 8, 10, tzinfo=utc)
    assert valuta(foto(ultimo_movimento=fa(900)), apertura)[INVII][0] == OK
    v = valuta(foto(ultimo_movimento=fa(900)), dt.datetime(2026, 11, 11, 8, 30, tzinfo=utc))
    assert v[INVII][0] == ROSSO and "non ha ancora toccato la coda" in v[INVII][1]
    assert valuta(foto(ultimo_movimento=None), mer)[INVII][0] == ROSSO
    # --- righe in invio da piu' di 10 minuti: gialle, e sommate agli invii fermi restano rosse
    v = valuta(foto(in_invio=[fa(11), fa(3)]), mer)
    assert v[INVII][0] == GIALLO and "1 email è rimasta «in invio»" in v[INVII][1] and "alle 10:19" in v[INVII][1]
    v = valuta(foto(in_invio=["2026-11-09T12:00:00+00:00", fa(30), None]), mer)
    assert "3 email sono rimaste" in v[INVII][1] and "del 09/11 alle 13:00" in v[INVII][1]
    assert valuta(foto(in_invio=[fa(9)]), mer)[INVII][0] == OK
    v = valuta(foto(in_invio=[fa(40)], ultimo_movimento=fa(40)), mer)
    assert v[INVII][0] == ROSSO and "fermi" in v[INVII][1] and "in invio" in v[INVII][1]

    # --- campagne
    camp = {"id": "c1", "nome": "1 · Prova", "stato": "programmata", "data_partenza": "2026-11-16",
            "testi_stato": "pronti", "modello_email": "pannello", "aggiornato_il": fa(3000)}
    assert stati(valuta(foto(campagne=[camp]), mer)) == tutto_ok                      # parte lunedi': niente
    in_prep = {**camp, "stato": "in_preparazione", "aggiornato_il": fa(21)}
    v = valuta(foto(campagne=[in_prep]), mer)
    assert v[CAMPAGNE][0] == ROSSO and "«1 · Prova» è ferma in preparazione" in v[CAMPAGNE][1]
    assert valuta(foto(campagne=[{**in_prep, "aggiornato_il": fa(19)}]), mer)[CAMPAGNE][0] == OK
    # la ripresa a blocchi dell'app aggiorna avvio_blocco_il: finche' avanza non e' ferma
    assert valuta(foto(campagne=[{**in_prep, "avvio_blocco_il": fa(2)}]), mer)[CAMPAGNE][0] == OK
    oggi = {**camp, "data_partenza": "2026-11-11"}
    v = valuta(foto(campagne=[oggi]), mer)
    assert v[CAMPAGNE][0] == ROSSO and "doveva partire oggi e non è ancora partita" in v[CAMPAGNE][1]
    assert valuta(foto(campagne=[oggi]), dt.datetime(2026, 11, 11, 8, 59, tzinfo=utc))[CAMPAGNE][0] == OK   # 9:59
    assert valuta(foto(campagne=[oggi]), dt.datetime(2026, 11, 11, 9, 0, tzinfo=utc))[CAMPAGNE][0] == ROSSO  # 10:00
    v = valuta(foto(campagne=[{**camp, "data_partenza": "2026-11-09"}]), mer)
    assert "doveva partire il 09/11" in v[CAMPAGNE][1]
    v = valuta(foto(campagne=[{**oggi, "testi_stato": "da_preparare"}], testi={"c1": {"ultimo": fa(5)}}), mer)
    assert v[CAMPAGNE][0] == ROSSO and "aspetta i testi" in v[CAMPAGNE][1]
    assert valuta(foto(campagne=[{**oggi, "stato": "attiva"}]), mer)[CAMPAGNE][0] == OK
    assert valuta(foto(campagne=[{**oggi, "stato": "bozza"}]), mer)[CAMPAGNE][0] == OK

    # --- testi
    lenta = {**camp, "testi_stato": "da_preparare"}
    v = valuta(foto(campagne=[lenta], testi={"c1": {"ultimo": fa(121), "da_generare": 400}}), mer)
    assert v[TESTI][0] == GIALLO and "fermi da più di 2 ore: restano 400 testi" in v[TESTI][1]
    assert valuta(foto(campagne=[lenta], testi={"c1": {"ultimo": fa(119), "da_generare": 400}}), mer)[TESTI][0] == OK
    # se il job dei testi ha gia' detto perche' e' fermo (tetto di spesa), non si ripete
    assert valuta(foto(campagne=[lenta], testi={"c1": {"ultimo": fa(500)}}, avviso_testi=True), mer)[TESTI][0] == OK
    # nessuna riga: vale quando sono stati chiesti
    assert valuta(foto(campagne=[{**lenta, "aggiornato_il": fa(130)}], testi={"c1": {}}), mer)[TESTI][0] == GIALLO
    assert valuta(foto(campagne=[{**lenta, "aggiornato_il": fa(10)}], testi={"c1": {}}), mer)[TESTI][0] == OK
    # la vigilia (venerdi' 13 per lunedi' 16): non pronti = avviso; pronti, o in preparazione che avanza, no
    ven = dt.datetime(2026, 11, 13, 9, 30, tzinfo=utc)
    v = valuta(foto(campagne=[{**camp, "testi_stato": "nessuno"}]), ven)
    assert v[TESTI][0] == GIALLO and "parte il 16/11 e i testi personalizzati non sono pronti" in v[TESTI][1]
    assert valuta(foto(campagne=[camp]), ven)[TESTI][0] == OK
    viva = foto(campagne=[lenta], testi={"c1": {"ultimo": fa(5, ven), "da_generare": 900}})
    assert valuta(viva, ven)[TESTI][0] == OK
    ferma = foto(campagne=[lenta], testi={"c1": {"ultimo": fa(45, ven), "da_generare": 900}})
    assert valuta(ferma, ven)[TESTI][0] == GIALLO
    assert valuta(foto(campagne=[{**camp, "testi_stato": "nessuno"}]), mer)[TESTI][0] == OK      # due giorni prima
    assert valuta(foto(campagne=[{**camp, "testi_stato": "nessuno", "modello_email": "altro"}]), ven)[TESTI][0] == OK
    # nessun messaggio contiene indirizzi o identificativi interni
    for f in (foto(ultimo_movimento=fa(25), in_invio=[fa(40)], campagne=[in_prep, oggi]), ferma):
        for _, m in valuta(f, mer).values():
            assert "@" not in m and "c1" not in m

    # --- giro: scrive solo cio' che cambia, non cancella, fuori orario non tocca
    class Finto:
        def __init__(self, **k):
            self.f, self.righe, self.scritte = foto(**k), {}, []

        def config(self):
            return self.f["cfg"]

        def righe_stato(self):
            return {k: dict(v) for k, v in self.righe.items()}

        def inviate_oggi(self, adesso):
            return self.f["inviate_oggi"]

        def dovuta(self, adesso):
            return self.f["dovuta"]

        def ultimo_movimento(self):
            return self.f["ultimo_movimento"]

        def in_invio(self):
            return self.f["in_invio"]

        def campagne(self):
            return self.f["campagne"]

        def testi(self, cid):
            return self.f["testi"].get(cid, {})

        def scrivi_stato(self, servizio, stato, messaggio):
            self.righe[servizio] = {"servizio": servizio, "stato": stato, "messaggio": messaggio}
            self.scritte.append((servizio, stato))

    detto = []
    arc = Finto()
    assert giro(arc, mer, detto.append) is True
    assert sorted(arc.scritte) == sorted((s, OK) for s in SERVIZI) and not detto        # le righe nascono 'ok'
    assert giro(arc, mer, detto.append) is True and len(arc.scritte) == 3 and not detto  # niente cambia: niente scritture
    arc.f["ultimo_movimento"] = fa(30)
    assert giro(arc, mer, detto.append) is False
    assert arc.scritte[-1] == (INVII, ROSSO) and len(detto) == 1 and "fermi" in detto[0]
    assert giro(arc, mer, detto.append) is False and len(arc.scritte) == 4 and len(detto) == 1   # stesso problema: una volta
    # fuori orario: non si scrive, e il problema di prima resta un problema
    sera = dt.datetime(2026, 11, 11, 19, 0, tzinfo=utc)
    arc.f["ultimo_movimento"] = fa(1, sera)
    assert giro(arc, sera, detto.append) is False and len(arc.scritte) == 4
    # torna a posto: la riga si aggiorna (non sparisce) e lo si scrive una volta
    domani = dt.datetime(2026, 11, 12, 9, 30, tzinfo=utc)
    arc.f["ultimo_movimento"] = fa(1, domani)
    assert giro(arc, domani, detto.append) is True
    assert arc.scritte[-1] == (INVII, OK) and "tornato a posto" in detto[-1] and set(arc.righe) == set(SERVIZI)
    assert giro(arc, sera, detto.append) is True
    # --secco: legge e giudica, non scrive
    secco = Finto(ultimo_movimento=fa(30))
    assert giro(secco, mer, detto.append, scrivi=False) is False and not secco.scritte
    # il job dei testi ha gia' il suo avviso: la sentinella non lo ripete
    doppio = Finto(campagne=[lenta], testi={"c1": {"ultimo": fa(500)}})
    doppio.righe["testi_campagna"] = {"servizio": "testi_campagna", "stato": GIALLO, "messaggio": "tetto"}
    assert giro(doppio, mer, detto.append) is True
    # database fermo: l'errore sale a main, che lo scrive e chiama /fail
    class Rotto(Finto):
        def config(self):
            raise ConnectionError("giu'")
    try:
        giro(Rotto(), mer, detto.append)
        raise AssertionError("doveva sollevare")
    except ConnectionError:
        pass

    # --- la funzione del database non c'e' ancora: stesse condizioni applicate qui
    class Risposta:
        def __init__(self, data=None, count=None):
            self.data, self.count = data, count

    class Query:
        def __init__(self, tabelle, nome):
            self.t, self.nome, self.filtri = tabelle, nome, {}

        def select(self, *a, **k):
            return self

        def eq(self, campo, valore):
            self.filtri[campo] = valore
            return self

        def in_(self, campo, valori):
            self.filtri[campo + "_in"] = set(valori)
            return self

        def is_(self, *a):
            return self

        def lte(self, *a):
            return self

        def order(self, *a, **k):
            return self

        def limit(self, n):
            return self

        def execute(self):
            righe = self.t.get(self.nome, [])
            if self.nome == "aziende":
                righe = [r for r in righe if r["id"] in self.filtri["id_in"] and r["esclusa"]]
            if self.nome == "log_risposte_rilevate":
                righe = [r for r in righe if r["azienda_id"] in self.filtri["azienda_id_in"]]
            return Risposta(righe)

    class Cliente:
        def __init__(self, **tabelle):
            self.t = tabelle

        def table(self, nome):
            return Query(self.t, nome)

        def rpc(self, nome):
            class _Manca:
                code = "PGRST202"

                def execute(self):
                    e = RuntimeError("Could not find the function public.prossima_riga_automatica")
                    e.code = "PGRST202"
                    raise e
            return _Manca()

    def dovuta(**tabelle):
        arc_ = Archivio.__new__(Archivio)
        arc_.c = Cliente(**tabelle)
        return arc_.dovuta(mer)

    seq = {"id": "r1", "azienda_id": "a1", "campagna_id": None}
    cam = {"id": "r2", "azienda_id": "a2", "campagna_id": "k1"}
    assert dovuta(coda_invii_automatici=[]) is False
    assert dovuta(coda_invii_automatici=[seq], aziende=[]) is True
    assert dovuta(coda_invii_automatici=[seq], aziende=[{"id": "a1", "esclusa": True}]) is False
    assert dovuta(coda_invii_automatici=[cam], campagne=[], aziende=[]) is False                   # campagna non attiva
    assert dovuta(coda_invii_automatici=[cam], campagne=[{"id": "k1"}], aziende=[]) is True
    assert dovuta(coda_invii_automatici=[cam], campagne=[{"id": "k1"}], aziende=[],
                  log_risposte_rilevate=[{"azienda_id": "a2"}]) is False                         # risposta da verificare
    # una risposta ferma la riga di campagna, non quella della sequenza
    assert dovuta(coda_invii_automatici=[{**seq, "azienda_id": "a2"}], aziende=[],
                  log_risposte_rilevate=[{"azienda_id": "a2"}]) is True
    tante = [{"id": f"r{i}", "azienda_id": f"a{i}", "campagna_id": "k1"} for i in range(LETTE_MAX)]
    assert dovuta(coda_invii_automatici=tante, campagne=[], aziende=[]) is None       # tutte ferme fra le prime: non si sa

    class ConFunzione(Cliente):
        def rpc(self, nome):
            class _C:
                def execute(self_):
                    return Risposta(self.t["rpc"])
            return _C()
    c = Archivio.__new__(Archivio)
    c.c = ConFunzione(rpc=[{"id": "r1"}])
    assert c.dovuta(mer) is True
    c.c = ConFunzione(rpc=[])
    assert c.dovuta(mer) is False

    # --- segnale esterno: /fail sul problema, mai un'eccezione, mai l'indirizzo nel log
    chiamate = []

    class _Risp:
        def close(self):
            pass

    def apri(url, timeout):
        chiamate.append((url, timeout))
        return _Risp()
    battito("https://esempio.invalid/abc", True, detto.append, apri)
    battito("https://esempio.invalid/abc/", False, detto.append, apri)
    battito("", True, detto.append, apri)
    battito(None, False, detto.append, apri)
    assert chiamate == [("https://esempio.invalid/abc", 10), ("https://esempio.invalid/abc/fail", 10)]

    def rotto(url, timeout):
        raise TimeoutError("lento")
    n = len(detto)
    battito("https://esempio.invalid/segreto", True, detto.append, rotto)
    assert len(detto) == n + 1 and "non riuscito (TimeoutError)" in detto[-1] and "segreto" not in detto[-1]
    print("ok")


if __name__ == "__main__":
    sys.exit(main())
