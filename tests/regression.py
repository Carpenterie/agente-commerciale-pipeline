"""Regression test del prompt (PRD §8): `python -m tests.regression`.

Rilancia le 26 aziende del campione dalla cache (zero fetch) con il
classify.py e il prompts.py DI PRODUZIONE — il guardiano protegge il file
che gira davvero — e confronta con le classificazioni validate in
tests/campione_26/risultati.csv. Una classificazione validata che cambia =
ci si ferma e si capisce perché. Si esegue prima di ogni commit che tocca
prompts.py.
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

# classify (e il suo `import prompts`) DEVE risolversi sulla radice del repo
# PRIMA di mettere il campione nel path: anche il campione ha un prompts.py
import classify  # noqa: E402  (produzione)

CAMPIONE = Path(__file__).parent / "campione_26"
sys.path.insert(0, str(CAMPIONE))

import fetch  # noqa: E402  (dal campione: cache piatta in tests/campione_26/cache)
import main as _main_campione  # noqa: E402  (COLONNE del CSV di baseline)

COLONNE_BASELINE = _main_campione.COLONNE


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")

    from anthropic import Anthropic

    client = Anthropic()

    with (CAMPIONE / "risultati.csv").open(encoding="utf-8", newline="") as f:
        baseline = [r for r in csv.DictReader(f) if r["esito_fetch"] == "OK"]

    print(f"Regression su {len(baseline)} aziende validate (dalla cache).\n")
    differenze, avvisi, costo = [], [], 0.0
    # le righe non-OK (fetch fallito) restano com'erano: non si riclassificano
    with (CAMPIONE / "risultati.csv").open(encoding="utf-8", newline="") as f:
        righe_nuove = [r for r in csv.DictReader(f) if r["esito_fetch"] != "OK"]

    for i, atteso in enumerate(baseline, 1):
        nome, url = atteso["nome"], atteso["url"]
        # crawler=None: con la cache completa non viene mai toccato
        esito, contenuto, pagine = asyncio.run(fetch.fetch_azienda(None, url))
        if esito != "OK":
            differenze.append(f"{nome}: cache incompleta, fetch {esito}")
            print(f"[{i}/{len(baseline)}] {nome} | CACHE MANCANTE")
            continue

        dati = classify.classifica(client, contenuto)
        costo += dati["costo_analisi_eur"]

        ok = dati["classificazione"] == atteso["classificazione"]
        if not ok:
            differenze.append(
                f"{nome}: {atteso['classificazione']} -> {dati['classificazione']}"
                f"  ({dati['motivazione']})"
            )
        if dati["confidenza"] != atteso["confidenza"]:
            avvisi.append(f"{nome}: confidenza {atteso['confidenza']} -> {dati['confidenza']}")
        righe_nuove.append({**atteso, "pagine_analizzate": pagine,
                            "costo_stimato_eur": dati["costo_analisi_eur"],
                            **{c: "; ".join(v) if isinstance(v, list) else v
                               for c, v in dati.items() if c in COLONNE_BASELINE}})
        if pagine != int(atteso["pagine_analizzate"]):
            avvisi.append(f"{nome}: pagine {atteso['pagine_analizzate']} -> {pagine}")

        print(f"[{i}/{len(baseline)}] {nome} | {dati['classificazione']} | "
              f"{'ok' if ok else 'DIVERSA (era ' + atteso['classificazione'] + ')'}")

    if "--salva" in sys.argv:
        # ricongelamento: la baseline diventa questo run. Si usa DOPO che
        # l'utente ha validato le differenze, mai in automatico.
        import csv as _csv

        with (CAMPIONE / "risultati.csv").open("w", encoding="utf-8",
                                               newline="") as f:
            w = _csv.DictWriter(f, fieldnames=COLONNE_BASELINE)
            w.writeheader()
            for r in righe_nuove:
                w.writerow({c: r.get(c, "") for c in COLONNE_BASELINE})
        print(f"\nBaseline ricongelata: {len(righe_nuove)} righe in "
              f"{CAMPIONE / 'risultati.csv'}")

    print(f"\nCosto del run: {costo:.4f} EUR")
    if avvisi:
        print("\nAvvisi (non bloccanti):")
        for a in avvisi:
            print(f"  - {a}")
    if differenze:
        print(f"\nFALLITO: {len(differenze)} classificazioni cambiate:")
        for d in differenze:
            print(f"  - {d}")
        return 1
    print(f"\nPASSATO: {len(baseline)}/{len(baseline)} classificazioni identiche.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
