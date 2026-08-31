"""CLI: orchestrazione di un ciclo (PRD §3, §11).

    python main.py --provincia RM --limite 50 --dry-run

--dry-run: tutto tranne la scrittura su Supabase. Senza --limite: ciclo
pieno sulla provincia.

Sequenza (§4-§10): sourcing Maps + Exa -> dedup interno -> esclusioni e
già-visti -> fetch -> filtro territorio -> classificazione -> arricchimento
e segnali (solo A/B) -> scrittura.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import arricchimento
import classify
import config
import costi
import db
import dedup
import fetch
import segnali_lavoro
import sourcing_exa
import sourcing_maps
import territorio
from collections import Counter

from data.comuni_lazio import COMUNI


def _argomenti():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provincia", required=True, choices=sorted(COMUNI),
                   help="sigla della provincia (RM, LT, FR, RI, VT)")
    p.add_argument("--limite", type=int, help="max aziende da analizzare")
    p.add_argument("--comuni", type=int, metavar="N",
                   help="interroga solo i primi N comuni della provincia: il "
                        "sourcing si paga a comune e --limite taglia solo dopo")
    p.add_argument("--dry-run", action="store_true",
                   help="tutto tranne la scrittura su Supabase")
    p.add_argument("--sourcing-fresco", action="store_true",
                   help="rifà Maps ed Exa anche se il sourcing salvato è "
                        "recente (default: riusa entro 24 ore, non ripaga)")
    p.add_argument("--riusa-sourcing", action="store_true",
                   help="riusa il sourcing salvato QUALUNQUE sia la sua età: "
                        "le aziende su Maps non cambiano in pochi giorni e "
                        "rifarlo costa ~4,70 USD")
    p.add_argument("--gratuite-openapi", type=int,
                   default=config.CHIAMATE_OPENAPI_GRATUITE_MESE,
                   help="chiamate Openapi gratuite ancora disponibili questo mese")
    return p.parse_args()


SOURCING_VALIDO_ORE = 24
# modulo-level perché i test la puntino altrove: il sourcing salvato è dato
# di produzione e un test non deve sovrascriverlo
CARTELLA_CACHE = Path(__file__).parent / "cache"


def raccogli(provincia: str, totali: dict, max_comuni: int | None = None,
             fresco: bool = False, riusa: bool = False) -> list[dict]:
    """Sourcing dalle due fonti validate. Maps per primo: a parità di
    dominio il dedup tiene la scheda coi recapiti (§4).

    Il risultato si salva su disco: Maps ed Exa si pagano a ogni chiamata e
    rilanciare lo stesso ciclo in giornata non deve ripagarli. Con
    `fresco=True` (o dopo 24 ore) si interroga di nuovo la rete.
    """
    salvato = CARTELLA_CACHE / f"sourcing_{provincia}.json"
    if not fresco and salvato.exists():
        eta_ore = (time.time() - salvato.stat().st_mtime) / 3600
        if eta_ore < SOURCING_VALIDO_ORE or riusa:
            dati = json.loads(salvato.read_text(encoding="utf-8"))
            print(f"sourcing riusato da {salvato.name} "
                  f"({len(dati['schede'])} schede, {eta_ore:.1f} ore fa, "
                  f"già pagato {dati['costo_maps_usd']:.4f} USD): "
                  "usa --sourcing-fresco per rifarlo")
            costi.registra_apify(totali, dati["schede_maps"], costo_usd=0.0)
            return dati["schede"]

    comuni = list(COMUNI[provincia])[:max_comuni] if max_comuni else list(COMUNI[provincia])
    schede, costo_maps = sourcing_maps.cerca(comuni)
    costi.registra_apify(totali, len(schede), costo_usd=costo_maps)

    trovate_exa = sourcing_exa.cerca(config.PROVINCE[provincia])
    costi.registra_exa(totali, ricerche=len(config.QUERY_EXA),
                       risultati=len(trovate_exa))

    tutte = schede + trovate_exa
    salvato.parent.mkdir(parents=True, exist_ok=True)
    salvato.write_text(json.dumps({"schede": tutte, "schede_maps": len(schede),
                                   "costo_maps_usd": costo_maps}),
                       encoding="utf-8")
    return tutte


async def analizza(azienda: dict, crawler, client, totali: dict) -> dict:
    """Fetch -> territorio -> classificazione. Restituisce i pezzi che
    servono a costruire la riga. Non solleva: un fallimento su una singola
    azienda non ferma il ciclo (§10)."""
    esito = {"esito_fetch": "", "dati": None, "territorio": None,
             "pagine": 0, "costo": 0.0, "classe": "indeterminato",
             "segnale_sede": None}

    sito = (azienda.get("sito") or "").strip()
    if not sito or dedup.e_portale(sito):
        # senza sito, o con un social al posto del sito: entra comunque in
        # DB coi recapiti Maps (§4), senza pagare una classificazione su un
        # login wall
        esito["esito_fetch"] = "nessun_sito"
        if sito:
            print(f"  sito su portale/social ({dedup.norm_dominio(sito)}): "
                  "trattata come senza sito")
        return esito

    try:
        stato, contenuto, pagine = await fetch.fetch_azienda(
            crawler, azienda["sito"])
    except Exception as e:  # noqa: BLE001
        print(f"  fetch KO {azienda.get('nome')}: {type(e).__name__}: {e}")
        esito["esito_fetch"] = "FETCH_FALLITO"
        return esito

    esito["esito_fetch"], esito["pagine"] = stato, pagine
    if stato != "OK" or not contenuto.strip():
        esito["esito_fetch"] = "FETCH_FALLITO"
        return esito

    esito["territorio"] = territorio.valuta(contenuto)
    if esito["territorio"]["esito"] == "fuori":
        return esito  # registrata ma non classificata: non si paga (§5)

    try:
        dati = classify.classifica(client, contenuto)
    except Exception as e:  # noqa: BLE001
        print(f"  analisi KO {azienda.get('nome')}: {type(e).__name__}: {e}")
        esito["esito_fetch"] = "ERRORE_ANALISI"
        return esito

    esito["dati"] = dati
    esito["costo"] = dati["costo_analisi_eur"]
    esito["classe"] = classify.classe_db(
        dati["classificazione"], dati["confidenza"], dati.get("capacita_officina", ""))
    costi.registra_analisi(totali, dati["token_input"], dati["token_output"])

    # la sede letta dal modello batte l'euristica sui prefissi: se dichiara
    # un'altra regione, l'azienda esce dal perimetro del ciclo. La CLASSE
    # resta quella calcolata: dice quanto vale l'azienda, non dove sta —
    # quando si aprirà la Lombardia queste sono già analizzate e pagate, e
    # devono essere recuperabili per classe. A filtrare bastano il campo
    # regione e il segnale dedicato.
    fuori_sede = territorio.verifica_sede(dati)
    if fuori_sede:
        print(f"  fuori territorio dopo l'analisi: {fuori_sede['segnale']}")
        esito["territorio"] = {"esito": "fuori", "segnale": fuori_sede["segnale"]}
        esito["segnale_sede"] = fuori_sede
    return esito


def arricchisci_ab(azienda: dict, esito: dict, totali: dict,
                   stat: dict, provincia: str = "") -> tuple[dict, list]:
    """Segnali di lavoro su TUTTI i TARGET, poi Openapi solo su A e B.

    L'ordine conta: il segnale di bisogno decide la classe A, quindi va
    raccolto prima di stabilirla — cercarlo solo su A/B sarebbe circolare.
    Una query Exa costa ~0,006 EUR: su 180 target è circa un euro a ciclo.
    Openapi invece costa 0,10 EUR e resta sulle sole A/B: su 180 target
    sarebbero 18 EUR a ciclo.
    """
    dati = esito["dati"] or {}
    if dati.get("classificazione") != "TARGET":
        return {}, []

    preliminare = esito["classe"]
    nome = azienda.get("nome", "")
    segnali = segnali_lavoro.cerca(nome)
    costi.registra_exa(totali, ricerche=1, risultati=len(segnali))

    # classe definitiva: ora i segnali sono noti
    esito["classe"] = classify.classe_db(
        dati["classificazione"], dati["confidenza"],
        dati.get("capacita_officina", ""), segnali)
    if segnali:
        print(f"  segnale di bisogno -> classe A ({segnali[0]['ruolo']})")
        stat["con_segnale"] += 1
        for s in segnali:
            stat["ruoli"][s["ruolo"]] += 1
        if esito["classe"] == "A" and preliminare != "A":
            stat["saliti_ad_A"] += 1

    if esito["classe"] not in ("A", "B"):
        return {}, segnali

    stat["arricchibili"] = stat.get("arricchibili", 0) + 1
    anagrafica = arricchimento_sicuro(azienda, nome, totali, provincia)
    if anagrafica:
        stat["arricchite"] += 1
        comune_sito = (dati.get("sede_comune") or "").strip()
        comune_openapi = anagrafica.get("sede_comune", "")
        stat.setdefault("dettaglio", []).append({
            "nome": nome, "piva": anagrafica.get("piva", ""),
            "dipendenti": anagrafica.get("dipendenti"),
            "anno": anagrafica.get("anno_bilancio"),
            "sede": f"{comune_openapi} ({anagrafica.get('sede_provincia','')})",
            "categoria": dati.get("categoria", ""),
            "comune_sito": comune_sito,
            "corretto": bool(comune_sito and comune_openapi
                             and comune_sito.lower() != comune_openapi.lower()),
        })
    if anagrafica and anagrafica.get("dipendenti"):
        prima = esito["classe"]
        esito["classe"] = classify.modula_dipendenti(
            esito["classe"], dati.get("categoria", ""), anagrafica["dipendenti"])
        if esito["classe"] != prima:
            stat["scesi_per_organico"] += 1
            stat.setdefault("declassate", []).append(
                (nome, dati.get("categoria", ""), anagrafica["dipendenti"],
                 prima, esito["classe"]))
            print(f"  organico {anagrafica['dipendenti']} dipendenti: "
                  f"{prima} -> {esito['classe']}")
    return anagrafica, segnali


def arricchimento_sicuro(azienda: dict, nome: str, totali: dict,
                         provincia: str = "") -> dict:
    """Senza P.IVA servono due chiamate (search + advanced): le registra
    entrambe, altrimenti il costo del ciclo è sottostimato della metà."""
    dati = arricchimento.arricchisci(
        nome, piva=(azienda.get("piva") or "").strip(), provincia=provincia) or {}
    costi.registra_openapi(totali, dati.get("chiamate", 1) if dati else 1)
    return dati


async def esegui(args) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    from anthropic import Anthropic
    from crawl4ai import AsyncWebCrawler

    totali = costi.nuovo_ciclo(gratuite_openapi=args.gratuite_openapi)
    # dry-run = tutto tranne la SCRITTURA (§3): esclusioni e già-visti si
    # leggono comunque, altrimenti la prova non verifica il dedup
    try:
        sb = db.client()
    except Exception as e:  # noqa: BLE001
        print(f"Supabase non raggiungibile ({type(e).__name__}): dedup su DB saltato")
        sb = None
    ciclo_id = None
    if sb and not args.dry_run:
        ciclo_id = db.avvia_ciclo(sb, "Lazio", note=f"provincia {args.provincia}")
        print(f"ciclo {ciclo_id} avviato")

    # 1. sourcing
    schede = raccogli(args.provincia, totali, args.comuni, args.sourcing_fresco,
                      args.riusa_sourcing)
    n_trovate = len(schede)

    # 2. dedup interno, poi esclusioni e già-visti (§4: dedup PRIMA, non dopo)
    schede = dedup.dedup_interno(schede)
    if sb:
        elenco = db.esclusioni(sb)
        attivi = [r for r in elenco
                  if (r.get("motivo") or "").strip().lower()
                  == config.MOTIVO_CLIENTE_ATTIVO]
        ex = [r for r in elenco if r not in attivi]
        print(f"elenco clienti: {len(attivi)} attivi (escludono), "
              f"{len(ex)} ex clienti (marcano)")
        # solo i clienti attivi escono dalla ricerca
        schede = dedup.filtra(schede, dedup.riferimenti(attivi), "clienti attivi")
        # gli ex clienti restano nei risultati, marcati per il commerciale
        schede = dedup.marca(schede, dedup.riferimenti(ex))
        schede = dedup.filtra(schede, dedup.riferimenti(db.riferimenti_aziende(sb)),
                              "già in aziende")
    else:
        print("dedup su DB saltato: nessuna connessione")

    if args.limite:
        schede = schede[:args.limite]
    print(f"\n{len(schede)} aziende da lavorare (trovate {n_trovate})\n")

    # 3. analisi + scrittura, una alla volta: un crash a metà non lascia
    # il ciclo incoerente, le aziende già scritte restano (§12)
    client = Anthropic()
    valutazioni, esiti_scrittura, n_in_target = [], [], 0
    stat = {"classi": Counter(), "ruoli": Counter(), "con_segnale": 0,
            "saliti_ad_A": 0, "scesi_per_organico": 0, "arricchite": 0}

    async with AsyncWebCrawler(verbose=False) as crawler:
        for i, azienda in enumerate(schede, 1):
            print(f"[{i}/{len(schede)}] {azienda.get('nome', '?')[:60]}")
            try:
                esito = await analizza(azienda, crawler, client, totali)
                anagrafica, segnali = arricchisci_ab(azienda, esito, totali,
                                                     stat, args.provincia)
                if esito["segnale_sede"]:
                    segnali = [esito["segnale_sede"], *segnali]
                if esito["territorio"]:
                    valutazioni.append(esito["territorio"])
                stat["classi"][esito["classe"]] += 1
                nel_territorio = (esito["territorio"] or {}).get("esito") != "fuori"
                if esito["classe"] in ("A", "B") and nel_territorio:
                    n_in_target += 1

                riga = db.riga_azienda(
                    azienda, dati=esito["dati"], territorio=esito["territorio"],
                    anagrafica=anagrafica, segnali=segnali, classe=esito["classe"],
                    esito_fetch=esito["esito_fetch"], ciclo_id=ciclo_id,
                    pagine=esito["pagine"], costo=esito["costo"])
                if sb and not args.dry_run:
                    esiti_scrittura.append(db.scrivi_azienda(sb, riga))
                else:
                    print("  --- riga che verrebbe scritta:")
                    for campo, valore in riga.items():
                        if valore in (None, "", 0, []):
                            continue
                        testo = str(valore)
                        print(f"      {campo:<20} "
                              f"{testo[:110] + ' …' if len(testo) > 110 else testo}")
            except Exception as e:  # noqa: BLE001 - il ciclo non si ferma mai
                print(f"  SALTATA {azienda.get('nome')}: {type(e).__name__}: {e}")

    # 4. riepiloghi
    print("\n" + "=" * 52)
    print("CLASSI ASSEGNATE")
    for classe in ("A", "B", "C", "indeterminato"):
        print(f"  {classe:<16} {stat['classi'][classe]}")
    print(f"\nSEGNALI DI LAVORO: {stat['con_segnale']} aziende con almeno un annuncio")
    for ruolo, n in stat["ruoli"].most_common():
        print(f"  {ruolo:<16} {n}")
    print(f"  saliti in classe A per il segnale: {stat['saliti_ad_A']}")

    # le tre percentuali da dichiarare al cliente
    arricchibili = stat.get("arricchibili", 0)
    dettaglio = stat.get("dettaglio", [])
    con_dip = [d for d in dettaglio if d["dipendenti"] is not None]
    pct = lambda n, d: f"{100 * n / d:.0f}%" if d else "n/d"  # noqa: E731
    print("\nARRICCHIMENTO OPENAPI")
    print(f"  A/B tentate                 {arricchibili:>4}")
    print(f"  agganciate in anagrafica    {len(dettaglio):>4}   "
          f"({pct(len(dettaglio), arricchibili)} delle tentate)")
    print(f"  con numero dipendenti       {len(con_dip):>4}   "
          f"({pct(len(con_dip), len(dettaglio))} delle agganciate, "
          f"{pct(len(con_dip), arricchibili)} delle tentate)")
    if dettaglio:
        print("  senza dipendenti la modulazione organico non può applicarsi")
        print(f"  {'azienda':<34}{'P.IVA':<13}{'dip.':<6}{'sede':<24}categoria")
        for d in dettaglio:
            dip = f"{d['dipendenti']} ({d['anno']})" if d["dipendenti"] is not None else "-"
            print(f"  {d['nome'][:32]:<34}{d['piva'] or '-':<13}{dip:<6}"
                  f"{d['sede'][:22]:<24}{d['categoria']}")
        corrette = [d for d in dettaglio if d["corretto"]]
        print(f"\n  sedi corrette da Openapi rispetto al sito: {len(corrette)}")
        for d in corrette:
            print(f"    {d['nome'][:34]}: sito diceva '{d['comune_sito']}' "
                  f"-> anagrafica '{d['sede']}'")
    for nome, cat, dip, prima, dopo in stat.get("declassate", []):
        print(f"  DECLASSATA {nome[:34]}: {cat}, {dip} dipendenti, {prima} -> {dopo}")
    if stat["arricchite"] < arricchibili:
        print(f"  {arricchibili - stat['arricchite']} aziende A/B NON arricchite: "
              f"sarebbero costate {(arricchibili - stat['arricchite']) * config.COSTO_OPENAPI_EUR:.2f} EUR "
              f"(al netto delle {config.CHIAMATE_OPENAPI_GRATUITE_MESE} gratuite/mese)")
        print("  ATTENZIONE: senza arricchimento la MODULAZIONE ORGANICO non si "
              "applica, nessuna classe A è scesa a B per numero di dipendenti")
    else:
        print(f"  scesi di classe per organico ampio: {stat['scesi_per_organico']}")
    print("=" * 52)

    territorio.riepilogo(valutazioni)
    riepilogo = costi.stampa(totali)
    if esiti_scrittura:
        print("scritture:", dict(Counter(esiti_scrittura)))
    if sb and not args.dry_run:
        db.chiudi_ciclo(sb, ciclo_id, riepilogo, n_trovate, n_in_target,
                        note=f"provincia {args.provincia}")
        print(f"ciclo {ciclo_id} chiuso")
    return 0


def main() -> int:
    return asyncio.run(esegui(_argomenti()))


if __name__ == "__main__":
    raise SystemExit(main())
