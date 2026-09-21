"""Import della lista del direttore commerciale: le NON trovate CON sito.

La lista (3.625 aziende laziali, anno 2020) e' stata incrociata con
l'archivio il 2026-09-20: 668 trovate, 2.957 no. Di queste, quelle con un
sito utilizzabile si possono analizzare come un ciclo normale — fetch,
classificazione, arricchimento — e il cliente ha approvato la spesa
(~60 EUR). Le righe entrano con `fonte = 'lista_commerciale'`, cosi' in
archivio si distinguono da Maps ed Exa.

    python importa_lista.py /percorso/lista.csv            # conta, non scrive
    python importa_lista.py /percorso/lista.csv --scrivi   # importa davvero

Regole (decise dall'utente il 2026-09-21):
- il CSV NON entra mai in git: e' un dato commerciale del cliente, come
  l'elenco clienti. Sul server viaggia via scp, fuori dalla directory
  rsyncata o dentro cache/ (che rsync esclude);
- telefono ed email della lista si scrivono SOLO dove il sito non da' di
  meglio: sono dati del 2020;
- dedup PERMISSIVO contro l'archivio prima di scrivere — al contrario del
  ciclo normale, dove il permissivo vale solo per l'elenco clienti. Qui un
  falso positivo costa un lead vecchio di sei anni, un mancato aggancio
  costa un'analisi doppia e una riga doppione davanti al commerciale;
- i SITI MORTI sono attesi e non sono un errore: la riga resta come
  anagrafica con l'esito del fetch, e si contano nel riepilogo.
"""

from __future__ import annotations

import asyncio
import csv
import re
import sys
from collections import Counter

import config  # noqa: F401  (carica gli enum usati da db)
import costi
import db
import dedup
import main as ciclo  # analizza() e arricchisci_ab() sono il ciclo vero


def norm_tel(t) -> str:
    """Solo cifre, senza prefisso internazionale. Attenzione ai cellulari:
    iniziano per 39, il prefisso si toglie solo se il resto e' plausibile."""
    d = re.sub(r"\D", "", str(t or ""))
    if d.startswith("0039"):
        d = d[4:]
    elif d.startswith("39") and len(d) >= 10 and d[2:3] == "0":
        # 39 + numero che inizia per 0: e' sempre il prefisso paese, perche'
        # ogni fisso italiano inizia per 0 (anche i distretti 039x di Monza
        # arrivano qui col loro 0 davanti)
        d = d[2:]
    elif d.startswith("39") and len(d) == 12 and d[2:3] == "3":
        d = d[2:]
    return d if len(d) >= 8 else ""


def leggi_lista(percorso: str) -> list[dict]:
    with open(percorso, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def gia_in_archivio(riga: dict, idx: dict) -> str | None:
    """Il criterio dell'incrocio del 20/9, nello stesso ordine:
    dominio -> telefono -> nome permissivo. -> criterio o None."""
    d = dedup.dominio_azienda(riga.get("web") or "")
    if d and d in idx["domini"]:
        return "dominio"
    t = norm_tel(riga.get("telefono"))
    if t and t in idx["telefoni"]:
        return "telefono"
    rag = dedup.norm_ragione(riga.get("ragione_sociale") or "")
    com = (riga.get("citta") or "").strip().lower()
    if rag and (rag, com) in idx["ragioni_comune"]:
        return "nome+comune"
    if dedup.nome_confrontabile(rag):
        for ar in idx["ragioni_lunghe"]:
            if rag in ar or ar in rag:
                return "nome permissivo"
    return None


def scheda_da_riga(riga: dict) -> dict:
    """La riga del CSV nel formato delle schede di sourcing."""
    return {
        "fonte": "lista_commerciale",
        "nome": (riga.get("ragione_sociale") or "").strip(),
        "sito": (riga.get("web") or "").strip(),
        "telefono": (riga.get("telefono") or "").strip(),
        "comune": (riga.get("citta") or "").strip(),
        "provincia": (riga.get("provincia") or "").strip().upper(),
        # non e' un campo delle schede Maps: serve solo al fallback email
        "email_lista": (riga.get("email") or "").strip(),
    }


def main_() -> int:
    percorso = next((a for a in sys.argv[1:] if not a.startswith("--")), "")
    scrivi = "--scrivi" in sys.argv
    if not percorso:
        print("uso: python importa_lista.py /percorso/lista.csv [--scrivi]")
        return 1

    from dotenv import load_dotenv
    load_dotenv()
    sb = db.client()

    lista = leggi_lista(percorso)
    arch, off = [], 0
    while True:
        b = sb.table("aziende").select(
            "ragione_sociale,comune,telefono,sito,dominio").range(off, off + 999).execute().data
        arch += b
        if len(b) < 1000:
            break
        off += 1000
    idx = {"domini": set(), "telefoni": set(), "ragioni_comune": set(),
           "ragioni_lunghe": []}
    for a in arch:
        d = dedup.dominio_azienda(a.get("sito") or a.get("dominio") or "")
        if d:
            idx["domini"].add(d)
        t = norm_tel(a.get("telefono"))
        if t:
            idx["telefoni"].add(t)
        rag = dedup.norm_ragione(a.get("ragione_sociale") or "")
        com = (a.get("comune") or "").strip().lower()
        if rag:
            idx["ragioni_comune"].add((rag, com))
        if dedup.nome_confrontabile(rag):
            idx["ragioni_lunghe"].append(rag)

    candidate = [r for r in lista
                 if not gia_in_archivio(r, idx)
                 and dedup.dominio_azienda(r.get("web") or "")]
    print(f"lista: {len(lista)} — non trovate con sito utilizzabile: {len(candidate)}")

    schede = dedup.dedup_interno([scheda_da_riga(r) for r in candidate])
    elenco = db.esclusioni(sb)
    attivi = [r for r in elenco if config.esclude(r.get("motivo"))]
    ex = [r for r in elenco if r not in attivi]
    schede = dedup.filtra(schede, dedup.riferimenti(attivi), "clienti attivi",
                          permissivo=True)
    schede = dedup.marca(schede, dedup.riferimenti(ex), permissivo=True)
    # PERMISSIVO anche qui, a differenza del ciclo (vedi docstring)
    schede = dedup.filtra(schede, dedup.riferimenti(db.riferimenti_aziende(sb)),
                          "già in aziende", permissivo=True)
    print(f"da importare: {len(schede)}   costo stimato: ~{len(schede) * 0.09:.0f} EUR")
    if not scrivi:
        print("\n(prova: nessun fetch, nessuna analisi. Rilancia con --scrivi)")
        return 0

    from anthropic import Anthropic
    from crawl4ai import AsyncWebCrawler

    totali = costi.nuovo_ciclo(gratuite_openapi=0)   # le gratuite del mese sono finite
    ciclo_id = db.avvia_ciclo(sb, "Lazio", note="import lista direttore commerciale")
    print(f"ciclo {ciclo_id} avviato")
    client = Anthropic()
    stat = {"classi": Counter(), "ruoli": Counter(), "con_segnale": 0,
            "saliti_ad_A": 0, "scesi_per_organico": 0, "arricchite": 0,
            "ex_in_riga": 0, "ex_scritti": 0}
    esiti_fetch, scritture = Counter(), Counter()
    email_lista_usate, tel_lista_usati = 0, 0
    errori_di_fila = 0

    async def giro():
        nonlocal email_lista_usate, tel_lista_usati, errori_di_fila
        async with AsyncWebCrawler(verbose=False) as crawler:
            for i, azienda in enumerate(schede, 1):
                print(f"[{i}/{len(schede)}] {azienda.get('nome', '?')[:60]}")
                try:
                    esito = await ciclo.analizza(azienda, crawler, client, totali)
                    anagrafica, segnali = ciclo.arricchisci_ab(
                        azienda, esito, totali, stat,
                        provincia=azienda.get("provincia", ""))
                    if esito["segnale_sede"]:
                        segnali = [esito["segnale_sede"], *segnali]
                    stat["classi"][esito["classe"]] += 1
                    esiti_fetch[esito["esito_fetch"]] += 1
                    riga = db.riga_azienda(
                        azienda, dati=esito["dati"], territorio=esito["territorio"],
                        anagrafica=anagrafica, segnali=segnali,
                        classe=esito["classe"], esito_fetch=esito["esito_fetch"],
                        ciclo_id=ciclo_id, pagine=esito["pagine"],
                        costo=esito["costo"])
                    # i recapiti del 2020 solo dove il sito non da' di meglio
                    if not riga.get("email_aziendale") and azienda.get("email_lista"):
                        riga["email_aziendale"] = azienda["email_lista"]
                        email_lista_usate += 1
                    if riga.get("telefono") == azienda.get("telefono") \
                            and azienda.get("telefono"):
                        tel_lista_usati += 1
                    scritta = db.scrivi_azienda(sb, riga)
                    scritture[scritta] += 1
                    errori_di_fila = errori_di_fila + 1 if scritta == "errore" else 0
                    if errori_di_fila >= ciclo.MAX_ERRORI_SCRITTURA:
                        print("STOP: il database non risponde")
                        break
                except Exception as e:  # noqa: BLE001 - una riga non ferma il giro
                    print(f"  SALTATA {azienda.get('nome')}: {type(e).__name__}: {e}")

    asyncio.run(giro())

    morti = esiti_fetch.get("FETCH_FALLITO", 0)
    print("\n" + "=" * 52)
    print(f"importate: {sum(scritture.values())}  {dict(scritture)}")
    print(f"SITI MORTI (fetch fallito, restano come anagrafica): {morti}")
    print(f"esiti fetch: {dict(esiti_fetch)}")
    print(f"classi: {dict(stat['classi'])}")
    print(f"recapiti 2020 usati come ripiego — email: {email_lista_usate}, "
          f"telefoni: {tel_lista_usati}")
    riepilogo = costi.riepilogo(totali)
    db.chiudi_ciclo(sb, ciclo_id, riepilogo, len(candidate),
                    sum(scritture.values()),
                    note="import lista direttore commerciale")
    costi.stampa(totali)
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        assert norm_tel("+39 06 491404") == "06491404"
        assert norm_tel("0039 0774 050307") == "0774050307"
        assert norm_tel("+393208644940") == "3208644940"      # cellulare con prefisso
        assert norm_tel("3927452682") == "3927452682"          # cellulare NUDO: 39 resta
        assert norm_tel("06.81102427") == "0681102427"
        assert norm_tel("123") == ""
        idx = {"domini": {"allartcenter.it"}, "telefoni": {"0681102427"},
               "ragioni_comune": {("met serramenti", "roma")},
               "ragioni_lunghe": ["met serramenti"]}
        assert gia_in_archivio({"web": "http://www.allartcenter.it"}, idx) == "dominio"
        assert gia_in_archivio({"telefono": "06 81102427"}, idx) == "telefono"
        assert gia_in_archivio({"ragione_sociale": "MET SERRAMENTI SRL",
                                "citta": "Roma"}, idx) == "nome+comune"
        assert gia_in_archivio({"ragione_sociale": "Met Serramenti di Mario",
                                "citta": "Latina"}, idx) == "nome permissivo"
        assert gia_in_archivio({"ragione_sociale": "Ferro e Fuoco",
                                "citta": "Rieti"}, idx) is None
        s = scheda_da_riga({"ragione_sociale": " X Srl ", "citta": "Anzio",
                            "provincia": "rm", "telefono": "06 1", "web": "x.it",
                            "email": "a@x.it", "fonte": "LAZIO"})
        assert s["fonte"] == "lista_commerciale" and s["provincia"] == "RM"
        assert s["email_lista"] == "a@x.it" and s["nome"] == "X Srl"
        print("ok")
    else:
        sys.exit(main_())
