"""Le chiavi del .env funzionano davvero? (diagnostica, non fa parte del ciclo)

Una chiamata minima per servizio, la piu' economica che dimostri che la
chiave e' valida: nessuna run Apify, nessun sourcing, nessuna scrittura su
Supabase. Costa qualche centesimo di Anthropic e $0,007 di Exa.

Serve quando il cliente cambia una chiave: il cron gira di notte e senza
questo lo scoprirebbe il mattino dopo, a ciclo fallito. Va lanciato anche
sul server, non solo in locale — i due .env sono file distinti e possono
divergere.

    python verifica_chiavi.py
    ssh utente@server 'cd /opt/agente-commerciale-pipeline && .venv/bin/python verifica_chiavi.py'
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

import config      # importa per primo: imposta SSL_CERT_FILE
import classify
import sourcing_maps

CACHE_CAMPIONE = pathlib.Path(__file__).resolve().parent / "tests/campione_26/cache"


def impronta(nome: str) -> str:
    """Lunghezza e prefisso, mai il valore: l'output puo' finire in un log."""
    v = os.environ.get(nome, "").strip()
    if not v:
        return f"  {nome}: ASSENTE dal .env"
    return f"  {nome}: presente, {len(v)} caratteri, inizia per {v[:8]}..."


def prova_anthropic(log) -> bool:
    """Una classificazione vera su una pagina gia' in cache: verifica la
    chiave E che il modello risponda ancora nel formato atteso."""
    try:
        import anthropic

        pagina = json.loads(sorted(CACHE_CAMPIONE.glob("*.json"))[0]
                            .read_text(encoding="utf-8"))
        d = classify.classifica(anthropic.Anthropic(), pagina["markdown"][:6000])
        log(f"  OK — {d['classificazione']} / confidenza {d['confidenza']}"
            f" / categoria {d['categoria']}")
        log(f"  {d['token_input']} token in + {d['token_output']} out"
            f" = {d['costo_analisi_eur']:.4f} EUR")
        return True
    except Exception as e:  # noqa: BLE001 - qualunque errore vale come "non risponde"
        log(f"  FALLITA — {type(e).__name__}: {str(e)[:300]}")
        return False


def prova_exa(log) -> bool:
    """Una query da 1 risultato senza `contents`: la ricerca piu' economica."""
    try:
        req = urllib.request.Request(
            "https://api.exa.ai/search",
            data=json.dumps({"query": "fabbro Roma", "type": "auto",
                             "numResults": 1}).encode(),
            headers={"content-type": "application/json",
                     "x-api-key": os.environ.get("EXA_API_KEY", "")})
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r).get("results", [])
        log(f"  OK — {len(res)} risultato ({config.PREZZO_EXA_RICERCA_USD} USD)")
        return True
    except urllib.error.HTTPError as e:
        log(f"  FALLITA — HTTP {e.code}: {e.read().decode()[:300]}")
        return False
    except Exception as e:  # noqa: BLE001
        log(f"  FALLITA — {type(e).__name__}: {str(e)[:300]}")
        return False


def prova_apify(log) -> tuple[bool, str]:
    """`users/me` non lancia nessuna run e non e' fatturata. Dice anche il
    piano: sul FREE il ciclo delle cinque province non arriva in fondo."""
    try:
        req = urllib.request.Request(
            "https://api.apify.com/v2/users/me",
            headers={"Authorization": f"Bearer {os.environ.get('APIFY_TOKEN', '')}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            u = json.load(r).get("data", {})
        piano = (u.get("plan") or {}).get("id", "?")
        log(f"  OK — account '{u.get('username')}', piano {piano}")
        credito = sourcing_maps.credito(log=log)
        if credito:
            usato, tetto = credito
            log(f"  credito: {usato:.2f} / {tetto:.2f} USD usati"
                f" — restano {tetto - usato:.2f}")
        return True, piano
    except urllib.error.HTTPError as e:
        log(f"  FALLITA — HTTP {e.code}: {e.read().decode()[:300]}")
        return False, "?"
    except Exception as e:  # noqa: BLE001
        log(f"  FALLITA — {type(e).__name__}: {str(e)[:300]}")
        return False, "?"


def main(log=print) -> int:
    from dotenv import load_dotenv

    load_dotenv()

    log("=== chiavi lette dal .env")
    for n in ("ANTHROPIC_API_KEY", "EXA_API_KEY", "APIFY_TOKEN", "OPENAPI_TOKEN"):
        log(impronta(n))

    log("\n=== Anthropic (classificazione su pagina in cache)")
    esiti = {"anthropic": prova_anthropic(log)}
    log("\n=== Exa (una query, 1 risultato)")
    esiti["exa"] = prova_exa(log)
    log("\n=== Apify (nessuna run lanciata)")
    esiti["apify"], piano = prova_apify(log)

    log("\n=== ESITO")
    for k, ok in esiti.items():
        log(f"  {k:10} {'RISPONDE' if ok else 'NON RISPONDE'}")
    if esiti["apify"] and piano.upper() == "FREE":
        log("  ATTENZIONE: piano Apify FREE, il ciclo completo non arriva in fondo")
    # exit code: lo si puo' incatenare al cron senza leggere l'output
    return 0 if all(esiti.values()) else 1


if __name__ == "__main__":
    if "--test" in sys.argv:
        # self-check senza rete: le impronte non devono mai mostrare la chiave
        os.environ["_FINTA"] = "sk-ant-supersegretissima-1234567890"
        riga = impronta("_FINTA")
        assert "supersegretissima" not in riga and "1234567890" not in riga, riga
        assert f"{len(os.environ["_FINTA"])} caratteri" in riga, riga
        assert "ASSENTE" in impronta("_NON_ESISTE_")
        assert CACHE_CAMPIONE.is_dir(), "manca la cache del campione"
        print("ok")
    else:
        sys.exit(main())
