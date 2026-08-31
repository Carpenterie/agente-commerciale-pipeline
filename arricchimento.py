"""Openapi: anagrafica base, solo classe A e B (PRD §9).

Endpoint IT-advanced della Company API: P.IVA come segmento di path,
token Bearer da .env. L'API Imprese citata nel PRD è stata deprecata il
31/12/2025 e sostituita dalla Company API — vedi README, Limiti noti.

Dopo l'arricchimento il chiamante applica la modulazione dipendenti
(classify.modula_dipendenti) e il dedup su P.IVA.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import config

BASE = "https://company.openapi.com"


def _numero(valore) -> int | None:
    """I campi numerici a volte arrivano come stringa o come dict annidato."""
    if isinstance(valore, dict):
        valore = valore.get("value") or valore.get("valore")
    try:
        return int(str(valore).strip())
    except (TypeError, ValueError):
        return None


def _normalizza(dati: dict) -> dict:
    """Risposta Openapi -> i soli campi che servono alla pipeline.

    I dipendenti NON stanno in un campo top-level: sono in
    `balanceSheets.last.employees`, cioè nell'ultimo bilancio depositato.
    Un'azienda senza bilanci (ditte individuali, società giovani) non ha il
    dato e la modulazione organico semplicemente non si applica.
    """
    sede = (dati.get("address") or {}).get("registeredOffice") or {}
    bilancio = (dati.get("balanceSheets") or {}).get("last") or {}
    return {
        "piva": (dati.get("vatCode") or dati.get("taxCode") or "").strip(),
        "denominazione": (dati.get("companyName") or "").strip(),
        "sede_comune": (sede.get("town") or "").strip(),
        "sede_provincia": (sede.get("province") or "").strip(),
        "sede_cap": (sede.get("zipCode") or "").strip(),
        "dipendenti": _numero(bilancio.get("employees")),
        "anno_bilancio": _numero(bilancio.get("year")),
    }


def _chiama(percorso: str, token: str, log) -> dict | list | None:
    req = urllib.request.Request(f"{BASE}/{percorso}",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            corpo = json.load(r)
    except urllib.error.HTTPError as e:
        log(f"openapi {e.code} su {percorso.split('?')[0]}: "
            f"{e.read().decode()[:140]}")
        return None
    except Exception as e:  # noqa: BLE001 - un fallimento non ferma il ciclo
        log(f"openapi errore su {percorso.split('?')[0]}: {type(e).__name__}: {e}")
        return None
    return corpo.get("data")


def cerca_id(nome: str, provincia: str, token: str, log) -> str | None:
    """IT-search per denominazione: restituisce solo l'id interno Openapi.
    La provincia restringe e riduce le omonimie (in Italia i "Fabbro
    Rossi" sono molti)."""
    qs = f"companyName={urllib.parse.quote(nome)}"
    if provincia:
        qs += f"&province={urllib.parse.quote(provincia)}"
    dati = _chiama(f"IT-search?{qs}", token, log)
    if not isinstance(dati, list) or not dati:
        return None
    if len(dati) > 1:
        log(f"openapi: {len(dati)} omonimi per '{nome}', prendo il primo")
    return dati[0].get("id")


def arricchisci(nome: str, piva: str = "", provincia: str = "",
                log=print) -> dict | None:
    """-> dati anagrafici, o None se non trovata / errore (non è fatale:
    l'azienda resta in DB senza arricchimento).

    Le schede di Maps ed Exa non portano la P.IVA, quindi quasi sempre si
    passa dal nome: IT-search dà l'id, IT-advanced i dati. Sono DUE
    chiamate, e il contatore dei costi le registra entrambe.
    """
    token = os.environ.get("OPENAPI_TOKEN", "").strip()
    if not token:
        log("openapi: OPENAPI_TOKEN non configurato, arricchimento saltato")
        return None

    chiave, chiamate = piva.strip(), 1
    if not chiave:
        chiave = cerca_id(nome, provincia, token, log)
        chiamate = 2
        if not chiave:
            log(f"openapi: nessuna corrispondenza per '{nome}'"
                + (f" in provincia {provincia}" if provincia else ""))
            return None

    dati = _chiama(f"{config.ENDPOINT_OPENAPI}/{urllib.parse.quote(chiave)}",
                   token, log)
    if isinstance(dati, list):
        dati = dati[0] if dati else None
    if not dati:
        log(f"openapi: nessun dato per '{nome}'")
        return None
    esito = _normalizza(dati)
    esito["chiamate"] = chiamate
    return esito


def da_arricchire(aziende: list[dict]) -> list[dict]:
    """Solo classe A e B (§9): sulle altre non si spende."""
    return [a for a in aziende if a.get("classe") in ("A", "B")]


if __name__ == "__main__":
    n = _normalizza({
        "companyName": " Officina Rossi Srl ", "vatCode": "01234567890",
        "balanceSheets": {"last": {"year": 2023, "employees": 12}},
        "address": {"registeredOffice": {"town": "Tivoli", "province": "RM",
                                          "zipCode": "00019"}},
    })
    assert n["denominazione"] == "Officina Rossi Srl"
    assert n["piva"] == "01234567890" and n["dipendenti"] == 12
    assert n["sede_comune"] == "Tivoli" and n["sede_provincia"] == "RM"

    # risposta povera: niente indirizzo, dipendenti assenti -> None, non crash
    p = _normalizza({"companyName": "X", "vatCode": "1"})
    assert p["dipendenti"] is None and p["sede_comune"] == ""
    # i dipendenti stanno nell'ultimo bilancio, non top-level
    b = _normalizza({"companyName": "Y", "vatCode": "1",
                     "balanceSheets": {"last": {"year": 2024, "employees": 24}}})
    assert b["dipendenti"] == 24 and b["anno_bilancio"] == 2024
    # azienda senza bilanci depositati: nessun dato, nessun crash
    assert _normalizza({"balanceSheets": {}})["dipendenti"] is None
    assert _normalizza({"balanceSheets": {"last": {}}})["dipendenti"] is None
    assert _numero({"value": "7"}) == 7
    assert _numero("n.d.") is None and _numero(None) is None

    aziende = [{"classe": "A"}, {"classe": "B"}, {"classe": "C"},
               {"classe": "indeterminato"}, {}]
    assert len(da_arricchire(aziende)) == 2

    print("ok")
