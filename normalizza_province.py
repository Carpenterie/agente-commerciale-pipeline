"""Porta il campo `provincia` dell'archivio alla sola sigla a due lettere.

Il modello restituiva `sede_provincia` a volte come sigla e a volte per
esteso, e in archivio finivano come valori distinti: il menu di filtro
dell'app mostrava "FR" e "Frosinone" come due voci, e chi ne sceglieva una
perdeva meta' delle aziende.

Da qui in avanti ci pensa `db.riga_azienda` (via `config.sigla_provincia`).
Questo comando sistema le righe gia' scritte, senza rianalizzare.

    python normalizza_province.py             # elenco, non scrive
    python normalizza_province.py --applica   # scrive
"""

from __future__ import annotations

import collections
import sys

import config
import db


def da_correggere(righe: list[dict]) -> list[tuple[dict, str]]:
    """-> [(riga, sigla_nuova)] solo dove il valore cambia davvero."""
    fuori = []
    for r in righe:
        vecchio = (r.get("provincia") or "").strip()
        if not vecchio:
            continue
        nuovo = config.sigla_provincia(vecchio)
        if nuovo and nuovo != vecchio:
            fuori.append((r, nuovo))
    return fuori


def main() -> int:
    applica = "--applica" in sys.argv
    sb = db.client()
    righe, off = [], 0
    while True:
        b = sb.table("aziende").select("id,ragione_sociale,provincia").range(
            off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            break
        off += 1000

    fuori = da_correggere(righe)
    print(f"righe in archivio: {len(righe)}")
    print(f"da correggere:     {len(fuori)}\n")
    for (vecchio, nuovo), n in sorted(collections.Counter(
            ((r.get("provincia"), s) for r, s in fuori)).items(),
            key=lambda x: -x[1]):
        print(f"  {vecchio:<14} -> {nuovo}   {n:>4} righe")

    # cio' che resta fuori tabella: va guardato, non corretto alla cieca
    ignoti = {(r.get("provincia") or "").strip() for r in righe
              if (r.get("provincia") or "").strip()
              and len((r.get("provincia") or "").strip()) != 2
              and (r.get("provincia") or "").strip().lower()
              not in config.SIGLE_PROVINCE}
    if ignoti:
        print(f"\n  NON in SIGLE_PROVINCE, lasciate invariate: {sorted(ignoti)}")

    if not fuori or not applica:
        if fuori:
            print("\n(prova: nessuna scrittura. Rilancia con --applica)")
        return 0
    for r, nuovo in fuori:
        sb.table("aziende").update({"provincia": nuovo}).eq("id", r["id"]).execute()
    print(f"\n{len(fuori)} righe corrette.")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        righe = [{"provincia": "Roma"}, {"provincia": "RM"}, {"provincia": ""},
                 {"provincia": None}, {"provincia": "Frosinone"},
                 {"provincia": "Oltrepo"}]
        esiti = da_correggere(righe)
        assert [s for _, s in esiti] == ["RM", "FR"], esiti
        # una sigla gia' giusta non si riscrive, e l'ignota non si tocca
        assert not any(r.get("provincia") in ("RM", "Oltrepo") for r, _ in esiti)
        print("ok")
    else:
        sys.exit(main())
