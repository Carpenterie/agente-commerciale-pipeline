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
# Costo VERO per comune delle 9 province toscane del giro dell'8-9/10, con
# visure (registro del wallet) e bozze: 113,3 EUR / 125 comuni. Le province
# grandi come Firenze (16,60 + visure su 20 comuni): il fattore 1,8 di Roma
# non reggeva. Le ricerche dense allargate (9/10) aggiungono qualcosa: il
# margine del 150% lo copre.
EUR_PER_COMUNE = 0.91
EUR_PER_COMUNE_GRANDI = 1.05
SOGLIA_SFORO = 1.5


def proiezione(provincia: str) -> float:
    per = EUR_PER_COMUNE_GRANDI if provincia in config.PROVINCE_GRANDI else EUR_PER_COMUNE
    return round(len(COMUNI[provincia]) * per, 2)


def ordine(regione: str, salta: set) -> list[str]:
    prov = [p for p in config.REGIONI[regione]["province"] if p not in salta]
    return sorted(prov, key=lambda p: (p in config.PROVINCE_GRANDI, len(COMUNI[p]), p))


def motivo_stop(rc_ciclo: int, rc_bozze: int | None, costo: float, proj: float | None) -> str:
    if rc_ciclo != 0:
        return f"ciclo uscito con codice {rc_ciclo}"
    if rc_bozze not in (0, None):
        return f"bozze uscite con codice {rc_bozze}"
    if proj is not None and costo > proj * SOGLIA_SFORO:
        return f"costo {costo:.2f} EUR oltre il 150% della proiezione ({proj:.2f})"
    return ""


def _gira(argv: list[str], log: pathlib.Path) -> int:
    with log.open("a") as f:
        return subprocess.run([str(QUI / ".venv/bin/python"), "-u", *argv], cwd=QUI,
                              stdout=f, stderr=subprocess.STDOUT).returncode


def _testo(log: pathlib.Path) -> str:
    """Il log, o vuoto se non c'e' ancora (8/10: il log delle bozze letto
    prima delle bozze ha fermato la sequenza dopo Prato)."""
    return log.read_text(errors="replace") if log.exists() else ""


def _ultima(log: pathlib.Path, pattern: str) -> str:
    righe = [r for r in _testo(log).splitlines() if re.search(pattern, r)]
    return re.sub(r"\x1b\[[0-9;]*m", "", righe[-1]).strip() if righe else ""


def riepilogo(sb, provincia: str, avvio: str, log: pathlib.Path, log_bozze: pathlib.Path,
              costo_bozze: float) -> tuple[str, float, str | None]:
    """-> (testo, costo totale EUR, id ciclo)."""
    c = (sb.table("cicli_ricerca").select("*").like("note", f"provincia {provincia}%")
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
    testo_log = _testo(log)
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
             f"bozze {costo_bozze:.2f} — TOTALE {costo:.2f} (proiezione {proiezione(provincia):.2f}; "
             f"per il recupero non vale)\n"
             f"- {territorio}\n"
             f"- anomalie: " + ", ".join(f"{k} {v}" for k, v in anomalie.items() if v) + "\n"
             f"- {_ultima(log, r'ESITO:')} | bozze: {_ultima(log_bozze, r'salvate:')}\n")
    return testo, costo, c["id"]


def ciclo_di(sb, provincia: str, avvio: str) -> str | None:
    c = (sb.table("cicli_ricerca").select("id").like("note", f"provincia {provincia}%")
         .gte("avviato_il", avvio).order("avviato_il", desc=True).limit(1).execute().data)
    return c[0]["id"] if c else None


def rientro(regione: str, gira, cartella_log: pathlib.Path, file_riep: pathlib.Path,
            log=print) -> int:
    """Prima dei cicli di una regione: le sue schede marcate fuori territorio
    quando c'era solo il Lazio tornano dentro (rimetti_dentro.py), quelle col
    sito si rianalizzano (riprendi_analisi.py --ids, visure variante 2) e le
    A/B/C che ne escono prendono la bozza (salva_bozze.py --ids)."""
    flog = cartella_log / f"pipeline-rientro-{regione.lower()}.log"
    ids = QUI / "cache" / "rientro_ids.txt"
    log(f"{datetime.datetime.now():%H:%M} {regione}: rientro delle schede fuori territorio")
    for argv in (["rimetti_dentro.py", "--regione", regione, "--scrivi"],
                 ["riprendi_analisi.py", "--ids", str(ids), "--scrivi"],
                 ["salva_bozze.py", "--scrivi", "--ids", str(ids)]):
        rc = gira(argv, flog)
        if rc != 0:
            testo = f"## Rientro {regione}\n- **SEQUENZA FERMATA: {argv[0]} uscito con codice {rc}**\n\n"
            _scrivi(file_riep, testo, log)
            return rc
    testo_log = _testo(flog)
    righe = [r for r in testo_log.splitlines()
             if re.search(r"schede fuori da rimettere|segnale tolto|classi:|salvate:|TOTALE", r)]
    _scrivi(file_riep, f"## Rientro {regione}\n" + "".join(f"- {r.strip()}\n" for r in righe) + "\n", log)
    return 0


def _scrivi(file_riep: pathlib.Path, testo: str, log=print) -> None:
    try:
        with file_riep.open("a") as f:
            f.write(testo)
    except OSError as e:
        log(f"  riepilogo non scrivibile ({e})")


def sequenza(regione: str, province: list[str], sb, gira, cartella_log: pathlib.Path,
             file_riep: pathlib.Path, log=print, argv_extra: tuple = (),
             tetto_eur: float | None = None, con_proiezione: bool = True) -> int:
    """Le province una dopo l'altra. `gira(argv, file_log) -> codice` lancia
    ciclo e bozze (nel test e' finto). Gli stop sono SOLO quelli previsti
    (motivo_stop, piu' `tetto_eur` complessivo per il recupero): un errore
    nel riepilogo si scrive e si va avanti."""
    speso, massimo = 0.0, 0.0
    for p in province:
        # prudente: la prossima parte solo se ci sta anche costando quanto la
        # provincia piu' cara vista finora (il tetto non si sfora a meta')
        if tetto_eur is not None and speso + massimo > tetto_eur:
            log(f"ESITO: sequenza {regione} FERMATA prima di {p}: tetto di {tetto_eur:.2f} EUR raggiunto ({speso:.2f})")
            _scrivi(file_riep, f"- **SEQUENZA FERMATA prima di {p}: tetto {tetto_eur:.2f} EUR ({speso:.2f})**\n\n", log)
            return 1
        avvio = datetime.datetime.now(datetime.timezone.utc).isoformat()
        flog = cartella_log / f"pipeline-{p.lower()}.log"
        flog_b = cartella_log / f"pipeline-bozze-{p.lower()}.log"
        log(f"{datetime.datetime.now():%H:%M} {p}: ciclo (proiezione {proiezione(p):.2f} EUR)")
        rc = gira(["main.py", "--provincia", p, *argv_extra], flog)
        rc_b, costo_b, costo, stop = None, 0.0, None, ""
        try:
            ciclo_id = ciclo_di(sb, p, avvio)
        except Exception as e:  # noqa: BLE001
            ciclo_id = None
            log(f"  {p}: ciclo non leggibile ({type(e).__name__})")
        if rc == 0 and ciclo_id:
            log(f"{datetime.datetime.now():%H:%M} {p}: bozze del ciclo {ciclo_id[:8]}")
            rc_b = gira(["salva_bozze.py", "--scrivi", "--ciclo", ciclo_id], flog_b)
            t = re.findall(r"TOTALE\s+([\d.]+) EUR", _testo(flog_b))
            costo_b = float(t[-1]) if t else 0.0
        try:
            testo, costo, _ = riepilogo(sb, p, avvio, flog, flog_b, costo_b)
        except Exception as e:  # noqa: BLE001 - il riepilogo non ferma mai la sequenza
            testo = (f"## {p}\n- ERRORE nel riepilogo ({type(e).__name__}: {str(e)[:160]}): "
                     f"vedi {flog} e {flog_b}\n")
        speso += costo or 0.0
        massimo = max(massimo, costo or 0.0)
        stop = motivo_stop(rc, rc_b, costo if costo is not None else 0.0,
                           proiezione(p) if con_proiezione else None)
        if costo is None and not stop:
            testo += "- costo non verificabile: controllo del 150% saltato per questa provincia\n"
        _scrivi(file_riep, testo + (f"- **SEQUENZA FERMATA: {stop}**\n" if stop else "") + "\n", log)
        log(f"{datetime.datetime.now():%H:%M} {p}: fatto"
            + (f", {costo:.2f} EUR" if costo is not None else "") + (f" — STOP: {stop}" if stop else ""))
        if stop:
            log(f"ESITO: sequenza {regione} FERMATA a {p}: {stop}")
            return 1
    log(f"ESITO: sequenza {regione} COMPLETATA ({len(province)} province)")
    return 0


def province_dense(regione: str, salta: set) -> list[str]:
    """Province della regione con ricerche dense nel sourcing salvato."""
    import json
    import sourcing_maps
    out = []
    for p in ordine(regione, salta):
        f = QUI / "cache" / f"sourcing_{p}.json"
        if f.exists() and sourcing_maps.ricerche_dense(json.loads(f.read_text())["schede"], p):
            out.append(p)
    return out


def main() -> int:
    """--regioni A,B[,..] [--rientro] [--salta X,Y] | --regione R --recupero-dense --tetto-eur N"""
    from dotenv import load_dotenv
    load_dotenv(QUI / ".env")
    import db
    arg = lambda k: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else ""
    regioni = [r for r in (arg("--regioni") or arg("--regione")).split(",") if r]
    salta = set(filter(None, arg("--salta").split(",")))
    recupero = "--recupero-dense" in sys.argv
    lucchetto = (QUI / "cache" / ".lucchetto_giro_regione").open("w")
    try:
        fcntl.flock(lucchetto, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("ESITO: un altro giro_regione e' gia' in esecuzione — esco")
        return 1
    log = lambda m: print(m, flush=True)
    sb = db.client()
    for regione in regioni:
        province = province_dense(regione, salta) if recupero else ordine(regione, salta)
        file_riep = QUI / "cache" / f"riepilogo_{regione}{'_recupero' if recupero else ''}.md"
        log(f"{datetime.datetime.now():%Y-%m-%d %H:%M} {regione}"
            f"{' (recupero ricerche dense)' if recupero else ''}: {', '.join(province)}")
        if "--rientro" in sys.argv and rientro(regione, _gira, pathlib.Path("/var/log"), file_riep, log) != 0:
            log(f"ESITO: rientro {regione} FALLITO — sequenza fermata")
            return 1
        rc = sequenza(regione, province, sb, _gira, pathlib.Path("/var/log"), file_riep, log=log,
                      argv_extra=("--recupero-dense",) if recupero else (),
                      tetto_eur=float(arg("--tetto-eur")) if arg("--tetto-eur") else None,
                      con_proiezione=not recupero)
        if rc != 0:
            return rc
    log(f"ESITO: TUTTE le regioni COMPLETATE ({', '.join(regioni)})")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        o = ordine("Toscana", {"PI"})
        assert o[0] == "PO" and o[-1] == "FI" and "PI" not in o and len(o) == 9, o
        assert proiezione("PI") == round(16 * EUR_PER_COMUNE, 2)
        assert proiezione("FI") == round(20 * EUR_PER_COMUNE_GRANDI, 2) > proiezione("AR")
        assert ordine("Campania", set())[-1] == "NA" and ordine("Puglia", set())[-1] == "BA"
        assert motivo_stop(0, 0, 999, None) == ""          # recupero: niente 150%
        assert motivo_stop(0, 0, 10, 10) == "" and motivo_stop(0, 0, 15, 10) == ""
        assert "150%" in motivo_stop(0, 0, 15.1, 10)
        assert "ciclo" in motivo_stop(1, None, 0, 10) and "bozze" in motivo_stop(0, 1, 0, 10)
        # PROVA A VUOTO: due province di fila con ciclo e bozze finti
        import tempfile

        class _Q:
            def __init__(self, dati): self.dati = dati
            def __getattr__(self, _): return lambda *a, **k: self
            def execute(self): return type("R", (), {"data": self.dati})()

        class _SB:
            def __init__(self, rompi=False): self.rompi = rompi
            def table(self, t):
                if t == "aziende" and self.rompi:
                    raise RuntimeError("riepilogo rotto apposta")
                return _Q([{"id": "c-1", "avviato_il": "2026-10-08T10:00", "concluso_il": None,
                            "n_trovate": 10, "n_analizzate": 5, "costo_eur": 3.0,
                            "costo_apify_eur": 1, "costo_exa_eur": 0.5, "costo_anthropic_eur": 1.5,
                            "costo_openapi_eur": 0}] if t == "cicli_ricerca"
                          else [{"classe": "A", "esito_fetch": "OK"}])

        lanciati = []

        def finto(argv, flog):
            lanciati.append(argv[0])
            flog.write_text("territorio: 1 valutate\nESITO: ciclo COMPLETATO — prova\n"
                            if argv[0] == "main.py" else "salvate: 1\nTOTALE 0.10 EUR\n")
            return 0

        for rompi in (False, True):
            d = pathlib.Path(tempfile.mkdtemp())
            lanciati.clear()
            rc = sequenza("Toscana", ["PO", "MS"], _SB(rompi), finto, d, d / "riep.md", log=lambda m: None)
            riep = (d / "riep.md").read_text()
            assert rc == 0 and lanciati == ["main.py", "salva_bozze.py"] * 2, (rompi, lanciati)
            assert riep.count("## PO") == 1 and riep.count("## MS") == 1, riep
            assert ("ERRORE nel riepilogo" in riep) == rompi, riep
        # il caso dell'8/10: log delle bozze ancora assente -> vuoto, nessun errore
        assert _ultima(pathlib.Path("/non/esiste.log"), "x") == ""
        # gli stop veri restano: ciclo in errore -> la seconda provincia non parte
        d = pathlib.Path(tempfile.mkdtemp())
        lanciati.clear()
        rc = sequenza("Toscana", ["PO", "MS"], _SB(), lambda a, f: (lanciati.append(a[0]), 1)[1],
                      d, d / "riep.md", log=lambda m: None)
        assert rc == 1 and lanciati == ["main.py"] and "SEQUENZA FERMATA" in (d / "riep.md").read_text()
        # recupero: argomenti in piu' a main e tetto complessivo in euro
        d = pathlib.Path(tempfile.mkdtemp())
        argv_visti = []
        rc = sequenza("Toscana", ["PO", "MS", "LI"], _SB(), lambda a, f: (argv_visti.append(a), finto(a, f))[1],
                      d, d / "riep.md", log=lambda m: None, argv_extra=("--recupero-dense",),
                      tetto_eur=5.0, con_proiezione=False)
        assert rc == 1 and argv_visti[0][-1] == "--recupero-dense"
        assert sum(a[0] == "main.py" for a in argv_visti) == 1, argv_visti   # 3,10 + 3,10 > 5: la seconda no
        assert "tetto" in (d / "riep.md").read_text()
        # rientro: i tre passi in ordine, e uno che fallisce ferma tutto
        d = pathlib.Path(tempfile.mkdtemp())
        passi = []
        assert rientro("Abruzzo", lambda a, f: (passi.append(a[0]), f.write_text("classi: x\n"), 0)[2],
                       d, d / "riep.md", log=lambda m: None) == 0
        assert passi == ["rimetti_dentro.py", "riprendi_analisi.py", "salva_bozze.py"], passi
        assert rientro("Marche", lambda a, f: 2 if a[0] == "riprendi_analisi.py" else 0,
                       d, d / "riep.md", log=lambda m: None) == 2
        assert "Rientro Marche" in (d / "riep.md").read_text()
        print("ok", o)
        sys.exit(0)
    sys.exit(main())
