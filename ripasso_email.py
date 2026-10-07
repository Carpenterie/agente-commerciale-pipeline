"""Ripasso email per le A/B/C ancora senza email_aziendale (richiesta del
commerciale, 2026-09-29: 56 email trovate a mano; diagnosi: in 20 casi su
27 la pagina contatti perdeva la gara degli slot in fetch, ora ha lo slot
garantito).

    python ripasso_email.py             # misura: solo cache, zero rete
    python ripasso_email.py --scrivi    # scrive, e scarica la pagina
                                        # contatti dove la cache non basta
    python ripasso_email.py --pec           # misura: PEC in email_aziendale
    python ripasso_email.py --pec --scrivi  # le sposta in email_pec
    python ripasso_email.py --test

Regole:
- si riempie SOLO email_aziendale vuota, mai sovrascritture;
- una PEC non diventa MAI email_aziendale: va in email_pec se vuota
  (fetch.e_pec, 7/10: un'email commerciale non parte mai verso una PEC);
- ogni scrittura porta il segnale email_dal_sito con la provenienza;
- il download e' UNA pagina per azienda: il link contatti letto dalla
  homepage in cache, o <sito>/contatti alla cieca. La pagina finisce in
  cache e resta per i cicli futuri.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import sys
from urllib.parse import urldefrag, urljoin, urlparse

import config
import dedup
import fetch

MAX_ERRORI_SCRITTURA = 10


def _dominio(sito: str) -> str:
    d = urlparse(sito if "//" in sito else "https://" + sito).netloc
    return d.lower().removeprefix("www.")


def _record_home(sito: str) -> tuple[dict, str] | tuple[None, None]:
    """Il record di cache della homepage, provando le varianti di URL
    (slash, schema, www) con cui puo' essere stata scaricata."""
    s = sito.strip()
    varianti = []
    for base in (s, s.rstrip("/"), s.rstrip("/") + "/"):
        for schema in (base, base.replace("http://", "https://"),
                       base.replace("https://", "http://")):
            for w in (schema, schema.replace("://www.", "://"),
                      schema.replace("://", "://www.", 1)):
                if w not in varianti:
                    varianti.append(w)
    for v in varianti:
        p = fetch._cache_path(v)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")), v
            except ValueError:
                continue
    return None, None


def _email_da_cache(sito: str, pec: bool = False) -> list[str]:
    cartella = fetch.CACHE / _dominio(sito)
    if not cartella.is_dir():
        return []
    testi = []
    for f in cartella.glob("*.json"):
        try:
            testi.append(json.loads(f.read_text(encoding="utf-8"))["markdown"])
        except (ValueError, KeyError):
            continue
    return fetch.estrai_email("\n".join(testi), sito, pec=pec)


def _url_contatti(sito: str) -> str:
    """Il link contatti dalla homepage in cache, o /contatti alla cieca."""
    home, base = _record_home(sito)
    if home:
        for href, testo in zip(home["links"], home["testi"]):
            ago = f"{href} {testo}".lower()
            if "contatt" in ago or "contact" in ago:
                assoluto = urldefrag(urljoin(base, href)).url.rstrip("/")
                if urlparse(assoluto).netloc == urlparse(base).netloc:
                    return assoluto
    return sito.rstrip("/") + "/contatti"


def candidate(sb) -> list[dict]:
    righe, da = [], 0
    while True:
        b = (sb.table("aziende")
             .select("id,ragione_sociale,sito,email_aziendale,email_pec,classe,stato,segnali")
             .in_("classe", list(config.CLASSI_DA_ARRICCHIRE))
             .range(da, da + 999).execute().data)
        righe += b
        if len(b) < 1000:
            break
        da += 1000
    return [r for r in righe
            if r.get("stato") != "scartato"
            and not (r.get("email_aziendale") or "").strip()
            and (r.get("sito") or "").strip()
            and not dedup.e_portale(r["sito"])]


def giro(scrivi: bool, log=print) -> None:
    import db
    sb = db.client()
    righe = candidate(sb)
    log(f"A/B/C senza email e con sito vero: {len(righe)}")

    oggi = datetime.date.today().isoformat()
    da_cache, da_scarico, senza, errori_fila = 0, 0, [], 0

    def salva(r, email, provenienza) -> bool:
        nonlocal errori_fila
        segnali = (r.get("segnali") or []) + [{
            "tipo": "email_dal_sito",
            "segnale": f"email {email} {provenienza} — ripasso del {oggi}"}]
        try:
            sb.table("aziende").update(
                {"email_aziendale": email, "segnali": segnali}
            ).eq("id", r["id"]).execute()
            errori_fila = 0
            return True
        except Exception as e:  # noqa: BLE001
            errori_fila += 1
            log(f"  ERRORE scrittura {r['ragione_sociale'][:30]}: {type(e).__name__}")
            return False

    def salva_pec(r, testo_o_lista, provenienza) -> None:
        """La PEC trovata dal ripasso va in email_pec, se vuota."""
        pec = (testo_o_lista if isinstance(testo_o_lista, list)
               else fetch.estrai_email(testo_o_lista, r["sito"], pec=True))
        if scrivi and pec and not (r.get("email_pec") or "").strip():
            r["segnali"] = (r.get("segnali") or []) + [{
                "tipo": "email_pec",
                "segnale": f"PEC {pec[0]} {provenienza}, in email_pec — ripasso del {oggi}"}]
            sb.table("aziende").update({"email_pec": pec[0], "segnali": r["segnali"]}
                                       ).eq("id", r["id"]).execute()
            r["email_pec"] = pec[0]

    resto = []
    for r in righe:
        salva_pec(r, _email_da_cache(r["sito"], pec=True), "dalle pagine del sito in cache")
        trovate = _email_da_cache(r["sito"])
        if trovate:
            log(f"  [cache]    {r['ragione_sociale'][:44]:<46} {trovate[0]}")
            if not scrivi or salva(r, trovate[0], "dalle pagine del sito in cache"):
                da_cache += 1
        else:
            resto.append(r)
        if errori_fila >= MAX_ERRORI_SCRITTURA:
            log(f"STOP: {errori_fila} scritture fallite di fila")
            return

    if not scrivi:
        log(f"MISURA: {da_cache} recuperabili subito dalla cache, "
            f"{len(resto)} richiederebbero la pagina contatti (--scrivi)")
        return

    async def _scarica_contatti() -> None:
        nonlocal da_scarico, errori_fila
        from crawl4ai import AsyncWebCrawler
        async with AsyncWebCrawler(verbose=False) as crawler:
            for i, r in enumerate(resto, 1):
                url = _url_contatti(r["sito"])
                try:
                    dati = await fetch._scarica(crawler, url)
                except Exception as e:  # noqa: BLE001
                    log(f"  fetch KO {r['ragione_sociale'][:30]}: {type(e).__name__}")
                    dati = None
                salva_pec(r, (dati or {}).get("markdown", ""), f"dalla pagina {url}")
                trovate = fetch.estrai_email((dati or {}).get("markdown", ""),
                                             r["sito"])
                if trovate:
                    log(f"  [contatti] {r['ragione_sociale'][:44]:<46} {trovate[0]}")
                    if salva(r, trovate[0], f"dalla pagina {url}"):
                        da_scarico += 1
                else:
                    senza.append(r["ragione_sociale"])
                if errori_fila >= MAX_ERRORI_SCRITTURA:
                    log(f"STOP: {errori_fila} scritture fallite di fila")
                    return
                if i % 25 == 0:
                    log(f"  [{i}/{len(resto)}]")

    asyncio.run(_scarica_contatti())
    log(f"\nRIPASSO: {da_cache} email dalla cache (gratis), "
        f"{da_scarico} dalla pagina contatti scaricata, "
        f"{len(senza)} restano senza")


def sposta_pec(scrivi: bool, log=print) -> None:
    """Una tantum (7/10): le PEC finite in email_aziendale passano in
    email_pec. Niente si cancella: la PEC resta in email_pec, il passaggio
    in un segnale; al suo posto un'altra email NON PEC del sito in cache,
    altrimenti email_aziendale vuota (la scheda torna fra le senza email)."""
    import db
    sb = db.client()
    righe, da = [], 0
    while True:
        b = (sb.table("aziende").select("id,ragione_sociale,sito,email_aziendale,email_pec,segnali")
             .not_.is_("email_aziendale", "null").range(da, da + 999).execute().data)
        righe += b
        if len(b) < 1000:
            break
        da += 1000
    pec = [r for r in righe if fetch.e_pec(r["email_aziendale"])]
    oggi = datetime.date.today().isoformat()
    sostituite = 0
    for r in pec:
        vecchia = r["email_aziendale"].strip()
        altra = (_email_da_cache(r["sito"]) or [None])[0] if (r.get("sito") or "").strip() else None
        sostituite += bool(altra)
        log(f"  {r['ragione_sociale'][:44]:<46} {vecchia} -> "
            f"{altra or 'email_aziendale vuota'}")
        if not scrivi:
            continue
        segnale = (f"PEC {vecchia} spostata da email_aziendale a email_pec"
                   + (f"; email_aziendale ora {altra}, dalle pagine del sito in cache"
                      if altra else "; nessun'altra email nella cache del sito: "
                                    "email_aziendale vuota")
                   + f" — ripasso del {oggi}")
        sb.table("aziende").update({
            "email_pec": (r.get("email_pec") or "").strip() or vecchia,
            "email_aziendale": altra,
            "segnali": (r.get("segnali") or []) + [{"tipo": "email_pec", "segnale": segnale}],
        }).eq("id", r["id"]).execute()
    log(f"{'SPOSTATE' if scrivi else 'MISURA'}: {len(pec)} PEC in email_aziendale, "
        f"{sostituite} con un'altra email del sito, {len(pec) - sostituite} restano senza")


if __name__ == "__main__":
    if "--test" in sys.argv:
        md = ("Scrivici: [info@rossi.it](mailto:info@rossi.it) oppure "
              "commerciale@rossi.it — commerciale@rossi.it — "
              "![logo](logo@2x.png) support@sentry.io x@example.com")
        e = fetch.estrai_email(md, "https://www.rossi.it/")
        assert e[0] == "info@rossi.it", e            # dominio + info@ prima
        assert "commerciale@rossi.it" in e and len(e) == 2, e
        assert fetch.estrai_email("nulla qui") == []
        e2 = fetch.estrai_email("a@altro.it b@altro.it b@altro.it", "rossi.it")
        assert e2[0] == "b@altro.it", e2             # a parita', frequenza
        assert _dominio("http://www.abc.it/x") == "abc.it"
        assert _url_contatti("https://sito-mai-visto-xyz.it")\
            == "https://sito-mai-visto-xyz.it/contatti"
        print("ok")
        sys.exit(0)

    from dotenv import load_dotenv
    load_dotenv()
    if "--pec" in sys.argv:
        sposta_pec(scrivi="--scrivi" in sys.argv)
    else:
        giro(scrivi="--scrivi" in sys.argv)
