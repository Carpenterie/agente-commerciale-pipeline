"""Solo il sourcing di una o piu' province: nessuna analisi, nessuna scrittura.

Serve a misurare quante aziende produce davvero una provincia prima di
impegnarsi con l'analisi, e a spendere il credito Apify prima che il ciclo
di fatturazione si chiuda.

Il risultato finisce in `cache/sourcing_<provincia>.json`, lo stesso file
che `main.py` rilegge: quando l'analisi partira', con `--riusa-sourcing`,
Maps ed Exa **non si ripagano**.

    python sourcing_solo.py LT FR RI
"""

from __future__ import annotations

import json
import sys
import time

import config
import costi
import dedup
import sourcing_exa
import sourcing_maps
from data.comuni_lazio import COMUNI
from main import CARTELLA_CACHE


def riepiloga(provincia: str, schede: list[dict], maps: int,
              costo_usd: float) -> dict:
    """Numeri per il preventivo: uniche dopo dedup, con sito, fuori regione."""
    uniche = dedup.dedup_interno(schede, log=lambda *a: None)
    lazio = set(config.PROVINCE)
    return {
        "provincia": provincia,
        "comuni": len(COMUNI[provincia]),
        "ricerche": len(COMUNI[provincia]) * len(config.CATEGORIE_MAPS),
        "maps": maps,
        "exa": len(schede) - maps,
        "totali": len(schede),
        "uniche": len(uniche),
        "con_sito": sum(1 for s in uniche if (s.get("sito") or "").strip()),
        "fuori_regione": sum(
            1 for s in uniche
            if (s.get("provincia") or "").strip()
            and config.sigla_provincia(s["provincia"]) not in lazio),
        "chiuse": sum(1 for s in uniche if s.get("chiusa_definitivamente")),
        "costo_usd": costo_usd,
    }


def main() -> int:
    # le chiavi stanno nel .env: senza questo APIFY_TOKEN non esiste e lo
    # script muore alla prima chiamata (main.py lo fa dentro esegui())
    from dotenv import load_dotenv

    load_dotenv()

    province = [p.upper() for p in sys.argv[1:] if p.upper() in COMUNI]
    if not province:
        print(f"uso: python sourcing_solo.py {' '.join(sorted(COMUNI))}")
        return 1

    credito = sourcing_maps.credito()
    if credito:
        print(f"credito Apify: {credito[0]:.2f}/{credito[1]:.2f} USD usati, "
              f"restano {credito[1] - credito[0]:.2f}\n")

    totali, righe = costi.nuovo_ciclo(), []
    for p in province:
        print(f"--- {config.PROVINCE[p]} ({p}): {len(COMUNI[p])} comuni")
        schede, costo = sourcing_maps.cerca(list(COMUNI[p]))
        costi.registra_apify(totali, len(schede), costo_usd=costo)
        exa = sourcing_exa.cerca(config.PROVINCE[p])
        costi.registra_exa(totali, ricerche=len(config.QUERY_EXA),
                           risultati=len(exa))
        tutte = schede + exa
        salvato = CARTELLA_CACHE / f"sourcing_{p}.json"
        salvato.parent.mkdir(parents=True, exist_ok=True)
        salvato.write_text(json.dumps({"schede": tutte,
                                       "schede_maps": len(schede),
                                       "costo_maps_usd": costo}), encoding="utf-8")
        righe.append(riepiloga(p, tutte, len(schede), costo))
        print(f"    salvato in {salvato.name}\n")

    print("=" * 78)
    print(f"{'prov':<6}{'comuni':>7}{'ricerche':>10}{'maps':>7}{'exa':>6}"
          f"{'uniche':>8}{'con sito':>10}{'fuori':>7}{'USD':>8}{'USD/com':>9}")
    for r in righe:
        print(f"{r['provincia']:<6}{r['comuni']:>7}{r['ricerche']:>10}"
              f"{r['maps']:>7}{r['exa']:>6}{r['uniche']:>8}{r['con_sito']:>10}"
              f"{r['fuori_regione']:>7}{r['costo_usd']:>8.2f}"
              f"{r['costo_usd']/r['comuni']:>9.3f}")
    tot_u = sum(r["uniche"] for r in righe)
    tot_c = sum(r["costo_usd"] for r in righe)
    tot_com = sum(r["comuni"] for r in righe)
    print(f"{'TOT':<6}{tot_com:>7}{sum(r['ricerche'] for r in righe):>10}"
          f"{sum(r['maps'] for r in righe):>7}{sum(r['exa'] for r in righe):>6}"
          f"{tot_u:>8}{sum(r['con_sito'] for r in righe):>10}"
          f"{sum(r['fuori_regione'] for r in righe):>7}{tot_c:>8.2f}"
          f"{tot_c/tot_com:>9.3f}")
    print(f"\n  {tot_u/tot_com:.1f} aziende uniche per comune  "
          f"({tot_u} su {tot_com} comuni)")
    costi.stampa(totali, credito=sourcing_maps.credito())
    print("\nNESSUNA analisi, NESSUNA scrittura in archivio.")
    print("Quando l'analisi partira': main.py --provincia XX --riusa-sourcing")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        s = [{"nome": "A", "sito": "https://a.it", "provincia": "Milano"},
             {"nome": "A2", "sito": "https://www.a.it/x", "provincia": "MI"},
             {"nome": "B", "sito": "", "provincia": "LT",
              "chiusa_definitivamente": True}]
        r = riepiloga("LT", s, maps=2, costo_usd=1.5)
        assert r["totali"] == 3 and r["uniche"] == 2, r   # a.it e' un doppione
        assert r["exa"] == 1 and r["fuori_regione"] == 1, r
        assert r["chiuse"] == 1 and r["ricerche"] == 18 * 3
        print("ok")
    else:
        sys.exit(main())
