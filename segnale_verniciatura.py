"""Aggiunge il segnale `verniciatura_interna` alle righe GIA' in archivio.

Il segnale nasce col catalogo del 2026-09 e la pipeline lo scrive da sola
sui cicli nuovi, ma il cron e' fermo: senza questo, le 1169 aziende gia'
analizzate non lo avrebbero mai. Rilegge `materiali` e `motivazione`, che
sono gia' in tabella: non rianalizza e non spende.

    python segnale_verniciatura.py             # elenco, non scrive
    python segnale_verniciatura.py --applica   # scrive
"""

from __future__ import annotations

import collections
import sys

import config
import db


def da_marcare(righe: list[dict]) -> list[dict]:
    fuori = []
    for r in righe:
        if r.get("stato") == "scartato":
            continue
        segnali = r.get("segnali") or []
        if any(s.get("tipo") == "verniciatura_interna" for s in segnali):
            continue                      # gia' marcata: il comando e' ripetibile
        if db.verniciatura_interna({"materiali_rilevati": r.get("materiali"),
                                    "motivazione": r.get("motivazione")}):
            fuori.append(r)
    return fuori


def main() -> int:
    applica = "--applica" in sys.argv
    sb = db.client()
    righe, off = [], 0
    while True:
        b = sb.table("aziende").select(
            "id,ragione_sociale,classe,stato,materiali,motivazione,segnali").range(
            off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            break
        off += 1000

    fuori = da_marcare(righe)
    print(f"righe in archivio: {len(righe)}")
    print(f"da marcare 'verniciatura_interna': {len(fuori)}")
    print(f"  per classe: {dict(collections.Counter(r['classe'] for r in fuori))}\n")
    for r in fuori[:15]:
        print(f"  {(r['ragione_sociale'] or '')[:38]:<40} {r['classe']}")
    if len(fuori) > 15:
        print(f"  … e altre {len(fuori) - 15}")

    if not fuori or not applica:
        if fuori:
            print("\n(prova: nessuna scrittura. Rilancia con --applica)")
        return 0
    for r in fuori:
        segnali = list(r.get("segnali") or [])
        segnali.append({"tipo": "verniciatura_interna",
                        "nota": config.NOTA_VERNICIATURA})
        sb.table("aziende").update({"segnali": segnali}).eq("id", r["id"]).execute()
    print(f"\n{len(fuori)} aziende marcate.")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        righe = [
            {"motivazione": "zincatura interna", "stato": "da_lavorare", "segnali": []},
            {"motivazione": "vende pvc", "stato": "da_lavorare", "segnali": []},
            {"motivazione": "zincatura", "stato": "scartato", "segnali": []},
            {"motivazione": "zincatura", "stato": "da_lavorare",
             "segnali": [{"tipo": "verniciatura_interna"}]},      # gia' fatta
        ]
        assert len(da_marcare(righe)) == 1, da_marcare(righe)
        print("ok")
    else:
        sys.exit(main())
