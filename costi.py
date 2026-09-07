"""Contatore token/€ per azienda e per ciclo (PRD §9).

Due prodotti distinti:
- `costo_anthropic()`: il costo della singola azienda, che finisce in
  `costo_analisi_eur` sulla riga dell'azienda;
- `riepilogo()`: i totali di ciclo per `cicli_ricerca`, con le voci
  SEPARATE per fonte (Anthropic, Openapi, Exa, Apify) — è il materiale del
  report consumi al cliente, dove le voci vanno distinte, non aggregate.

I prezzi stanno in config, letti dalla documentazione delle fonti.
"""

from __future__ import annotations

import config


def _eur(usd: float) -> float:
    return round(usd * config.USD_EUR, 6)


def costo_anthropic(token_input: int, token_output: int) -> float:
    """Costo della singola analisi -> `costo_analisi_eur` dell'azienda."""
    return _eur(token_input * config.PREZZO_INPUT_USD_PER_TOKEN
                + token_output * config.PREZZO_OUTPUT_USD_PER_TOKEN)


def nuovo_ciclo(gratuite_openapi: int = config.CHIAMATE_OPENAPI_GRATUITE_MESE) -> dict:
    """Accumulatore di ciclo. `gratuite_openapi`: quante delle 30 mensili
    sono ancora disponibili — sono per MESE, non per ciclo, quindi al
    secondo ciclo dello stesso mese il chiamante passa quelle rimaste."""
    return {"token_input": 0, "token_output": 0, "aziende_analizzate": 0,
            "chiamate_openapi": 0, "ricerche_exa": 0, "risultati_exa": 0,
            "schede_apify": 0, "gratuite_openapi": gratuite_openapi}


def registra_analisi(tot: dict, token_input: int, token_output: int) -> float:
    """Contabilizza un'analisi e restituisce il costo di QUELLA azienda."""
    tot["token_input"] += token_input
    tot["token_output"] += token_output
    tot["aziende_analizzate"] += 1
    return costo_anthropic(token_input, token_output)


def registra_openapi(tot: dict, chiamate: int = 1) -> None:
    tot["chiamate_openapi"] += chiamate


def registra_exa(tot: dict, ricerche: int = 1, risultati: int = 0) -> None:
    """I contenuti (highlights) si pagano a pagina restituita, non a ricerca."""
    tot["ricerche_exa"] += ricerche
    tot["risultati_exa"] += risultati


def registra_apify(tot: dict, schede: int, costo_usd: float | None = None) -> None:
    """`costo_usd`: quello dichiarato da Apify a fine run. Se assente si
    ricade sulla stima a scheda (config)."""
    tot["schede_apify"] += schede
    if costo_usd is not None:
        tot["costo_apify_usd_reale"] = tot.get("costo_apify_usd_reale", 0.0) + costo_usd


def riepilogo(tot: dict) -> dict:
    """Totali di ciclo per `cicli_ricerca`, voci separate per fonte."""
    a_pagamento = max(0, tot["chiamate_openapi"] - tot["gratuite_openapi"])
    voci = {
        "costo_anthropic_eur": costo_anthropic(tot["token_input"], tot["token_output"]),
        "costo_openapi_eur": round(a_pagamento * config.COSTO_OPENAPI_EUR, 6),
        "costo_exa_eur": _eur(tot["ricerche_exa"] * config.PREZZO_EXA_RICERCA_USD
                              + tot["risultati_exa"] * config.PREZZO_EXA_PAGINA_USD),
        "costo_apify_eur": _eur(tot.get("costo_apify_usd_reale")
                                if tot.get("costo_apify_usd_reale") is not None
                                else tot["schede_apify"] * config.PREZZO_APIFY_SCHEDA_USD),
    }
    totale = round(sum(voci.values()), 6)
    analizzate = tot["aziende_analizzate"]
    return {
        **voci,
        "costo_totale_eur": totale,
        "costo_medio_azienda_eur": round(totale / analizzate, 6) if analizzate else 0.0,
        "aziende_analizzate": analizzate,
        "token_input": tot["token_input"], "token_output": tot["token_output"],
        "chiamate_openapi": tot["chiamate_openapi"],
        "chiamate_openapi_pagate": a_pagamento,
        "ricerche_exa": tot["ricerche_exa"], "schede_apify": tot["schede_apify"],
    }


def stampa(tot: dict, log=print, credito: tuple | None = None) -> dict:
    """Riepilogo leggibile: è la base del report consumi (§9)."""
    r = riepilogo(tot)
    log("\n" + "=" * 52)
    log(f"Aziende analizzate: {r['aziende_analizzate']}")
    log(f"  Anthropic  {r['costo_anthropic_eur']:>9.4f} EUR  "
        f"({r['token_input']:,} in / {r['token_output']:,} out)")
    log(f"  Openapi    {r['costo_openapi_eur']:>9.4f} EUR  "
        f"({r['chiamate_openapi']} chiamate, {r['chiamate_openapi_pagate']} a pagamento)")
    log(f"  Exa        {r['costo_exa_eur']:>9.4f} EUR  ({r['ricerche_exa']} ricerche)")
    log(f"  Apify      {r['costo_apify_eur']:>9.4f} EUR  ({r['schede_apify']} schede)")
    if credito:
        # in USD e non in EUR: il tetto del piano e' in dollari, convertirlo
        # a cambio fisso farebbe leggere margine dove non ce n'e'
        usato, tetto = credito
        log(f"    credito Apify: {usato:.2f} / {tetto:.2f} USD usati nel mese"
            f" — restano {tetto - usato:.2f}")
    log(f"  TOTALE     {r['costo_totale_eur']:>9.4f} EUR")
    log(f"Costo medio per azienda analizzata: {r['costo_medio_azienda_eur']:.4f} EUR")
    log("=" * 52)
    return r


if __name__ == "__main__":
    # costo azienda: 1M input + 1M output = (3 + 15) USD * cambio
    assert abs(costo_anthropic(1_000_000, 1_000_000) - 18 * config.USD_EUR) < 1e-6
    assert costo_anthropic(0, 0) == 0

    t = nuovo_ciclo()
    costo = registra_analisi(t, 10_000, 500)
    assert costo == costo_anthropic(10_000, 500)
    assert t["aziende_analizzate"] == 1

    # le prime 30 Openapi non si pagano, la 31esima sì
    registra_openapi(t, 30)
    assert riepilogo(t)["costo_openapi_eur"] == 0
    registra_openapi(t, 2)
    r = riepilogo(t)
    assert r["chiamate_openapi"] == 32 and r["chiamate_openapi_pagate"] == 2
    assert abs(r["costo_openapi_eur"] - 0.20) < 1e-9
    # secondo ciclo dello stesso mese: gratuite già consumate
    t2 = nuovo_ciclo(gratuite_openapi=0)
    registra_openapi(t2, 1)
    assert abs(riepilogo(t2)["costo_openapi_eur"] - config.COSTO_OPENAPI_EUR) < 1e-9

    # Exa: ricerche + pagine restituite; Apify: a scheda
    registra_exa(t, ricerche=5, risultati=125)
    registra_apify(t, 480)  # senza costo reale: stima a scheda
    r = riepilogo(t)
    atteso_exa = (5 * config.PREZZO_EXA_RICERCA_USD
                  + 125 * config.PREZZO_EXA_PAGINA_USD) * config.USD_EUR
    assert abs(r["costo_exa_eur"] - atteso_exa) < 1e-6
    assert abs(r["costo_apify_eur"] - 480 * config.PREZZO_APIFY_SCHEDA_USD
               * config.USD_EUR) < 1e-6

    # il credito: si stampa se c'e', si tace se manca (Apify irraggiungibile)
    righe = []
    stampa(t, log=righe.append, credito=(4.70, 19.0))
    assert any("restano 14.30" in r for r in righe), righe
    righe.clear()
    stampa(t, log=righe.append)
    assert not any("credito Apify" in r for r in righe)
    stampa(t, log=righe.append, credito=None)   # credito non leggibile
    assert not any("credito Apify" in r for r in righe)

    # le voci restano DISTINTE e sommano al totale
    voci = ("costo_anthropic_eur", "costo_openapi_eur", "costo_exa_eur",
            "costo_apify_eur")
    assert abs(sum(r[v] for v in voci) - r["costo_totale_eur"]) < 1e-9
    assert len({r[v] for v in voci}) == 4  # nessuna voce aggregata per sbaglio
    assert r["costo_medio_azienda_eur"] == round(r["costo_totale_eur"] / 1, 6)

    # ciclo vuoto: nessuna divisione per zero
    vuoto = riepilogo(nuovo_ciclo())
    assert vuoto["costo_totale_eur"] == 0 and vuoto["costo_medio_azienda_eur"] == 0

    righe = []
    stampa(t, log=righe.append)
    assert any("Anthropic" in r_ for r_ in righe) and any("Apify" in r_ for r_ in righe)
    # quando Apify dichiara il costo reale, quello vince sulla stima
    t3 = nuovo_ciclo()
    registra_apify(t3, 68, costo_usd=0.1020)
    assert abs(riepilogo(t3)["costo_apify_eur"] - 0.1020 * config.USD_EUR) < 1e-6
    print("ok")
