"""Apify Google Maps per comune (PRD §4, replicato dal test di sourcing).

Una sola run dell'attore con tutte le ricerche (categoria x comune): stesso
numero di schede di N run separate ma un solo avvio, quindi meno credito.
Le aziende senza sito NON si scartano: entrano con i recapiti Maps (§4).
"""

from __future__ import annotations

import os

import config


def _normalizza(voce: dict) -> dict:
    """Scheda Apify -> dict comune a tutta la pipeline. Salva SEMPRE
    nome, sito, telefono, indirizzo, comune (§4).

    La scheda grezza ha 60 campi: qui si tengono quelli che servono.
    - `cap` e `provincia` sono il segnale territoriale primario (93-95%
      valorizzati), più affidabili dell'euristica sulla pagina;
    - `recensioni` e `punteggio` concorrono alla priorità commerciale
      (86%), MAI all'esclusione: metà delle aziende del settore ha meno di
      dieci recensioni perché lavora B2B, non perché è ferma;
    - `chiusa_definitivamente` e `chiusa_temporaneamente` evitano di
      analizzare (e pagare) attività che non esistono più.
    """
    return {
        "fonte": "maps",
        "query": voce.get("searchString", "") or "",
        "nome": (voce.get("title", "") or "").strip(),
        "sito": voce.get("website") or "",
        "telefono": voce.get("phone") or "",
        "indirizzo": voce.get("address") or "",
        "comune": voce.get("city") or "",
        "cap": (voce.get("postalCode") or "").strip(),
        "provincia": (voce.get("state") or "").strip(),
        "recensioni": voce.get("reviewsCount"),
        "punteggio": voce.get("totalScore"),
        "chiusa_definitivamente": bool(voce.get("permanentlyClosed")),
        "chiusa_temporaneamente": bool(voce.get("temporarilyClosed")),
        # la categoria dichiarata da Google ("Parrucchiere", "Fabbro"...):
        # dal 2026-09-28 si valuta in scrittura, PRIMA che la riga entri —
        # il sourcing per parole chiave pesca anche saloni e ristoranti,
        # e senza questo campo il rumore si vedeva solo in archivio
        "categoria_maps": (voce.get("categoryName") or "").strip(),
    }


def credito(log=print) -> tuple[float, float] | None:
    """-> (usato, tetto) in USD nel ciclo di fatturazione corrente, o None.

    Il piano ha un tetto rigido (`maxMonthlyUsageUsd`): oltre quello le run
    falliscono. Il cron gira una provincia al giorno, quindi dal secondo
    giorno serve sapere quanto resta PRIMA che a fermarsi sia l'ultima.
    `users/me/limits` non e' fatturata: non lancia nessuna run.
    """
    from apify_client import ApifyClient

    try:
        # il client restituisce un oggetto tipizzato, non un dict
        d = ApifyClient(os.environ["APIFY_TOKEN"]).user().limits()
        return (float(d.current.monthly_usage_usd),
                float(d.limits.max_monthly_usage_usd))
    except Exception as e:  # noqa: BLE001 - il credito e' informativo, non blocca
        log(f"apify: credito non leggibile ({type(e).__name__})")
        return None


def ricerche_dense(schede: list[dict], provincia: str) -> list[str]:
    """Le ricerche Maps che hanno riempito tutti i posti con almeno
    config.SOGLIA_RICERCA_DENSA schede della provincia cercata."""
    from collections import defaultdict
    per = defaultdict(list)
    for s in schede:
        if s.get("fonte") == "maps" and s.get("query"):
            per[s["query"]].append(s)
    return sorted(q for q, v in per.items()
                  if len(v) >= config.MAX_RISULTATI_PER_QUERY
                  and sum((config.sigla_provincia(s.get("provincia") or "") or "").upper() == provincia
                          for s in v) >= config.SOGLIA_RICERCA_DENSA)


def tetto_allargate(n_ricerche: int) -> float:
    return max(0.5, config.tetto_apify_usd(n_ricerche, config.MAX_RISULTATI_ALLARGATA))


def cerca(comuni: list[str], log=print, tetto_usd: float | None = None,
          ricerche: list[str] | None = None,
          per_ricerca: int | None = None) -> tuple[list[dict], float]:
    """-> (schede normalizzate, costo REALE della run in USD).

    Il costo lo dichiara Apify a fine run (`usage_total_usd`): va nel report
    consumi al posto della stima a scheda. `tetto_usd` e' il limite RIGIDO
    della run (Apify la ferma li', minimo 0,50 USD)."""
    from apify_client import ApifyClient

    client = ApifyClient(os.environ["APIFY_TOKEN"])
    ricerche = ricerche or [f"{cat} {com}" for com in comuni for cat in config.CATEGORIE_MAPS]
    per_ricerca = per_ricerca or config.MAX_RISULTATI_PER_QUERY
    log(f"maps: {len(ricerche)} ricerche in una sola run "
        f"(max {per_ricerca} schede l'una)")

    run = client.actor(config.ATTORE_MAPS).call(run_input={
        "searchStringsArray": ricerche,
        "maxCrawledPlacesPerSearch": per_ricerca,
        "language": config.LINGUA_MAPS,
        # senza questo l'attore geolocalizza dagli USA e "fabbro Roma"
        # pesca Rome (NY): i posti lontani li scarta, ma sono ricerche buttate
        "countryCode": config.PAESE_MAPS,
    }, max_total_charge_usd=max(tetto_usd, 0.5) if tetto_usd else None)
    schede = [_normalizza(v)
              for v in client.dataset(run.default_dataset_id).iterate_items()]
    costo_usd = float(run.usage_total_usd or 0)
    con_sito = sum(1 for s in schede if s["sito"])
    chiuse = sum(1 for s in schede if s["chiusa_definitivamente"])
    log(f"maps: {len(schede)} schede, {con_sito} con sito, "
        f"{len(schede) - con_sito} senza sito (si tengono comunque) "
        f"- costo reale {costo_usd:.4f} USD")
    if chiuse:
        log(f"maps: {chiuse} risultano chiuse definitivamente")
    return schede, costo_usd


if __name__ == "__main__":
    voce = {"searchString": "fabbro Roma", "title": " Officina X ",
            "website": "https://x.it", "phone": "+39 06 123", "address": "Via Y 1, Roma",
            "city": "Roma", "postalCode": "00179", "state": "RM",
            "reviewsCount": 176, "totalScore": 4.8, "permanentlyClosed": False}
    n = _normalizza(voce)
    assert n["nome"] == "Officina X" and n["sito"] == "https://x.it"
    assert n["cap"] == "00179" and n["provincia"] == "RM"
    assert n["recensioni"] == 176 and n["punteggio"] == 4.8
    assert n["chiusa_definitivamente"] is False
    # scheda che non dichiara i campi nuovi: None/False, mai KeyError
    v = _normalizza({"title": "Y"})
    assert v["cap"] == "" and v["recensioni"] is None
    assert v["chiusa_definitivamente"] is False
    assert n["telefono"] == "+39 06 123" and n["comune"] == "Roma"
    assert _normalizza({})["sito"] == ""  # senza sito: campi vuoti, non None/KeyError
    # ricerche dense: 20 su 20 e almeno 15 della provincia -> si allarga
    def _s(q, prov, n):
        return [{"fonte": "maps", "query": q, "provincia": prov}] * n
    schede = (_s("fabbro Livorno", "LI", 16) + _s("fabbro Livorno", "PI", 4)      # densa
              + _s("fabbro Cecina", "LI", 14) + _s("fabbro Cecina", "BO", 6)      # 14: no
              + _s("fabbro Piombino", "Provincia di Livorno", 15)                 # 15 ma non piena
              + _s("fabbro Bibbona", "LI", 20) + [{"fonte": "exa", "query": "x", "provincia": "LI"}])
    assert ricerche_dense(schede, "LI") == ["fabbro Bibbona", "fabbro Livorno"], ricerche_dense(schede, "LI")
    assert tetto_allargate(0) == 0.5 and tetto_allargate(10) == round(0.30 + 10 * 60 * 0.0030, 2)
    assert _normalizza({"categoryName": " Parrucchiere "})["categoria_maps"] == "Parrucchiere"
    assert _normalizza({})["categoria_maps"] == ""
    print("ok")
