"""Rimette nel territorio le schede marcate fuori quando era attivo il solo
Lazio (o per il difetto della provincia scritta per esteso, corretto il
7/10), prima del giro della loro regione: il controllo doppioni le
salterebbe come "gia' in archivio" e resterebbero fuori per sempre.

    python rimetti_dentro.py --regione Toscana [--anche-per-esteso]   # misura
    python rimetti_dentro.py --regione Toscana --anche-per-esteso --scrivi

Decisione del committente (7/10), per gruppi:
- gia' analizzate (A/B/C): si toglie il segnale fuori, classe e bozza restano;
- senza sito: si toglie il segnale, restano indeterminato;
- con sito, mai analizzate: si toglie il segnale e si rianalizzano con le
  regole del ciclo (riprendi_analisi.py --ids, visura compresa).
Le schede anche fuori settore, doppione o chiuse non si toccano: restano
fuori dalle liste comunque. Stato, recapiti del commerciale e segnali messi
a mano non si toccano mai. Al posto del segnale tolto resta traccia:
{"tipo": "territorio", "esito": "dentro", "segnale": "rimessa dentro ..."}.
"""

from __future__ import annotations

import collections
import datetime
import re
import sys

import config
from data import comuni

FERMANO = ("fuori_settore", "doppione", "chiusa_definitivamente")
RE_ESTESA = re.compile(r"^provincia (.+) da Google Maps$")


def fuori(r: dict) -> bool:
    return (any((s.get("tipo") == "territorio" and s.get("esito") == "fuori")
                or s.get("tipo") == "fuori_territorio_sede_dichiarata"
                for s in r.get("segnali") or [])
            or (r.get("motivazione") or "").startswith(MOTIVAZIONE_FUORI))


MOTIVAZIONE_FUORI = "fuori territorio"


def per_esteso(r: dict) -> bool:
    """Fuori per la provincia di Maps, che oggi e' attiva: il difetto del
    7/10 (scritta per esteso) e le sigle delle regioni aperte il 7/10 —
    le 13 schede approvate dal committente."""
    for s in r.get("segnali") or []:
        m = RE_ESTESA.match(s.get("segnale") or "")
        if s.get("tipo") == "territorio" and s.get("esito") == "fuori" and m \
                and (config.sigla_provincia(m.group(1)) or "").upper() in config.SIGLE_ATTIVE:
            return True
    return False


def provincia(r: dict) -> str:
    return ((r.get("provincia") or "").strip().upper()
            or (comuni.provincia_di(r.get("comune")) or ""))


def regione(r: dict) -> str:
    """Dalla provincia o dal comune; se mancano entrambi, dal CAP scritto
    nel segnale di fuori territorio (4 schede toscane al 7/10)."""
    p = provincia(r)
    if p:
        return config.REGIONE_DI.get(p, "")
    testo = " ".join(s.get("segnale") or "" for s in r.get("segnali") or [])
    regioni = {reg for cap in re.findall(r"cap (\d{5})", testo)
               for reg, d in config.REGIONI.items() if cap[:2] in d["cap"]}
    return regioni.pop() if len(regioni) == 1 else ""


def gruppo(r: dict) -> str:
    if any(s.get("tipo") in FERMANO for s in r.get("segnali") or []):
        return "resta fuori lista (fuori settore, doppione o chiusa)"
    if r.get("esito_analisi"):
        return "gia' analizzata: solo segnale"
    if not (r.get("sito") or "").strip() or r.get("esito_fetch") == "nessun_sito":
        return "senza sito: solo segnale"
    return "da rianalizzare"


def scelte(righe: list[dict], regione: str, anche_per_esteso: bool) -> list[dict]:
    return [r for r in righe if fuori(r) and (globals()["regione"](r) == regione
                                              or (anche_per_esteso and per_esteso(r)))]


def senza_fuori(r: dict, oggi: str) -> dict:
    """I segnali senza quelli di fuori territorio, piu' la traccia."""
    tenuti = [s for s in r.get("segnali") or []
              if not ((s.get("tipo") == "territorio" and s.get("esito") == "fuori")
                      or s.get("tipo") == "fuori_territorio_sede_dichiarata")]
    tolti = [s.get("segnale") for s in r.get("segnali") or [] if s not in tenuti]
    tenuti.append({"tipo": "territorio", "esito": "dentro",
                   "segnale": f"rimessa dentro il {oggi}: regione attiva "
                              f"(prima: {'; '.join(t for t in tolti if t)[:160]})"})
    agg = {"segnali": tenuti}
    if (r.get("motivazione") or "").startswith(MOTIVAZIONE_FUORI) and not r.get("esito_analisi"):
        import db
        agg["motivazione"] = db.MOTIVAZIONE_NO_SITO if gruppo(r).startswith("senza sito") else None
    return agg


def main() -> int:
    import db
    regione = sys.argv[sys.argv.index("--regione") + 1]
    scrivi, anche = "--scrivi" in sys.argv, "--anche-per-esteso" in sys.argv
    sb = db.client()
    righe, i = [], 0
    while True:
        b = (sb.table("aziende").select("id,ragione_sociale,comune,provincia,classe,stato,sito,"
                                        "esito_fetch,esito_analisi,motivazione,segnali,"
                                        "bozza_corpo,bozza_generata")
             .order("id").range(i, i + 999).execute().data)
        righe += b
        if len(b) < 1000:
            break
        i += 1000
    sel = scelte(righe, regione, anche)
    per_gruppo = collections.Counter(gruppo(r) for r in sel)
    print(f"{regione}{' + provincia per esteso' if anche else ''}: {len(sel)} schede fuori da rimettere dentro")
    print("  con la provincia vuota (trovate da comune o CAP):",
          sum(not (r.get("provincia") or "").strip() for r in sel),
          "| per il difetto della provincia per esteso:", sum(per_esteso(r) for r in sel))
    for g, n in per_gruppo.most_common():
        print(f"  {g:<55} {n}")
    print("  per provincia:", dict(collections.Counter(provincia(r) or "?" for r in sel)))
    print("  classe:", dict(collections.Counter(r.get("classe") for r in sel)))
    rian = [r for r in sel if gruppo(r) == "da rianalizzare"]
    print(f"  rianalisi: ~{len(rian) * 0.06:.2f} EUR di modello + visure sulle A/B/C che ne escono")
    if not scrivi:
        print("\n(misura: niente scritto. Rilancia con --scrivi)")
        return 0
    oggi = datetime.date.today().isoformat()
    n = 0
    for r in sel:
        if gruppo(r).startswith("resta fuori"):
            continue
        sb.table("aziende").update(senza_fuori(r, oggi)).eq("id", r["id"]).execute()
        n += 1
    with open("cache/rientro_ids.txt", "w") as f:
        f.write("\n".join(r["id"] for r in rian) + "\n")
    print(f"segnale tolto su {n} schede; {len(rian)} id in cache/rientro_ids.txt per "
          f"'python riprendi_analisi.py --ids cache/rientro_ids.txt --scrivi'")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        f = {"tipo": "territorio", "esito": "fuori", "segnale": "provincia PROVINCIA DI PISA da Google Maps"}
        r = {"provincia": "PI", "segnali": [f, {"tipo": "ex_cliente"}], "esito_analisi": None,
             "sito": "", "esito_fetch": "nessun_sito", "motivazione": "fuori territorio (x)"}
        assert fuori(r) and per_esteso(r) and gruppo(r).startswith("senza sito")
        agg = senza_fuori(r, "2026-10-07")
        assert [s["tipo"] for s in agg["segnali"]] == ["ex_cliente", "territorio"]
        assert agg["segnali"][-1]["esito"] == "dentro" and "PROVINCIA DI PISA" in agg["segnali"][-1]["segnale"]
        assert agg["motivazione"].startswith("nessuna fonte web")
        assert not per_esteso({"segnali": [{"tipo": "territorio", "esito": "fuori",
                                            "segnale": "provincia BG da Google Maps"}]})
        assert scelte([r, {**r, "provincia": "MI", "segnali": [{"tipo": "territorio", "esito": "fuori",
                                                               "segnale": "cap 20121"}]}],
                      "Toscana", False) == [r]
        assert gruppo({**r, "segnali": [{"tipo": "doppione"}]}).startswith("resta fuori")
        assert regione({"segnali": [{"tipo": "territorio", "esito": "fuori",
                                     "segnale": "cap 56121"}]}) == "Toscana"
        assert regione({"segnali": [{"segnale": "cap 20251; cap 81020"}]}) == "Campania"
        assert per_esteso({"segnali": [{"tipo": "territorio", "esito": "fuori",
                                        "segnale": "provincia PE da Google Maps"}]})
        print("ok")
        sys.exit(0)
    from dotenv import load_dotenv
    load_dotenv()
    sys.exit(main())
