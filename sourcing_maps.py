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
    }


def cerca(comuni: list[str], log=print) -> tuple[list[dict], float]:
    """-> (schede normalizzate, costo REALE della run in USD).

    Il costo lo dichiara Apify a fine run (`usage_total_usd`): va nel report
    consumi al posto della stima a scheda."""
    from apify_client import ApifyClient

    client = ApifyClient(os.environ["APIFY_TOKEN"])
    ricerche = [f"{cat} {com}" for com in comuni for cat in config.CATEGORIE_MAPS]
    log(f"maps: {len(ricerche)} ricerche in una sola run "
        f"(max {config.MAX_RISULTATI_PER_QUERY} schede l'una)")

    run = client.actor(config.ATTORE_MAPS).call(run_input={
        "searchStringsArray": ricerche,
        "maxCrawledPlacesPerSearch": config.MAX_RISULTATI_PER_QUERY,
        "language": config.LINGUA_MAPS,
        # senza questo l'attore geolocalizza dagli USA e "fabbro Roma"
        # pesca Rome (NY): i posti lontani li scarta, ma sono ricerche buttate
        "countryCode": config.PAESE_MAPS,
    })
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
    print("ok")
