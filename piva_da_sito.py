"""Estrae la partita IVA dal testo del sito gia' in cache (PRD §9 agg.).

Perche' il sito e non Openapi: la P.IVA nel footer e' l'azienda che dichiara
la propria, accanto a ragione sociale, sede legale e numero REA. Openapi
invece la deduce da una ricerca per denominazione che "prende il primo" fra
gli omonimi. Misurato sulle 53 righe dove esistono entrambe: **concordano
nel 72% dei casi, e nei 15 discordi esaminati e' il sito ad avere ragione**.

Nessun sito viene riscaricato: si rilegge la cache di fetch.

    python piva_da_sito.py                    # elenco, non scrive
    python piva_da_sito.py --applica          # riempie i campi VUOTI
    python piva_da_sito.py --applica --correggi   # e corregge i discordi
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import config  # noqa: F401
import db
import dedup

ETICHETTA = re.compile(r"(?:p\.?\s*iva|partita\s+iva|vat)", re.I)
UNDICI = re.compile(r"(?<!\d)(\d{11})(?!\d)")
CACHE = pathlib.Path(__file__).parent / "cache"


def valida(piva: str) -> bool:
    """Checksum della partita IVA italiana. Senza questo, un numero di
    telefono di undici cifre passerebbe per partita IVA."""
    if len(piva) != 11 or not piva.isdigit():
        return False
    totale = 0
    for i, ch in enumerate(piva[:10]):
        d = int(ch)
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        totale += d
    return (10 - totale % 10) % 10 == int(piva[10])


def estrai(testo: str) -> str | None:
    """La prima P.IVA valida del testo. Cinque strategie diverse (prima,
    ultima, solo etichettate, solo se unica) danno lo stesso risultato sul
    campione: nelle pagine ce n'e' praticamente sempre una sola."""
    for m in UNDICI.finditer(testo or ""):
        if valida(m.group(1)):
            return m.group(1)
    return None


def testo_in_cache(sito: str) -> str:
    cartella = CACHE / dedup.dominio_azienda(sito or "")
    if not cartella.is_dir():
        return ""
    pezzi = []
    for f in cartella.glob("*.json"):
        try:
            pezzi.append(json.loads(f.read_text(encoding="utf-8")).get("markdown", ""))
        except Exception:  # noqa: BLE001 - un file illeggibile non ferma il resto
            pass
    return "".join(pezzi)


def main() -> int:
    applica = "--applica" in sys.argv
    correggi = "--correggi" in sys.argv
    classe = sys.argv[sys.argv.index("--classe") + 1] if "--classe" in sys.argv else "A"

    sb = db.client()
    righe, off = [], 0
    while True:
        b = sb.table("aziende").select(
            "id,ragione_sociale,classe,stato,sito,partita_iva,n_dipendenti,"
            "struttura,comune").range(off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            break
        off += 1000

    candidate = [r for r in righe if r["stato"] != "scartato"
                 and r["classe"] == classe and (r.get("sito") or "").strip()]
    vuote, discordi, gia_ok, non_trovate = [], [], 0, 0
    for r in candidate:
        p = estrai(testo_in_cache(r["sito"]))
        if not p:
            non_trovate += 1
            continue
        attuale = re.sub(r"\D", "", r.get("partita_iva") or "")
        if not attuale:
            vuote.append((r, p))
        elif attuale == p:
            gia_ok += 1
        else:
            discordi.append((r, attuale, p))

    print(f"classe {classe} con sito: {len(candidate)}")
    print(f"  P.IVA trovata nel testo e campo VUOTO:  {len(vuote)}   <-- da riempire")
    print(f"  trovata e uguale a quella in archivio:  {gia_ok}")
    print(f"  trovata e DIVERSA da quella di Openapi: {len(discordi)}")
    print(f"  non trovata nel testo:                  {non_trovate}\n")
    for r, vecchia, nuova in discordi:
        print(f"  {r['ragione_sociale'][:36]:<38} openapi {vecchia} -> sito {nuova}"
              f"   (dipendenti={r.get('n_dipendenti')})")

    if not applica:
        print("\n(prova: nessuna scrittura. Rilancia con --applica [--correggi])")
        return 0

    for r, p in vuote:
        sb.table("aziende").update({"partita_iva": p}).eq("id", r["id"]).execute()
    print(f"\n{len(vuote)} partite IVA scritte nei campi vuoti.")

    if correggi and discordi:
        for r, _, nuova in discordi:
            # se la P.IVA era di un'altra azienda, lo erano anche gli altri
            # dati della stessa visura: dipendenti e struttura si azzerano
            sb.table("aziende").update({
                "partita_iva": nuova, "n_dipendenti": None, "struttura": None,
            }).eq("id", r["id"]).execute()
        print(f"{len(discordi)} corrette, con dipendenti e struttura azzerati.")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        assert valida("06330721009") and valida("00844160572")
        assert not valida("06330721000")          # checksum sbagliato
        assert not valida("1234567890") and not valida("abcdefghijk")
        assert estrai("Partita IVA: 06330721009 | Privacy") == "06330721009"
        assert estrai("tel 06330721000 nessuna piva") is None   # checksum
        assert estrai("") is None and estrai(None) is None
        # un numero di telefono lungo non passa per partita IVA
        assert estrai("chiama il 39064455667") is None
        print("ok")
    else:
        sys.exit(main())
