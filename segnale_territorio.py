"""Aggiunge il segnale `territorio` alle righe fuori Lazio che ne sono prive.

Le aziende dei primi cicli sono state scritte quando il segnale territoriale
non veniva registrato in questa forma: nell'app compaiono nell'elenco
normale e le loro province finiscono nel menu di filtro.

Tocca SOLO le righe con una provincia valorizzata e non laziale, e SOLO il
campo `segnali`. Chi il segnale ce l'ha gia' non viene toccato, quindi il
comando e' ripetibile.

Le righe SENZA provincia non si marcano: non sappiamo dove siano, e
inventare un "fuori" sarebbe peggio del vuoto.

    python segnale_territorio.py             # elenco, non scrive
    python segnale_territorio.py --applica   # scrive
"""

from __future__ import annotations

import collections
import sys

import config
import db


def ha_territorio(riga: dict) -> bool:
    return any(s.get("tipo") == "territorio" for s in (riga.get("segnali") or []))


def da_marcare(righe: list[dict]) -> list[dict]:
    lazio = set(config.PROVINCE)
    return [r for r in righe
            if r.get("stato") != "scartato"
            and (r.get("provincia") or "").strip()
            and r["provincia"].strip().upper() not in lazio
            and not ha_territorio(r)]


def segnale(provincia: str) -> dict:
    return {"tipo": "territorio", "esito": "fuori",
            "segnale": f"provincia {provincia.strip().upper()} "
                       f"fuori dal territorio di ricerca"}


def main() -> int:
    applica = "--applica" in sys.argv
    sb = db.client()
    righe, off = [], 0
    while True:
        b = sb.table("aziende").select(
            "id,ragione_sociale,provincia,stato,segnali").range(
            off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            break
        off += 1000

    fuori = da_marcare(righe)
    vive = [r for r in righe if r.get("stato") != "scartato"]
    senza = [r for r in vive if not (r.get("provincia") or "").strip()]
    print(f"righe consegnabili: {len(vive)}")
    print(f"  da marcare come fuori territorio: {len(fuori)}")
    print(f"  province: {dict(collections.Counter(r['provincia'].strip().upper() for r in fuori).most_common(8))}")
    print(f"  senza provincia, non classificabili: {len(senza)} "
          f"(di cui {sum(1 for r in senza if not ha_territorio(r))} anche senza segnale)")

    if not fuori or not applica:
        if fuori:
            print("\n(prova: nessuna scrittura. Rilancia con --applica)")
        return 0
    for r in fuori:
        segnali = list(r.get("segnali") or [])
        segnali.append(segnale(r["provincia"]))
        sb.table("aziende").update({"segnali": segnali}).eq("id", r["id"]).execute()
    print(f"\n{len(fuori)} righe marcate.")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        righe = [
            {"provincia": "MI", "stato": "da_lavorare", "segnali": []},
            {"provincia": "RM", "stato": "da_lavorare", "segnali": []},   # laziale
            {"provincia": "", "stato": "da_lavorare", "segnali": []},     # ignota
            {"provincia": "BG", "stato": "scartato", "segnali": []},      # scartata
            {"provincia": "CO", "stato": "da_lavorare",                   # gia' fatta
             "segnali": [{"tipo": "territorio", "esito": "fuori"}]},
            {"provincia": " mi ", "stato": "da_lavorare",
             "segnali": [{"tipo": "reputazione_google"}]},
        ]
        scelte = da_marcare(righe)
        assert len(scelte) == 2, scelte
        s = segnale(" mi ")
        assert s["esito"] == "fuori" and s["segnale"].startswith("provincia MI"), s
        # il segnale si AGGIUNGE, non sostituisce
        assert len(righe[5]["segnali"]) == 1
        print("ok")
    else:
        sys.exit(main())
