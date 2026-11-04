"""Sede OPERATIVA da Google Maps nelle colonne indirizzo, cap, indirizzo_fonte (4/11).

Due passi, stesse regole di abbinamento:

    python indirizzi_maps.py --cache [--scrivi]       # gratis, dalla cache/sourcing_*.json
    python indirizzi_maps.py --ricerca [--scrivi] [--tetto 3]
        # Apify: una ricerca "ragione sociale comune" per ogni scheda A/B/C
        # ancora senza indirizzo. Lancio unico programmato il 7/11 (rinnovo).

Regole (decisione del committente, 4/11):
- si scrive SOLO indirizzo, cap e indirizzo_fonte='maps'. comune, provincia
  e regione non si toccano (servono a territorio e filtri); niente si cancella;
- una scheda Maps vale se coincide il dominio o il telefono, oppure se il
  nome e' identico E coincide anche il comune. Se gli abbinamenti danno due
  indirizzi diversi non si scrive niente (si sceglierebbe a caso);
- le pagine dei siti NON si usano: l'estrazione dal testo e' inaffidabile;
- mai sopra un indirizzo gia' presente, mai su indirizzo_fonte='manuale';
- la ricerca rispetta il lucchetto dei lavori sull'archivio
  (cache/.lucchetto_giro_regione) e non parte se un'altra pipeline gira.
"""

from __future__ import annotations

import collections
import datetime
import fcntl
import glob
import json
import os
import pathlib
import re
import subprocess
import sys
import time

QUI = pathlib.Path(__file__).resolve().parent
LUCCHETTO = QUI / "cache" / ".lucchetto_giro_regione"
CLASSI = ("A", "B", "C")
TETTO_USD = 3.0
ATTESA_MAX_S = 6 * 3600          # lucchetto occupato o credito non ancora rinnovato
PAUSA_S = 15 * 60
COLONNE = ("id,ragione_sociale,comune,provincia,dominio,sito,telefono,classe,"
           "indirizzo,indirizzo_fonte,segnali")


def _norm(t: str | None) -> str:
    return " ".join((t or "").split()).casefold()


def tel(t: str | None) -> str:
    """Solo cifre, senza prefisso internazionale: '+39 06 123' == '06 123'."""
    c = re.sub(r"\D", "", t or "")
    if c.startswith("0039"):
        c = c[4:]
    elif c.startswith("39") and len(c) >= 11:
        c = c[2:]
    return c if len(c) >= 6 else ""


def _dominio(sito: str | None) -> str:
    if not sito:
        return ""
    import dedup
    return dedup.dominio_azienda(sito) or ""


def coincide(riga: dict, scheda: dict) -> str:
    """-> il criterio che abbina la scheda Maps alla riga ('' se nessuno)."""
    d = riga.get("dominio") or _dominio(riga.get("sito"))
    if d and d == _dominio(scheda.get("sito")):
        return "dominio"
    t = tel(riga.get("telefono"))
    if t and t == tel(scheda.get("telefono")):
        return "telefono"
    if (_norm(riga.get("ragione_sociale")) and _norm(riga.get("ragione_sociale")) == _norm(scheda.get("nome"))
            and _norm(riga.get("comune")) and _norm(riga.get("comune")) == _norm(scheda.get("comune"))):
        return "nome+comune"
    return ""


def scegli(riga: dict, candidate: list[dict]) -> tuple[dict | None, str]:
    """-> (campi da scrivere, esito). Esito: il criterio, 'nessuno' o 'ambiguo'."""
    import db
    validi = {}
    for s in candidate:
        crit = coincide(riga, s)
        campi = db.indirizzo_maps(s) if crit else {}
        if campi:
            validi.setdefault(_norm(campi["indirizzo"]), (campi, crit))
    if not validi:
        return None, "nessuno"
    if len(validi) > 1:
        return None, "ambiguo"
    campi, crit = next(iter(validi.values()))
    return campi, crit


class Indice:
    """Schede Maps indicizzate per dominio, telefono e nome: solo per
    trovare le candidate, la decisione resta a coincide()."""

    def __init__(self, schede: list[dict]):
        self.per = collections.defaultdict(list)
        for s in schede:
            if s.get("fonte") != "maps" or not (s.get("indirizzo") or "").strip():
                continue
            for k in (("d", _dominio(s.get("sito"))), ("t", tel(s.get("telefono"))),
                      ("n", _norm(s.get("nome")))):
                if k[1]:
                    self.per[k].append(s)

    def candidate(self, riga: dict) -> list[dict]:
        out = []
        for k in (("d", riga.get("dominio") or _dominio(riga.get("sito"))),
                  ("t", tel(riga.get("telefono"))), ("n", _norm(riga.get("ragione_sociale")))):
            if k[1]:
                out += self.per.get(k, [])
        return out


def schede_cache() -> list[dict]:
    schede = []
    for f in sorted(glob.glob(str(QUI / "cache" / "sourcing_*.json"))):
        schede += json.load(open(f)).get("schede") or []
    return schede


def righe_db(sb) -> list[dict]:
    righe, da = [], 0
    while True:
        b = sb.table("aziende").select(COLONNE).range(da, da + 999).execute().data or []
        righe += b
        if len(b) < 1000:
            return righe
        da += 1000


def da_riempire(r: dict) -> bool:
    return not (r.get("indirizzo") or "").strip() and r.get("indirizzo_fonte") != "manuale"


def scrivi(sb, riga: dict, campi: dict) -> bool:
    """Solo le tre colonne, solo se l'indirizzo e' ancora vuoto (anche in DB)."""
    if riga.get("indirizzo_fonte") == "manuale":
        return False
    agg = {k: campi.get(k) for k in ("indirizzo", "cap", "indirizzo_fonte")}
    r = sb.table("aziende").update(agg).eq("id", riga["id"]).is_("indirizzo", "null").execute()
    return bool(r.data)


def _attiva(r: dict) -> bool:
    import territorio
    tipi = {s.get("tipo") for s in (r.get("segnali") or []) if isinstance(s, dict)}
    return not (territorio.esclusa(r) or tipi & {"doppione", "chiusa_definitivamente", "piva_cessata"})


def abbina(sb, righe: list[dict], indice: Indice, scrivi_db: bool, log) -> dict:
    stat = {"scritte": collections.Counter(), "criterio": collections.Counter(),
            "nessuno": collections.Counter(), "ambiguo": collections.Counter(), "esempi": []}
    for r in righe:
        if not da_riempire(r):
            continue
        campi, esito = scegli(r, indice.candidate(r))
        cl = r.get("classe") or "indeterminato"
        if not campi:
            stat[esito][cl] += 1
            continue
        if not scrivi_db or scrivi(sb, r, campi):
            stat["scritte"][cl] += 1
            stat["criterio"][esito] += 1
            r.update(campi)
            if len(stat["esempi"]) < 200:
                stat["esempi"].append((r["ragione_sociale"], campi["indirizzo"], esito))
    return stat


def _resoconto(stat: dict, log, titolo: str) -> None:
    log(f"== {titolo}")
    for k, nome in (("scritte", "scritte"), ("nessuno", "nessun abbinamento valido"),
                    ("ambiguo", "ambigue (indirizzi diversi)")):
        log(f"  {nome}: {sum(stat[k].values())} {dict(sorted(stat[k].items()))}")
    log(f"  criterio: {dict(stat['criterio'])}")


def passo_cache(scrivi_db: bool, log=print) -> int:
    import db
    if scrivi_db:
        lucchetto = LUCCHETTO.open("w")
        try:
            fcntl.flock(lucchetto, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("ESITO: lucchetto dei lavori sull'archivio occupato — non scrivo")
            return 1
        if _altri_lavori():
            log(f"ESITO: altro lavoro in corso ({_altri_lavori()[0][:120]}) — non scrivo")
            return 1
    sb = db.client()
    righe = righe_db(sb)
    stat = abbina(sb, righe, Indice(schede_cache()), scrivi_db, log)
    _resoconto(stat, log, f"cache Maps ({'SCRITTO' if scrivi_db else 'prova, non scrive'})")
    resto = [r for r in righe if da_riempire(r) and r.get("classe") in CLASSI]
    log(f"  A/B/C ancora senza indirizzo: {len(resto)} "
        f"{dict(collections.Counter(r['classe'] for r in resto))}")
    return 0


def ricerche(righe: list[dict]) -> list[tuple[str, dict]]:
    """Una ricerca per scheda A/B/C senza indirizzo: attive prima, poi A, B, C."""
    resto = [r for r in righe if da_riempire(r) and r.get("classe") in CLASSI
             and (r.get("ragione_sociale") or "").strip()]
    resto.sort(key=lambda r: (not _attiva(r), CLASSI.index(r["classe"])))
    out = []
    for r in resto:
        dove = (r.get("comune") or "").strip() or (r.get("provincia") or "").strip()
        out.append((" ".join(f"{r['ragione_sociale'].strip()} {dove}".split()), r))
    return out


def per_ricerca(n: int, tetto: float) -> int:
    """2 risultati a ricerca se ci stanno nel tetto (col 10% di margine), sennò 1."""
    import config
    stima = lambda k: config.APIFY_USD_AVVIO + n * k * config.APIFY_USD_SCHEDA_MISURATO
    return 2 if stima(2) <= tetto * 0.9 else 1


def _altri_lavori() -> list[str]:
    """Altri processi della pipeline sul server (oltre a questo)."""
    try:
        out = subprocess.run(["pgrep", "-af", r"\.venv/bin/python"], capture_output=True,
                             text=True).stdout.splitlines()
    except OSError:
        return []
    mio = str(os.getpid())
    return [l for l in out if l.split(" ", 1)[0] != mio and "indirizzi_maps.py" not in l]


def _aspetta(cosa: str, pronto, log) -> bool:
    fine = time.time() + ATTESA_MAX_S
    while True:
        ok, nota = pronto()
        if ok:
            return True
        if time.time() >= fine:
            log(f"ESITO: {cosa} ancora non disponibile dopo {ATTESA_MAX_S // 3600} ore "
                f"({nota}) — non lancio niente")
            return False
        log(f"{datetime.datetime.now():%H:%M} attendo: {nota}")
        time.sleep(PAUSA_S)


def passo_ricerca(scrivi_db: bool, tetto: float, log=print) -> int:
    import config
    import db
    import sourcing_maps

    lucchetto = LUCCHETTO.open("w")

    def libero():
        try:
            fcntl.flock(lucchetto, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False, "lucchetto dei lavori sull'archivio occupato"
        altri = _altri_lavori()
        if altri:
            fcntl.flock(lucchetto, fcntl.LOCK_UN)
            return False, f"altro lavoro in corso: {altri[0][:120]}"
        return True, ""

    log(f"{datetime.datetime.now():%Y-%m-%d %H:%M} ricerca indirizzi su Maps, tetto {tetto:.2f} USD")
    if not _aspetta("archivio libero", libero, log):
        return 1

    def credito():
        c = sourcing_maps.credito(log)
        if c is None:
            return False, "credito Apify non leggibile"
        usato, massimo = c
        resto = massimo - usato
        return (resto >= tetto + config.APIFY_MARGINE_USD,
                f"credito Apify {resto:.2f} USD, servono {tetto + config.APIFY_MARGINE_USD:.2f}")

    if not _aspetta("credito Apify", credito, log):
        return 1

    sb = db.client()
    righe = righe_db(sb)
    lista = ricerche(righe)
    if not lista:
        log("ESITO: nessuna scheda A/B/C senza indirizzo — niente da cercare")
        return 0
    k = per_ricerca(len(lista), tetto)
    log(f"{len(lista)} ricerche, {k} risultati l'una "
        f"({dict(collections.Counter(r['classe'] for _, r in lista))})")
    schede, costo = sourcing_maps.cerca([], log=log, tetto_usd=tetto,
                                        ricerche=[q for q, _ in lista], per_ricerca=k)
    # i risultati grezzi restano in cache: un nuovo abbinamento non ripaga Apify
    (QUI / "cache" / f"indirizzi_ricerca_{datetime.date.today():%Y%m%d}.json").write_text(
        json.dumps({"schede": schede, "costo_usd": costo}, ensure_ascii=False), encoding="utf-8")
    per_query = collections.defaultdict(list)
    for s in schede:
        per_query[_norm(s.get("query"))].append(s)
    stat = {"scritte": collections.Counter(), "criterio": collections.Counter(),
            "nessuno": collections.Counter(), "ambiguo": collections.Counter()}
    senza_risultati = collections.Counter()
    for q, r in lista:
        cand = per_query.get(_norm(q), [])
        if not cand:
            senza_risultati[r["classe"]] += 1
        campi, esito = scegli(r, cand)
        if not campi:
            stat[esito][r["classe"]] += 1
        elif not scrivi_db or scrivi(sb, r, campi):
            stat["scritte"][r["classe"]] += 1
            stat["criterio"][esito] += 1
    _resoconto(stat, log, f"ricerca Maps ({'SCRITTO' if scrivi_db else 'prova, non scrive'})")
    log(f"  ricerche senza risultati (o fermate dal tetto): {sum(senza_risultati.values())} "
        f"{dict(senza_risultati)}")
    c = sourcing_maps.credito(log)
    log(f"  costo reale {costo:.2f} USD (tetto {tetto:.2f})"
        + (f"; credito Apify rimasto {c[1] - c[0]:.2f} USD" if c else ""))
    log("ESITO: ricerca indirizzi completata")
    return 0


def _test() -> None:
    assert tel("+39 06 123 4567") == tel("06 1234567") == "061234567"
    assert tel("+39 392 123 4567") == tel("392 1234567") == "3921234567"
    assert tel("12") == "" and tel(None) == ""
    riga = {"id": 1, "ragione_sociale": "Fabbro Rossi", "comune": "Tivoli", "dominio": "rossi.it",
            "telefono": "0774 111111", "classe": "A"}
    s = lambda **k: {"fonte": "maps", "nome": "X", "comune": "Roma", "indirizzo": "Via A 1, 00100 Roma RM",
                     "cap": "00100", **k}
    assert coincide(riga, s(sito="https://www.rossi.it/contatti")) == "dominio"
    assert coincide(riga, s(telefono="+39 0774 111111")) == "telefono"
    # nome identico ma comune diverso: NON vale
    assert coincide(riga, s(nome="fabbro  rossi")) == ""
    assert coincide(riga, s(nome="Fabbro Rossi", comune="tivoli")) == "nome+comune"
    # nome simile non vale
    assert coincide(riga, s(nome="Fabbro Rossi Srl", comune="Tivoli")) == ""
    # due abbinamenti con lo stesso indirizzo: si scrive; con indirizzi diversi no
    campi, esito = scegli(riga, [s(sito="http://rossi.it"), s(telefono="0774111111")])
    assert esito == "dominio" and campi["indirizzo"] == "Via A 1, 00100 Roma RM"
    assert campi["indirizzo_fonte"] == "maps" and campi["cap"] == "00100"
    assert scegli(riga, [s(sito="http://rossi.it"),
                         s(telefono="0774111111", indirizzo="Via B 2, Tivoli")]) == (None, "ambiguo")
    assert scegli(riga, [s(nome="Altro")]) == (None, "nessuno")
    # l'indice trova le candidate per dominio, telefono e nome
    ind = Indice([s(sito="http://rossi.it"), s(telefono="0774 111111"), s(nome="Fabbro Rossi"),
                  s(nome="Fabbro Rossi", indirizzo=""), {"fonte": "exa", "sito": "http://rossi.it",
                                                         "indirizzo": "Via Z"}])
    assert len(ind.candidate(riga)) == 3
    # manuale e gia' pieni non si toccano
    assert not da_riempire({"indirizzo": None, "indirizzo_fonte": "manuale"})
    assert not da_riempire({"indirizzo": "Via Q 1", "indirizzo_fonte": "maps"})
    assert da_riempire({"indirizzo": None, "indirizzo_fonte": None})
    assert scrivi(None, {"id": 1, "indirizzo_fonte": "manuale"}, {"indirizzo": "x"}) is False
    # ricerche: solo A/B/C senza indirizzo, attive prima, poi per classe
    import territorio
    vero = territorio.esclusa
    territorio.esclusa = lambda r: r.get("fuori", False)
    try:
        rr = [{"ragione_sociale": "C1", "comune": "Bari", "classe": "C"},
              {"ragione_sociale": "A fuori", "comune": "Lecce", "classe": "A", "fuori": True},
              {"ragione_sociale": "B1", "comune": "", "provincia": "BA", "classe": "B"},
              {"ragione_sociale": "A1", "comune": "Bari", "classe": "A", "indirizzo": "Via"},
              {"ragione_sociale": "N1", "comune": "Bari", "classe": "indeterminato"},
              {"ragione_sociale": "A2", "comune": "Bari", "classe": "A",
               "segnali": [{"tipo": "doppione"}]}]
        assert [q for q, _ in ricerche(rr)] == ["B1 BA", "C1 Bari", "A fuori Lecce", "A2 Bari"]
    finally:
        territorio.esclusa = vero
    assert per_ricerca(300, 3.0) == 2 and per_ricerca(600, 3.0) == 1
    print("ok")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(QUI / ".env")
    sys.path.insert(0, str(QUI))
    if "--test" in sys.argv:
        _test()
        sys.exit(0)
    scrivi_db = "--scrivi" in sys.argv
    if "--cache" in sys.argv:
        sys.exit(passo_cache(scrivi_db))
    if "--ricerca" in sys.argv:
        t = float(sys.argv[sys.argv.index("--tetto") + 1]) if "--tetto" in sys.argv else TETTO_USD
        sys.exit(passo_ricerca(scrivi_db, min(t, TETTO_USD), lambda m: print(m, flush=True)))
    print(__doc__)
    sys.exit(2)
