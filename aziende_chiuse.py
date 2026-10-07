"""Aziende chiuse definitivamente: il segnale `chiusa_definitivamente`
(con la fonte) toglie la scheda dalle liste del commerciale SENZA toccare
lo stato, come `fuori_settore` (decisione del committente, 2026-10-07).

    python aziende_chiuse.py --segna ID "fonte" "dettaglio"   # a mano
    python aziende_chiuse.py --verifica                  # misura (Apify)
    python aziende_chiuse.py --verifica --scrivi         # e segna le certe
    python aziende_chiuse.py --segna-da-verifica         # le certe dell'ultima
                                                         # misura, senza ripagare Apify
    python aziende_chiuse.py --test

--verifica cerca la scheda Google per nome e comune delle righe della lista
del direttore (mai passate da Maps) e di quelle in VERIFICARE. Regola:
chiusa SOLO se la scheda della stessa azienda e' chiusa definitivamente e
non ne esiste una attiva. Prima passata a 1 risultato per ricerca; chi
risulta chiuso si riguarda a 5 risultati, per cercare la scheda attiva.
Nome solo simile, o nessuna scheda trovata: elenco dei dubbi, nessun segno.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys

import config
import dedup
import fetch

TIPO = "chiusa_definitivamente"
TETTO_USD = 5.0
# le tre abbinate per telefono a una scheda Google chiusa (7/10): un
# telefono condiviso con una vecchia scheda non basta, si riverificano
VERIFICARE = ("ART METAL di Polimadei Paolo",
              "BPE SERRAMENTI S.N.C. DI PASQUALE CICCHI",
              "Infissi F.Lli Muggia Soc.Coop.")


def segnale(fonte: str, dettaglio: str) -> dict:
    return {"tipo": TIPO, "fonte": fonte,
            "segnale": f"{dettaglio} — {datetime.date.today().isoformat()}"}


def chiusa(riga: dict) -> bool:
    return any(s.get("tipo") == TIPO for s in riga.get("segnali") or [])


def segna(sb, id_: str, s: dict, log=print) -> bool:
    """Aggiunge il segnale, se non c'e' gia'. Rilegge i segnali della riga
    subito prima di scrivere: niente sovrascritture di dati vecchi."""
    r = sb.table("aziende").select("id,ragione_sociale,segnali").eq("id", id_).execute().data
    if not r:
        log(f"  riga {id_} non trovata")
        return False
    if chiusa(r[0]):
        return False
    sb.table("aziende").update({"segnali": (r[0].get("segnali") or []) + [s]}
                               ).eq("id", id_).execute()
    log(f"  segnata chiusa: {r[0]['ragione_sociale']} ({s['fonte']})")
    return True


def _tel(t: str | None) -> str:
    return re.sub(r"\D", "", t or "")[-9:]


def stessa_azienda(riga: dict, scheda: dict) -> str | None:
    """-> "certa" (telefono, dominio, nome+comune uguali), "simile" (nome
    contenuto nello stesso comune), None."""
    if _tel(riga.get("telefono")) and _tel(riga.get("telefono")) == _tel(scheda.get("telefono")):
        return "certa"
    d = dedup.dominio_azienda(riga.get("sito") or "")
    if d and d == dedup.dominio_azienda(scheda.get("sito") or ""):
        return "certa"
    criterio, _ = dedup.cerca_riferimento(scheda, dedup.riferimenti([riga]), permissivo=True)
    if criterio == "ragione+comune":
        return "certa"
    if criterio == "nome contenuto (stesso comune)":
        return "simile"
    return None


def decidi(riga: dict, schede: list[dict]) -> tuple[str, str]:
    """-> (esito, motivo). esito: chiusa | attiva | dubbio | non_trovata."""
    pari = [(stessa_azienda(riga, s), s) for s in schede]
    pari = [(g, s) for g, s in pari if g]
    if not pari:
        return "non_trovata", "nessuna scheda Google della stessa azienda"
    attive = [s for g, s in pari if not s.get("chiusa_definitivamente")]
    chiuse = [(g, s) for g, s in pari if s.get("chiusa_definitivamente")]
    if attive:
        return "attiva", f"scheda attiva: {attive[0]['nome']}"
    if any(g == "certa" for g, _ in chiuse):
        return "chiusa", f"scheda Google chiusa definitivamente: {chiuse[0][1]['nome']}"
    return "dubbio", f"chiusa ma nome solo simile: {chiuse[0][1]['nome']}"


def _cerca(ricerche: list[str], per_ricerca: int, tetto: float, log=print) -> tuple[dict, float]:
    """-> ({ricerca: [schede]}, costo USD). Tetto rigido sulla run."""
    from apify_client import ApifyClient
    import sourcing_maps
    client = ApifyClient(os.environ["APIFY_TOKEN"])
    run = client.actor(config.ATTORE_MAPS).call(
        run_input={"searchStringsArray": ricerche,
                   "maxCrawledPlacesPerSearch": per_ricerca,
                   "language": config.LINGUA_MAPS, "countryCode": config.PAESE_MAPS},
        max_total_charge_usd=tetto)
    trovate: dict = {q: [] for q in ricerche}
    for v in client.dataset(run.default_dataset_id).iterate_items():
        s = sourcing_maps._normalizza(v)
        trovate.setdefault(s["query"], []).append(s)
    costo = float(run.usage_total_usd or 0)
    log(f"apify: {len(ricerche)} ricerche x {per_ricerca}, costo reale {costo:.4f} USD")
    return trovate, costo


def verifica(scrivi: bool, log=print) -> None:
    import db
    sb = db.client()
    righe, da = [], 0
    while True:
        b = (sb.table("aziende").select("id,ragione_sociale,comune,telefono,sito,classe,stato,"
                                        "fonte,segnali").range(da, da + 999).execute().data)
        righe += b
        if len(b) < 1000:
            break
        da += 1000
    righe = [r for r in righe if (r.get("fonte") == "lista_commerciale"
                                  or r["ragione_sociale"] in VERIFICARE) and not chiusa(r)]
    q = {r["id"]: f"{r['ragione_sociale']} {r.get('comune') or ''}".strip() for r in righe}
    log(f"da verificare: {len(righe)} righe")

    trovate, speso = _cerca(sorted(set(q.values())), 1, TETTO_USD - 0.5, log)
    esiti = {r["id"]: decidi(r, trovate.get(q[r["id"]], [])) for r in righe}
    # chi risulta chiuso o dubbio si riguarda a 5 risultati: la scheda
    # attiva della stessa azienda puo' stare sotto quella chiusa
    rivedere = [r for r in righe if esiti[r["id"]][0] in ("chiusa", "dubbio")]
    if rivedere and speso < TETTO_USD - 0.3:
        altre, costo = _cerca(sorted({q[r["id"]] for r in rivedere}), 5, TETTO_USD - speso, log)
        speso += costo
        for r in rivedere:
            esiti[r["id"]] = decidi(r, altre.get(q[r["id"]], []) + trovate.get(q[r["id"]], []))

    conta: dict = {}
    for r in righe:
        conta[esiti[r["id"]][0]] = conta.get(esiti[r["id"]][0], 0) + 1
    log(f"ESITI: {conta} — Apify {speso:.2f} USD")
    for e in ("chiusa", "dubbio"):
        for r in righe:
            if esiti[r["id"]][0] == e:
                log(f"  [{e}] {r['classe'] or '-':<13} {r['stato']:<11} "
                    f"{r['ragione_sociale'][:42]:<43} {(r.get('comune') or '')[:16]:<17} "
                    f"{esiti[r['id']][1][:70]}")
    if scrivi:
        n = sum(segna(sb, r["id"], segnale("maps", f"ricerca Google per nome e comune: "
                                           f"{esiti[r['id']][1]}"), log)
                for r in righe if esiti[r["id"]][0] == "chiusa")
        log(f"segnate chiuse: {n}")
    json.dump({r["id"]: {"nome": r["ragione_sociale"], "comune": r.get("comune"),
                         "esito": esiti[r["id"]][0], "motivo": esiti[r["id"]][1]}
               for r in righe}, open(fetch.CACHE / "verifica_chiuse.json", "w"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    if "--test" in sys.argv:
        riga = {"ragione_sociale": "Ferro Rossi Srl", "comune": "Tivoli",
                "telefono": "0774 123456", "sito": "https://www.ferrorossi.it"}
        chiusa_g = {"nome": "Ferro Rossi", "comune": "Tivoli", "telefono": "+39 0774 123456",
                    "sito": "", "chiusa_definitivamente": True}
        attiva_g = {**chiusa_g, "chiusa_definitivamente": False}
        assert decidi(riga, [chiusa_g])[0] == "chiusa"
        assert decidi(riga, [chiusa_g, attiva_g])[0] == "attiva"     # c'e' un'attiva
        assert decidi(riga, [])[0] == "non_trovata"
        altra = {"nome": "Pizzeria Bella", "comune": "Tivoli", "telefono": "",
                 "sito": "", "chiusa_definitivamente": True}
        assert decidi(riga, [altra])[0] == "non_trovata"            # non e' lei
        simile = {"nome": "Ferro Rossi Infissi e Cancelli", "comune": "Tivoli",
                  "telefono": "", "sito": "", "chiusa_definitivamente": True}
        assert decidi({**riga, "telefono": "", "sito": ""}, [simile])[0] == "dubbio"
        assert stessa_azienda(riga, {"nome": "X", "comune": "Roma", "telefono": "",
                                     "sito": "http://ferrorossi.it/"}) == "certa"
        s = segnale("rimbalzo", "prova")
        assert s["tipo"] == TIPO and s["fonte"] == "rimbalzo" and chiusa({"segnali": [s]})
        print("ok")
        sys.exit(0)

    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    if "--segna" in sys.argv:
        import db
        i = sys.argv.index("--segna")
        segna(db.client(), sys.argv[i + 1], segnale(sys.argv[i + 2], sys.argv[i + 3]))
    elif "--segna-da-verifica" in sys.argv:
        import db
        sb = db.client()
        esiti = json.load(open(fetch.CACHE / "verifica_chiuse.json"))
        n = sum(segna(sb, id_, segnale("maps", f"ricerca Google per nome e comune: {e['motivo']}"))
                for id_, e in esiti.items() if e["esito"] == "chiusa")
        print(f"segnate chiuse: {n}")
    elif "--verifica" in sys.argv:
        verifica(scrivi="--scrivi" in sys.argv)
