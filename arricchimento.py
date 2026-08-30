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
    """Risposta Openapi -> i soli campi che servono alla pipeline."""
    sede = dati.get("address", {}).get("registeredOffice", {}) or {}
    return {
        "piva": (dati.get("vatCode") or dati.get("taxCode") or "").strip(),
        "denominazione": (dati.get("companyName") or "").strip(),
        "sede_comune": (sede.get("town") or "").strip(),
        "sede_provincia": (sede.get("province") or "").strip(),
        "sede_cap": (sede.get("zipCode") or "").strip(),
        "dipendenti": _numero(dati.get("employees")),
    }


def arricchisci(piva_o_nome: str, log=print) -> dict | None:
    """-> dati anagrafici, o None se non trovata / errore (non è fatale:
    l'azienda resta in DB senza arricchimento)."""
    token = os.environ.get("OPENAPI_TOKEN", "").strip()
    if not token:
        log("openapi: OPENAPI_TOKEN non configurato, arricchimento saltato")
        return None
    url = f"{BASE}/{config.ENDPOINT_OPENAPI}/{urllib.parse.quote(piva_o_nome)}"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            corpo = json.load(r)
    except urllib.error.HTTPError as e:
        log(f"openapi {e.code} per {piva_o_nome}: {e.read().decode()[:200]}")
        return None
    except Exception as e:  # noqa: BLE001 - un fallimento non ferma il ciclo
        log(f"openapi errore per {piva_o_nome}: {type(e).__name__}: {e}")
        return None

    dati = corpo.get("data")
    if isinstance(dati, list):
        dati = dati[0] if dati else None
    if not dati:
        log(f"openapi: nessun risultato per {piva_o_nome}")
        return None
    return _normalizza(dati)


def da_arricchire(aziende: list[dict]) -> list[dict]:
    """Solo classe A e B (§9): sulle altre non si spende."""
    return [a for a in aziende if a.get("classe") in ("A", "B")]


if __name__ == "__main__":
    n = _normalizza({
        "companyName": " Officina Rossi Srl ", "vatCode": "01234567890",
        "employees": "12",
        "address": {"registeredOffice": {"town": "Tivoli", "province": "RM",
                                          "zipCode": "00019"}},
    })
    assert n["denominazione"] == "Officina Rossi Srl"
    assert n["piva"] == "01234567890" and n["dipendenti"] == 12
    assert n["sede_comune"] == "Tivoli" and n["sede_provincia"] == "RM"

    # risposta povera: niente indirizzo, dipendenti assenti -> None, non crash
    p = _normalizza({"companyName": "X", "vatCode": "1"})
    assert p["dipendenti"] is None and p["sede_comune"] == ""
    assert _numero({"value": "7"}) == 7
    assert _numero("n.d.") is None and _numero(None) is None

    aziende = [{"classe": "A"}, {"classe": "B"}, {"classe": "C"},
               {"classe": "indeterminato"}, {}]
    assert len(da_arricchire(aziende)) == 2

    print("ok")
