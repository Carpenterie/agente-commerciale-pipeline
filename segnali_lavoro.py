"""Annunci di lavoro via Exa, solo classe A e B (PRD §9).

Una query per azienda. Un risultato conta come annuncio solo se (13/10,
dopo 306 A su 310 rette da annunci non loro):
- e' una pagina "lavora con noi" sul dominio DELL'AZIENDA, oppure
- e' un annuncio singolo di un portale (indeed/infojobs/subito/bakeca), non
  una pagina di ricerca, che NOMINA l'azienda ed e' della SUA provincia.

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
from data import comuni

SAGOMA_QUERY = ('"{nome}" (assunzione OR cercasi OR "offerta di lavoro") '
                "(saldatore OR operaio OR carpentiere OR magazziniere)")


def _e_annuncio(url: str) -> bool:
    """Portale di annunci, o pagina lavora-con-noi (di chiunque: il dominio
    si controlla in `_valido`)."""
    u = (url or "").lower()
    dominio = urlparse(u).netloc
    return (any(d in dominio for d in config.DOMINI_ANNUNCI)
            or any(p in u for p in config.PERCORSI_ANNUNCI))


def _bacheca(url: str) -> bool:
    return any(d in urlparse((url or "").lower()).netloc for d in config.DOMINI_ANNUNCI)


# pagine di risultati, non annunci: indeed /q-.../l-..., subito ?q= e
# /annunci-italia/, ricerche generiche con ?q= o /jobs?
RE_RICERCA = re.compile(r"indeed\.[a-z.]+/(q-|l-|jobs\b|lavoro\b)|[?&](q|what|kw)=|/annunci-italia/")


def _norm(testo: str) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", (testo or "").lower()).split()) + " "


# ponytail: nomi di province + comuni delle province attive; un comune
# minore di una regione non attiva non si riconosce (annuncio scartato)
LUOGHI = [(_norm(n), s) for n, s in config.SIGLE_PROVINCE.items()] + \
         [(_norm(c), s) for c, s in comuni.PROVINCIA_DI_COMUNE.items()]

FORME = {"srl", "srls", "snc", "sas", "spa", "s", "r", "l", "n", "c", "a", "p",
         "di", "e", "ditta", "societa", "soc", "coop"}


def _nome_corto(ragione_sociale: str) -> str:
    """Il nome senza forma giuridica e senza la coda descrittiva di Maps
    ("FM Fratelli Meucci - Oknoplast Premium Partner" -> "fm fratelli meucci")."""
    testa = re.split(r"\s[-–|]\s|,", ragione_sociale or "")[0]
    parole = [p for p in _norm(testa).split() if p not in FORME]
    return " ".join(parole)


def _luoghi(testo: str) -> set[str]:
    t = _norm(testo)
    return {sigla for nome, sigla in LUOGHI if nome.strip() and nome in t}


def _valido(url: str, testo: str, nome: str, dominio: str, provincia: str) -> str:
    """'' se l'annuncio e' dell'azienda, altrimenti il motivo dello scarto."""
    d = urlparse((url or "").lower()).netloc.removeprefix("www.")
    mio = (dominio or "").lower().removeprefix("www.")
    if not _bacheca(url):
        return "" if mio and (d == mio or d.endswith("." + mio)) else "lavora con noi di un'altra azienda"
    if RE_RICERCA.search(url.lower()):
        return "pagina di ricerca, non un annuncio"
    corto = _nome_corto(nome)
    if not corto or f" {corto} " not in _norm(testo):
        return "l'annuncio non nomina l'azienda"
    if (provincia or "").upper() not in _luoghi(url + " " + testo):
        return "annuncio di un'altra provincia o senza luogo"
    return ""


def _ruoli_citati(testo: str) -> list[str]:
    """I ruoli presenti, in ordine di PRIORITÀ (saldatore primo), non di
    apparizione nel testo. Match su radice: "saldat" prende saldatore,
    saldatori e "addetto alla saldatura"; "operai" prende operaio/operaia."""
    minuscolo = (testo or "").lower()
    return [ruolo for ruolo in config.RUOLI_ANNUNCI
            if re.search(rf"\b{re.escape(config.RADICI_ANNUNCI[ruolo])}", minuscolo)]


def _segnali_da_risultati(risultati: list[dict], nome: str = "", dominio: str = "",
                          provincia: str = "") -> list[dict]:
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
        if _valido(url, testo, nome, dominio, provincia):
            continue
        segnali.append({"tipo": "annuncio_lavoro", "ruolo": ruoli[0], "fonte": url})
    # i segnali con saldatore vengono per primi; a parità, ordine di rilevanza Exa
    return sorted(segnali, key=lambda s: config.RUOLI_ANNUNCI.index(s["ruolo"]))


# 11/10: Exa senza credito (402) o che non risponde -> niente piu' query per
# il resto del ciclo (ognuna aspetterebbe fino a 120 s). Il log lo dice per
# azienda: senza segnali una TARGET che sarebbe A per annuncio resta B.
ESAURITO = False
NON_CERCATI = "segnali non cercati (Exa esaurito)"


def cerca(ragione_sociale: str, log=print, dominio: str = "",
          provincia: str = "") -> list[dict]:
    """Una query Exa per azienda. Lista vuota se non trova nulla o su errore
    (un fallimento qui non ferma il ciclo)."""
    global ESAURITO
    if ESAURITO:
        log(f"{NON_CERCATI}: {ragione_sociale}")
        return []
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
        if getattr(e, "code", None) == 402 or isinstance(e, TimeoutError) \
                or isinstance(getattr(e, "reason", None), TimeoutError):
            ESAURITO = True
            log(f"{NON_CERCATI}: {ragione_sociale}")
        return []

    segnali = _segnali_da_risultati(risultati, ragione_sociale, dominio, provincia)
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

    # le regole del 13/10, sui casi veri
    v = lambda url, testo, nome="Fabbro X Srl", dom="fabbrox.it", pr="RM": \
        _valido(url, testo, nome, dom, pr)
    assert v("https://www.fabbrox.it/lavora-con-noi", "") == ""                 # proprio sito
    assert "altra azienda" in v("https://www.fortinfissi.it/it/posizioni-aperte", "")
    assert "ricerca" in v("https://it.indeed.com/q-operaio-infissi-offerte-lavoro.html",
                          "Fabbro X Roma")
    assert "ricerca" in v("https://www.subito.it/annunci-italia/vendita/offerte-lavoro/?q=infissi",
                          "Fabbro X Roma")
    firenze = "https://www.subito.it/offerte-lavoro/operaio-per-lavorazione-e-posa-infissi-firenze-605805050.htm"
    assert "non nomina" in v(firenze, "Operaio per lavorazione e posa infissi",
                             "La Marco Infissi", "lamarcoinfissi.com", "MT")
    assert "provincia" in v(firenze, "La Marco Infissi cerca operaio",
                            "La Marco Infissi", "lamarcoinfissi.com", "MT")
    assert v("https://chieti.bakeca.it/dettaglio/operai/saldatori-54jm299584564",
             "TC Metal cerca saldatori a Vasto", "TC Metal Vasto", "tcmetal.it", "CH") \
        == "l'annuncio non nomina l'azienda"                            # nome intero richiesto
    assert v("https://chieti.bakeca.it/dettaglio/operai/saldatori-54jm299584564",
             "Saldatori - Officina Rossi Srl, Vasto", "Officina Rossi S.r.l.", "", "CH") == ""
    assert _nome_corto("FM Fratelli Meucci - Oknoplast Premium Partner") == "fm fratelli meucci"
    assert _nome_corto("Infissi e Costruzioni Edili Del Corvo S.A.S.") == "infissi costruzioni edili del corvo"

    risultati = [
        {"url": "https://fabbrox.it/prodotti", "title": "Grate"},            # non annuncio
        {"url": "https://it.indeed.com/viewjob?jk=a", "title": "Fabbro X Roma: magazziniere"},
        {"url": "https://www.infojobs.it/b", "title": "Fabbro X cerca saldatore a Roma"},
        {"url": "https://it.indeed.com/viewjob?jk=c", "title": "Fabbro X Roma cerca contabile"},
        {"url": "https://fabbrox.it/lavora-con-noi", "title": "Lavora con noi",
         "highlights": ["cerchiamo un carpentiere"]},
        {"url": "https://altri.it/lavora-con-noi", "title": "saldatore"},     # sito altrui
        {"url": "https://www.infojobs.it/z", "title": "saldatore a Roma"},    # non nomina
    ]
    s = _segnali_da_risultati(risultati, "Fabbro X Srl", "fabbrox.it", "RM")
    assert [x["ruolo"] for x in s] == ["saldatore", "carpentiere", "magazziniere"], s
    assert s[0]["fonte"] == "https://www.infojobs.it/b"
    assert all(x["tipo"] == "annuncio_lavoro" for x in s)
    assert _segnali_da_risultati([]) == []

    # un annuncio che cita entrambi porta il saldatore
    misto = _segnali_da_risultati([{"url": "https://it.indeed.com/viewjob?jk=d",
                                    "title": "Fabbro X Roma: magazziniere e saldatore"}],
                                  "Fabbro X", "", "RM")
    assert misto[0]["ruolo"] == "saldatore", misto

    assert len(da_cercare([{"classe": "A"}, {"classe": "B"}, {"classe": "C"}, {}])) == 2
    assert '"Officina Rossi"' in SAGOMA_QUERY.format(nome="Officina Rossi")
    print("ok")
