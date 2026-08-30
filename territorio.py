"""Filtro geografico euristico pre-classificazione (PRD §5).

È l'unico modulo che decide di NON classificare: un falso `fuori` è
invisibile — l'azienda sparisce e nessuno se ne accorge. Quindi sbaglia
sempre verso `incerto`, mai verso `fuori`:

- `fuori`  SOLO con segnali forti e diretti: CAP o prefisso telefonico di
  altra regione nella pagina contatti (o nel footer della homepage, se la
  pagina contatti non è stata scaricata). Un capoluogo citato nel testo
  NON basta: "lavoriamo anche a Milano" non è una sede.
- `lazio`  richiede un segnale positivo esplicito: CAP 00-04, prefisso
  telefonico del Lazio, o un comune di data/comuni_lazio.py.
- tutto il resto è `incerto` = si classifica comunque, la sede la estrae
  il modello (§7).

L'esito e il segnale che l'ha determinato vanno registrati (campo
`territorio_segnale`): servono al controllo a campione di cosa è stato
scartato.
"""

from __future__ import annotations

import re

import config
from data.comuni_lazio import COMUNI

_TUTTI_COMUNI = tuple(c.lower() for prov in COMUNI.values() for c in prov)
_RE_COMUNI = re.compile(r"\b(" + "|".join(re.escape(c) for c in _TUTTI_COMUNI) + r")\b")
# "Via Roma 1, Milano": il nome della via non è il comune
_RE_VIA = re.compile(r"(?:via|viale|piazza|p\.zza|corso|largo|vicolo|strada)\s+$")
# gli URL sono la prima fonte di falsi CAP (query string, hash di immagini):
# si tolgono prima di cercare qualsiasi cosa
_RE_URL = re.compile(r"https?://\S+")
# 5 cifre isolate: niente cifre/lettere/punteggiatura attaccate
# (esclude P.IVA, importi, hash tipo 11062b, "UNI EN 13659:2009")
_RE_CAP = re.compile(r"(?<![\w.,])\d{5}(?![\w.,:])")
# fisso italiano: 0 + 8-11 cifre totali, separatori tolleranti, +39 opzionale.
# Il minimo di 9 cifre esclude le date (06/05/2024 -> 8 cifre).
_RE_TEL = re.compile(r"(?:\+?39[\s.]?)?(0\d(?:[\s.\-/]?\d){7,10})")


def _sezione_contatti(contenuto: str) -> str:
    """La pagina contatti se scaricata, altrimenti la homepage: i recapiti
    stanno nel footer. Le altre pagine non si guardano (gallery e referenze
    citano cantieri ovunque)."""
    sezioni = contenuto.split("# PAGINA: ")
    for s in sezioni:
        url = s.split("\n", 1)[0].lower()
        if "contatt" in url or "contact" in url:
            return s
    return sezioni[1] if len(sezioni) > 1 else contenuto


def _cap(testo: str) -> list[str]:
    trovati = []
    for m in _RE_CAP.finditer(testo):
        if not 10 <= int(m.group()) <= 98168:
            continue  # fuori dall'intervallo reale dei CAP italiani
        contesto = testo[max(0, m.start() - 12):m.end() + 12].lower()
        if any(x in contesto for x in ("€", "eur", "tel", "fax", "cell", "+39",
                                       "uni", "iso", "oltre", "circa")):
            continue  # prezzo, telefono, norma tecnica o quantità ("oltre 15000 finestre")
        trovati.append(m.group())
    return trovati


def _telefoni(testo: str) -> list[str]:
    return [re.sub(r"\D", "", m) for m in _RE_TEL.findall(testo)]


def valuta(contenuto: str) -> dict:
    """-> {"esito": "lazio"|"fuori"|"incerto", "segnale": str}"""
    testo = _RE_URL.sub(" ", _sezione_contatti(contenuto))
    lazio, fuori = [], []

    for cap in _cap(testo):
        if cap[:2] in config.PREFISSI_CAP_LAZIO:
            lazio.append(f"cap {cap}")
        else:
            fuori.append(f"cap {cap}")

    for tel in _telefoni(testo):
        if tel.startswith(config.PREFISSI_TEL_LAZIO):
            p = next(p for p in config.PREFISSI_TEL_LAZIO if tel.startswith(p))
            lazio.append(f"prefisso {p}")
        elif tel.startswith(config.PREFISSI_TEL_FUORI):
            p = next(p for p in config.PREFISSI_TEL_FUORI if tel.startswith(p))
            fuori.append(f"prefisso {p}")
        # prefisso in nessuna lista: non è un segnale

    minuscolo = testo.lower()
    for m in _RE_COMUNI.finditer(minuscolo):
        if _RE_VIA.search(minuscolo[max(0, m.start() - 12):m.start()]):
            continue  # è il nome di una via
        lazio.append(f"comune {m.group(1)}")
        break

    # un segnale positivo Lazio vince sempre: lazio e incerto classificano
    # comunque, solo fuori scarta — e fuori deve restare l'ultima parola
    if lazio:
        segnale = "; ".join(dict.fromkeys(lazio[:3]))
        if fuori:
            segnale += f" (anche segnali fuori: {'; '.join(dict.fromkeys(fuori[:2]))})"
        return {"esito": "lazio", "segnale": segnale}
    if fuori:
        return {"esito": "fuori", "segnale": "; ".join(dict.fromkeys(fuori[:3]))}
    return {"esito": "incerto", "segnale": "nessun segnale nei contatti"}


def verifica_sede(dati: dict, regione_ciclo: str = config.REGIONE_CICLO) -> dict | None:
    """Controllo DOPO la classificazione: il modello legge la sede dalla
    pagina contatti, ed è un dato migliore dell'euristica sui prefissi.
    Se dichiara una regione diversa da quella del ciclo, la riga va marcata
    fuori territorio — meglio scoprirlo dopo aver pagato l'analisi che
    consegnare un'azienda lombarda in un ciclo laziale.

    -> segnale da aggiungere alla riga, o None se la sede non contraddice.
    """
    regione = (dati.get("sede_regione") or "").strip()
    if not regione or regione.lower() in ("null", "none", regione_ciclo.lower()):
        return None
    sede = ", ".join(str(dati.get(c) or "").strip()
                     for c in ("sede_comune", "sede_provincia") if dati.get(c))
    return {"tipo": "fuori_territorio_sede_dichiarata",
            "regione": regione, "sede": sede or None,
            "segnale": f"sede dichiarata dal sito: {sede or '?'} ({regione}), "
                       f"fuori da {regione_ciclo}"}


def riepilogo(valutazioni: list[dict], log=print) -> None:
    """Da chiamare a fine ciclo: quante scartate come `fuori` e con quali
    segnali, raggruppati. Se su un ciclo laziale la quota di fuori esplode,
    deve vedersi dal log, non dai risultati mancanti."""
    from collections import Counter

    esiti = Counter(v["esito"] for v in valutazioni)
    tot = len(valutazioni) or 1
    log(f"territorio: {len(valutazioni)} valutate — "
        f"lazio {esiti['lazio']}, incerto {esiti['incerto']}, "
        f"fuori {esiti['fuori']} ({100 * esiti['fuori'] // tot}%)")
    segnali = Counter(v["segnale"].split(";")[0].strip()
                      for v in valutazioni if v["esito"] == "fuori")
    for segnale, n in segnali.most_common():
        log(f"  fuori per {segnale}: {n}")


if __name__ == "__main__":
    # --- casi sintetici: le regole una per una ---
    v = valuta("# PAGINA: https://x.it/contatti\n\nVia Roma 1, 20121 Milano - Tel 02 1234567")
    assert v["esito"] == "fuori" and "cap 20121" in v["segnale"], v

    v = valuta("# PAGINA: https://x.it/\n\nOfficina in Via Appia 10, 00179 Roma")
    assert v["esito"] == "lazio" and "cap 00179" in v["segnale"], v

    v = valuta("# PAGINA: https://x.it/\n\nChiamaci: 06 44041234")
    assert v["esito"] == "lazio" and "prefisso 06" in v["segnale"], v

    v = valuta("# PAGINA: https://x.it/\n\nSede a Palombara Sabina, in zona industriale")
    assert v["esito"] == "lazio" and "comune palombara sabina" in v["segnale"], v

    # un capoluogo citato nel testo NON basta per fuori
    v = valuta("# PAGINA: https://x.it/\n\nLavoriamo anche a Milano e Torino")
    assert v["esito"] == "incerto", v

    # prezzo e data non sono CAP/telefono
    v = valuta("# PAGINA: https://x.it/\n\nGrate da 15000 euro, promo del 02/05/2024")
    assert v["esito"] == "incerto", v

    # quantità e numeri fuori intervallo CAP non sono segnali
    v = valuta("# PAGINA: https://x.it/\n\nposa oltre 15000 finestre in PVC all'anno")
    assert v["esito"] == "incerto", v
    v = valuta("# PAGINA: https://x.it/\n\ncodice prodotto 99999")
    assert v["esito"] == "incerto", v

    # prefisso fuori lista (0765 è Lazio ma non in elenco): nessun segnale
    v = valuta("# PAGINA: https://x.it/\n\nTel 0765 123456")
    assert v["esito"] == "incerto", v

    # conflitto sede+filiale: vince il segnale Lazio, si classifica
    v = valuta("# PAGINA: https://x.it/contatti\n\nSede: 00187 Roma. Filiale: 20121 Milano")
    assert v["esito"] == "lazio" and "anche segnali fuori" in v["segnale"], v

    # la pagina contatti vince sulla homepage; le altre pagine si ignorano
    v = valuta("# PAGINA: https://x.it/\n\nhome\n\n# PAGINA: https://x.it/gallery\n\n"
               "cantiere a 20121 Milano\n\n# PAGINA: https://x.it/contatti\n\n00187 Roma")
    assert v["esito"] == "lazio" and "00187" in v["segnale"], v

    # --- verifica della sede dichiarata dopo la classificazione ---
    v = verifica_sede({"sede_comune": "RODANO", "sede_provincia": "MI",
                       "sede_regione": "Lombardia"})
    assert v and v["regione"] == "Lombardia" and "RODANO, MI" in v["segnale"], v
    assert verifica_sede({"sede_regione": "Lazio"}) is None
    assert verifica_sede({"sede_regione": "lazio"}) is None      # maiuscole
    assert verifica_sede({"sede_regione": ""}) is None           # non dichiarata
    assert verifica_sede({"sede_regione": "null"}) is None       # il modello scrive la parola
    assert verifica_sede({}) is None

    # --- casi reali dalla cache del campione ---
    import csv
    import sys
    from pathlib import Path

    campione = Path(__file__).parent / "tests" / "campione_26"
    sys.path.insert(0, str(campione))
    import asyncio

    import fetch as fetch_campione  # il fetch del campione: cache piatta, offline

    esiti = {}
    with (campione / "risultati.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["esito_fetch"] != "OK":
                continue
            ok, contenuto, _ = asyncio.run(fetch_campione.fetch_azienda(None, r["url"]))
            assert ok == "OK", r["nome"]
            v = valuta(contenuto)
            esiti[r["nome"]] = v
            print(f"{v['esito']:<8} {r['nome'][:45]:<45} {v['segnale'][:60]}")

    # tutte le aziende note come laziali, comprese quelle senza segnali in cache
    LAZIALI = ["Serramenti Lazio", "Lema Infissi 85 srl", "Infissi Torelli",
               "ROMANA FINESTRE", "GE.MAT. INFISSI SRL", "Fabbro Vita Antonio",
               "Il Fabbro Roma", "Centro Infissi G.A. di Pizzo Giampietro",
               "La Porta Srl", "Paterno Serramenti",
               "Serramenti E Infissi Faler Snc Di Vitale Enzo E Pisanu Riccardo",
               "Loi Carpenterie Generali Verniciatura industriale", "Iron & Steel Srl"]
    # fuori regione con recapiti veri in cache (Forza Infissi: Calusco d'Adda BG).
    # Brianza Serramenti non c'è: nelle sue pagine in cache non ci sono recapiti,
    # solo una quantità ("oltre 15000 finestre") che ora è filtrata -> incerto
    FUORI = ["Forza Infissi | Serramenti in Alluminio", "Gruppo Serramenti",
             "Fabbro Como", "Fabbro Monza Urgente",
             "Fabbro Lissone - sostituzione, riparazione e pronto intervento",
             "Carpenterie Lombarde S.r.l.", "Carpenteria Bonatese",
             "CMA srl Carpenteria metallica Milano Fabbro Bergamo Pronto Intervento"
             " Monza Lodi e provincia Crema"]

    # la regola d'oro: nessuna laziale deve MAI finire fuori
    finite_fuori = [n for n in LAZIALI if esiti[n]["esito"] == "fuori"]
    assert not finite_fuori, finite_fuori
    # le laziali con recapiti in cache danno lazio (Il Fabbro Roma non li ha:
    # solo cellulari, che giustamente non sono un segnale geografico)
    non_lazio = [n for n in LAZIALI if n != "Il Fabbro Roma"
                 and esiti[n]["esito"] != "lazio"]
    assert not non_lazio, non_lazio
    # il caso senza segnali nei contatti resta incerto: si classifica comunque
    assert esiti["Il Fabbro Roma"]["esito"] == "incerto", esiti["Il Fabbro Roma"]
    # le fuori regione con recapiti in cache danno fuori
    non_fuori = [n for n in FUORI if esiti[n]["esito"] != "fuori"]
    assert not non_fuori, non_fuori

    # riepilogo di fine ciclo: conteggi e raggruppamento dei segnali fuori
    righe_log = []
    riepilogo(list(esiti.values()), log=righe_log.append)
    assert f"fuori {len(FUORI)}" in righe_log[0], righe_log[0]
    assert any("fuori per cap 22100" in r for r in righe_log), righe_log
    print(*righe_log, sep="\n")
    print("ok")
