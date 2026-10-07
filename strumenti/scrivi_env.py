"""Scrive UNA chiave nel .env leggendo il valore da stdin, senza stamparlo.

    printf '%s' "$VALORE" | python3 strumenti/scrivi_env.py OPENAPI_TOKEN .env

Il valore non passa mai da argv (che si vede in `ps`) ne' dall'output:
riscrive la riga della chiave (o la aggiunge), file temporaneo + rename,
permessi 600. Stampa solo la chiave e l'esito.
"""

import os
import re
import sys


def scrivi(testo: str, chiave: str, valore: str) -> str:
    riga = f"{chiave}={valore}"
    if re.search(rf"(?m)^{re.escape(chiave)}=", testo):
        return re.sub(rf"(?m)^{re.escape(chiave)}=.*$", lambda _: riga, testo)
    return testo.rstrip("\n") + "\n" + riga + "\n"


if __name__ == "__main__":
    if "--test" in sys.argv:
        assert scrivi("A=1\nOPENAPI_TOKEN=vecchio\nB=2\n", "OPENAPI_TOKEN", "x\\1") \
            == "A=1\nOPENAPI_TOKEN=x\\1\nB=2\n"
        assert scrivi("A=1", "OPENAPI_TOKEN", "n") == "A=1\nOPENAPI_TOKEN=n\n"
        print("ok")
        sys.exit(0)
    chiave, percorso = sys.argv[1], sys.argv[2]
    valore = sys.stdin.read().strip()
    if not valore or "\n" in valore:
        sys.exit(f"{chiave}: valore vuoto o su piu' righe, .env NON toccato")
    testo = open(percorso).read() if os.path.exists(percorso) else ""
    tmp = percorso + ".tmp"
    with open(tmp, "w") as f:
        f.write(scrivi(testo, chiave, valore))
    os.chmod(tmp, 0o600)
    os.replace(tmp, percorso)
    print(f"{chiave} aggiornata in {os.path.abspath(percorso)}")
