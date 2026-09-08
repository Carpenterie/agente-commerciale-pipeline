"""Toglie dall'archivio le righe che sono PAGINE DI PORTALE, non aziende.

Usa `config.PORTALI_INTERMEDIAZIONE` e NON l'intera `PORTALI_ESCLUSI`: in
quella ci sono anche i social, e un'azienda vera il cui unico sito e' una
pagina Facebook deve restare in archivio. Sono due casi diversi — sito
debole contro azienda inesistente — e la motivazione dello scarto sarebbe
falsa sulla prima.

Non cancella: mette `stato='scartato'` con il motivo in testa alla
motivazione, come per i clienti attivi. Reversibile e tracciabile.

    python scarta_portali.py            # elenco, non scrive
    python scarta_portali.py --scarta   # scrive
"""

from __future__ import annotations

import sys

import config
import db
import dedup

MOTIVO = "SCARTATA: portale di intermediazione, non un'azienda produttrice"


def e_intermediazione(sito: str) -> bool:
    s = (sito or "").lower()
    return any(d in s for d in config.PORTALI_INTERMEDIAZIONE)


def da_scartare(righe: list[dict]) -> list[dict]:
    return [r for r in righe
            if r.get("stato") != "scartato" and e_intermediazione(r.get("sito") or "")]


def main() -> int:
    scarta = "--scarta" in sys.argv
    sb = db.client()
    righe, off = [], 0
    while True:
        b = sb.table("aziende").select(
            "id,ragione_sociale,comune,classe,stato,sito,motivazione").range(
            off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            break
        off += 1000

    fuori = da_scartare(righe)
    print(f"righe in archivio: {len(righe)}")
    print(f"da scartare come portali: {len(fuori)}\n")
    for r in fuori:
        print(f"  {(r['ragione_sociale'] or '')[:44]:<46} {r['classe']:<14}"
              f" {(r.get('sito') or '')[:40]}")
    if not fuori:
        return 0
    if not scarta:
        print("\n(prova: nessuna scrittura. Rilancia con --scarta)")
        return 0
    for r in fuori:
        sb.table("aziende").update({
            "stato": "scartato",
            "motivazione": f"{MOTIVO} — " + (r.get("motivazione") or ""),
        }).eq("id", r["id"]).execute()
    print(f"\n{len(fuori)} righe messe in stato 'scartato'.")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        righe = [
            {"sito": "https://www.archisio.it/imprese", "stato": "da_lavorare"},
            {"sito": "https://fabbro.roma.it/x", "stato": "da_lavorare"},
            {"sito": "https://carpenteriabianchini.it/", "stato": "da_lavorare"},
            {"sito": "", "stato": "da_lavorare"},
            {"sito": "https://archisio.it/x", "stato": "scartato"},  # gia' fuori
        ]
        assert len(da_scartare(righe)) == 2, da_scartare(righe)
        # un'azienda vera con la sola pagina Facebook NON si scarta
        assert not e_intermediazione("https://www.facebook.com/toncheisrl")
        assert not e_intermediazione("https://sites.google.com/view/bottega")
        assert e_intermediazione("https://fabbro.assisitop.it/")
        # ma per il sourcing resta un portale: non si parte da li'
        assert dedup.e_portale("https://www.facebook.com/toncheisrl")
        assert MOTIVO.startswith("SCARTATA:")
        print("ok")
    else:
        sys.exit(main())
