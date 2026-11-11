"""Un solo lavoro alla volta sull'archivio (5/11, preventivo PREV-2026-06).

Stesso file di giro_regione.py e indirizzi_maps.py (cache/.lucchetto_giro_regione):
chi lo tiene esclude gli altri. In piu' si controlla che non giri un'altra
pipeline senza lucchetto.
flock si rilascia da solo alla morte del processo: niente lucchetti stantii.

Dall'11/11 lo prende anche main.py quando parte da solo (i cicli del cron).
Chi lo lancia tenendo gia' il lucchetto (giro_regione.py) lo dichiara al figlio
con la variabile d'ambiente LUCCHETTO_ARCHIVIO=tenuto: il figlio non lo riprende,
altrimenti lo troverebbe occupato dal padre e non partirebbe mai.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import os
import pathlib
import subprocess

FILE = pathlib.Path(__file__).resolve().parent / "cache" / ".lucchetto_giro_regione"
# Job che non scrivono sull'archivio (lucchetto proprio, o sola lettura): non occupano.
ESENTI = ("testi_campagna.py", "sentinella.py")
VARIABILE, TENUTO = "LUCCHETTO_ARCHIVIO", "tenuto"


def tenuto_dal_padre() -> bool:
    """True se chi ha lanciato questo processo tiene gia' il lucchetto."""
    return os.environ.get(VARIABILE) == TENUTO


def ambiente_figlio() -> dict:
    """L'ambiente per un sottoprocesso lanciato da chi tiene il lucchetto."""
    return {**os.environ, VARIABILE: TENUTO}


def altri_lavori(mio: str) -> list[str]:
    """Altri processi Python della pipeline (escluso questo script)."""
    try:
        righe = subprocess.run(["pgrep", "-af", r"\.venv/bin/python"], capture_output=True,
                               text=True).stdout.splitlines()
    except OSError:
        return []
    pid = str(os.getpid())
    return [r for r in righe if r.split(" ", 1)[0] != pid and mio not in r
            and not any(e in r for e in ESENTI)]


def prendi(mio: str, log=print):
    """-> l'handle del lucchetto (va tenuto vivo fino alla fine), o None se
    l'archivio e' occupato: in quel caso non si parte."""
    FILE.parent.mkdir(parents=True, exist_ok=True)
    h = FILE.open("w")
    try:
        fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("ESITO: lucchetto dei lavori sull'archivio occupato — non parto")
        return None
    altri = altri_lavori(mio)
    if altri:
        fcntl.flock(h, fcntl.LOCK_UN)
        log(f"ESITO: un altro lavoro della pipeline e' in corso ({altri[0][:100]}) — non parto")
        return None
    return h


def scaduto(entro: str | None) -> bool:
    """True se e' passata l'ora limite (ISO, es. 2026-11-07T07:30+00:00): il
    giro si ferma pulito e riprende dopo, per non toccare un lavoro programmato."""
    if not entro:
        return False
    limite = dt.datetime.fromisoformat(entro)
    if limite.tzinfo is None:
        limite = limite.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc) >= limite


if __name__ == "__main__":
    assert not scaduto(None) and not scaduto("2999-01-01T00:00+00:00")
    assert scaduto("2000-01-01T00:00") and scaduto("2000-01-01T00:00+00:00")
    assert "indirizzi_maps.py" not in "".join(altri_lavori("indirizzi_maps.py"))
    # il figlio di chi tiene il lucchetto lo sa dall'ambiente, e solo da li'
    assert ambiente_figlio()[VARIABILE] == TENUTO and "PATH" in ambiente_figlio()
    _prima = os.environ.pop(VARIABILE, None)
    assert not tenuto_dal_padre()
    os.environ[VARIABILE] = TENUTO
    assert tenuto_dal_padre()
    os.environ[VARIABILE] = "altro"
    assert not tenuto_dal_padre()
    os.environ.pop(VARIABILE)
    if _prima is not None:
        os.environ[VARIABILE] = _prima
    # il lucchetto vero: finche' un handle lo tiene, un secondo non lo ottiene
    import tempfile
    with tempfile.TemporaryDirectory() as _t:
        _f = pathlib.Path(_t) / "l"
        _a, _b = _f.open("w"), _f.open("w")
        fcntl.flock(_a, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fcntl.flock(_b, fcntl.LOCK_EX | fcntl.LOCK_NB)
            raise AssertionError("due lucchetti insieme")
        except OSError:
            pass
        _a.close()
        fcntl.flock(_b, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _b.close()
    for _e in ESENTI:
        assert (pathlib.Path(__file__).resolve().parent / _e).exists(), f"{_e}: script esente che non esiste"
    print("ok")
