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
# Tetto di spesa sugli omonimi: la verifica costa una IT-advanced ciascuno.
# Oltre questo numero non si aggancia niente: con cinque o piu' omonimi la
# probabilita' di scegliere giusto non vale cinque chiamate.
MAX_OMONIMI = 4
STATI_MORTI = ("CESSATA", "INATTIVA")


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
        "stato": (dati.get("activityStatus") or "").strip().upper(),
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


def cerca_omonimi(nome: str, provincia: str, token: str, log) -> list[str]:
    """IT-search per denominazione: TUTTI gli id, non il primo. "Prendo il
    primo" ha scritto in archivio la visura di un'AC Infissi CESSATA di
    Colleferro al posto di quella di Anzio (2026-09-19): l'ordine dei
    risultati non e' nemmeno stabile fra una chiamata e l'altra."""
    qs = f"companyName={urllib.parse.quote(nome)}"
    if provincia:
        qs += f"&province={urllib.parse.quote(provincia)}"
    dati = _chiama(f"IT-search?{qs}", token, log)
    if not isinstance(dati, list):
        return []
    if len(dati) > 1:
        log(f"openapi: {len(dati)} omonimi per '{nome}'")
    return [d.get("id") for d in dati if d.get("id")]


def _concorde(comune: str | None, noti: set[str]) -> bool:
    c = (comune or "").strip().casefold()
    return bool(c) and c in noti


def decidi(candidati: list[dict], comuni_noti=()) -> tuple[dict | None, str]:
    """Quale omonimo agganciare, se uno. -> (visura, "") o (None, motivo).

    Pura e testabile: qui sta la regola decisa il 2026-09-19.
    - le CESSATA e INATTIVA si scartano subito: una visura morta non si
      scrive mai in una scheda consegnabile;
    - fra piu' omonimi vivi aggancia solo quello che concorda col comune
      noto (Maps o sede letta dal sito). Zero concordi, o piu' d'uno:
      nessun aggancio — meglio un campo vuoto che la visura di un altro;
    - anche l'omonimo UNICO deve concordare, quando un comune noto c'e':
      il caso AC Infissi era proprio una visura che contraddiceva Maps e
      sito concordi fra loro. Una visura senza sede non puo' concordare,
      quindi non si aggancia: e' la stessa regola, non un caso a parte.
    """
    noti = {str(c).strip().casefold() for c in comuni_noti if c and str(c).strip()}
    vivi = [c for c in candidati if c.get("stato") not in STATI_MORTI]
    if not vivi:
        return None, "in visura solo omonimi cessati o inattivi"
    if len(vivi) > 1:
        concordi = [c for c in vivi if _concorde(c.get("sede_comune"), noti)]
        if len(concordi) != 1:
            quanti = "nessuno" if not concordi else f"{len(concordi)}"
            return None, (f"{len(vivi)} omonimi attivi in visura, "
                          f"{quanti} concorde con Maps o col sito")
        return concordi[0], ""
    scelto = vivi[0]
    if noti and not _concorde(scelto.get("sede_comune"), noti):
        dove = scelto.get("sede_comune") or "senza sede"
        return None, (f"la visura ({dove}) contraddice il comune noto "
                      f"({', '.join(sorted(noti))})")
    return scelto, ""


def _advanced(chiave: str, token: str, log) -> dict | None:
    dati = _chiama(f"{config.ENDPOINT_OPENAPI}/{urllib.parse.quote(chiave)}",
                   token, log)
    if isinstance(dati, list):
        dati = dati[0] if dati else None
    return dati


def arricchisci(nome: str, piva: str = "", provincia: str = "",
                comuni_noti=(), log=print) -> dict | None:
    """-> visura agganciata, oppure {"chiamate", "non_agganciata": motivo}
    quando la visura c'e' ma non e' affidabile, oppure None (token assente,
    nessun risultato, errore rete — non e' fatale, la scheda resta senza).

    L'AGGANCIO decide la fiducia (regola del 2026-09-19):
    - per P.IVA (dal sito dell'azienda): una chiamata, fiducia piena —
      e' l'azienda a dichiarare chi e';
    - per NOME: IT-search da' gli omonimi, IT-advanced UNO PER UNO (si
      registrano tutte), e `decidi()` sceglie o rinuncia. `comuni_noti`
      sono i comuni di Maps e della sede letta dal sito: la visura che li
      contraddice non scrive niente.
    """
    token = os.environ.get("OPENAPI_TOKEN", "").strip()
    if not token:
        log("openapi: OPENAPI_TOKEN non configurato, arricchimento saltato")
        return None

    if piva.strip():
        dati = _advanced(piva.strip(), token, log)
        if not dati:
            log(f"openapi: nessun dato per '{nome}'")
            return None
        esito = _normalizza(dati)
        esito["chiamate"], esito["aggancio"] = 1, "piva"
        return esito

    ids = cerca_omonimi(nome, provincia, token, log)
    if not ids:
        log(f"openapi: nessuna corrispondenza per '{nome}'"
            + (f" in provincia {provincia}" if provincia else ""))
        return None
    if len(ids) > MAX_OMONIMI:
        return {"chiamate": 1, "non_agganciata":
                f"{len(ids)} omonimi in visura, oltre il tetto di {MAX_OMONIMI}"}
    chiamate, candidati = 1, []
    for oid in ids:
        d = _advanced(oid, token, log)
        chiamate += 1
        if d:
            candidati.append(_normalizza(d))
    if not candidati:
        log(f"openapi: nessun dato per '{nome}'")
        return None
    scelto, motivo = decidi(candidati, comuni_noti)
    if not scelto:
        log(f"openapi: visura non agganciata per '{nome}' — {motivo}")
        return {"chiamate": chiamate, "non_agganciata": motivo}
    scelto["chiamate"], scelto["aggancio"] = chiamate, "nome"
    return scelto


def da_arricchire(aziende: list[dict]) -> list[dict]:
    """Solo le classi in config.CLASSI_DA_ARRICCHIRE (§9): sulle altre non
    si spende. Restringere a ("A",) e' una scelta di costo, non di codice."""
    return [a for a in aziende if a.get("classe") in config.CLASSI_DA_ARRICCHIRE]


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
    assert p["dipendenti"] is None and p["sede_comune"] == "" and p["stato"] == ""
    assert _normalizza({"activityStatus": "cessata"})["stato"] == "CESSATA"
    # i dipendenti stanno nell'ultimo bilancio, non top-level
    b = _normalizza({"companyName": "Y", "vatCode": "1",
                     "balanceSheets": {"last": {"year": 2024, "employees": 24}}})
    assert b["dipendenti"] == 24 and b["anno_bilancio"] == 2024
    # azienda senza bilanci depositati: nessun dato, nessun crash
    assert _normalizza({"balanceSheets": {}})["dipendenti"] is None
    assert _normalizza({"balanceSheets": {"last": {}}})["dipendenti"] is None
    assert _numero({"value": "7"}) == 7
    assert _numero("n.d.") is None and _numero(None) is None

    # --- decidi(): il caso AC Infissi non deve ripetersi ---
    # tre omonimi reali del 2026-09-19: attiva a Roma, CESSATA a
    # Colleferro, INATTIVA a Genazzano. Maps e sito concordi su Anzio:
    # NESSUNA delle tre deve scrivere.
    tre = [{"stato": "ATTIVA", "sede_comune": "ROMA", "piva": "1"},
           {"stato": "CESSATA", "sede_comune": "COLLEFERRO", "piva": "2"},
           {"stato": "INATTIVA", "sede_comune": "GENAZZANO", "piva": "3"}]
    v, motivo = decidi(tre, comuni_noti=("Anzio", "Anzio"))
    assert v is None and "contraddice" in motivo, (v, motivo)
    # le morte si scartano anche da sole
    assert decidi([tre[1]], ("Colleferro",))[0] is None
    assert "cessati" in decidi([tre[1], tre[2]], ())[1]
    # unico vivo e concorde: si aggancia
    v, _ = decidi(tre, comuni_noti=("Roma",))
    assert v and v["piva"] == "1"
    # unico vivo, nessun comune noto (riga Exa senza sede): come prima
    assert decidi([tre[0]], ())[0] is not None
    # piu' vivi: aggancia SOLO quello concorde...
    due = [dict(tre[0]), {"stato": "ATTIVA", "sede_comune": "Anzio", "piva": "4"}]
    v, _ = decidi(due, ("ANZIO",))
    assert v and v["piva"] == "4"
    # ...e con zero concordi non aggancia nessuno
    v, motivo = decidi(due, ("Latina",))
    assert v is None and "nessuno concorde" in motivo, motivo
    # la visura senza sede non puo' concordare: non scrive
    assert decidi([{"stato": "ATTIVA", "sede_comune": ""}], ("Anzio",))[0] is None
    # maiuscole e spazi non contano
    assert decidi([{"stato": "ATTIVA", "sede_comune": " Fonte Nuova "}],
                  ("fonte nuova",))[0] is not None

    aziende = [{"classe": "A"}, {"classe": "B"}, {"classe": "C"},
               {"classe": "indeterminato"}, {}]
    assert len(da_arricchire(aziende)) == len(
        [a for a in aziende if a.get("classe") in config.CLASSI_DA_ARRICCHIRE])
    # la restrizione e' un parametro, non una modifica al codice
    salvato = config.CLASSI_DA_ARRICCHIRE
    config.CLASSI_DA_ARRICCHIRE = ("A",)
    assert [a["classe"] for a in da_arricchire(aziende)] == ["A"]
    config.CLASSI_DA_ARRICCHIRE = salvato

    print("ok")
