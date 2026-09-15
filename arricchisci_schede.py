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

    python arricchisci_schede.py                # quante sono, costo stimato
    python arricchisci_schede.py --applica
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys

import classify
import config  # noqa: F401
import costi
import db
import fetch

CONSERVATI = ("annuncio_lavoro", "reputazione_google", "territorio",
              "ex_cliente", "verniciatura_interna", "chiusa_temporaneamente",
              "fuori_territorio_sede_dichiarata")


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


def main() -> int:
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

    fuori = da_arricchire(righe, classe)
    prima = fotografia(fuori)
    print(f"classe {classe} con sito: {prima['righe']}")
    print(f"  PRIMA — gamma {prima['gamma']}, leva {prima['leva']}, "
          f"prodotto {prima['prodotto']}, segnali medi {prima['segnali_medi']}")
    print(f"  costo stimato: ~{prima['righe'] * 0.064:.2f} EUR")
    if not applica:
        print("\n(prova: nessuna scrittura. Rilancia con --applica)")
        return 0

    from anthropic import Anthropic

    client = Anthropic()
    totali = costi.nuovo_ciclo()
    fatte, saltate, cambierebbero = 0, [], []
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
            "segnali": segnali_uniti(r.get("segnali"),
                                     [db._testo(x) for x in
                                      (d.get("segnali_positivi") or []) if db._testo(x)]),
        }
        if db._testo(d.get("prodotto_da_proporre")):
            agg["prodotto_apertura"] = db._testo(d.get("prodotto_da_proporre"))
        if db._testo(d.get("motivazione")):
            agg["motivazione"] = db._testo(d.get("motivazione"))
        sb.table("aziende").update(agg).eq("id", r["id"]).execute()
        fatte += 1
        if i % 20 == 0:
            print(f"  [{i}/{len(fuori)}]")

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
        f = fotografia([{"segnali": [1, 2]}, {"segnali": []}, {"gamma": ["x"]}])
        assert f["segnali_medi"] == 0.67 and f["gamma"] == 1
        print("ok")
    else:
        sys.exit(main())
