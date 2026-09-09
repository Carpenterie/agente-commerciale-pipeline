"""Riscrive le motivazioni che citano i numeri delle regole (classe A).

Fino al 2026-09-09 il prompt non vietava di citare "regola 3" o di usare le
etichette TARGET/NON_TARGET dentro la motivazione, e il 74% delle schede di
classe A le contiene. Il commerciale che apre la scheda non ha l'elenco
delle regole: legge "si applica la regola 7" e non sa cosa voglia dire.

Una pulizia testuale con espressioni regolari e' stata provata e scartata
(vedi README): solo l'inciso fra parentesi si toglie in sicurezza, e sono
32 righe su 375. Qui si rianalizza con il prompt nuovo.

NON tocca la classificazione: la classe in archivio e' stata validata e
resta. Se la rianalisi cambierebbe idea lo dice, ma non lo applica — qui si
riscrive un testo, non si ridiscute un giudizio.

Legge le pagine dalla cache di fetch: nessun sito viene riscaricato. Va
lanciato SUL SERVER, dove la cache dei cicli reali esiste.

    python riscrivi_motivazioni.py             # elenco e costo stimato
    python riscrivi_motivazioni.py --applica   # riscrive
    python riscrivi_motivazioni.py --classe B  # un'altra classe
"""

from __future__ import annotations

import asyncio
import re
import sys

import classify
import config
import costi
import db
import fetch

GERGO = re.compile(r"\bregol[ae]\s*\d+|\b(?:NON_TARGET|TARGET|INDETERMINATO)\b")


def da_riscrivere(righe: list[dict], classe: str) -> list[dict]:
    return [r for r in righe
            if r.get("classe") == classe and r.get("stato") != "scartato"
            and r.get("motivazione") and GERGO.search(r["motivazione"])
            and (r.get("sito") or "").strip()]


def main() -> int:
    applica = "--applica" in sys.argv
    classe = sys.argv[sys.argv.index("--classe") + 1] if "--classe" in sys.argv else "A"

    sb = db.client()
    righe, off = [], 0
    while True:
        b = sb.table("aziende").select(
            "id,ragione_sociale,classe,stato,sito,motivazione,esito_analisi").range(
            off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            break
        off += 1000

    fuori = da_riscrivere(righe, classe)
    print(f"classe {classe}: {len(fuori)} motivazioni col gergo da riscrivere")
    print(f"costo stimato: ~{len(fuori) * 0.055:.2f} EUR")
    if not applica:
        print("\n(prova: nessuna scrittura. Rilancia con --applica)")
        return 0

    from anthropic import Anthropic

    client = Anthropic()
    totali = costi.nuovo_ciclo()
    riscritte, saltate, cambierebbero = 0, [], []
    for i, r in enumerate(fuori, 1):
        nome = (r["ragione_sociale"] or "?")[:40]
        esito, contenuto, _ = asyncio.run(fetch.fetch_azienda(None, r["sito"]))
        if esito != "OK" or not contenuto:
            saltate.append((nome, f"pagina non in cache ({esito})"))
            continue
        try:
            d = classify.classifica(client, contenuto)
        except Exception as e:  # noqa: BLE001
            saltate.append((nome, f"{type(e).__name__}"))
            continue
        costi.registra_analisi(totali, d["token_input"], d["token_output"])
        nuova = (d.get("motivazione") or "").strip()
        if not nuova or GERGO.search(nuova):
            saltate.append((nome, "la nuova conterrebbe ancora gergo"))
            continue
        # la CLASSIFICAZIONE non si tocca: si annota e basta
        if d.get("classificazione") and d["classificazione"] != r.get("esito_analisi"):
            cambierebbero.append(
                (nome, r.get("esito_analisi"), d["classificazione"]))
        sb.table("aziende").update({"motivazione": nuova}).eq("id", r["id"]).execute()
        riscritte += 1
        print(f"[{i}/{len(fuori)}] {nome}")

    print(f"\nriscritte: {riscritte}")
    print(f"saltate:   {len(saltate)}")
    for nome, perche in saltate[:10]:
        print(f"    {nome[:38]:<40} {perche}")
    print(f"\nCLASSIFICAZIONI CHE SAREBBERO CAMBIATE (non applicate): "
          f"{len(cambierebbero)}")
    for nome, prima, dopo in cambierebbero:
        print(f"    {nome[:38]:<40} {prima} -> {dopo}")
    costi.stampa(totali)
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        righe = [
            {"classe": "A", "stato": "da_lavorare", "sito": "http://x.it",
             "motivazione": "rientra nella regola 3: vende al finale"},
            {"classe": "A", "stato": "da_lavorare", "sito": "http://y.it",
             "motivazione": "produce grate in acciaio, con officina propria"},
            {"classe": "A", "stato": "scartato", "sito": "http://z.it",
             "motivazione": "regola 1"},                      # scartata: no
            {"classe": "B", "stato": "da_lavorare", "sito": "http://w.it",
             "motivazione": "regola 3"},                      # altra classe
            {"classe": "A", "stato": "da_lavorare", "sito": "",
             "motivazione": "regola 3"},                      # senza sito
            {"classe": "A", "stato": "da_lavorare", "sito": "http://v.it",
             "motivazione": "la classificazione INDETERMINATO e' corretta"},
        ]
        scelte = da_riscrivere(righe, "A")
        assert len(scelte) == 2, scelte
        assert all("y.it" not in (r["sito"] or "") for r in scelte)
        assert len(da_riscrivere(righe, "B")) == 1
        print("ok")
    else:
        sys.exit(main())
