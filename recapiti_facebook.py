"""Recapiti dalle pagine Facebook PUBBLICHE delle aziende (richiesta del
cliente, 2026-09-28). Actor apify/facebook-pages-scraper, ~0,008 USD a
pagina misurati sul pilota (45 pagine: 78% con email, 78% con telefono).

    python recapiti_facebook.py                          # misura, non spende
    python recapiti_facebook.py --scrivi --budget-usd 3.4

Regole (decise col pilota):
- solo agganci CERTI: la pagina Facebook viene dal LORO sito (dal campo
  sito quando il "sito" e' la pagina FB, o dal markdown delle pagine in
  cache). Niente ricerca per nome+citta': quella e' un'altra storia, con
  le regole degli omonimi;
- i recapiti NON sovrascrivono mai un dato gia' presente da fonte
  migliore; ogni scrittura porta il segnale `recapito_facebook`;
- il registro cache/fb_scrappate.json ricorda le pagine gia' comprate:
  una pagina senza email resta senza email, ripagarla non la riempie;
- prima le classi A/B/C, poi le senza classificazione;
- tetto di spesa esplicito (--budget-usd), e comunque mai oltre il
  credito residuo del periodo meno 30 cent di margine.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys

import dedup
import fetch

QUI = pathlib.Path(__file__).parent
REGISTRO = QUI / "cache" / "fb_scrappate.json"
USD_A_PAGINA = 0.0085          # 0,0082 misurato + margine
RE_FB = re.compile(r"https?://(?:www\.|m\.|it-it\.)?facebook\.com/([^\s\"'<>)]+)", re.I)
NO_FB = ("sharer", "share.php", "/groups/", "/events/", "plugins", "login",
         "l.facebook", "/hashtag/", "photo.php", "watch/")


def pagina_fb(url: str) -> str:
    m = RE_FB.search(url or "")
    if not m:
        return ""
    u = m.group(0).split("?")[0].rstrip("/")
    if any(x in u.lower() for x in NO_FB):
        return ""
    coda = u.split("facebook.com/", 1)[1]
    return u if coda and coda not in ("", "pages") else ""


def chiave_url(u: str) -> str:
    u = (u or "").split("?")[0].rstrip("/").lower()
    u = u.replace("m.facebook", "www.facebook")
    for p in ("https://", "http://", "www."):
        u = u.removeprefix(p)
    return u


def campo(item: dict, *nomi) -> str:
    for n in nomi:
        v = item.get(n)
        if isinstance(v, list) and v:
            return str(v[0]).strip()
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def fb_dalla_cache(dominio: str) -> str:
    """Il link Facebook nel markdown delle pagine gia' scaricate. I `links`
    salvati sono solo interni: il Facebook sta nel testo."""
    cartella = QUI / "cache" / dominio
    if not dominio or not cartella.is_dir():
        return ""
    for f in cartella.glob("*.json"):
        try:
            dati = json.load(open(f))
        except Exception:  # noqa: BLE001
            continue
        testo = (dati.get("markdown") or "") + " ".join(
            str(t) for t in (dati.get("testi") or []))
        for m in RE_FB.finditer(testo):
            fb = pagina_fb(m.group(0))
            if fb:
                return fb
    return ""


def candidate(righe: list[dict], scrappate: dict) -> list[tuple[dict, str]]:
    """(riga, pagina fb) con aggancio certo, recapiti mancanti, mai comprate.
    Ordine: A, B, C, poi senza classificazione."""
    fuori = []
    for r in righe:
        if r.get("stato") == "scartato":
            continue
        if (r.get("email_aziendale") or "").strip() and (r.get("telefono") or "").strip():
            continue
        if any(s.get("tipo") == "recapito_facebook" for s in (r.get("segnali") or [])):
            continue
        fb = pagina_fb(r.get("sito") or "") or fb_dalla_cache(
            dedup.norm_dominio(r.get("sito") or r.get("dominio") or ""))
        if not fb or chiave_url(fb) in scrappate:
            continue
        fuori.append((r, fb))
    ordine = {"A": 0, "B": 1, "C": 2}
    return sorted(fuori, key=lambda x: ordine.get(x[0].get("classe"), 9))


def main_() -> int:
    scrivi = "--scrivi" in sys.argv
    budget = float(sys.argv[sys.argv.index("--budget-usd") + 1]) \
        if "--budget-usd" in sys.argv else 3.4

    from dotenv import load_dotenv
    load_dotenv(QUI / ".env")
    import db
    import sourcing_maps

    scrappate = json.loads(REGISTRO.read_text()) if REGISTRO.exists() else {}
    sb = db.client()
    righe, off = [], 0
    while True:
        b = sb.table("aziende").select(
            "id,ragione_sociale,classe,stato,email_aziendale,email_pec,telefono,"
            "sito,dominio,segnali").range(off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            break
        off += 1000
    cand = candidate(righe, scrappate)
    print(f"candidate certe mai comprate: {len(cand)} "
          f"(in classe: {sum(1 for r, _ in cand if r.get('classe') in 'ABC')})")

    c = sourcing_maps.credito(print)
    residuo = c[1] - c[0] if c else 0.0
    tetto = min(budget, max(0.0, residuo - 0.30))
    n_pagine = int(tetto / USD_A_PAGINA)
    urls = list(dict.fromkeys(fb for _, fb in cand))[:n_pagine]
    print(f"credito residuo {residuo:.2f} USD — tetto {tetto:.2f} -> {len(urls)} pagine")
    if not scrivi:
        print("(prova: nessuna spesa. Rilancia con --scrivi)")
        return 0
    if len(urls) < 5:
        print("meno di 5 pagine finanziabili: non vale una run")
        return 1

    from apify_client import ApifyClient
    client = ApifyClient(os.environ["APIFY_TOKEN"])
    run = client.actor("apify/facebook-pages-scraper").call(
        run_input={"startUrls": [{"url": u} for u in urls]})
    # il client 3.x restituisce un OGGETTO, non un dict
    did = getattr(run, "default_dataset_id", None) or getattr(run, "defaultDatasetId", None)
    usd = getattr(run, "usage_total_usd", None) or getattr(run, "usageTotalUsd", None)
    print(f"run: {getattr(run, 'status', '?')} — {usd} USD")
    items = list(client.dataset(did).iterate_items())

    per_url = {}
    for i in items:
        if i.get("error"):
            continue
        k = chiave_url(i.get("url") or i.get("pageUrl") or i.get("facebookUrl") or "")
        if k:
            per_url[k] = i
    import datetime
    oggi = datetime.date.today().isoformat()
    for u in urls:
        i = per_url.get(chiave_url(u))
        scrappate[chiave_url(u)] = {
            "quando": oggi,
            "email": bool(i and campo(i, "email", "emails")),
            "telefono": bool(i and campo(i, "phone", "phones", "phoneNumber"))}
    REGISTRO.write_text(json.dumps(scrappate, ensure_ascii=False))

    agg = em = tel = 0
    for r, fb in cand:
        i = per_url.get(chiave_url(fb))
        if not i:
            continue
        email = campo(i, "email", "emails")
        telefono = campo(i, "phone", "phones", "phoneNumber")
        aggiorna, presi = {}, []
        if email and fetch.e_pec(email):
            # una PEC non e' mai email_aziendale
            if not (r.get("email_pec") or "").strip():
                aggiorna["email_pec"] = email
                presi.append(f"PEC {email}")
        elif email and not (r.get("email_aziendale") or "").strip():
            aggiorna["email_aziendale"] = email
            em += 1
            presi.append(f"email {email}")
        if telefono and not (r.get("telefono") or "").strip():
            aggiorna["telefono"] = telefono
            tel += 1
            presi.append(f"telefono {telefono}")
        if not aggiorna:
            continue
        aggiorna["segnali"] = (r.get("segnali") or []) + [{
            "tipo": "recapito_facebook", "pagina": fb,
            "segnale": f"recapiti dalla pagina Facebook pubblica "
                       f"({', '.join(presi)}) — giro del {oggi}"}]
        sb.table("aziende").update(aggiorna).eq("id", r["id"]).execute()
        agg += 1
    con_email = sum(1 for i in per_url.values() if campo(i, "email", "emails"))
    print(f"pagine con dati: {len(per_url)}/{len(urls)} — con email {con_email}")
    print(f"aziende aggiornate: {agg} (email nuove {em}, telefoni nuovi {tel})")
    rimaste = len(cand) - len(urls)
    print(f"candidate rimaste per la tranche successiva: {rimaste}")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        assert pagina_fb("https://www.facebook.com/rossi.infissi/?ref=x") == \
            "https://www.facebook.com/rossi.infissi"
        assert pagina_fb("https://facebook.com/sharer/sharer.php?u=x") == ""
        assert pagina_fb("https://m.facebook.com/groups/12345") == ""
        assert pagina_fb("niente fb qui") == ""
        assert chiave_url("https://m.facebook.com/Rossi/?x=1") == "facebook.com/rossi"
        assert chiave_url("http://www.facebook.com/rossi/") == "facebook.com/rossi"
        assert campo({"emails": ["a@b.it", "c@d.it"]}, "email", "emails") == "a@b.it"
        assert campo({"email": " x@y.it "}, "email", "emails") == "x@y.it"
        assert campo({}, "email") == ""
        righe = [
            {"stato": "da_lavorare", "classe": None, "email_aziendale": "",
             "telefono": "06", "sito": "https://facebook.com/zeta", "segnali": []},
            {"stato": "da_lavorare", "classe": "A", "email_aziendale": "",
             "telefono": "", "sito": "https://facebook.com/alfa", "segnali": []},
            {"stato": "scartato", "classe": "A", "email_aziendale": "",
             "telefono": "", "sito": "https://facebook.com/no", "segnali": []},
            {"stato": "da_lavorare", "classe": "B", "email_aziendale": "a@b.it",
             "telefono": "06", "sito": "https://facebook.com/pieni", "segnali": []},
            {"stato": "da_lavorare", "classe": "C", "email_aziendale": "",
             "telefono": "", "sito": "https://facebook.com/gia",
             "segnali": [{"tipo": "recapito_facebook"}]},
        ]
        c = candidate(righe, {"facebook.com/comprata": {}})
        # scartate, complete, gia' marcate: fuori. A prima del senza classe.
        assert [x[1] for x in c] == ["https://facebook.com/alfa",
                                     "https://facebook.com/zeta"], c
        assert candidate([righe[0]], {"facebook.com/zeta": {}}) == []
        print("ok")
    else:
        sys.exit(main_())
