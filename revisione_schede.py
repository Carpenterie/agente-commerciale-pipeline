"""Schede da leggere insieme al committente nella sessione di revisione.

Estrae N schede a caso di una classe e le stampa per esteso, una per
schermata, con una riga vuota per il giudizio. Serve a farsi dire "questa la
chiamerei, questa no" mentre si e' collegati, e a registrare la risposta
subito invece che a memoria.

    python revisione_schede.py                        # 20 di classe A
    python revisione_schede.py --numero 30 --classe B
    python revisione_schede.py --seme 7               # ripesca le STESSE
    python revisione_schede.py --csv revisione.csv    # e le esporta

Il `--seme` serve se la chiamata cade o si riprende un altro giorno: con lo
stesso numero si riottengono le stesse schede nello stesso ordine.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import textwrap

import config  # noqa: F401  - imposta SSL_CERT_FILE
import db

CAMPI_CSV = ("n", "ragione_sociale", "comune", "categoria", "classe",
             "materiali", "officina", "segnali", "sito", "motivazione",
             "giudizio_CHIAMERei_SI_NO", "note_del_committente")


def _righe(campo) -> str:
    """I campi jsonb arrivano come liste o come stringhe, a seconda."""
    if isinstance(campo, list):
        return ", ".join(str(x) for x in campo if x)
    return str(campo or "").strip()


def _segnali(segnali) -> str:
    fuori = []
    for s in segnali or []:
        t = s.get("tipo", "?")
        if t == "annuncio_lavoro":
            fuori.append(f"annuncio di lavoro ({s.get('ruolo', '?')})")
        elif t == "reputazione_google":
            fuori.append(f"Google {s.get('punteggio', '?')}★ "
                         f"su {s.get('recensioni', '?')} recensioni")
        elif t == "ex_cliente":
            fuori.append(f"EX CLIENTE — {s.get('motivo', '')}")
        elif t == "verniciatura_interna":
            # il tipo da solo non dice niente in chiamata: l'argomento
            # commerciale e' la nota
            fuori.append(f"verniciatura interna — {s.get('nota', '')}".rstrip(" —"))
        elif t == "territorio":
            continue          # rumore in sessione: il comune si vede sopra
        else:
            fuori.append(t.replace("_", " "))
    return " | ".join(fuori) or "-"


def stampa(i: int, tot: int, r: dict, log=print) -> None:
    log("\n" + "=" * 74)
    log(f"[{i}/{tot}]  {r.get('ragione_sociale') or '(senza nome)'}")
    log("=" * 74)
    log(f"  comune      {r.get('comune') or '-'}")
    log(f"  categoria   {r.get('categoria') or '-'}"
        f"      classe {r.get('classe')}"
        f"   confidenza {r.get('confidenza') or '-'}")
    log(f"  materiali   {_righe(r.get('materiali')) or '-'}")
    log(f"  officina    {r.get('officina_propria') or '-'}"
        f"      fornitura {r.get('livello_fornitura') or '-'}")
    log(f"  sito        {r.get('sito') or '(nessuno)'}")
    log(f"  segnali     {_segnali(r.get('segnali'))}")
    log("\n  motivazione:")
    for riga in textwrap.wrap(_righe(r.get("motivazione")) or "-", 68):
        log(f"    {riga}")
    log("\n  GIUDIZIO: la chiamerebbe?  SI / NO / FORSE  ______________________")


def scegli(righe: list[dict], numero: int, seme: int) -> list[dict]:
    r = random.Random(seme)
    return r.sample(righe, min(numero, len(righe)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--numero", type=int, default=20)
    ap.add_argument("--classe", default="A", choices=list(config.ENUM_CLASSE))
    ap.add_argument("--seme", type=int, default=1,
                    help="stesso seme = stesse schede, per riprendere la sessione")
    ap.add_argument("--csv", metavar="FILE", help="esporta anche in CSV")
    args = ap.parse_args()

    sb = db.client()
    righe, off = [], 0
    while True:
        b = sb.table("aziende").select(
            "ragione_sociale,comune,categoria,classe,confidenza,materiali,"
            "officina_propria,livello_fornitura,sito,motivazione,segnali,stato"
        ).eq("classe", args.classe).range(off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            break
        off += 1000
    # le scartate non si sottopongono a giudizio: sono gia' fuori
    righe = [r for r in righe if r.get("stato") != "scartato"]

    if not righe:
        print(f"nessuna azienda in classe {args.classe}")
        return 1
    scelte = scegli(righe, args.numero, args.seme)
    print(f"{len(scelte)} schede di classe {args.classe} "
          f"(su {len(righe)} disponibili, seme {args.seme})")
    for i, r in enumerate(scelte, 1):
        stampa(i, len(scelte), r)

    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CAMPI_CSV)
            w.writeheader()
            for i, r in enumerate(scelte, 1):
                w.writerow({
                    "n": i,
                    "ragione_sociale": r.get("ragione_sociale") or "",
                    "comune": r.get("comune") or "",
                    "categoria": r.get("categoria") or "",
                    "classe": r.get("classe") or "",
                    "materiali": _righe(r.get("materiali")),
                    "officina": r.get("officina_propria") or "",
                    "segnali": _segnali(r.get("segnali")),
                    "sito": r.get("sito") or "",
                    "motivazione": _righe(r.get("motivazione")),
                    "giudizio_CHIAMERei_SI_NO": "",
                    "note_del_committente": "",
                })
        print(f"\nesportate in {args.csv} — due colonne vuote da compilare "
              f"durante la chiamata")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        assert _righe(["ferro", "acciaio"]) == "ferro, acciaio"
        assert _righe(None) == "" and _righe("  x ") == "x"
        s = _segnali([{"tipo": "annuncio_lavoro", "ruolo": "saldatore"},
                      {"tipo": "reputazione_google", "punteggio": 4.8,
                       "recensioni": 51},
                      {"tipo": "territorio", "esito": "lazio"}])
        assert "saldatore" in s and "51 recensioni" in s
        v = _segnali([{"tipo": "verniciatura_interna",
                       "nota": "può interessare l'assemblato grezzo"}])
        assert "assemblato grezzo" in v, v
        # senza nota non resta un trattino penzolante
        assert _segnali([{"tipo": "verniciatura_interna"}]) == "verniciatura interna"
        assert "territorio" not in s, "il territorio e' rumore in sessione"
        assert _segnali([]) == "-"
        # stesso seme = stesse schede, anche in giorni diversi
        finte = [{"ragione_sociale": f"az {i}"} for i in range(50)]
        assert scegli(finte, 20, 7) == scegli(finte, 20, 7)
        assert scegli(finte, 20, 7) != scegli(finte, 20, 8)
        assert len(scegli(finte, 99, 1)) == 50      # non chiede piu' di quante ce ne sono
        righe = []
        stampa(1, 1, {"ragione_sociale": "X", "motivazione": "perche' si"},
               log=righe.append)
        assert any("GIUDIZIO" in r for r in righe)
        print("ok")
    else:
        sys.exit(main())
