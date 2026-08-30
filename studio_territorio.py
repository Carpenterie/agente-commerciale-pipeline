"""Studio del territorio: conteggi per provincia, categoria e classe.

    python studio_territorio.py            # prospetto a schermo
    python studio_territorio.py --csv      # per il cliente

Legge la vista `studio_territorio` (studio_territorio.sql). L'etichetta
sulla natura del dato è nella vista stessa e viene stampata sempre: il
conteggio dice quante aziende IL SISTEMA ha individuato, non quante ne
esistono sul territorio.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter

import db

ETICHETTA = ("Aziende individuate e classificate dal sistema — "
             "non è un censimento del mercato")


def leggi(sb) -> list[dict]:
    return sb.table("studio_territorio").select("*").execute().data or []


def prospetto(righe: list[dict], log=print) -> None:
    log("=" * 74)
    log(ETICHETTA.upper())
    log("Il totale dipende dalle query di sourcing e dai comuni interrogati.")
    log("=" * 74)
    if not righe:
        log("\nNessuna azienda in archivio: il primo ciclo non è ancora stato "
            "eseguito (finora solo --dry-run).")
        return

    tot = sum(r["aziende"] for r in righe)
    for chiave, titolo in (("provincia", "PER PROVINCIA"),
                           ("categoria", "PER CATEGORIA"),
                           ("classe", "PER CLASSE")):
        conta = Counter()
        for r in righe:
            conta[r[chiave]] += r["aziende"]
        log(f"\n{titolo}")
        for valore, n in conta.most_common():
            log(f"  {valore:<28} {n:>5}  ({100 * n / tot:.1f}%)")

    log("\nDI CUI")
    for campo, etichetta in (("di_cui_target", "classificate TARGET"),
                             ("di_cui_senza_sito", "senza sito (recapiti Maps)"),
                             ("di_cui_con_segnale_lavoro", "con annuncio di lavoro"),
                             ("di_cui_ex_clienti", "già clienti in passato")):
        log(f"  {etichetta:<28} {sum(r[campo] for r in righe):>5}")
    log(f"\n  {'TOTALE':<28} {tot:>5}")
    log("=" * 74)


def main() -> int:
    righe = leggi(db.client())
    if "--csv" in sys.argv:
        w = csv.DictWriter(sys.stdout, fieldnames=list(righe[0]) if righe else ["vuoto"])
        w.writeheader()
        w.writerows(righe)
        return 0
    prospetto(righe)
    return 0


if __name__ == "__main__" and "--test" in sys.argv:
    finte = [
        {"provincia": "RM", "categoria": "fabbro", "classe": "A", "aziende": 10,
         "di_cui_target": 10, "di_cui_senza_sito": 0,
         "di_cui_con_segnale_lavoro": 2, "di_cui_ex_clienti": 1},
        {"provincia": "RM", "categoria": "serramentista", "classe": "B", "aziende": 30,
         "di_cui_target": 30, "di_cui_senza_sito": 5,
         "di_cui_con_segnale_lavoro": 0, "di_cui_ex_clienti": 3},
        {"provincia": "LT", "categoria": "fabbro", "classe": "indeterminato",
         "aziende": 10, "di_cui_target": 0, "di_cui_senza_sito": 10,
         "di_cui_con_segnale_lavoro": 0, "di_cui_ex_clienti": 0},
    ]
    righe = []
    prospetto(finte, log=righe.append)
    testo = "\n".join(righe)
    # l'etichetta non è opzionale: deve stare in cima al prospetto
    assert ETICHETTA.upper() in testo
    assert "non è un censimento" in testo.lower()
    assert "RM" in testo and "LT" in testo
    assert "50" in testo                       # totale 10+30+10
    assert "già clienti in passato" in testo
    # e con archivio vuoto lo dice, invece di stampare zeri
    vuoto = []
    prospetto([], log=vuoto.append)
    assert "non è ancora stato eseguito" in "\n".join(vuoto)
    print("ok")
elif __name__ == "__main__":
    raise SystemExit(main())
