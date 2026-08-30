"""Annunci di lavoro via Exa, solo classe A e B (PRD §9).

Una query per azienda. Un risultato conta come annuncio solo se sta su un
portale di annunci (indeed/infojobs/subito/bakeca) o su una pagina
"lavora con noi" del sito aziendale.

Il saldatore ha priorità su ogni altro ruolo: è la figura che il cliente
ha indicato come in via di sparizione ed è l'argomento di vendita del
prodotto. Se un annuncio cita saldatore e magazziniere, il segnale
registrato porta "saldatore"; e i segnali con saldatore vengono per primi.

Voce scritta nel campo `segnali` dell'azienda:
    {"tipo": "annuncio_lavoro", "ruolo": "saldatore", "fonte": "<url>"}
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

import config

SAGOMA_QUERY = ('"{nome}" (assunzione OR cercasi OR "offerta di lavoro") '
                "(saldatore OR operaio OR carpentiere OR magazziniere)")


def _e_annuncio(url: str) -> bool:
    """Portale di annunci, o pagina lavora-con-noi sul sito aziendale."""
    u = (url or "").lower()
    dominio = urlparse(u).netloc
    return (any(d in dominio for d in config.DOMINI_ANNUNCI)
            or any(p in u for p in config.PERCORSI_ANNUNCI))


def _ruoli_citati(testo: str) -> list[str]:
    """I ruoli presenti, in ordine di PRIORITÀ (saldatore primo), non di
    apparizione nel testo. Match su radice: "saldat" prende saldatore,
    saldatori e "addetto alla saldatura"; "operai" prende operaio/operaia."""
    minuscolo = (testo or "").lower()
    return [ruolo for ruolo in config.RUOLI_ANNUNCI
            if re.search(rf"\b{re.escape(config.RADICI_ANNUNCI[ruolo])}", minuscolo)]


def _segnali_da_risultati(risultati: list[dict]) -> list[dict]:
    """Risultati Exa -> voci `segnali`, saldatore per primo."""
    segnali = []
    for res in risultati:
        url = res.get("url") or ""
        if not _e_annuncio(url):
            continue
        testo = " ".join([res.get("title") or "",
                          " ".join(res.get("highlights") or [])])
        ruoli = _ruoli_citati(testo)
        if not ruoli:
            continue  # l'annuncio non nomina nessuno dei ruoli che ci interessano
        segnali.append({"tipo": "annuncio_lavoro", "ruolo": ruoli[0], "fonte": url})
    # i segnali con saldatore vengono per primi; a parità, ordine di rilevanza Exa
    return sorted(segnali, key=lambda s: config.RUOLI_ANNUNCI.index(s["ruolo"]))


def cerca(ragione_sociale: str, log=print) -> list[dict]:
    """Una query Exa per azienda. Lista vuota se non trova nulla o su errore
    (un fallimento qui non ferma il ciclo)."""
    chiave = os.environ["EXA_API_KEY"]
    query = SAGOMA_QUERY.format(nome=ragione_sociale)
    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=json.dumps({"query": query, "type": "auto", "numResults": 10,
                         "contents": {"highlights": True}}).encode(),
        headers={"content-type": "application/json", "x-api-key": chiave},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            risultati = json.load(r).get("results", [])
    except Exception as e:  # noqa: BLE001 - un fallimento non ferma il ciclo
        log(f"segnali: errore per {ragione_sociale}: {type(e).__name__}: {e}")
        return []

    segnali = _segnali_da_risultati(risultati)
    if segnali:
        log(f"segnali: {ragione_sociale} -> "
            + ", ".join(s["ruolo"] for s in segnali))
    return segnali


def da_cercare(aziende: list[dict]) -> list[dict]:
    """Solo classe A e B (§9)."""
    return [a for a in aziende if a.get("classe") in ("A", "B")]


if __name__ == "__main__":
    # priorità: saldatore primo anche se citato per ultimo nel testo
    assert _ruoli_citati("cercasi magazziniere e saldatore") == \
        ["saldatore", "magazziniere"]
    assert _ruoli_citati("Offerta: saldatori esperti") == ["saldatore"]
    # formulazioni reali degli annunci italiani per la figura chiave
    assert _ruoli_citati("addetto alla saldatura TIG") == ["saldatore"]
    assert _ruoli_citati("cercasi saldatore a filo continuo") == ["saldatore"]
    assert _ruoli_citati("operaio saldatore") == ["saldatore", "operaio"]
    assert _ruoli_citati("assumiamo operai e carpentieri") == \
        ["operaio", "carpentiere"]
    assert _ruoli_citati("cercasi contabile") == []
    assert _ruoli_citati("") == []

    assert _e_annuncio("https://it.indeed.com/offerta-123")
    assert _e_annuncio("https://www.infojobs.it/x") and _e_annuncio("https://subito.it/y")
    assert _e_annuncio("https://fabbrox.it/lavora-con-noi")
    assert not _e_annuncio("https://fabbrox.it/prodotti")
    assert not _e_annuncio("")

    risultati = [
        {"url": "https://fabbrox.it/prodotti", "title": "Grate"},            # non annuncio
        {"url": "https://it.indeed.com/a", "title": "Cercasi magazziniere"},
        {"url": "https://www.infojobs.it/b", "title": "Cercasi saldatore a Roma"},
        {"url": "https://it.indeed.com/c", "title": "Cercasi contabile"},    # ruolo fuori
        {"url": "https://fabbrox.it/lavora-con-noi", "title": "Lavora con noi",
         "highlights": ["cerchiamo un carpentiere"]},
    ]
    s = _segnali_da_risultati(risultati)
    assert [x["ruolo"] for x in s] == ["saldatore", "carpentiere", "magazziniere"], s
    assert s[0]["fonte"] == "https://www.infojobs.it/b"
    assert all(x["tipo"] == "annuncio_lavoro" for x in s)
    assert _segnali_da_risultati([]) == []

    # un annuncio che cita entrambi porta il saldatore
    misto = _segnali_da_risultati([{"url": "https://it.indeed.com/d",
                                    "title": "Cercasi magazziniere e saldatore"}])
    assert misto[0]["ruolo"] == "saldatore", misto

    assert len(da_cercare([{"classe": "A"}, {"classe": "B"}, {"classe": "C"}, {}])) == 2
    assert '"Officina Rossi"' in SAGOMA_QUERY.format(nome="Officina Rossi")
    print("ok")
