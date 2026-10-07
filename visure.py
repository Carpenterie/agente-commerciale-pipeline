"""Ripasso visure Openapi sulle schede di un ciclo, con le STESSE regole del
ciclo (main.applica_visura): aggancio affidabile o niente, sede in visura
fuori dalle regioni attive -> segnale, fabbro con organico ampio -> una
classe in meno. Nato il 7/10 per il pilota di Pisa, girato col token
Openapi rifiutato: 134 A/B/C senza visura.

    python visure.py --ciclo ID --classi A,B --per-nome A            # misura
    python visure.py --ciclo ID --classi A,B --per-nome A --scrivi

--classi:   le classi da visurare (con P.IVA in scheda: una visura).
--per-nome: le classi per cui, SENZA P.IVA, si cerca anche per nome
            (IT-search + fino a arricchimento.MAX_OMONIMI visure).
Le altre schede senza P.IVA si saltano. Lo stato non si tocca mai; la
classe cambia solo per la regola dei fabbri. Dal registro del wallet: si
ferma prima che il residuo dichiarato scenda sotto le visure di una scheda.
"""

from __future__ import annotations

import collections
import sys

import arricchimento
import config


def campi_da_visura(riga: dict, anagrafica: dict) -> dict:
    """Come db.riga_azienda: la P.IVA del sito vince (si riempie solo se
    manca), sede e provincia della visura vincono, organico dalla visura."""
    import db
    agg = {}
    if not (riga.get("partita_iva") or "").strip() and anagrafica.get("piva"):
        agg["partita_iva"] = anagrafica["piva"]
    if (anagrafica.get("sede_comune") or "").strip():
        agg["comune"] = anagrafica["sede_comune"].strip()
    prov = config.sigla_provincia((anagrafica.get("sede_provincia") or "").strip())
    if prov:
        agg["provincia"] = prov
    if anagrafica.get("dipendenti") is not None:
        agg["n_dipendenti"] = anagrafica["dipendenti"]
        agg["struttura"] = db._struttura(anagrafica["dipendenti"])
    return agg


def da_visurare(righe: list[dict], classi: set, per_nome: set) -> list[dict]:
    return [r for r in righe if r.get("classe") in classi
            and ((r.get("partita_iva") or "").strip() or r.get("classe") in per_nome)]


def giro(ciclo: str, classi: set, per_nome: set, scrivi: bool, log=print) -> None:
    import costi
    import crediti
    import db
    import main

    sb = db.client()
    righe = (sb.table("aziende").select("id,ragione_sociale,comune,provincia,partita_iva,"
                                        "categoria,classe,stato,segnali")
             .eq("ciclo_id", ciclo).execute().data)
    coda = da_visurare(righe, classi, per_nome)
    con_piva = sum(bool((r.get("partita_iva") or "").strip()) for r in coda)
    per_nome_n = len(coda) - con_piva
    log(f"da visurare: {len(coda)} ({con_piva} con P.IVA, {per_nome_n} per nome) — "
        f"costo previsto {con_piva * config.COSTO_OPENAPI_EUR + per_nome_n * 1.5 * config.COSTO_OPENAPI_EUR:.2f} "
        f"EUR, massimo {(con_piva + per_nome_n * arricchimento.MAX_OMONIMI) * config.COSTO_OPENAPI_EUR:.2f}")
    if not scrivi:
        return
    if crediti.token_openapi_ok(log) is not True:
        log("ESITO: token Openapi non accettato, niente visure")
        return
    totali = costi.nuovo_ciclo()
    stat = collections.Counter()
    stat["arricchite"] = stat["scesi_per_organico"] = 0
    cambi = []
    for r in coda:
        residuo = crediti.residuo_openapi()
        if residuo is not None and residuo < config.COSTO_OPENAPI_EUR * arricchimento.MAX_OMONIMI:
            log(f"STOP: residuo Openapi dichiarato {residuo:.2f} EUR — le altre restano senza visura")
            break
        azienda = {"nome": r["ragione_sociale"], "comune": r.get("comune") or "",
                   "piva": r.get("partita_iva") or ""}
        dati = {"partita_iva": r.get("partita_iva") or "", "sede_comune": r.get("comune") or "",
                "categoria": r.get("categoria") or ""}
        esito = {"classe": r["classe"]}
        anagrafica, segnali = main.applica_visura(azienda, dati, esito, totali, stat,
                                                  r.get("provincia") or "")
        agg = campi_da_visura(r, anagrafica or {})
        if esito["classe"] != r["classe"]:
            agg["classe"] = esito["classe"]
            cambi.append((r["ragione_sociale"], r["classe"], esito["classe"]))
        if segnali:
            attuali = sb.table("aziende").select("segnali").eq("id", r["id"]).execute().data[0]
            agg["segnali"] = (attuali.get("segnali") or []) + segnali
        if agg:
            try:
                sb.table("aziende").update(agg).eq("id", r["id"]).execute()
            except Exception as e:  # noqa: BLE001 - es. P.IVA gia' su un'altra riga
                stat["errori"] += 1
                log(f"  errore su {r['ragione_sociale'][:30]}: {str(e)[:120]}")
                agg.pop("partita_iva", None)
                if agg:
                    sb.table("aziende").update(agg).eq("id", r["id"]).execute()
        stat["visurate"] += 1
    log(f"\nvisurate {stat['visurate']}, agganciate {stat['arricchite']}, non agganciate "
        f"{stat.get('visure_non_agganciate', 0)}, errori {stat.get('errori', 0)}")
    log(f"classe cambiata per la regola dei fabbri: {len(cambi)}")
    for nome, prima, dopo in cambi:
        log(f"  {nome[:45]}: {prima} -> {dopo}")
    costi.stampa(totali, log=log)
    log(f"residuo Openapi dichiarato: {crediti.residuo_openapi()} EUR")


if __name__ == "__main__":
    if "--test" in sys.argv:
        righe = [{"classe": "A", "partita_iva": "1"}, {"classe": "A", "partita_iva": ""},
                 {"classe": "B", "partita_iva": "2"}, {"classe": "B", "partita_iva": None},
                 {"classe": "C", "partita_iva": "3"}]
        assert len(da_visurare(righe, {"A", "B"}, {"A"})) == 3
        assert len(da_visurare(righe, {"A", "B", "C"}, {"A", "B", "C"})) == 5
        a = campi_da_visura({"partita_iva": "01234567890"},
                            {"piva": "999", "sede_comune": "Cascina", "sede_provincia": "Pisa",
                             "dipendenti": 20})
        assert a == {"comune": "Cascina", "provincia": "PI", "n_dipendenti": 20,
                     "struttura": "piccola"}, a
        assert campi_da_visura({"partita_iva": ""}, {"piva": "999"}) == {"partita_iva": "999"}
        assert campi_da_visura({}, {}) == {}
        print("ok")
        sys.exit(0)

    from dotenv import load_dotenv
    load_dotenv()
    arg = lambda k: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else ""
    giro(arg("--ciclo"), set(filter(None, arg("--classi").split(","))),
         set(filter(None, arg("--per-nome").split(","))), "--scrivi" in sys.argv)
