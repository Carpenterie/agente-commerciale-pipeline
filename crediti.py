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


def controllo(serve_apify_usd: float = 0, serve_anthropic: bool = False,
              serve_openapi_eur: float = 0, log=print) -> list[str]:
    """-> gli avvisi che devono FERMARE il giro (vuota = si parte).
    Ogni avviso dice quale credito ricaricare e di quanto."""
    problemi = []
    if serve_apify_usd > 0:
        r = saldo_apify(log)
        if r is not None and r < serve_apify_usd:
            problemi.append(f"credito Apify insufficiente: restano {r:.2f} USD, "
                            f"il giro ne stima {serve_apify_usd:.2f} — attendere "
                            f"il rinnovo del periodo o alzare il tetto")
    if serve_anthropic:
        ok = anthropic_ok(log)
        if ok is False:
            problemi.append("credito Anthropic ESAURITO: ricaricare su "
                            "console.anthropic.com prima di rilanciare")
    if serve_openapi_eur > 0:
        saldo, desc = saldo_openapi(log)
        if saldo is not None and saldo < serve_openapi_eur:
            problemi.append(f"wallet Openapi insufficiente: {saldo:.2f} EUR, "
                            f"il giro ne stima {serve_openapi_eur:.2f} — "
                            f"ricaricare almeno {serve_openapi_eur - saldo:.0f} EUR")
        elif saldo is None and "presente" not in desc and "non configurato" not in desc:
            log(f"saldo Openapi {desc}: non blocco, ma il salvavita in corsa vigila")
    return problemi


if __name__ == "__main__":
    if "--test" in sys.argv:
        m = RE_SALDO_402.search('{"message":"Billing error message: Insufficient '
                                'Credit in Wallet: 0.1 > 0.057 code 810"}')
        assert m and m.group(1) == "0.057"
        assert RE_SALDO_402.search("altro errore") is None
        print("ok")
    else:
        from dotenv import load_dotenv
        load_dotenv()
        import datetime
        print(f"=== SALDI {datetime.date.today().isoformat()} ===")
        r = saldo_apify()
        print(f"Apify   : {'?' if r is None else f'{r:.2f} USD residui nel periodo'}")
        ok = anthropic_ok()
        print(f"Anthropic: {'credito presente' if ok else 'ESAURITO' if ok is False else 'non verificabile'}")
        saldo, desc = saldo_openapi()
        print(f"Openapi : {desc}")
