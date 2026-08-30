"""Download homepage + fino a 4 pagine interne rilevanti, in markdown, con cache su disco."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

CACHE = Path(__file__).parent / "cache"
MAX_PAGINE_INTERNE = 4
MAX_PAROLE = 15_000
TIMEOUT_MS = 30_000

# pagine di prodotto: sono quelle che dicono davvero se lavorano l'acciaio
PAROLE_PRODOTTO = (
    "grate", "persiane", "cancelli", "inferriate", "recinzioni", "blindat",
    "sicurezza", "portoni", "ringhiere", "ferro", "acciaio",
)
PAROLE_GENERICHE = (
    "prodotti", "servizi", "lavorazioni", "chi-siamo", "chi_siamo", "chisiamo",
    "chi siamo", "azienda", "realizzazioni", "lavori", "gallery", "galleria",
    "portfolio",
)
PAROLE_CHIAVE = PAROLE_GENERICHE + PAROLE_PRODOTTO
# blog, news e social parlano dei prodotti ma non provano la produzione:
# eleggibili solo se avanzano slot (caso Fabbro a Milano: 11 articoli
# "porte blindate" escludevano le pagine realizzazione-cancelli/ringhiere)
DEPRIORITA = ("/blog", "/news", "facebook", "instagram", "linkedin", "youtube", "twitter")


def _cache_path(url: str) -> Path:
    return CACHE / (hashlib.md5(url.encode()).hexdigest() + ".json")


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

    config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=TIMEOUT_MS)
    for tentativo in range(2):
        try:
            result = await crawler.arun(url=url, config=config)
            if result.success:
                dati = {
                    "markdown": _markdown(result),
                    "links": [l.get("href", "") for l in (result.links or {}).get("internal", [])],
                    "testi": [l.get("text", "") for l in (result.links or {}).get("internal", [])],
                }
                CACHE.mkdir(exist_ok=True)
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
        candidate.append((depri, not prodotto, indice, assoluto))
    return [url for *_, url in sorted(candidate)[:MAX_PAGINE_INTERNE]]


def tronca(testo: str, max_parole: int = MAX_PAROLE) -> str:
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
