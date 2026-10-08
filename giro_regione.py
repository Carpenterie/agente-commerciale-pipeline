"""Le province di una regione una dopo l'altra, sul server, senza bisogno
del Mac: ciclo (visure comprese, variante del cliente), poi le bozze del
solo ciclo appena fatto. Nato l'8/10 per la Toscana dopo il pilota di Pisa.

    nohup .venv/bin/python -u giro_regione.py --regione Toscana --salta PI \\
        > /var/log/pipeline-toscana.log 2>&1 < /dev/null &

Ordine: dalla provincia con meno comuni alla piu' grande, le grandi
(config.PROVINCE_GRANDI) per ultime. Log per provincia in
/var/log/pipeline-<pr>.log (ciclo) e pipeline-bozze-<pr>.log; dopo ogni
provincia un riepilogo in cache/riepilogo_<Regione>.md.

LA SEQUENZA SI FERMA da sola, senza passare alla provincia successiva, se:
- il ciclo o le bozze escono con errore (codice diverso da 0: comprende il
  controllo del credito e del token, che main fa prima di spendere);
- il costo della provincia supera di oltre il 50% la proiezione, calcolata
  sul costo reale per comune del pilota di Pisa.
"""

from __future__ import annotations

import datetime
import fcntl
import pathlib
import re
import subprocess
import sys

import config
from data.comuni import COMUNI

QUI = pathlib.Path(__file__).parent
# Pilota di Pisa (7/10), 16 comuni, con le visure della variante 2
PISA = {"comuni": 16, "apify": 2.4179, "exa": 1.0368, "anthropic": 16.3068, "openapi": 7.20}
FATTORE_GRANDI = 1.8      # Roma costava per comune ~1,8 volte le altre laziali
SOGLIA_SFORO = 1.5


def proiezione(provincia: str) -> float:
    n, g = len(COMUNI[provincia]), (FATTORE_GRANDI if provincia in config.PROVINCE_GRANDI else 1)
    per = lambda k: PISA[k] / PISA["comuni"]
    return round(n * (per("apify") + (per("anthropic") + per("openapi")) * g) + PISA["exa"], 2)


def ordine(regione: str, salta: set) -> list[str]:
    prov = [p for p in config.REGIONI[regione]["province"] if p not in salta]
    return sorted(prov, key=lambda p: (p in config.PROVINCE_GRANDI, len(COMUNI[p]), p))


def motivo_stop(rc_ciclo: int, rc_bozze: int | None, costo: float, proj: float) -> str:
    if rc_ciclo != 0:
        return f"ciclo uscito con codice {rc_ciclo}"
    if rc_bozze not in (0, None):
        return f"bozze uscite con codice {rc_bozze}"
    if costo > proj * SOGLIA_SFORO:
        return f"costo {costo:.2f} EUR oltre il 150% della proiezione ({proj:.2f})"
    return ""


def _gira(argv: list[str], log: pathlib.Path) -> int:
    with log.open("a") as f:
        return subprocess.run([str(QUI / ".venv/bin/python"), "-u", *argv], cwd=QUI,
                              stdout=f, stderr=subprocess.STDOUT).returncode


def _ultima(log: pathlib.Path, pattern: str) -> str:
    righe = [r for r in log.read_text(errors="replace").splitlines() if re.search(pattern, r)]
    return re.sub(r"\x1b\[[0-9;]*m", "", righe[-1]).strip() if righe else ""


def riepilogo(sb, provincia: str, avvio: str, log: pathlib.Path, log_bozze: pathlib.Path,
              costo_bozze: float) -> tuple[str, float, str | None]:
    """-> (testo, costo totale EUR, id ciclo)."""
    c = (sb.table("cicli_ricerca").select("*").eq("note", f"provincia {provincia}")
         .gte("avviato_il", avvio).order("avviato_il", desc=True).limit(1).execute().data)
    if not c:
        return f"## {provincia}\nnessun ciclo registrato (vedi {log})\n", 0.0, None
    c = c[0]
    righe, i = [], 0
    while True:
        b = (sb.table("aziende").select("classe,esito_fetch").eq("ciclo_id", c["id"])
             .range(i, i + 999).execute().data)
        righe += b
        if len(b) < 1000:
            break
        i += 1000
    classi = {k: sum(r["classe"] == k for r in righe) for k in ("A", "B", "C")}
    testo_log = log.read_text(errors="replace")
    anomalie = {
        "siti non scaricabili": sum(r["esito_fetch"] == "FETCH_FALLITO" for r in righe),
        "visure fermate per credito": testo_log.count("STOP visure"),
        "token Openapi rifiutato": testo_log.count("Wrong Token"),
        "doppioni Exa non scritti": int((re.findall(r"DOPPIONI EXA[^:]*: (\d+)", testo_log) or ["0"])[-1]),
        "aziende saltate per errore": testo_log.count("SALTATA "),
    }
    territorio = _ultima(log, r"^territorio: ")
    costo = round((c["costo_eur"] or 0) + costo_bozze, 2)
    testo = (f"## {provincia} — {config.PROVINCE[provincia]} ({len(COMUNI[provincia])} comuni)\n"
             f"- ciclo {c['id']}, {c['avviato_il'][:16]} -> {(c['concluso_il'] or '')[:16]}\n"
             f"- trovate {c['n_trovate']}, analizzate {c['n_analizzate']}, scritte {len(righe)}; "
             f"A {classi['A']}, B {classi['B']}, C {classi['C']}\n"
             f"- costi EUR: Apify {c['costo_apify_eur'] or 0:.2f}, Exa {c['costo_exa_eur'] or 0:.2f}, "
             f"modello {c['costo_anthropic_eur'] or 0:.2f}, Openapi {c['costo_openapi_eur'] or 0:.2f}, "
             f"bozze {costo_bozze:.2f} — TOTALE {costo:.2f} (proiezione {proiezione(provincia):.2f})\n"
             f"- {territorio}\n"
             f"- anomalie: " + ", ".join(f"{k} {v}" for k, v in anomalie.items() if v) + "\n"
             f"- {_ultima(log, r'ESITO:')} | bozze: {_ultima(log_bozze, r'salvate:')}\n")
    return testo, costo, c["id"]


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(QUI / ".env")
    import db
    regione = sys.argv[sys.argv.index("--regione") + 1]
    salta = set(sys.argv[sys.argv.index("--salta") + 1].split(",")) if "--salta" in sys.argv else set()
    lucchetto = (QUI / "cache" / ".lucchetto_giro_regione").open("w")
    try:
        fcntl.flock(lucchetto, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("ESITO: un altro giro_regione e' gia' in esecuzione — esco")
        return 1
    file_riep = QUI / "cache" / f"riepilogo_{regione}.md"
    sequenza = ordine(regione, salta)
    print(f"{datetime.datetime.now():%Y-%m-%d %H:%M} {regione}: {', '.join(sequenza)}", flush=True)
    sb = db.client()
    for p in sequenza:
        avvio = datetime.datetime.now(datetime.timezone.utc).isoformat()
        log = pathlib.Path(f"/var/log/pipeline-{p.lower()}.log")
        log_bozze = pathlib.Path(f"/var/log/pipeline-bozze-{p.lower()}.log")
        print(f"{datetime.datetime.now():%H:%M} {p}: ciclo (proiezione {proiezione(p):.2f} EUR)", flush=True)
        rc = _gira(["main.py", "--provincia", p], log)
        _, _, ciclo_id = riepilogo(sb, p, avvio, log, log_bozze, 0.0)
        rc_b, costo_b = None, 0.0
        if rc == 0 and ciclo_id:
            print(f"{datetime.datetime.now():%H:%M} {p}: bozze del ciclo {ciclo_id[:8]}", flush=True)
            rc_b = _gira(["salva_bozze.py", "--scrivi", "--ciclo", ciclo_id], log_bozze)
            t = re.findall(r"TOTALE\s+([\d.]+) EUR", log_bozze.read_text(errors="replace"))
            costo_b = float(t[-1]) if t else 0.0
        testo, costo, _ = riepilogo(sb, p, avvio, log, log_bozze, costo_b)
        stop = motivo_stop(rc, rc_b, costo, proiezione(p))
        with file_riep.open("a") as f:
            f.write(testo + (f"- **SEQUENZA FERMATA: {stop}**\n" if stop else "") + "\n")
        print(f"{datetime.datetime.now():%H:%M} {p}: fatto, {costo:.2f} EUR" +
              (f" — STOP: {stop}" if stop else ""), flush=True)
        if stop:
            print(f"ESITO: sequenza {regione} FERMATA a {p}: {stop}")
            return 1
    print(f"ESITO: sequenza {regione} COMPLETATA ({len(sequenza)} province)")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        o = ordine("Toscana", {"PI"})
        assert o[0] == "PO" and o[-1] == "FI" and "PI" not in o and len(o) == 9, o
        assert abs(proiezione("PI") - (2.4179 + 1.0368 + 16.3068 + 7.20)) < 0.02
        assert proiezione("FI") > proiezione("AR")
        assert motivo_stop(0, 0, 10, 10) == "" and motivo_stop(0, 0, 15, 10) == ""
        assert "150%" in motivo_stop(0, 0, 15.1, 10)
        assert "ciclo" in motivo_stop(1, None, 0, 10) and "bozze" in motivo_stop(0, 1, 0, 10)
        print("ok", o)
        sys.exit(0)
    sys.exit(main())
