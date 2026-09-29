"""crawl4ai con cache su disco per dominio (PRD §6).

Porting del fetch del campione, fix priorità incluso: homepage + fino a 4
pagine interne, prima le pagine prodotto, poi le generiche, blog/news/social
solo se avanzano slot. Cache in cache/<dominio>/, riuso totale tra
esecuzioni. Timeout 30s, 1 retry, poi FETCH_FALLITO e avanti.

Differenza dal fetch del campione: la keyword `contatti` (PRD §6) — la
pagina contatti serve al filtro territorio (§5). Il campione resta senza
per non toccare la baseline congelata.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import config

CACHE = Path(__file__).parent / "cache"

# pagine di prodotto: sono quelle che dicono davvero se lavorano l'acciaio
PAROLE_PRODOTTO = (
    "grate", "persiane", "cancelli", "inferriate", "recinzioni", "blindat",
    "sicurezza", "portoni", "ringhiere", "ferro", "acciaio",
)
PAROLE_GENERICHE = (
    "prodotti", "servizi", "lavorazioni", "chi-siamo", "chi_siamo", "chisiamo",
    "chi siamo", "azienda", "realizzazioni", "lavori", "gallery", "galleria",
    "portfolio", "contatti", "contact",
)
PAROLE_CHIAVE = PAROLE_GENERICHE + PAROLE_PRODOTTO
# blog, news e social parlano dei prodotti ma non provano la produzione:
# eleggibili solo se avanzano slot
DEPRIORITA = ("/blog", "/news", "facebook", "instagram", "linkedin", "youtube", "twitter")


def _cache_path(url: str) -> Path:
    dominio = urlparse(url).netloc.replace("www.", "").lower() or "senza-dominio"
    return CACHE / dominio / (hashlib.md5(url.encode()).hexdigest() + ".json")


def _markdown(result) -> str:
    # crawl4ai recenti restituiscono un oggetto, i vecchi una stringa
    md = getattr(result, "markdown", "") or ""
    return getattr(md, "raw_markdown", None) or str(md)


async def _scarica(crawler, url: str) -> dict | None:
    """Una pagina: cache -> tentativo -> 1 retry. None se fallisce."""
    cached = _cache_path(url)
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))

    from crawl4ai import CacheMode, CrawlerRunConfig

    conf = CrawlerRunConfig(cache_mode=CacheMode.BYPASS,
                            page_timeout=config.TIMEOUT_FETCH_MS)
    for tentativo in range(2):
        try:
            result = await crawler.arun(url=url, config=conf)
            if result.success:
                dati = {
                    "markdown": _markdown(result),
                    "links": [l.get("href", "") for l in (result.links or {}).get("internal", [])],
                    "testi": [l.get("text", "") for l in (result.links or {}).get("internal", [])],
                }
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(dati), encoding="utf-8")
                return dati
        except Exception as e:  # noqa: BLE001 - un fallimento non ferma la pipeline
            if tentativo:
                print(f"    fetch fallito {url}: {type(e).__name__}: {e}")
        if not tentativo:
            await asyncio.sleep(1)
    return None


def _pagine_rilevanti(home: dict, base_url: str) -> list[str]:
    """Fino a 4 link interni con keyword: prima le pagine prodotto, poi le
    generiche, in fondo blog/news/social; a parità, l'ordine di pagina."""
    dominio = urlparse(base_url).netloc
    visti = {urldefrag(base_url).url.rstrip("/")}
    candidate: list[tuple] = []
    for indice, (href, testo) in enumerate(zip(home["links"], home["testi"])):
        if not href:
            continue
        assoluto = urldefrag(urljoin(base_url, href)).url.rstrip("/")
        if urlparse(assoluto).netloc != dominio or assoluto in visti:
            continue
        ago = f"{href} {testo}".lower()
        if not any(k in ago for k in PAROLE_CHIAVE):
            continue
        visti.add(assoluto)
        depri = any(d in assoluto.lower() for d in DEPRIORITA)
        prodotto = any(k in ago for k in PAROLE_PRODOTTO)
        contatti = "contatt" in ago or "contact" in ago
        candidate.append((depri, not prodotto, indice, assoluto, contatti))
    ordinate = sorted(candidate)
    scelte = ordinate[:config.MAX_PAGINE_INTERNE]
    # slot GARANTITO alla pagina contatti: nella diagnosi del 29/9 in 20
    # casi su 27 perdeva la gara con le pagine prodotto e l'email non
    # veniva mai scaricata
    if not any(c[4] for c in scelte):
        con_contatti = next((c for c in ordinate if c[4]), None)
        if con_contatti:
            scelte[-1] = con_contatti
    return [c[3] for c in scelte]


RE_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)*\.[a-zA-Z]{2,}")
# residui tipici del markdown: nomi di file responsive (logo@2x.png) e
# domini segnaposto dei template
ESTENSIONI_FILE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
                   ".css", ".js", ".pdf", ".woff", ".woff2", ".ico", ".mp4")
DOMINI_FINTI = ("example", "esempio", "sentry", "wixpress", "mysite",
                "tuodominio", "nomesito", "yourdomain", "domain.com")


def estrai_email(testo: str, sito: str = "") -> list[str]:
    """Email dal testo delle pagine (mailto compresi: nel markdown restano
    in chiaro), SENZA modello. Ordinate: prima quelle sul dominio del sito,
    poi info@, poi le piu' frequenti."""
    dominio = ""
    if sito:
        d = urlparse(sito if "//" in sito else "https://" + sito).netloc
        dominio = d.lower().removeprefix("www.")
    conta: dict[str, int] = {}
    for m in RE_EMAIL.findall(testo or ""):
        e = m.lower().rstrip(".")
        dom_e = e.split("@")[1]
        if e.endswith(ESTENSIONI_FILE) or any(f in dom_e for f in DOMINI_FINTI):
            continue
        conta[e] = conta.get(e, 0) + 1
    return sorted(conta, key=lambda e: (
        0 if dominio and e.endswith("@" + dominio) else 1,
        0 if e.startswith("info@") else 1,
        -conta[e], e))


def tronca(testo: str, max_parole: int = config.MAX_PAROLE) -> str:
    """Taglia a ~max_parole mantenendo le righe (la struttura markdown aiuta l'LLM)."""
    totale, righe = 0, []
    for riga in testo.splitlines():
        n = len(riga.split())
        if totale + n > max_parole:
            break
        righe.append(riga)
        totale += n
    return "\n".join(righe)


async def fetch_azienda(crawler, url: str) -> tuple[str, str, int]:
    """-> (esito, contenuto_markdown, n_pagine_analizzate)"""
    home = await _scarica(crawler, url)
    if home is None:
        return "FETCH_FALLITO", "", 0

    pezzi = [f"# PAGINA: {url}\n\n{home['markdown']}"]
    for pagina in _pagine_rilevanti(home, url):
        dati = await _scarica(crawler, pagina)
        if dati:
            pezzi.append(f"# PAGINA: {pagina}\n\n{dati['markdown']}")

    return "OK", tronca("\n\n---\n\n".join(pezzi)), len(pezzi)


if __name__ == "__main__":
    assert _cache_path("https://www.fabbrox.it/grate").parent.name == "fabbrox.it"
    assert _cache_path("http://fabbrox.it/grate") != _cache_path("http://fabbrox.it/persiane")

    home = {
        "links": ["/blog/porte-blindate", "/chi-siamo", "/grate", "/contatti",
                  "/news/cancelli", "/persiane", "/gallery", "https://altro.it/grate"],
        "testi": ["Porte blindate", "Chi siamo", "Grate", "Contatti",
                  "Cancelli", "Persiane", "Gallery", "Grate"],
    }
    scelte = _pagine_rilevanti(home, "https://x.it/")
    # prodotto prima delle generiche, blog/news in fondo, dominio esterno mai
    assert scelte == ["https://x.it/grate", "https://x.it/persiane",
                      "https://x.it/chi-siamo", "https://x.it/contatti"], scelte

    testo = "\n".join(f"riga {i} con cinque parole" for i in range(100))
    assert len(tronca(testo, 20).split()) <= 20
    assert tronca(testo, 10_000) == testo
    print("ok")
