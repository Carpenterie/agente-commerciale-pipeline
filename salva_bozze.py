"""Scrive in archivio la bozza di ogni scheda in classe A, B o C.

`bozze_email.py` genera UNA bozza per volta, su richiesta, ed e' giusto
cosi' per chi lavora da riga di comando. Ma l'app Lovable non esegue Python
e non puo' chiamare il modello: la bozza personalizzata la vede solo se
qualcuno gliela mette nel database. Quindi si generano in blocco e si
salvano, e l'app legge cinque colonne invece di ricostruire il testo.

La bozza salvata e' un PUNTO DI PARTENZA: il commerciale la modifica prima
di inviare, e quello che parte davvero resta in `attivita`. Nessuno rilegge
queste colonne per sapere cosa e' stato mandato.

    python salva_bozze.py                 # prova: quante, quali testi, stima
    python salva_bozze.py --scrivi        # genera e SALVA le schede SENZA bozza
    python salva_bozze.py --scrivi --classe A
    python salva_bozze.py --scrivi --rigenera   # riscrive anche quelle che ce l'hanno
    python salva_bozze.py --scrivi --ripieghi   # solo quelle finite sul testo fisso

Di suo tocca SOLO le schede senza bozza: chi lo rilancia per sbaglio non
cancella niente. Serve `--rigenera` per riscriverle, e va usato dopo una
rianalisi che tocchi leva_commerciale, gamma o livello_fornitura — sono gli
ingressi della personalizzazione, e una bozza vecchia racconta una scheda
che non esiste piu'.

`bozza_corpo` resta sempre la bozza GENERATA: l'app non ci riscrive sopra
la versione modificata dal commerciale, quella vive in `attivita`, che e'
il registro di cosa e' partito davvero.
"""

from __future__ import annotations

import collections as _c
import datetime
import pathlib
import sys

import bozze_email
import costi
import db

# Le colonne che questo script DEVE scrivere. Stessa guardia di
# arricchisci_schede.py, per lo stesso motivo: il 2026-09-15 due campi
# dichiarati e mai scritti sono costati 265 schede e 20 EUR da rifare.
CAMPI_SCRITTI = ("bozza_oggetto", "bozza_corpo", "bozza_testo_id",
                 "bozza_generata", "bozza_creata_il")

CAMPI_LETTI = ("id,ragione_sociale,classe,stato,categoria,livello_fornitura,"
               "segnali,materiali,gamma,comune,officina_propria,"
               "prodotto_apertura,leva_commerciale,referente_nome,"
               "referente_ruolo,bozza_corpo,bozza_generata")


def da_scrivere(righe: list[dict], classi: list[str], solo_mancanti: bool,
                solo_ripieghi: bool = False) -> list[dict]:
    vive = [r for r in righe
            if r.get("classe") in classi and r.get("stato") != "scartato"]
    if solo_ripieghi:
        return [r for r in vive if r.get("bozza_generata") is False]
    return [r for r in vive
            if not (solo_mancanti and (r.get("bozza_corpo") or "").strip())]


def main() -> int:
    scrivi = "--scrivi" in sys.argv
    solo_ripieghi = "--ripieghi" in sys.argv
    solo_mancanti = "--rigenera" not in sys.argv
    classe = sys.argv[sys.argv.index("--classe") + 1] if "--classe" in sys.argv else "TUTTE"
    classi = ["A", "B", "C"] if classe == "TUTTE" else [classe]

    sb = db.client()
    righe, off = [], 0
    while True:
        b = sb.table("aziende").select(CAMPI_LETTI).range(off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            break
        off += 1000

    fuori = da_scrivere(righe, classi, solo_mancanti, solo_ripieghi)
    if solo_ripieghi:
        print("--ripieghi: solo le bozze finite sul testo approvato")
    elif not solo_mancanti:
        print("--rigenera: riscrive anche le bozze gia' in archivio")
    scelte = _c.Counter(bozze_email.scegli_testo(r) or "NESSUNA" for r in fuori)
    print(f"classi {','.join(classi)}: {len(fuori)} schede")
    for testo_id, n in scelte.most_common():
        print(f"    {testo_id:<24}{n:>5}")
    if not scrivi:
        print("\n(prova: nessuna chiamata al modello. Rilancia con --scrivi)")
        return 0

    from anthropic import Anthropic

    client = Anthropic(max_retries=1)
    totali = costi.nuovo_ciclo()
    salvate, ripieghi, senza, errori = 0, [], [], []
    lunghezze = []
    for i, r in enumerate(fuori, 1):
        nome = (r["ragione_sociale"] or "?")[:38]
        bozza = bozze_email.genera(r, client, log=lambda m: None)
        if bozza is None:
            senza.append(nome)
            continue
        costi.registra_analisi(totali, bozza.get("token_input", 0),
                               bozza.get("token_output", 0))
        problemi = bozze_email.verifica(bozza)
        if problemi:
            # non deve succedere: il ripiego e' un testo approvato e le
            # generate sono gia' passate da verifica(forma=True). Se
            # succede, la bozza NON si salva.
            errori.append((nome, "; ".join(problemi)))
            continue
        if not bozza["generata"]:
            ripieghi.append(nome)
        lunghezze.append(len(bozze_email._senza_accessori(bozza["corpo"]).split()))
        agg = {
            "bozza_oggetto": bozza["oggetto"],
            "bozza_corpo": bozza["corpo"],
            "bozza_testo_id": bozza["testo_id"],
            "bozza_generata": bool(bozza["generata"]),
            "bozza_creata_il": datetime.datetime.now(
                datetime.timezone.utc).isoformat(timespec="seconds"),
        }
        sb.table("aziende").update(agg).eq("id", r["id"]).execute()
        salvate += 1
        if i % 20 == 0:
            print(f"  [{i}/{len(fuori)}]", flush=True)

    quota = 100 * len(ripieghi) / salvate if salvate else 0
    lunghezze.sort()
    print(f"\nsalvate: {salvate}")
    print(f"  personalizzate: {salvate - len(ripieghi)}")
    print(f"  ripiego sul testo approvato: {len(ripieghi)}  ({quota:.0f}%)")
    for n in ripieghi[:10]:
        print(f"      {n}")
    if lunghezze:
        print(f"  parole: {lunghezze[0]}-{lunghezze[-1]}, "
              f"mediana {lunghezze[len(lunghezze) // 2]}")
    print(f"  nessun testo applicabile (scheda da leggere a mano): {len(senza)}")
    for n in senza:
        print(f"      {n}")
    if errori:
        print(f"\n!! NON SALVATE, bozza fuori regola: {len(errori)}")
        for n, p in errori:
            print(f"      {n:<40} {p}")
    costi.stampa(totali)
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        righe = [{"classe": "A", "stato": "da_lavorare", "bozza_corpo": None},
                 {"classe": "A", "stato": "scartato", "bozza_corpo": None},
                 {"classe": "B", "stato": "da_lavorare", "bozza_corpo": "gia' fatta"},
                 {"classe": None, "stato": "da_lavorare", "bozza_corpo": None}]
        assert len(da_scrivere(righe, ["A", "B", "C"], False)) == 2
        assert len(da_scrivere(righe, ["A", "B", "C"], True)) == 1
        assert len(da_scrivere(righe, ["A"], False)) == 1
        ripieghi = [{"classe": "A", "stato": "da_lavorare", "bozza_generata": False},
                    {"classe": "A", "stato": "da_lavorare", "bozza_generata": True},
                    {"classe": "A", "stato": "da_lavorare", "bozza_generata": None},
                    {"classe": "A", "stato": "scartato", "bozza_generata": False}]
        assert len(da_scrivere(ripieghi, ["A"], True, True)) == 1
        # ogni campo dichiarato deve comparire davvero nell'update
        sorgente = pathlib.Path(__file__).read_text(encoding="utf-8")
        corpo = sorgente[sorgente.index("agg = {"):sorgente.index(".update(agg)")]
        for campo in CAMPI_SCRITTI:
            assert f'"{campo}"' in corpo, f"{campo} dichiarato ma mai scritto"
        # le colonne lette devono bastare a scegliere e a comporre il testo
        for campo in ("categoria", "livello_fornitura", "segnali", "materiali",
                      "gamma", "leva_commerciale", "referente_ruolo"):
            assert campo in CAMPI_LETTI, campo
        print("ok")
    else:
        sys.exit(main())
