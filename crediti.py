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
- EXA: nessun endpoint di saldo (verificato il 29/9: /balance, /account,
  /usage rispondono 404) — canarino da una ricerca minima (~mezzo
  centesimo): presente/esaurito. Il controllo vero e' il tetto di spesa
  DENTRO i giri Exa, che leggono costDollars a ogni risposta;
- OPENAPI: nessun endpoint di saldo raggiungibile col token (la console
  e' dietro Cloudflare). Il numero lo rivela SOLO l'errore 402
  ("Insufficient Credit in Wallet: 0.1 > 0.057"): il controllo fa una
  IT-advanced sulla P.IVA della committente — a wallet vuoto la 402 e'
  gratis e porta il saldo, a wallet carico la visura costa il pedaggio
  di 0,10 EUR e vale come semaforo verde.
Il controllo iniziale non copre l'esaurimento A META' giro: per quello
c'e' il salvavita delle dieci analisi fallite uguali (main.py).

REGISTRO OPENAPI (2026-10-07): finche' il wallet ha credito il saldo non
si legge, quindi il controllo non poteva fermare un giro PRIMA di finirlo.
Ora alla ricarica si dichiara il saldo:

    python crediti.py --openapi-saldo 50

e ogni visura pagata (arricchimento._chiama, canarino compreso) lo scala
in cache/openapi_saldo.json. Il controllo pre-giro confronta il residuo con
la stima della provincia e non parte se non basta; dentro il giro, main
smette di chiedere visure prima di arrivare a zero. Le 30 chiamate gratis
del mese non si scalano: il residuo stimato e' per difetto, mai per eccesso.
"""

from __future__ import annotations

import os
import re
import sys

# La P.IVA della committente: una visura vera come canarino Openapi, cosi'
# il pedaggio da 0,10 almeno interroga un dato reale.
PIVA_CANARINO = "05962321005"
RE_SALDO_402 = re.compile(r"Insufficient Credit in Wallet: [\d.]+ > ([\d.]+)")
# Rispecchiano cron.example: cadenza trimestrale per regione, sfalsata di
# mese in mese perche' nessun periodo Apify (dal 7 al 6) porti piu' di un
# terzo dei ripassi. (mesi, primo giorno, mese saltato dalla guardia):
# Lazio dal 1°; Toscana e Abruzzo dall'8 dei mesi dopo; Campania, Puglia e
# Marche dall'8 di quelli dopo ancora. Le guardie saltano il primo giro
# di chi e' stato appena raccolto a mano. Se cambia il cron, cambia qui.
CALENDARIO_GIRI = (((1, 4, 7, 10), 1, (2026, 10)),
                   ((2, 5, 8, 11), 8, (2026, 11)),
                   ((3, 6, 9, 12), 8, (2026, 12)))
REGISTRO_OPENAPI = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "cache", "openapi_saldo.json")


def dichiara_openapi(saldo_eur: float) -> dict:
    """Alla ricarica: il saldo letto sulla console Openapi."""
    import datetime
    import json
    r = {"saldo_eur": float(saldo_eur), "speso_eur": 0.0,
         "dal": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    os.makedirs(os.path.dirname(REGISTRO_OPENAPI), exist_ok=True)
    with open(REGISTRO_OPENAPI, "w") as f:
        json.dump(r, f)
    return r


def _registro() -> dict | None:
    import json
    try:
        with open(REGISTRO_OPENAPI) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def registra_spesa_openapi(eur: float) -> None:
    import json
    r = _registro()
    if r is None:
        return              # nessun saldo dichiarato: niente da scalare
    r["speso_eur"] = round(r.get("speso_eur", 0) + eur, 2)
    with open(REGISTRO_OPENAPI, "w") as f:
        json.dump(r, f)


def residuo_openapi(sb=None) -> float | None:
    """EUR residui stimati dal registro, o None se nessun saldo e' dichiarato."""
    r = _registro()
    return None if r is None else round(r["saldo_eur"] - r.get("speso_eur", 0), 2)


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
    Apify), su tutto il calendario delle regioni, saltando i mesi in guardia."""
    import datetime
    date = [datetime.date(anno, mese, giorno)
            for anno in range(oggi.year, oggi.year + 3)
            for mesi, giorno, guardia in CALENDARIO_GIRI for mese in mesi
            if (anno, mese) != guardia]
    future = [d for d in date if d > oggi]
    return min(future) if future else None


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


def exa_ok(log=print) -> bool | None:
    """True/False = il credito Exa c'e'/non c'e'. None = non conclusivo."""
    import json
    import urllib.error
    import urllib.request

    k = os.environ.get("EXA_API_KEY", "").strip()
    if not k:
        return None
    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=json.dumps({"query": "test", "numResults": 1}).encode(),
        headers={"content-type": "application/json", "x-api-key": k})
    try:
        with urllib.request.urlopen(req, timeout=30):
            return True
    except urllib.error.HTTPError as e:
        corpo = e.read().decode()[:200].lower()
        if e.code in (402, 403) or "credit" in corpo or "balance" in corpo:
            return False
        log(f"canarino Exa non conclusivo (HTTP {e.code})")
        return None
    except Exception as e:  # noqa: BLE001
        log(f"canarino Exa non conclusivo: {type(e).__name__}")
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
            registra_spesa_openapi(0.10)
            return None, "presente (>0,10 EUR; pedaggio di 0,10 pagato)"
    except urllib.error.HTTPError as e:
        corpo = e.read().decode()
        m = RE_SALDO_402.search(corpo)
        if m:
            return float(m.group(1)), f"ESAURITO: {m.group(1)} EUR"
        return None, f"non leggibile (HTTP {e.code})"
    except Exception as e:  # noqa: BLE001
        return None, f"non leggibile ({type(e).__name__})"


def token_openapi_ok(log=print) -> bool | None:
    """Il token e' accettato? Con una IT-search in dryRun (nel gratuito).
    Il 7/10 il pilota di Pisa ha girato con il token rifiutato ("Wrong
    Token", 401): niente visure su 90 A/B/C, e il controllo non lo vedeva
    perche' il registro del saldo aveva tolto il canarino."""
    import urllib.error
    import urllib.request
    token = os.environ.get("OPENAPI_TOKEN", "").strip()
    if not token:
        return False
    req = urllib.request.Request(
        # dryRun=1: restituisce solo il conteggio. Listino Openapi (Company
        # Search, verificato il 7/10): 100 richieste al giorno gratuite, dryRun
        # compreso, poi 0,01 EUR + IVA l'una — una per giro resta nel gratuito
        "https://company.openapi.com/IT-search?companyName=carpenterie&province=RM&dryRun=1",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30):
            return True
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False
        return True if e.code in (402, 404, 204) else None
    except Exception as e:  # noqa: BLE001
        log(f"verifica token Openapi non conclusiva: {type(e).__name__}")
        return None


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
            serve_openapi_eur: float = 0, serve_exa: bool = False,
            fonte: str = "controllo_pre_giro",
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
    if serve_exa:
        ok = exa_ok(log)
        if ok is False:
            m = ("Credito Exa ESAURITO: ricaricare su dashboard.exa.ai "
                 "prima del prossimo aggiornamento")
            righe.append(_riga("exa", "esaurito", None, None, None, m, fonte))
            problemi.append("credito Exa ESAURITO: ricaricare su dashboard.exa.ai")
        elif ok is None:
            righe.append(_riga("exa", "non_verificabile", None, None, None,
                               "Credito Exa non verificabile (rete?)", fonte))
        else:
            righe.append(_riga("exa", "ok", None, None, None,
                               "Credito Exa presente (il saldo non e' esposto: "
                               "i giri hanno il tetto di spesa interno)", fonte))
    residuo = residuo_openapi() if serve_openapi_eur > 0 else None
    if serve_openapi_eur > 0 and token_openapi_ok(log) is False:
        m = ("Token Openapi RIFIUTATO (401 Wrong Token): generarne uno nuovo "
             "sulla console Openapi e aggiornare OPENAPI_TOKEN nel .env")
        righe.append(_riga("openapi", "esaurito", residuo, "EUR", serve_openapi_eur, m, fonte))
        problemi.append("token Openapi rifiutato: le visure fallirebbero tutte — "
                        "aggiornare OPENAPI_TOKEN prima del giro")
    elif residuo is not None:
        # saldo dichiarato alla ricarica: niente canarino (e niente pedaggio)
        if residuo < serve_openapi_eur:
            m = (f"Credito Openapi quasi finito: residuo stimato {residuo:.2f} EUR, "
                 f"un ciclo ne stima {serve_openapi_eur:.2f} — ricaricare e poi "
                 f"'python crediti.py --openapi-saldo <saldo>'")
            righe.append(_riga("openapi", "sotto_soglia", residuo, "EUR",
                               serve_openapi_eur, m, fonte))
            problemi.append(f"wallet Openapi: residuo stimato {residuo:.2f} EUR, il "
                            f"ciclo ne stima {serve_openapi_eur:.2f} — ricaricare "
                            f"prima di questa provincia")
        else:
            righe.append(_riga("openapi", "ok", residuo, "EUR", serve_openapi_eur,
                               f"Credito Openapi: residuo stimato {residuo:.2f} EUR "
                               f"(saldo dichiarato meno le visure pagate)", fonte))
    elif serve_openapi_eur > 0:
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
        serve_exa="exa" in rossi,
        fonte="ricontrollo_allarme", log=log)
    scrivi_stato(sb, righe, log)
    return righe


def controllo(serve_apify_usd: float = 0, serve_anthropic: bool = False,
              serve_openapi_eur: float = 0, serve_exa: bool = False,
              log=print, sb=None) -> list[str]:
    """-> gli avvisi che devono FERMARE il giro (vuota = si parte).
    Se `sb` c'e', la lettura finisce anche in `stato_sistema`."""
    righe, problemi = letture(serve_apify_usd, serve_anthropic,
                              serve_openapi_eur, serve_exa,
                              "controllo_pre_giro", log)
    scrivi_stato(sb, righe, log)
    return problemi


if __name__ == "__main__":
    if "--openapi-saldo" in sys.argv:
        r = dichiara_openapi(float(sys.argv[sys.argv.index("--openapi-saldo") + 1]
                                   .replace(",", ".")))
        print(f"saldo Openapi dichiarato: {r['saldo_eur']:.2f} EUR dal {r['dal']}")
        sys.exit(0)
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
        # dopo il Lazio di gennaio: Toscana e Abruzzo l'8 febbraio, poi marzo
        assert prossimo_giro_apify(datetime.date(2027, 1, 1)) == datetime.date(2027, 2, 8)
        assert prossimo_giro_apify(datetime.date(2027, 2, 10)) == datetime.date(2027, 3, 8)
        # novembre e dicembre 2026 in guardia (regioni appena raccolte a mano)
        assert prossimo_giro_apify(datetime.date(2026, 10, 7)) == datetime.date(2027, 1, 1)
        # registro Openapi: si scala, e senza saldo dichiarato non si sa
        import tempfile
        globals()["REGISTRO_OPENAPI"] = os.path.join(tempfile.mkdtemp(), "o.json")
        assert residuo_openapi() is None
        registra_spesa_openapi(0.10)            # senza registro: niente
        dichiara_openapi(50)
        registra_spesa_openapi(0.10); registra_spesa_openapi(0.10)
        assert residuo_openapi() == 49.8, residuo_openapi()
        globals()["token_openapi_ok"] = lambda log=print: True     # niente rete nel test
        _, problemi = letture(serve_openapi_eur=60, log=lambda *a: None)
        assert problemi and "49.80" in problemi[0], problemi
        assert letture(serve_openapi_eur=8, log=lambda *a: None)[1] == []
        globals()["token_openapi_ok"] = lambda log=print: False
        assert "token Openapi rifiutato" in letture(serve_openapi_eur=8, log=lambda *a: None)[1][0]
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
                           serve_exa=True, fonte="log_mensile")
        for r in righe:
            print(f"{r['servizio']:<9}: {r['messaggio']}")
        try:
            import db
            scrivi_stato(db.client(), righe)
        except Exception as e:  # noqa: BLE001
            print(f"stato_sistema non aggiornata ({type(e).__name__})")
