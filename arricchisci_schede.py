"""Rianalizza le schede di una classe per popolare i campi nuovi.

`gamma`, `leva_commerciale` e i segnali letti dal sito (anni di attività,
certificazioni, showroom, impianti interni) sono stati aggiunti al prompt il
2026-09-14: le righe scritte prima non li hanno. Qui si rilegge la pagina
dalla CACHE — nessun sito riscaricato — e si riclassifica.

La CLASSIFICAZIONE non si tocca: quella in archivio e' validata. Se la
rianalisi cambierebbe idea lo scrive, ma non lo applica.

I segnali gia' presenti (reputazione, territorio, ex cliente, verniciatura,
annuncio di lavoro) restano: si sostituiscono solo quelli di tipo
`dal_sito`, cosi' il comando e' ripetibile senza accumulare doppioni.

    python arricchisci_schede.py                  # quante sono, costo stimato
    python arricchisci_schede.py --proponi        # analizza e SALVA le proposte
    python arricchisci_schede.py --applica-proposte   # scrive quelle salvate
    python arricchisci_schede.py --applica        # analizza e scrive in un colpo

`--proponi` esiste per non pagare due volte: l'analisi costa, quindi si fa
una volta sola e il risultato resta su disco finche' non si decide.
"""

from __future__ import annotations

import asyncio
import collections as _c
import json
import pathlib
import statistics
import sys

import classify
import config  # noqa: F401
import costi
import db
import fetch

# Campi che il modello produce e che questo script DEVE scrivere. Il
# 2026-09-15 referente_nome e referente_ruolo erano nel prompt, in
# classify.CAMPI e in db.riga_azienda, ma non qui: sono stati estratti su
# 265 schede e buttati, e il giro e' costato 20 EUR da rifare. Il self-check
# confronta questa lista con i campi che l'aggiornamento scrive davvero.
CAMPI_SCRITTI = ("gamma", "leva_commerciale", "referente_nome",
                 "referente_ruolo", "segnali", "prodotto_apertura",
                 "motivazione", "categoria", "officina_propria",
                 "livello_fornitura")

CONSERVATI = ("annuncio_lavoro", "reputazione_google", "territorio",
              "ex_cliente", "verniciatura_interna", "chiusa_temporaneamente",
              "fuori_territorio_sede_dichiarata", "visura_non_agganciata")


def da_arricchire(righe: list[dict], classe: str) -> list[dict]:
    return [r for r in righe if r.get("classe") == classe
            and r.get("stato") != "scartato" and (r.get("sito") or "").strip()]


def segnali_uniti(vecchi: list, nuovi_dal_sito: list) -> list:
    """I segnali di sistema restano, quelli letti dal sito si rifanno."""
    tenuti = [s for s in (vecchi or []) if s.get("tipo") != "dal_sito"]
    return tenuti + [{"tipo": "dal_sito", "nota": n} for n in nuovi_dal_sito[:6]]


def fotografia(righe: list[dict]) -> dict:
    """I numeri PRIMA di scrivere: senza questi il confronto non esiste."""
    n = len(righe)
    return {
        "righe": n,
        "gamma": sum(1 for r in righe if r.get("gamma")),
        "leva": sum(1 for r in righe if (r.get("leva_commerciale") or "").strip()),
        "prodotto": sum(1 for r in righe if (r.get("prodotto_apertura") or "").strip()),
        "segnali_medi": round(statistics.mean(
            [len(r.get("segnali") or []) for r in righe]), 2) if n else 0,
    }


PROPOSTE = pathlib.Path("proposte_arricchimento.json")


def cambio_classe(r: dict, d: dict) -> bool:
    """La classificazione cambierebbe? Allora la riga NON si tocca: quella
    in archivio e' validata, e cambiare la categoria sotto una classe
    validata lascerebbe la scheda incoerente."""
    nuovo = d.get("classificazione")
    return bool(nuovo) and nuovo != r.get("esito_analisi")


def main() -> int:
    proponi = "--proponi" in sys.argv
    applica_proposte = "--applica-proposte" in sys.argv
    applica = "--applica" in sys.argv
    classe = sys.argv[sys.argv.index("--classe") + 1] if "--classe" in sys.argv else "A"

    sb = db.client()
    righe, off = [], 0
    while True:
        b = sb.table("aziende").select(
            "id,ragione_sociale,classe,stato,sito,segnali,gamma,leva_commerciale,"
            "prodotto_apertura,esito_analisi,motivazione").range(
            off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            break
        off += 1000

    if applica_proposte:
        salvate = json.loads(PROPOSTE.read_text(encoding="utf-8"))
        for riga in salvate["proposte"]:
            sb.table("aziende").update(riga["agg"]).eq("id", riga["id"]).execute()
        print(f"{len(salvate['proposte'])} schede aggiornate dalle proposte del "
              f"{salvate['quando']}.")
        print(f"bloccate perche' cambierebbe la classificazione: "
              f"{len(salvate['bloccate'])}")
        return 0

    classi = [classe] if classe != "TUTTE" else ["A", "B", "C"]
    fuori = [r for c in classi for r in da_arricchire(righe, c)]
    prima = fotografia(fuori)
    print(f"classi {','.join(classi)} con sito: {prima['righe']}")
    print(f"  PRIMA — gamma {prima['gamma']}, leva {prima['leva']}, "
          f"prodotto {prima['prodotto']}, segnali medi {prima['segnali_medi']}")
    print(f"  costo stimato: ~{prima['righe'] * 0.064:.2f} EUR")
    if not (applica or proponi):
        print("\n(prova: nessuna analisi. Rilancia con --proponi)")
        return 0

    from anthropic import Anthropic

    # max_retries=1: il client SDK ne farebbe due per conto suo, che sommate
    # al nostro retry fanno fino a 18 minuti su una sola scheda incagliata
    client = Anthropic(max_retries=1)
    totali = costi.nuovo_ciclo()
    fatte, saltate, cambierebbero = 0, [], []
    proposte, bloccate, cat_cambiate, liv_cambiati = [], [], [], []
    for i, r in enumerate(fuori, 1):
        nome = (r["ragione_sociale"] or "?")[:40]
        esito, contenuto, _ = asyncio.run(fetch.fetch_azienda(None, r["sito"]))
        if esito != "OK" or not contenuto:
            saltate.append((nome, f"pagina non in cache ({esito})"))
            continue
        try:
            d = classify.classifica(client, contenuto)
        except Exception as e:  # noqa: BLE001
            saltate.append((nome, type(e).__name__))
            continue
        costi.registra_analisi(totali, d["token_input"], d["token_output"])
        if d.get("classificazione") and d["classificazione"] != r.get("esito_analisi"):
            cambierebbero.append((nome, r.get("esito_analisi"), d["classificazione"]))
        agg = {
            "gamma": db._lista(d.get("gamma")),
            "leva_commerciale": db._testo(d.get("leva_commerciale")),
            "referente_nome": db._testo(d.get("referente_nome")),
            "referente_ruolo": db._testo(d.get("referente_ruolo")),
            "segnali": segnali_uniti(r.get("segnali"),
                                     [db._testo(x) for x in
                                      (d.get("segnali_positivi") or []) if db._testo(x)]),
        }
        if db._testo(d.get("prodotto_da_proporre")):
            agg["prodotto_apertura"] = db._testo(d.get("prodotto_da_proporre"))
        if db._testo(d.get("motivazione")):
            agg["motivazione"] = db._testo(d.get("motivazione"))
        # categoria, officina e livello: la categoria in archivio viene da
        # un prompt precedente al cambio di perimetro, non e' un dato
        # validato. Ma se cambia anche la CLASSIFICAZIONE la riga si salta:
        # quella e' validata e la scheda resterebbe incoerente.
        if cambio_classe(r, d):
            bloccate.append((nome, r.get("esito_analisi"), d["classificazione"]))
            continue
        cat = db._enum(d.get("categoria"), config.ENUM_CATEGORIA, None)
        off_ = db._enum(d.get("capacita_officina"), config.ENUM_TERNARIO,
                        "non_determinabile")
        agg["categoria"] = cat
        agg["officina_propria"] = off_
        agg["livello_fornitura"] = db._fornitura(cat, off_)
        if cat != r.get("categoria"):
            cat_cambiate.append((r.get("categoria"), cat))
        if agg["livello_fornitura"] != r.get("livello_fornitura"):
            liv_cambiati.append((r.get("livello_fornitura"), agg["livello_fornitura"]))
        proposte.append({"id": r["id"], "nome": nome, "agg": agg})
        if applica:
            sb.table("aziende").update(agg).eq("id", r["id"]).execute()
        fatte += 1
        if i % 10 == 0:
            # flush: su file il print e' bufferizzato e l'avanzamento
            # resterebbe invisibile per minuti
            print(f"  [{i}/{len(fuori)}]", flush=True)

    import datetime
    if proponi:
        PROPOSTE.write_text(json.dumps(
            {"quando": datetime.datetime.now().isoformat(timespec="seconds"),
             "proposte": proposte, "bloccate": bloccate}), encoding="utf-8")
        print(f"\nanalizzate {fatte}, salvate in {PROPOSTE.name}. NESSUNA SCRITTURA.")
        print(f"saltate (pagina non in cache): {len(saltate)}")
        print(f"\nBLOCCATE perche' cambierebbe la CLASSIFICAZIONE: {len(bloccate)}")
        for n, a, b_ in bloccate:
            print(f"    {n[:38]:<40} {a} -> {b_}")
        print(f"\nCATEGORIE che cambierebbero: {len(cat_cambiate)} su {fatte}")
        for (da, a), n in _c.Counter(cat_cambiate).most_common():
            print(f"    {str(da):<16} -> {str(a):<16} {n:>4}")
        print(f"\nLIVELLO DI FORNITURA che cambierebbe: {len(liv_cambiati)}")
        for (da, a), n in _c.Counter(liv_cambiati).most_common(8):
            print(f"    {str(da):<18} -> {str(a):<18} {n:>4}")
        costi.stampa(totali)
        return 0

    dopo, off = [], 0
    while True:
        b = sb.table("aziende").select(
            "id,ragione_sociale,classe,stato,sito,segnali,gamma,leva_commerciale,"
            "prodotto_apertura").range(off, off + 999).execute().data
        dopo += b
        if len(b) < 1000:
            break
        off += 1000
    d2 = fotografia(da_arricchire(dopo, classe))
    print(f"\narricchite: {fatte}   saltate: {len(saltate)}")
    for n, p in saltate[:8]:
        print(f"    {n[:38]:<40} {p}")
    print(f"\n{'campo':<16}{'prima':>8}{'dopo':>8}")
    for k, et in (("gamma", "gamma"), ("leva", "leva_commerciale"),
                  ("prodotto", "prodotto_apertura"), ("segnali_medi", "segnali/scheda")):
        print(f"{et:<16}{prima[k]:>8}{d2[k]:>8}")
    print(f"\nCLASSIFICAZIONI CHE SAREBBERO CAMBIATE (non applicate): {len(cambierebbero)}")
    for n, a, b_ in cambierebbero:
        print(f"    {n[:38]:<40} {a} -> {b_}")
    costi.stampa(totali)
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        vecchi = [{"tipo": "reputazione_google"}, {"tipo": "dal_sito", "nota": "x"},
                  {"tipo": "territorio"}]
        u = segnali_uniti(vecchi, ["a", "b"])
        assert [s["tipo"] for s in u] == ["reputazione_google", "territorio",
                                          "dal_sito", "dal_sito"], u
        # ripetibile: non accumula
        assert len(segnali_uniti(u, ["a", "b"])) == 4
        assert len(segnali_uniti(None, ["a"] * 9)) == 6      # max sei
        righe = [{"classe": "A", "stato": "da_lavorare", "sito": "http://x.it"},
                 {"classe": "A", "stato": "scartato", "sito": "http://y.it"},
                 {"classe": "A", "stato": "da_lavorare", "sito": ""},
                 {"classe": "B", "stato": "da_lavorare", "sito": "http://z.it"}]
        assert len(da_arricchire(righe, "A")) == 1
        # ogni campo dichiarato deve comparire davvero nel codice che scrive
        sorgente = pathlib.Path(__file__).read_text(encoding="utf-8")
        corpo = sorgente[sorgente.index("agg = {"):sorgente.index("proposte.append")]
        for campo in CAMPI_SCRITTI:
            assert f'"{campo}"' in corpo, f"{campo} dichiarato ma mai scritto"
        f = fotografia([{"segnali": [1, 2]}, {"segnali": []}, {"gamma": ["x"]}])
        assert f["segnali_medi"] == 0.67 and f["gamma"] == 1
        print("ok")
    else:
        sys.exit(main())
