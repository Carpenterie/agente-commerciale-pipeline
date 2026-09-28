"""Controllo dei tre saldi PRIMA di spendere (Anthropic, Apify, Openapi).

In due settimane sono finiti tutti e tre, sempre scoperti a giro in corso:
il credito Anthropic a meta' import (290 righe a vuoto), il wallet Openapi
durante l'esplorativa agenti, l'Apify tenuto d'occhio a mano. Da oggi ogni
ciclo e ogni script che spende CONTROLLA prima, e se un saldo e' sotto la
soglia stimata per il giro non parte: l'ESITO dice quale ricaricare.

    python crediti.py       # stampa i tre saldi (riga mensile di cron)

Cosa si riesce a leggere, onestamente:
- APIFY: saldo numerico vero (users/me/limits, gratis);
- ANTHROPIC: nessuna API di saldo — solo un canarino da ~5 token
  (0,0002 USD): dice se il credito c'e', non quanto;
- OPENAPI: nessun endpoint di saldo raggiungibile col token (la console
  e' dietro Cloudflare). Il numero lo rivela SOLO l'errore 402
  ("Insufficient Credit in Wallet: 0.1 > 0.057"): il controllo fa una
  IT-advanced sulla P.IVA della committente — a wallet vuoto la 402 e'
  gratis e porta il saldo, a wallet carico la visura costa il pedaggio
  di 0,10 EUR e vale come semaforo verde.
Il controllo iniziale non copre l'esaurimento A META' giro: per quello
c'e' il salvavita delle dieci analisi fallite uguali (main.py).
"""

from __future__ import annotations

import os
import re
import sys

# La P.IVA della committente: una visura vera come canarino Openapi, cosi'
# il pedaggio da 0,10 almeno interroga un dato reale.
PIVA_CANARINO = "05962321005"
RE_SALDO_402 = re.compile(r"Insufficient Credit in Wallet: [\d.]+ > ([\d.]+)")
# Rispecchiano cron.example: cadenza trimestrale, e il trimestre di ottobre
# 2026 saltato dalla guardia. Se cambia la cadenza del cron, cambia qui.
MESI_CICLO = (1, 4, 7, 10)
GUARDIA_SALTA = (2026, 10)


def prossimo_rinnovo_apify(oggi):
    """Il prossimo 7 del mese (rinnovo del periodo di fatturazione Apify),
    strettamente futuro: sul 7 stesso il rinnovo di oggi e' gia' passato."""
    import datetime
    if oggi.day < 7:
        return datetime.date(oggi.year, oggi.month, 7)
    m = oggi.month % 12 + 1
    return datetime.date(oggi.year + (oggi.month == 12), m, 7)


def prossimo_giro_apify(oggi):
    """La prossima data in cui un ciclo da cron rifa' il sourcing (spende
    Apify): giorno 1 di un mese trimestrale, saltando il trimestre in
    guardia. E' RM il giorno 1 a spendere per primo, prima del rinnovo."""
    import datetime
    for anno in range(oggi.year, oggi.year + 21):
        for mese in MESI_CICLO:
            d = datetime.date(anno, mese, 1)
            if d > oggi and (d.year, d.month) != GUARDIA_SALTA:
                return d
    return None


def saldo_apify(log=print) -> float | None:
    """USD residui nel periodo di fatturazione corrente."""
    import sourcing_maps
    c = sourcing_maps.credito(log)
    return round(c[1] - c[0], 2) if c else None


def anthropic_ok(log=print) -> bool | None:
    """True/False = il credito c'e'/non c'e'. None = errore di rete
    (non e' un no: il giro decide il chiamante)."""
    import config
    from anthropic import Anthropic

    try:
        Anthropic(max_retries=0).messages.create(
            model=config.MODELLO, max_tokens=5, timeout=30,
            messages=[{"role": "user", "content": "ok"}])
        return True
    except Exception as e:  # noqa: BLE001
        testo = str(e)
        if "credit balance is too low" in testo:
            return False
        log(f"canarino Anthropic non conclusivo: {type(e).__name__}")
        return None


def saldo_openapi(log=print) -> tuple[float | None, str]:
    """-> (saldo EUR se il 402 lo rivela, descrizione). Saldo None con
    'presente' = credito >= 0,10 ma cifra non leggibile (limite noto)."""
    import urllib.error
    import urllib.request

    token = os.environ.get("OPENAPI_TOKEN", "").strip()
    if not token:
        return None, "OPENAPI_TOKEN non configurato"
    req = urllib.request.Request(
        f"https://company.openapi.com/IT-advanced/{PIVA_CANARINO}",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60):
            return None, "presente (>0,10 EUR; pedaggio di 0,10 pagato)"
    except urllib.error.HTTPError as e:
        corpo = e.read().decode()
        m = RE_SALDO_402.search(corpo)
        if m:
            return float(m.group(1)), f"ESAURITO: {m.group(1)} EUR"
        return None, f"non leggibile (HTTP {e.code})"
    except Exception as e:  # noqa: BLE001
        return None, f"non leggibile ({type(e).__name__})"


def _riga(servizio, stato, saldo, unita, soglia, messaggio, fonte):
    import datetime
    return {"servizio": servizio, "stato": stato, "saldo": saldo,
            "unita": unita, "soglia": soglia, "messaggio": messaggio,
            "letto_il": datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="seconds"), "fonte_lettura": fonte}


def scrivi_stato(sb, righe, log=print) -> None:
    """La lettura arriva in `stato_sistema`, dove la dashboard la mostra a
    chi puo' ricaricare. Aggiornamento sul posto (mai upsert/delete, vedi
    db.py); se la tabella non c'e' ancora, il controllo NON si rompe."""
    if sb is None:
        return
    for r in righe:
        try:
            fatti = sb.table("stato_sistema").update(r)                 .eq("servizio", r["servizio"]).execute().data
            if not fatti:
                sb.table("stato_sistema").insert(r).execute()
        except Exception as e:  # noqa: BLE001
            log(f"stato_sistema non scrivibile ({type(e).__name__}): "
                f"la tabella esiste?")
            return


def letture(serve_apify_usd: float = 0, serve_anthropic: bool = False,
            serve_openapi_eur: float = 0, fonte: str = "controllo_pre_giro",
            log=print) -> tuple[list[dict], list[str]]:
    """Legge SOLO i saldi richiesti. -> (righe per stato_sistema, problemi
    che fermano il giro). Ogni problema dice quale credito e di quanto."""
    righe, problemi = [], []
    if serve_apify_usd > 0:
        import datetime
        import sourcing_maps
        c = sourcing_maps.credito(log)
        if c is None:
            righe.append(_riga("apify", "non_verificabile", None, "USD",
                               serve_apify_usd, "Saldo Apify non leggibile: "
                               "verificare a mano su console.apify.com", fonte))
        else:
            residuo, tetto = round(c[1] - c[0], 2), c[1]
            oggi = datetime.date.today()
            giro = prossimo_giro_apify(oggi)
            quando = f"{giro:%d/%m/%Y}" if giro else "?"
            rinnova_prima = giro is None or prossimo_rinnovo_apify(oggi) <= giro
            # BLOCCO del giro in corso: sempre sul saldo di ADESSO — i soldi
            # per un giro che parte ora servono ora, non dopo il rinnovo
            if residuo < serve_apify_usd:
                problemi.append(f"credito Apify insufficiente: restano "
                                f"{residuo:.2f} USD, il giro ne stima "
                                f"{serve_apify_usd:.2f}")
            # STATO per il banner: guarda avanti. Un banner e' una richiesta
            # di AZIONE — se il credito si rinnova (il 7) prima del prossimo
            # giro in calendario, non c'e' niente da chiedere a Claudia
            effettivo = tetto if rinnova_prima else residuo
            if effettivo >= serve_apify_usd:
                if residuo < serve_apify_usd:
                    m = (f"Credito Apify {residuo:.2f} USD: si rinnova a "
                         f"{tetto:.0f} il 7, prima del prossimo giro ({quando}) "
                         f"— sufficiente, nessuna azione")
                else:
                    m = f"Credito Apify: {residuo:.2f} USD residui"
                righe.append(_riga("apify", "ok", residuo, "USD",
                                   serve_apify_usd, m, fonte))
            elif rinnova_prima:
                m = (f"Credito Apify: anche dopo il rinnovo del 7 restano solo "
                     f"{tetto:.0f} USD, ma un giro ne stima {serve_apify_usd:.0f} "
                     f"— alzare il tetto del piano")
                righe.append(_riga("apify", "sotto_soglia", residuo, "USD",
                                   serve_apify_usd, m, fonte))
            else:
                m = (f"Credito Apify quasi esaurito ({residuo:.2f} USD) e il "
                     f"prossimo giro ({quando}) cade prima del rinnovo del 7: "
                     f"ricaricare o rinviare il giro")
                righe.append(_riga("apify", "sotto_soglia", residuo, "USD",
                                   serve_apify_usd, m, fonte))
    if serve_anthropic:
        ok = anthropic_ok(log)
        if ok is False:
            m = ("Credito Anthropic ESAURITO: ricaricare su "
                 "console.anthropic.com prima del prossimo aggiornamento")
            righe.append(_riga("anthropic", "esaurito", None, None, None, m, fonte))
            problemi.append("credito Anthropic ESAURITO: ricaricare su "
                            "console.anthropic.com prima di rilanciare")
        elif ok is None:
            righe.append(_riga("anthropic", "non_verificabile", None, None, None,
                               "Credito Anthropic non verificabile (rete?)", fonte))
        else:
            righe.append(_riga("anthropic", "ok", None, None, None,
                               "Credito Anthropic presente", fonte))
    if serve_openapi_eur > 0:
        saldo, desc = saldo_openapi(log)
        if saldo is not None and saldo < serve_openapi_eur:
            manca = serve_openapi_eur - saldo
            m = (f"Credito Openapi esaurito ({saldo:.2f} EUR): ricaricare "
                 f"almeno {manca:.0f} EUR prima del prossimo aggiornamento")
            righe.append(_riga("openapi", "esaurito", saldo, "EUR",
                               serve_openapi_eur, m, fonte))
            problemi.append(f"wallet Openapi insufficiente: {saldo:.2f} EUR, "
                            f"il giro ne stima {serve_openapi_eur:.2f} — "
                            f"ricaricare almeno {manca:.0f} EUR")
        elif saldo is None and "presente" in desc:
            righe.append(_riga("openapi", "ok", None, "EUR", serve_openapi_eur,
                               "Credito Openapi presente", fonte))
        else:
            righe.append(_riga("openapi", "non_verificabile", None, "EUR",
                               serve_openapi_eur,
                               f"Saldo Openapi {desc}", fonte))
            log(f"saldo Openapi {desc}: non blocco, il salvavita in corsa vigila")
    return righe, problemi


def allarmi(sb=None, log=print) -> list[dict]:
    """Rilegge SOLO i servizi attualmente in allarme (sotto_soglia/esaurito):
    se Claudia ha ricaricato oggi, il banner si spegne domani invece che al
    1° del mese. Gratis per Apify e per Openapi a wallet vuoto (la 402); il
    pedaggio di 0,10 su Openapi si paga solo alla lettura che TROVA credito
    e scrive ok. I servizi gia' ok restano alla lettura mensile."""
    import config
    if sb is None:
        import db
        sb = db.client()
    try:
        stato = sb.table("stato_sistema").select("servizio,stato").execute().data
    except Exception as e:  # noqa: BLE001
        log(f"stato_sistema non leggibile ({type(e).__name__})")
        return []
    rossi = {r["servizio"] for r in stato
             if r["stato"] in ("sotto_soglia", "esaurito")}
    if not rossi:
        log("nessun servizio in allarme: niente da rileggere")
        return []
    righe, _ = letture(
        serve_apify_usd=config.STIMA_APIFY_CICLO_USD if "apify" in rossi else 0,
        serve_anthropic="anthropic" in rossi,
        serve_openapi_eur=config.STIMA_OPENAPI_CICLO_EUR if "openapi" in rossi else 0,
        fonte="ricontrollo_allarme", log=log)
    scrivi_stato(sb, righe, log)
    return righe


def controllo(serve_apify_usd: float = 0, serve_anthropic: bool = False,
              serve_openapi_eur: float = 0, log=print, sb=None) -> list[str]:
    """-> gli avvisi che devono FERMARE il giro (vuota = si parte).
    Se `sb` c'e', la lettura finisce anche in `stato_sistema`."""
    righe, problemi = letture(serve_apify_usd, serve_anthropic,
                              serve_openapi_eur, "controllo_pre_giro", log)
    scrivi_stato(sb, righe, log)
    return problemi


if __name__ == "__main__":
    if "--test" in sys.argv:
        m = RE_SALDO_402.search('{"message":"Billing error message: Insufficient '
                                'Credit in Wallet: 0.1 > 0.057 code 810"}')
        assert m and m.group(1) == "0.057"
        assert RE_SALDO_402.search("altro errore") is None
        r = _riga("openapi", "esaurito", 0.06, "EUR", 8.0, "msg", "log_mensile")
        assert r["servizio"] == "openapi" and r["saldo"] == 0.06
        assert r["letto_il"].endswith("+00:00") and r["fonte_lettura"] == "log_mensile"
        import datetime
        assert prossimo_rinnovo_apify(datetime.date(2026, 9, 28)) == datetime.date(2026, 10, 7)
        assert prossimo_rinnovo_apify(datetime.date(2026, 10, 7)) == datetime.date(2026, 11, 7)
        assert prossimo_rinnovo_apify(datetime.date(2026, 12, 20)) == datetime.date(2027, 1, 7)
        # il trimestre di ottobre 2026 e' saltato dalla guardia
        assert prossimo_giro_apify(datetime.date(2026, 9, 28)) == datetime.date(2027, 1, 1)
        assert prossimo_giro_apify(datetime.date(2027, 1, 1)) == datetime.date(2027, 4, 1)
        assert prossimo_giro_apify(datetime.date(2027, 2, 10)) == datetime.date(2027, 4, 1)
        print("ok")
    elif "--allarmi" in sys.argv:
        from dotenv import load_dotenv
        load_dotenv()
        righe = allarmi()
        for r in righe:
            print(f"{r['servizio']:<9}: {r['stato']} — {r['messaggio']}")
    else:
        from dotenv import load_dotenv
        load_dotenv()
        import datetime
        print(f"=== SALDI {datetime.date.today().isoformat()} ===")
        import config
        righe, _ = letture(serve_apify_usd=config.STIMA_APIFY_CICLO_USD,
                           serve_anthropic=True,
                           serve_openapi_eur=config.STIMA_OPENAPI_CICLO_EUR,
                           fonte="log_mensile")
        for r in righe:
            print(f"{r['servizio']:<9}: {r['messaggio']}")
        try:
            import db
            scrivi_stato(db.client(), righe)
        except Exception as e:  # noqa: BLE001
            print(f"stato_sistema non aggiornata ({type(e).__name__})")
