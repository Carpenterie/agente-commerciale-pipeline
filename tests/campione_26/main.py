"""Orchestrazione: aziende.csv -> fetch -> analisi LLM -> risultati.csv + riepilogo."""

from __future__ import annotations

import asyncio
import csv
import os
import sys
from collections import Counter
from pathlib import Path

import analyze
import fetch

QUI = Path(__file__).parent
INPUT = QUI / "aziende.csv"
OUTPUT = QUI / "risultati.csv"

COLONNE = [
    "nome", "url", "esito_fetch", "materiali_rilevati", "lavora_acciaio",
    "capacita_officina", "classificazione", "confidenza", "motivazione",
    "segnali_positivi", "segnali_dubbio", "prodotto_da_proporre",
    "pagine_analizzate", "token_input", "token_output", "costo_stimato_eur",
]

VUOTO = {c: "" for c in COLONNE[3:12]}


def _cella(valore) -> str:
    return "; ".join(str(v) for v in valore) if isinstance(valore, list) else str(valore)


async def processa(crawler, client, riga: dict) -> dict:
    nome, url = riga["nome"].strip(), (riga.get("url") or "").strip()
    base = {"nome": nome, "url": url, "pagine_analizzate": 0,
            "token_input": 0, "token_output": 0, "costo_stimato_eur": 0, **VUOTO}

    if not url:
        return {**base, "esito_fetch": "NO_SITO"}

    esito, contenuto, pagine = await fetch.fetch_azienda(crawler, url)
    if esito != "OK" or not contenuto.strip():
        return {**base, "esito_fetch": "FETCH_FALLITO"}

    try:
        dati = analyze.analizza(client, contenuto)
    except Exception as e:  # noqa: BLE001 - un fallimento non ferma le altre aziende
        return {**base, "esito_fetch": "ERRORE_ANALISI", "pagine_analizzate": pagine,
                "motivazione": f"{type(e).__name__}: {e}"}

    return {**base, "esito_fetch": "OK", "pagine_analizzate": pagine, **dati}


def leggi_aziende(path: Path) -> list[dict]:
    """CSV con separatore ',' o ';' (Numbers/Excel in locale italiano esportano ';')."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        intestazione = f.readline()
        f.seek(0)
        sep = ";" if intestazione.count(";") > intestazione.count(",") else ","
        righe = list(csv.DictReader(f, delimiter=sep))

    mancanti = {"nome", "url"} - set(righe[0] if righe else {})
    if mancanti:
        raise SystemExit(f"{path}: colonne mancanti {sorted(mancanti)} (attese: nome,url,note)")

    return [
        {"nome": (r["nome"] or "").strip(), "url": (r["url"] or "").strip()}
        for r in righe
        if (r["nome"] or "").strip()
    ]


def carica_esistenti(path: Path) -> dict[tuple[str, str], dict]:
    """Righe già analizzate con successo, per non ripagare la chiamata LLM.

    Chiave (nome, url): se correggi una url, l'azienda viene rianalizzata.
    I fetch falliti non entrano qui, così al rilancio ci si riprova (costo zero).
    Per rifare tutto da capo: cancella risultati.csv.
    """
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        righe = [r for r in csv.DictReader(f) if r.get("esito_fetch") == "OK"]

    for r in righe:  # il CSV è tutto stringhe, il riepilogo somma numeri
        for campo, tipo in (("pagine_analizzate", int), ("token_input", int),
                            ("token_output", int), ("costo_stimato_eur", float)):
            r[campo] = tipo(r[campo] or 0)
    return {(r["nome"], r["url"]): r for r in righe}


def riepiloga(righe: list[dict]) -> None:
    esiti = Counter(r["esito_fetch"] for r in righe)
    analizzate = [r for r in righe if r["esito_fetch"] == "OK"]
    tok_in = sum(r["token_input"] for r in righe)
    tok_out = sum(r["token_output"] for r in righe)
    costo = sum(r["costo_stimato_eur"] for r in righe)

    print("\n" + "=" * 60)
    print(f"Aziende totali:        {len(righe)}")
    print(f"  sito raggiungibile:  {esiti['OK']}")
    print(f"  senza sito:          {esiti['NO_SITO']}")
    print(f"  fetch fallito:       {esiti['FETCH_FALLITO']}")
    print(f"  errore analisi:      {esiti['ERRORE_ANALISI']}")

    for etichetta, campo, valori in [
        ("Classificazioni", "classificazione", ("TARGET", "NON_TARGET", "INDETERMINATO")),
        ("Confidenza", "confidenza", ("ALTA", "MEDIA", "BASSA")),
    ]:
        conta = Counter(r[campo] for r in analizzate)
        print(f"\n{etichetta}:")
        for v in valori:
            print(f"  {v:<16} {conta[v]}")

    print(f"\nToken input:  {tok_in:,}")
    print(f"Token output: {tok_out:,}")
    print(f"Costo totale stimato: {costo:.4f} EUR")
    if analizzate:
        print(f"Costo medio per azienda analizzata: {costo / len(analizzate):.4f} EUR")
    print("=" * 60)


async def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(QUI / ".env")
    chiave = os.environ.get("ANTHROPIC_API_KEY", "")
    if not chiave.startswith("sk-ant-"):
        raise SystemExit(
            f"Chiave API mancante. Aprire {QUI / '.env'} e incollarla dopo ANTHROPIC_API_KEY="
        )

    from anthropic import Anthropic
    from crawl4ai import AsyncWebCrawler

    aziende = leggi_aziende(INPUT)
    if len(sys.argv) > 1:  # "python main.py 3" -> prova solo le prime 3
        aziende = aziende[: int(sys.argv[1])]

    esistenti = carica_esistenti(OUTPUT)
    da_fare = sum(1 for a in aziende if (a["nome"], a["url"]) not in esistenti)
    print(f"{len(aziende)} aziende: {len(aziende) - da_fare} già analizzate, {da_fare} da analizzare.")

    client = Anthropic()
    righe: list[dict] = []

    async with AsyncWebCrawler(verbose=False) as crawler:
        for i, azienda in enumerate(aziende, 1):
            gia_fatta = esistenti.get((azienda["nome"], azienda["url"]))
            riga = gia_fatta or await processa(crawler, client, azienda)
            righe.append(riga)
            print(f"[{i}/{len(aziende)}] {riga['nome']} | {riga['esito_fetch']} | "
                  f"{riga['classificazione'] or '-'} | {riga['confidenza'] or '-'}"
                  f"{'  (già analizzata)' if gia_fatta else ''}")

    with OUTPUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNE)
        w.writeheader()
        for riga in righe:
            w.writerow({c: _cella(riga[c]) for c in COLONNE})

    riepiloga(righe)
    print(f"\nScritto: {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
