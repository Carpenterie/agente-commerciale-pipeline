"""Un solo lavoro alla volta sull'archivio (5/11, preventivo PREV-2026-06).

Stesso file di giro_regione.py e indirizzi_maps.py (cache/.lucchetto_giro_regione):
chi lo tiene esclude gli altri. In piu' si controlla che non giri un'altra
pipeline senza lucchetto (i cicli del cron lanciano main.py direttamente).
flock si rilascia da solo alla morte del processo: niente lucchetti stantii.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import os
import pathlib
import subprocess

FILE = pathlib.Path(__file__).resolve().parent / "cache" / ".lucchetto_giro_regione"


def altri_lavori(mio: str) -> list[str]:
    """Altri processi Python della pipeline (escluso questo script)."""
    try:
        righe = subprocess.run(["pgrep", "-af", r"\.venv/bin/python"], capture_output=True,
                               text=True).stdout.splitlines()
    except OSError:
        return []
    pid = str(os.getpid())
    return [r for r in righe if r.split(" ", 1)[0] != pid and mio not in r]


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
    print("ok")
