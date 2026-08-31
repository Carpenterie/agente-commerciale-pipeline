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

db.client = lambda: (_ for _ in ()).throw(RuntimeError("nessun DB nel test"))

# il sourcing salvato è dato di produzione: il test scrive altrove
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

main.CARTELLA_CACHE = Path(tempfile.mkdtemp(prefix="sourcing-test-"))
import segnali_lavoro  # noqa: E402
import sourcing_exa  # noqa: E402
import sourcing_maps  # noqa: E402

SCHEDE = [
    {"fonte": "maps", "nome": "Officina Rossi", "sito": "https://rossi.it",
     "telefono": "06 111", "comune": "Tivoli"},
    {"fonte": "maps", "nome": "Fabbro Bianchi", "sito": "",           # senza sito
     "telefono": "0774 222", "comune": "Guidonia"},
    {"fonte": "maps", "nome": "Fabbro Como", "sito": "https://como.it",  # fuori
     "telefono": "031 333", "comune": "Como"},
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
                             comuni=None, sourcing_fresco=True, gratuite_openapi=30)
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
assert "dedup interno: 7 -> 6" in uscita, uscita
# tutte e 5 le aziende sono state lavorate, nessuna ha fermato il ciclo
for nome in ("Officina Rossi", "Fabbro Bianchi", "Fabbro Como", "Sito Rotto",
             "Esplosivo", "Boom Arricchimento"):
    assert nome in uscita, nome
# un crash nel fetch non perde l'azienda: diventa FETCH_FALLITO e viene registrata
assert "fetch KO Esplosivo" in uscita and "[5/6] Esplosivo" in uscita, uscita
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
classify.classe_db = lambda c, conf, off="", seg=None: "C"  # valutata C

args2 = types.SimpleNamespace(provincia="RM", limite=1, dry_run=True,
                              comuni=None, sourcing_fresco=True, gratuite_openapi=30)
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
