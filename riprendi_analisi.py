"""Riprende le analisi interrotte di un ciclo: le righe ERRORE_ANALISI.

Il 2026-09-21 il credito Anthropic del cliente e' finito a meta' import:
290 righe sono in archivio come anagrafiche con `esito_fetch =
'ERRORE_ANALISI'` e le loro pagine sono GIA' in cache. Questo script le
rianalizza — fetch dalla cache, zero rifetch — e AGGIORNA le righe sul
posto: mai cancella-e-riscrivi, l'id e' per la vita dell'azienda (vedi
README e il self-check in db.py).

    python riprendi_analisi.py <ciclo_id>             # conta, non scrive
    python riprendi_analisi.py <ciclo_id> --scrivi    # rianalizza e aggiorna

I recapiti gia' in riga (email e telefono della lista del 2020, scritti
come ripiego) restano dove il sito non da' di meglio, come all'import.
Il salvavita delle analisi vale anche qui: dieci fallite di fila con lo
stesso errore e ci si ferma — se il credito non e' tornato, meglio
scoprirlo alla decima che alla duecentonovantesima.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter

import config  # noqa: F401
import costi
import db
import main as ciclo

# Cosa produce la rianalisi e cosa NON si tocca mai. `creato_il`, `id`,
# `ciclo_id`, `fonte` e `stato` restano quelli della riga: la ripresa
# completa un lavoro, non ne inventa uno nuovo.
NON_SI_TOCCANO = ("id", "creato_il", "ciclo_id", "fonte", "stato",
                  "n_contatti", "prossima_azione", "assegnato_a",
                  "ultimo_contatto")


def scheda_da_riga_db(r: dict) -> dict:
    """La riga d'archivio nel formato delle schede di sourcing."""
    return {
        "fonte": r.get("fonte") or "lista_commerciale",
        "nome": r.get("ragione_sociale") or "",
        "sito": r.get("sito") or "",
        "telefono": r.get("telefono") or "",
        "comune": r.get("comune") or "",
        "provincia": r.get("provincia") or "",
    }


def aggiornamento(riga_nuova: dict, esistente: dict) -> dict:
    """I campi da scrivere: tutto cio' che la rianalisi produce, senza
    toccare identita' e cronologia della riga, e senza regredire i
    recapiti di ripiego dove il sito non da' di meglio."""
    agg = {k: v for k, v in riga_nuova.items() if k not in NON_SI_TOCCANO}
    if not agg.get("email_aziendale") and esistente.get("email_aziendale"):
        agg["email_aziendale"] = esistente["email_aziendale"]
    if not agg.get("telefono") and esistente.get("telefono"):
        agg["telefono"] = esistente["telefono"]
    # la marcatura ex cliente fu fatta all'import, PRIMA della scrittura:
    # la rianalisi non puo' rifarla (non ha l'elenco davanti) e non deve
    # perderla — e' la lezione dei referenti del 15/9, i campi si perdono
    # nei passaggi che "ricostruiscono tutto"
    ex = [s for s in (esistente.get("segnali") or [])
          if s.get("tipo") == "ex_cliente"]
    if ex:
        nuovi = [s for s in (agg.get("segnali") or [])
                 if s.get("tipo") != "ex_cliente"]
        agg["segnali"] = ex + nuovi
    return agg


def main_() -> int:
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    scrivi = "--scrivi" in sys.argv
    if not argv:
        print("uso: python riprendi_analisi.py <ciclo_id> [--scrivi]")
        return 1
    ciclo_id = argv[0]

    from dotenv import load_dotenv
    load_dotenv()
    sb = db.client()
    righe, off = [], 0
    while True:
        b = sb.table("aziende").select("*").eq("ciclo_id", ciclo_id) \
            .eq("esito_fetch", "ERRORE_ANALISI").range(off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            break
        off += 1000
    print(f"righe ERRORE_ANALISI nel ciclo {ciclo_id[:8]}: {len(righe)}")
    print(f"costo stimato: ~{len(righe) * 0.10:.0f} EUR (pagine in cache)")
    if not scrivi:
        print("\n(prova: nessuna analisi. Rilancia con --scrivi)")
        return 0

    from anthropic import Anthropic
    from crawl4ai import AsyncWebCrawler

    totali = costi.nuovo_ciclo(gratuite_openapi=0)
    client = Anthropic()
    stat = {"classi": Counter(), "ruoli": Counter(), "con_segnale": 0,
            "saliti_ad_A": 0, "scesi_per_organico": 0, "arricchite": 0,
            "ex_in_riga": 0, "ex_scritti": 0}
    esiti, interrotto = Counter(), ""
    serie = ("", 0)

    async def giro():
        nonlocal interrotto, serie
        async with AsyncWebCrawler(verbose=False) as crawler:
            for i, r in enumerate(righe, 1):
                print(f"[{i}/{len(righe)}] {r['ragione_sociale'][:60]}")
                azienda = scheda_da_riga_db(r)
                try:
                    esito = await ciclo.analizza(azienda, crawler, client, totali)
                    serie = ciclo.aggiorna_serie(serie,
                                                 esito.get("errore_analisi", ""))
                    anagrafica, segnali = ciclo.arricchisci_ab(
                        azienda, esito, totali, stat,
                        provincia=azienda.get("provincia", ""))
                    if esito["segnale_sede"]:
                        segnali = [esito["segnale_sede"], *segnali]
                    stat["classi"][esito["classe"]] += 1
                    esiti[esito["esito_fetch"]] += 1
                    nuova = db.riga_azienda(
                        azienda, dati=esito["dati"], territorio=esito["territorio"],
                        anagrafica=anagrafica, segnali=segnali,
                        classe=esito["classe"], esito_fetch=esito["esito_fetch"],
                        ciclo_id=None, pagine=esito["pagine"], costo=esito["costo"])
                    sb.table("aziende").update(aggiornamento(nuova, r)) \
                        .eq("id", r["id"]).execute()
                    if serie[1] >= ciclo.MAX_ERRORI_ANALISI:
                        interrotto = (f"{serie[1]} analisi fallite di fila con lo "
                                      f"stesso errore ({serie[0]}): il credito "
                                      f"non e' tornato, o la rete e' giu'")
                        print(f"STOP: {interrotto}")
                        break
                except Exception as e:  # noqa: BLE001
                    print(f"  SALTATA {r['ragione_sociale']}: {type(e).__name__}: {e}")

    asyncio.run(giro())
    print("\n" + "=" * 52)
    if interrotto:
        print(f"ESITO: ripresa INTERROTTA — {interrotto}")
    print(f"esiti: {dict(esiti)}")
    print(f"classi: {dict(stat['classi'])}")
    costi.stampa(totali)
    return 1 if interrotto else 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        s = scheda_da_riga_db({"ragione_sociale": "X Srl", "sito": "http://x.it",
                               "telefono": "06 1", "comune": "Anzio",
                               "provincia": "RM", "fonte": "lista_commerciale"})
        assert s["nome"] == "X Srl" and s["fonte"] == "lista_commerciale"
        # identita' e cronologia non si toccano mai
        agg = aggiornamento({"id": "NO", "creato_il": "NO", "ciclo_id": "NO",
                             "fonte": "NO", "stato": "NO", "classe": "A",
                             "email_aziendale": None, "telefono": ""},
                            {"email_aziendale": "vecchia@lista.it",
                             "telefono": "06 2020"})
        for campo in NON_SI_TOCCANO:
            assert campo not in agg, campo
        assert agg["classe"] == "A"
        # i recapiti di ripiego restano dove il sito non da' di meglio...
        assert agg["email_aziendale"] == "vecchia@lista.it"
        assert agg["telefono"] == "06 2020"
        # ...ma il sito vince quando parla
        agg2 = aggiornamento({"email_aziendale": "nuova@sito.it",
                              "telefono": "06 999"},
                             {"email_aziendale": "vecchia@lista.it",
                              "telefono": "06 2020"})
        assert agg2["email_aziendale"] == "nuova@sito.it"
        assert agg2["telefono"] == "06 999"
        # la marcatura ex cliente sopravvive alla rianalisi
        agg3 = aggiornamento({"segnali": [{"tipo": "territorio"}]},
                             {"segnali": [{"tipo": "ex_cliente",
                                           "riconosciuto_per": "ragione+comune"}]})
        assert [x["tipo"] for x in agg3["segnali"]] == ["ex_cliente", "territorio"]
        assert aggiornamento({"segnali": None}, {"segnali": [{"tipo": "ex_cliente"}]}
                             )["segnali"][0]["tipo"] == "ex_cliente"
        print("ok")
    else:
        sys.exit(main_())
