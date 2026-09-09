"""Check del flusso di main.py con tutte le fonti simulate: zero chiamate
esterne, zero costi. `python -m tests.test_orchestrazione`

Verifica che un ciclo completo regga i casi che il PRD chiama per nome:
azienda normale, senza sito, fuori territorio, fetch fallito, e un'azienda
che fa esplodere il codice (il ciclo non si deve fermare).
"""

import asyncio
import sys
import types

# crawl4ai vero non serve: il fetch è simulato
finto = types.ModuleType("crawl4ai")


class _Crawler:
    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


finto.AsyncWebCrawler = _Crawler
sys.modules.setdefault("crawl4ai", finto)

import arricchimento  # noqa: E402
import classify  # noqa: E402
import fetch  # noqa: E402
import db  # noqa: E402
import main  # noqa: E402

# Dal 2026-09-09 il ciclo si FERMA se il database non c'e' (prima spendeva
# tutto e non scriveva niente), quindi qui serve un DB finto che risponda
# alle sole letture: la scrittura resta disattivata da dry_run.
db.client = lambda: object()
db.esclusioni = lambda sb: []
db.riferimenti_aziende = lambda sb: []

# il sourcing salvato è dato di produzione: il test scrive altrove
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

main.CARTELLA_CACHE = Path(tempfile.mkdtemp(prefix="sourcing-test-"))
import segnali_lavoro  # noqa: E402
import sourcing_exa  # noqa: E402
import sourcing_maps  # noqa: E402

SCHEDE = [
    {"fonte": "maps", "nome": "Officina Rossi", "sito": "https://rossi.it",
     "telefono": "06 111", "comune": "Tivoli", "cap": "00019", "provincia": "RM",
     "recensioni": 12, "punteggio": 4.2},
    {"fonte": "maps", "nome": "Fabbro Bianchi", "sito": "",           # senza sito
     "telefono": "0774 222", "comune": "Guidonia"},
    {"fonte": "maps", "nome": "Fabbro Como", "sito": "https://como.it",  # fuori
     "telefono": "031 333", "comune": "Como", "cap": "22100", "provincia": "CO"},
    {"fonte": "maps", "nome": "Chiusa Definitivamente", "sito": "https://chiusa.it",
     "comune": "Roma", "chiusa_definitivamente": True},
    {"fonte": "maps", "nome": "Chiusa Per Ora", "sito": "https://chiusaperora.it",
     "comune": "Roma", "cap": "00100", "provincia": "RM",
     "chiusa_temporaneamente": True},
    {"fonte": "exa", "nome": "Sito Rotto", "sito": "https://rotto.it"},  # fetch KO
    {"fonte": "exa", "nome": "Esplosivo", "sito": "https://boom.it"},    # crash nel fetch
    {"fonte": "exa", "nome": "Boom Arricchimento",                       # crash fuori fetch
     "sito": "https://boom2.it"},
    {"fonte": "exa", "nome": "Doppione", "sito": "https://www.rossi.it/"},  # dedup
]

CONTENUTI = {
    "https://rossi.it": "# PAGINA: https://rossi.it/contatti\n\n00019 Tivoli, tel 0774 1234567",
    "https://como.it": "# PAGINA: https://como.it/contatti\n\n22100 Como, tel 031 123456",
    "https://boom2.it": "# PAGINA: https://boom2.it/contatti\n\n00019 Tivoli, tel 0774 999",
}


async def _fetch_finto(crawler, url):
    if url == "https://rotto.it":
        return "FETCH_FALLITO", "", 0
    if url == "https://boom.it":
        raise RuntimeError("crash simulato nel fetch")
    return "OK", CONTENUTI[url], 3


def _classifica_finta(client, contenuto):
    return {"classificazione": "TARGET", "confidenza": "ALTA", "categoria": "fabbro",
            "lavora_acciaio": "SI", "capacita_officina": "SI",
            "materiali_rilevati": ["ferro"], "motivazione": "produce grate",
            "sede_comune": "Tivoli", "sede_provincia": "RM", "sede_regione": "Lazio",
            "email_aziendale": None, "telefono": None, "attivita_prevalente": "",
            "segnali_positivi": [], "segnali_dubbio": [],
            "prodotto_da_proporre": "grate",
            "token_input": 12000, "token_output": 600, "costo_analisi_eur": 0.045}


sourcing_maps.cerca = lambda comuni, log=print: (
    [s for s in SCHEDE if s["fonte"] == "maps"], 0.0045)
sourcing_exa.cerca = lambda provincia, log=print: [s for s in SCHEDE if s["fonte"] == "exa"]
fetch.fetch_azienda = _fetch_finto
classify.classifica = _classifica_finta
def _arricchisci_finto(nome, piva="", provincia="", log=print):
    if "Boom" in nome:
        raise RuntimeError("crash simulato nell'arricchimento")
    return _ANAGRAFICA


_ANAGRAFICA = {
    "piva": "01234567890", "denominazione": "X", "dipendenti": 30,
    "sede_comune": "Tivoli", "sede_provincia": "RM", "sede_cap": "00019",
    "anno_bilancio": 2024, "chiamate": 2}
arricchimento.arricchisci = _arricchisci_finto
segnali_lavoro.cerca = lambda nome, log=print: [
    {"tipo": "annuncio_lavoro", "ruolo": "saldatore", "fonte": "https://indeed.com/x"}]


class _FakeAnthropic:
    def __init__(self, *a, **k):
        pass


sys.modules["anthropic"] = types.ModuleType("anthropic")
sys.modules["anthropic"].Anthropic = _FakeAnthropic

args = types.SimpleNamespace(provincia="RM", limite=None, dry_run=True,
                             comuni=None, sourcing_fresco=True, riusa_sourcing=False,
                             gratuite_openapi=30)
# redirect_stdout e non builtins.print: i default `log=print` dei moduli
# legano il print originale all'import e sfuggirebbero alla cattura
import contextlib  # noqa: E402
import io  # noqa: E402

buffer = io.StringIO()
with contextlib.redirect_stdout(buffer):
    esito = asyncio.run(main.esegui(args))
uscita = buffer.getvalue()
assert esito == 0, esito

# il doppione (stesso dominio della prima) è stato tolto dal dedup interno
# 9 schede, meno 1 chiusa definitivamente = 8; il dedup toglie il doppione
assert "escluse 1 chiuse definitivamente" in uscita, uscita
assert "1 temporaneamente chiuse" in uscita, uscita
assert "dedup interno: 8 -> 7" in uscita, uscita
# tutte e 5 le aziende sono state lavorate, nessuna ha fermato il ciclo
for nome in ("Officina Rossi", "Fabbro Bianchi", "Fabbro Como", "Sito Rotto",
             "Esplosivo", "Boom Arricchimento"):
    assert nome in uscita, nome
# un crash nel fetch non perde l'azienda: diventa FETCH_FALLITO e viene registrata
assert "fetch KO Esplosivo" in uscita, uscita
# un crash fuori dal fetch salta la singola azienda ma non ferma il ciclo
assert "SALTATA Boom Arricchimento" in uscita, uscita
assert uscita.index("SALTATA Boom") < uscita.index("Aziende analizzate"), "ciclo fermato"
# senza sito e fuori territorio non pagano la classificazione: 2 sole analisi
assert "Aziende analizzate: 2" in uscita, uscita
# il fuori territorio è stato contato nel riepilogo del filtro geografico
assert "fuori 1" in uscita, uscita
# il segnale di bisogno porta il TARGET in classe A...
assert "segnale di bisogno -> classe A (saldatore)" in uscita, uscita
# ...e poi la modulazione organico (fabbro, 30 dipendenti) lo riporta a B
assert "organico 30 dipendenti: A -> B" in uscita, uscita
assert "classe               B" in uscita, uscita
# le righe si vedono per intero in dry-run
assert "riga che verrebbe scritta" in uscita, uscita
assert "livello_fornitura    kit" in uscita, uscita  # fabbro -> kit
# le voci di costo restano separate
for voce in ("Anthropic", "Openapi", "Exa", "Apify"):
    assert voce in uscita, voce

print("ok")

# --- il sourcing salvato si riusa senza ripagare Maps ed Exa -------------
chiamate = {"maps": 0, "exa": 0}
_maps, _exa = sourcing_maps.cerca, sourcing_exa.cerca


def _maps_contato(comuni, log=print):
    chiamate["maps"] += 1
    return _maps(comuni, log)


def _exa_contato(provincia, log=print):
    chiamate["exa"] += 1
    return _exa(provincia, log)


sourcing_maps.cerca, sourcing_exa.cerca = _maps_contato, _exa_contato

import costi  # noqa: E402

# primo giro: interroga la rete e salva
t1 = costi.nuovo_ciclo()
with contextlib.redirect_stdout(io.StringIO()):
    prime = main.raccogli("RM", t1, fresco=True)
assert chiamate == {"maps": 1, "exa": 1}, chiamate
salvato = main.CARTELLA_CACHE / "sourcing_RM.json"
assert salvato.exists(), "il sourcing non è stato salvato"

# secondo giro in giornata: riusa il file, zero chiamate, zero costo Apify
t2 = costi.nuovo_ciclo()
buffer2 = io.StringIO()
with contextlib.redirect_stdout(buffer2):
    seconde = main.raccogli("RM", t2)
assert chiamate == {"maps": 1, "exa": 1}, f"ha ripagato il sourcing: {chiamate}"
assert [s["nome"] for s in seconde] == [s["nome"] for s in prime]
assert "sourcing riusato" in buffer2.getvalue(), buffer2.getvalue()
assert costi.riepilogo(t2)["costo_apify_eur"] == 0, "Apify ripagato al riuso"
assert costi.riepilogo(t2)["costo_exa_eur"] == 0, "Exa ripagato al riuso"

# --sourcing-fresco forza comunque la rete
t3 = costi.nuovo_ciclo()
with contextlib.redirect_stdout(io.StringIO()):
    main.raccogli("RM", t3, fresco=True)
assert chiamate == {"maps": 2, "exa": 2}, chiamate

# il file di produzione non è stato toccato in tutto il test
assert main.CARTELLA_CACHE != Path(__file__).parent.parent / "cache"

print("ok (riuso sourcing verificato)")

# --- fuori territorio scoperto dopo l'analisi: classe conservata ---------
_classifica_lombarda = lambda client, contenuto: {  # noqa: E731
    **_classifica_finta(client, contenuto),
    "classificazione": "INDETERMINATO", "confidenza": "MEDIA",
    "sede_comune": "RODANO", "sede_provincia": "MI", "sede_regione": "Lombardia"}
classify.classifica = _classifica_lombarda
classify.classe_db = lambda c, conf, off="", seg=None, sch=None: "C"

args2 = types.SimpleNamespace(provincia="RM", limite=1, dry_run=True,
                              comuni=None, sourcing_fresco=True,
                              riusa_sourcing=False, gratuite_openapi=30)
buffer3 = io.StringIO()
with contextlib.redirect_stdout(buffer3):
    asyncio.run(main.esegui(args2))
uscita3 = buffer3.getvalue()

assert "fuori territorio dopo l'analisi" in uscita3, uscita3
assert "RODANO, MI (Lombardia)" in uscita3, uscita3
assert "classe               C" in uscita3, uscita3       # NON declassata
assert "regione              Lombardia" in uscita3, uscita3  # il campo che filtra
assert "esito_analisi        INDETERMINATO" in uscita3, uscita3  # conservato
assert "fuori_territorio_sede_dichiarata" in uscita3, uscita3    # segnale in cima

print("ok (fuori territorio post-analisi: classe conservata)")

# --- la marcatura ex cliente arriva in ARCHIVIO, non solo nei log --------
# È una richiesta esplicita del committente e finora era stata vista solo
# nei log di un dry-run, che per definizione non scrive niente. Qui il
# percorso è completo: elenco esclusioni -> dedup.marca -> riga_azienda ->
# scrittura riuscita -> conteggio nel riepilogo.
import importlib  # noqa: E402

import config  # noqa: E402

importlib.reload(classify)          # ripristina la classe_db vera
classify.classifica = _classifica_finta

ELENCO = [
    {"ragione_sociale": "Officina Rossi", "comune": "Tivoli",
     "motivo": "ex cliente: perso per prezzo"},
    {"ragione_sociale": "Ditta Mai Vista", "comune": "Roma",
     "motivo": config.MOTIVO_CLIENTE_ATTIVO},
]
scritte = []
db.client = lambda: object()
db.esclusioni = lambda sb: ELENCO
db.riferimenti_aziende = lambda sb: []
db.avvia_ciclo = lambda sb, regione, note="": "ciclo-finto"
db.chiudi_ciclo = lambda *a, **k: None
db.scrivi_azienda = lambda sb, riga, log=print: (scritte.append(riga), "inserita")[1]

args3 = types.SimpleNamespace(provincia="RM", limite=None, dry_run=False,
                              comuni=None, sourcing_fresco=True,
                              riusa_sourcing=False, gratuite_openapi=30)
buffer4 = io.StringIO()
with contextlib.redirect_stdout(buffer4):
    asyncio.run(main.esegui(args3))
uscita4 = buffer4.getvalue()

# il cliente attivo esclude, l'ex cliente marca e resta nei risultati
assert "1 attivi (escludono), 1 ex clienti (marcano)" in uscita4, uscita4
assert "ex cliente [ragione+comune]: Officina Rossi" in uscita4, uscita4
assert "Officina Rossi" in [r["ragione_sociale"] for r in scritte], scritte

# il segnale è nella riga scritta, in prima posizione
riga_rossi = next(r for r in scritte if r["ragione_sociale"] == "Officina Rossi")
assert riga_rossi["segnali"][0]["tipo"] == "ex_cliente", riga_rossi["segnali"]
assert riga_rossi["segnali"][0]["motivo"] == "ex cliente: perso per prezzo"

# e il riepilogo lo conta come ARRIVATO IN ARCHIVIO
assert "marcati nel sourcing           1" in uscita4, uscita4
assert "nelle righe costruite          1" in uscita4, uscita4
assert "scritti in archivio            1" in uscita4, uscita4
assert "dry-run" not in uscita4.split("EX CLIENTI")[1], uscita4

print("ok (ex cliente marcato, scritto e contato)")

# --- i tre modi di fallire di notte, che prima uscivano 0 -----------------
# Erano il difetto piu' grave trovato nella revisione pre-consegna: il cron
# registrava un successo mentre il ciclo aveva speso tutto senza scrivere.
_client, _escl, _rif = db.client, db.esclusioni, db.riferimenti_aziende
_cerca_maps = sourcing_maps.cerca

def _prova(args_, atteso_ok: bool):
    b = io.StringIO()
    with contextlib.redirect_stdout(b):
        codice = asyncio.run(main.esegui(args_))
    u = b.getvalue()
    assert (codice == 0) == atteso_ok, (codice, u[-400:])
    assert "ESITO: ciclo" in u, "manca la riga di verdetto in fondo al log"
    return codice, u

# 1. database assente all'avvio: si esce senza toccare Apify
chiamate_maps = []
sourcing_maps.cerca = lambda comuni, log=print: (chiamate_maps.append(1), ([], 0.0))[1]
db.client = lambda: (_ for _ in ()).throw(RuntimeError("connessione rifiutata"))
_, uscita = _prova(types.SimpleNamespace(
    provincia="RM", limite=None, dry_run=False, comuni=None,
    sourcing_fresco=True, riusa_sourcing=False, gratuite_openapi=30), False)
assert "Supabase non raggiungibile" in uscita, uscita
assert "Niente sourcing, nessuna spesa" in uscita
assert not chiamate_maps, "ha chiamato Apify pur senza database: e' spesa persa"
print("ok (senza database si esce prima di spendere)")

# 2. sourcing che esplode: la riga del ciclo si CHIUDE, non resta appesa
chiuso = {}
db.client, db.esclusioni, db.riferimenti_aziende = lambda: object(), _escl, _rif
db.avvia_ciclo = lambda sb, regione, note="": "ciclo-x"
db.chiudi_ciclo = lambda sb, cid, riep, nt, nit, note="": chiuso.update(
    {"id": cid, "note": note})
sourcing_maps.cerca = lambda comuni, log=print: (_ for _ in ()).throw(
    RuntimeError("monthly usage hard limit exceeded"))
_, uscita = _prova(types.SimpleNamespace(
    provincia="RM", limite=None, dry_run=False, comuni=None,
    sourcing_fresco=True, riusa_sourcing=False, gratuite_openapi=30), False)
assert chiuso.get("id") == "ciclo-x", "il ciclo e' rimasto aperto"
assert "INTERROTTO" in chiuso["note"] and "hard limit" in chiuso["note"], chiuso
print("ok (sourcing fallito: il ciclo si chiude col motivo)")

# 3. database che cade a meta': si smette dopo MAX_ERRORI_SCRITTURA, non a
# fine giro. Il campione di prova ha 6 aziende, meno della soglia vera: la
# si abbassa qui, la logica e' la stessa.
sourcing_maps.cerca = _cerca_maps
main.MAX_ERRORI_SCRITTURA = 3
db.scrivi_azienda = lambda sb, riga, log=print: "errore"
_, uscita = _prova(types.SimpleNamespace(
    provincia="RM", limite=None, dry_run=False, comuni=None,
    sourcing_fresco=True, riusa_sourcing=False, gratuite_openapi=30), False)
assert "STOP:" in uscita and "scritture fallite di fila" in uscita, uscita[-500:]
assert "INTERROTTO" in chiuso["note"], chiuso
# si e' fermato PRIMA di lavorarle tutte: e' il punto dell'esercizio
lavorate = len([x for x in uscita.splitlines() if x.startswith("[")])
assert lavorate < 6, f"le ha lavorate tutte lo stesso: {lavorate}"
print("ok (database giu' a meta': si interrompe, non analizza tutto)")

db.client, db.esclusioni, db.riferimenti_aziende = _client, _escl, _rif
