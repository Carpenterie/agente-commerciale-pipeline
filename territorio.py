"""Filtro geografico euristico pre-classificazione (PRD §5).

È l'unico modulo che decide di NON classificare: un falso `fuori` è
invisibile — l'azienda sparisce e nessuno se ne accorge. Quindi sbaglia
sempre verso `incerto`, mai verso `fuori`:

- `fuori`  SOLO con segnali forti e diretti: CAP o prefisso telefonico di
  una regione NON attiva (config.REGIONI) nella pagina contatti (o nel footer della homepage, se la
  pagina contatti non è stata scaricata). Un capoluogo citato nel testo
  NON basta: "lavoriamo anche a Milano" non è una sede.
- `dentro` richiede un segnale positivo esplicito: CAP, prefisso
  telefonico o comune (data/comuni.py) di una delle regioni attive. Fino
  al 2026-10-07 l'esito si chiamava `lazio`: le righe gia' scritte lo
  portano ancora, e vale come `dentro`.
- tutto il resto è `incerto` = si classifica comunque, la sede la estrae
  il modello (§7).

L'esito e il segnale che l'ha determinato vanno registrati (campo
`territorio_segnale`): servono al controllo a campione di cosa è stato
scartato.
"""

from __future__ import annotations

import re

import config
from data.comuni import ALTRI_NOMI, COMUNI

_TUTTI_COMUNI = tuple(c.lower() for prov in COMUNI.values() for c in prov) \
    + tuple(c.lower() for c in ALTRI_NOMI)
# trattino o spazio fra le parole, apostrofo dritto o curvo: "Montecatini
# Terme" e "Montecatini-Terme" sono lo stesso comune (7/10)
_RE_COMUNI = re.compile(r"\b(" + "|".join(
    re.escape(c).replace(r"\-", r"[\s-]+").replace(r"\ ", r"[\s-]+").replace("'", "['’]")
    for c in _TUTTI_COMUNI) + r")\b")
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


# Partita IVA e codici fiscali/REA sono 11 cifre che cominciano spesso per
# 0: "P.IVA 09902550962" diventava il prefisso 099 (Taranto) appena la
# Puglia e' entrata fra le regioni attive (7/10, Carpenterie Lombarde).
_RE_NON_TEL = re.compile(r"(?:iva|p\.\s?i\.?|c\.\s?f\.?|fiscale|rea|cod\w*)\W{0,4}$", re.I)


def _telefoni(testo: str) -> list[str]:
    return [re.sub(r"\D", "", m.group(1)) for m in _RE_TEL.finditer(testo)
            if not _RE_NON_TEL.search(testo[max(0, m.start() - 20):m.start()])]


def da_scheda(scheda: dict) -> dict | None:
    """Segnale territoriale PRIMARIO: il CAP e la provincia che Google Maps
    dichiara sulla scheda (93-95% valorizzati). È un dato di anagrafica,
    non una deduzione dal testo di una pagina: quando c'è, vince
    sull'euristica.

    -> esito, oppure None se la scheda non porta il dato.
    """
    cap = str(scheda.get("cap") or "").strip()
    provincia = str(scheda.get("provincia") or "").strip().upper()
    if cap and cap[:2] in config.PREFISSI_CAP_ATTIVI:
        return {"esito": "dentro", "segnale": f"cap {cap} da Google Maps"}
    if cap:
        return {"esito": "fuori", "segnale": f"cap {cap} da Google Maps"}
    if provincia and provincia in config.PROVINCE:
        return {"esito": "dentro", "segnale": f"provincia {provincia} da Google Maps"}
    if provincia:
        return {"esito": "fuori", "segnale": f"provincia {provincia} da Google Maps"}
    return None


def valuta(contenuto: str, scheda: dict | None = None) -> dict:
    """-> {"esito": "dentro"|"fuori"|"incerto", "segnale": str}

    Se la scheda della fonte porta CAP o provincia, quelli decidono: sono
    anagrafica, non deduzione. L'euristica sui recapiti della pagina resta
    il ripiego per il 7% di schede che non li hanno (e per Exa, che non ne
    ha mai).
    """
    if scheda:
        primario = da_scheda(scheda)
        if primario:
            return primario

    testo = _RE_URL.sub(" ", _sezione_contatti(contenuto))
    dentro, fuori = [], []

    for cap in _cap(testo):
        if cap[:2] in config.PREFISSI_CAP_ATTIVI:
            dentro.append(f"cap {cap}")
        else:
            fuori.append(f"cap {cap}")

    for tel in _telefoni(testo):
        if tel.startswith(config.PREFISSI_TEL_ATTIVI):
            p = next(p for p in config.PREFISSI_TEL_ATTIVI if tel.startswith(p))
            dentro.append(f"prefisso {p}")
        elif tel.startswith(config.PREFISSI_TEL_FUORI):
            p = next(p for p in config.PREFISSI_TEL_FUORI if tel.startswith(p))
            fuori.append(f"prefisso {p}")
        # prefisso in nessuna lista: non è un segnale

    minuscolo = testo.lower()
    for m in _RE_COMUNI.finditer(minuscolo):
        if _RE_VIA.search(minuscolo[max(0, m.start() - 12):m.start()]):
            continue  # è il nome di una via
        dentro.append(f"comune {m.group(1)}")
        break

    # un segnale positivo vince sempre: dentro e incerto classificano
    # comunque, solo fuori scarta — e fuori deve restare l'ultima parola
    if dentro:
        segnale = "; ".join(dict.fromkeys(dentro[:3]))
        if fuori:
            segnale += f" (anche segnali fuori: {'; '.join(dict.fromkeys(fuori[:2]))})"
        return {"esito": "dentro", "segnale": segnale}
    if fuori:
        return {"esito": "fuori", "segnale": "; ".join(dict.fromkeys(fuori[:3]))}
    return {"esito": "incerto", "segnale": "nessun segnale nei contatti"}


FUORI_DA = "fuori dalle regioni attive"


def regione_attiva(regione: str) -> bool:
    r = (regione or "").strip().lower()
    return any(r == a.lower() for a in config.REGIONI_ATTIVE)


def verifica_sede(dati: dict) -> dict | None:
    """Controllo DOPO la classificazione: il modello legge la sede dalla
    pagina contatti, ed è un dato migliore dell'euristica sui prefissi.
    Se dichiara una regione che non e' fra quelle attive, la riga va marcata
    fuori territorio — meglio scoprirlo dopo aver pagato l'analisi che
    consegnare un'azienda lombarda. Una sede toscana in un ciclo laziale
    invece e' dentro: si vende in tutte le regioni attive.

    -> segnale da aggiungere alla riga, o None se la sede non contraddice.
    """
    sede = ", ".join(str(dati.get(c) or "").strip()
                     for c in ("sede_comune", "sede_provincia") if dati.get(c))
    # La PROVINCIA dichiarata basta da sola (2026-09-21): "Lastra a Signa,
    # FI" senza regione passava indenne, perche' il controllo guardava solo
    # `sede_regione`. La sigla e' piu' specifica della regione e non mente:
    # se e' una provincia italiana fuori dalle regioni attive, la sede e' fuori.
    sigla = (config.sigla_provincia((dati.get("sede_provincia") or "").strip())
             or "").upper()
    if len(sigla) == 2 and sigla in config.SIGLE_PROVINCE.values() \
            and sigla not in config.SIGLE_ATTIVE:
        regione = (dati.get("sede_regione") or "").strip()
        return {"tipo": "fuori_territorio_sede_dichiarata",
                "regione": regione or None, "sede": sede or None,
                "segnale": f"sede dichiarata dal sito: {sede or '?'} "
                           f"(provincia {sigla}), {FUORI_DA}"}
    if len(sigla) == 2 and sigla in config.SIGLE_ATTIVE:
        return None     # la provincia attiva vince su una regione sbagliata
    regione = (dati.get("sede_regione") or "").strip()
    if not regione or regione.lower() in ("null", "none") or regione_attiva(regione):
        return None
    return {"tipo": "fuori_territorio_sede_dichiarata",
            "regione": regione, "sede": sede or None,
            "segnale": f"sede dichiarata dal sito: {sede or '?'} ({regione}), "
                       f"{FUORI_DA}"}


def riepilogo(valutazioni: list[dict], log=print) -> None:
    """Da chiamare a fine ciclo: quante scartate come `fuori` e con quali
    segnali, raggruppati. Se su un ciclo laziale la quota di fuori esplode,
    deve vedersi dal log, non dai risultati mancanti."""
    from collections import Counter

    esiti = Counter(v["esito"] for v in valutazioni)
    tot = len(valutazioni) or 1
    log(f"territorio: {len(valutazioni)} valutate — "
        f"dentro {esiti['dentro'] + esiti['lazio']}, incerto {esiti['incerto']}, "
        f"fuori {esiti['fuori']} ({100 * esiti['fuori'] // tot}%)")
    segnali = Counter(v["segnale"].split(";")[0].strip()
                      for v in valutazioni if v["esito"] == "fuori")
    for segnale, n in segnali.most_common():
        log(f"  fuori per {segnale}: {n}")


def _test_sede():
    # i due casi reali del 2026-09-21, sfuggiti al controllo sulla regione:
    # provincia dichiarata senza regione (Sycurferr, Lastra a Signa FI)...
    # (dal 7/10 la Toscana e' attiva: lo stesso caso si prova su Perugia)
    v = verifica_sede({"sede_comune": "BASTIA UMBRA", "sede_provincia": "PG"})
    assert v and "provincia PG" in v["segnale"], v
    # ...e regione dichiarata "Lazio" con provincia fuori (Door Al, CN):
    # la sigla e' piu' specifica e vince sulla regione sbagliata
    v = verifica_sede({"sede_comune": "TORRE SAN GIORGIO",
                       "sede_provincia": "CN", "sede_regione": "Lazio"})
    assert v and "provincia CN" in v["segnale"], v
    # provincia laziale: nessun segnale, con e senza regione
    assert verifica_sede({"sede_provincia": "RM"}) is None
    assert verifica_sede({"sede_provincia": "Latina", "sede_regione": "Lazio"}) is None
    # regione fuori senza provincia: scatta come prima
    v = verifica_sede({"sede_comune": "Rodano", "sede_regione": "Lombardia"})
    assert v and "Lombardia" in v["segnale"]
    # niente sede -> niente segnale; valore ignoto -> non e' una sigla
    assert verifica_sede({}) is None
    assert verifica_sede({"sede_provincia": "Oltrepo"}) is None
    # regioni attive dal 7/10: una sede toscana, campana o abruzzese e' dentro
    # anche in un ciclo laziale; la Lombardia resta fuori
    assert verifica_sede({"sede_comune": "LASTRA A SIGNA", "sede_provincia": "FI",
                          "sede_regione": "Toscana"}) is None
    assert verifica_sede({"sede_provincia": "Napoli"}) is None
    assert verifica_sede({"sede_regione": "Abruzzo"}) is None
    assert verifica_sede({"sede_provincia": "PG"})["segnale"].endswith(FUORI_DA)
    # provincia attiva + regione sbagliata dal modello: vince la provincia
    assert verifica_sede({"sede_provincia": "AN", "sede_regione": "Umbria"}) is None


if __name__ == "__main__":
    _test_sede()
    # --- casi sintetici: le regole una per una ---
    v = valuta("# PAGINA: https://x.it/contatti\n\nVia Roma 1, 20121 Milano - Tel 02 1234567")
    assert v["esito"] == "fuori" and "cap 20121" in v["segnale"], v

    v = valuta("# PAGINA: https://x.it/\n\nOfficina in Via Appia 10, 00179 Roma")
    assert v["esito"] == "dentro" and "cap 00179" in v["segnale"], v

    v = valuta("# PAGINA: https://x.it/\n\nChiamaci: 06 44041234")
    assert v["esito"] == "dentro" and "prefisso 06" in v["segnale"], v

    v = valuta("# PAGINA: https://x.it/\n\nSede a Palombara Sabina, in zona industriale")
    assert v["esito"] == "dentro" and "comune palombara sabina" in v["segnale"], v

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
    assert v["esito"] == "dentro" and "anche segnali fuori" in v["segnale"], v

    # la pagina contatti vince sulla homepage; le altre pagine si ignorano
    v = valuta("# PAGINA: https://x.it/\n\nhome\n\n# PAGINA: https://x.it/gallery\n\n"
               "cantiere a 20121 Milano\n\n# PAGINA: https://x.it/contatti\n\n00187 Roma")
    assert v["esito"] == "dentro" and "00187" in v["segnale"], v

    # le due grafie del comune valgono uguale (ISTAT e uso comune, 7/10)
    for forma in ("Montecatini Terme", "Montecatini-Terme", "Sannicandro Garganico",
                  "San Nicandro Garganico", "Popoli", "Popoli Terme", "Sant’Angelo dei Lombardi"):
        v = valuta(f"# PAGINA: https://x.it/\n\nLaboratorio a {forma}, zona artigianale")
        assert v["esito"] == "dentro", (forma, v)
    # la partita IVA non e' un telefono (09902550962 non e' Taranto)
    assert valuta("# PAGINA: https://x.it/\n\nP.IVA 09902550962")["esito"] == "incerto"
    assert valuta("# PAGINA: https://x.it/\n\nC.F. 08012345678")["esito"] == "incerto"
    # regioni nuove: CAP e prefissi toscani/pugliesi sono dentro, Milano no
    v = valuta("# PAGINA: https://x.it/contatti\n\nVia Pisana 3, 50143 Firenze - Tel 055 123456")
    assert v["esito"] == "dentro" and "cap 50143" in v["segnale"], v
    v = valuta("# PAGINA: https://x.it/\n\nChiamaci: 080 5551234")
    assert v["esito"] == "dentro" and "prefisso 080" in v["segnale"], v
    v = valuta("# PAGINA: https://x.it/\n\nTel 0571 123456")
    assert v["esito"] == "dentro" and "prefisso 0571" in v["segnale"], v
    assert da_scheda({"cap": "75100", "provincia": "MT"})["esito"] == "fuori"   # Matera
    assert da_scheda({"cap": "", "provincia": "FI"})["esito"] == "dentro"

    # --- CAP e provincia da Maps: segnale primario, batte l'euristica ---
    v = da_scheda({"cap": "00179", "provincia": "RM"})
    assert v["esito"] == "dentro" and "da Google Maps" in v["segnale"]
    assert da_scheda({"cap": "20121", "provincia": "MI"})["esito"] == "fuori"
    assert da_scheda({"cap": "", "provincia": "LT"})["esito"] == "dentro"
    assert da_scheda({"cap": "", "provincia": "BG"})["esito"] == "fuori"
    assert da_scheda({"cap": "", "provincia": ""}) is None   # si passa all'euristica
    assert da_scheda({}) is None

    # il CAP della scheda vince sui recapiti della pagina, che qui direbbero Roma
    pagina_romana = "# PAGINA: https://x.it/contatti\n\n00179 Roma, tel 06 1234567"
    v = valuta(pagina_romana, {"cap": "24061", "provincia": "BG"})
    assert v["esito"] == "fuori" and "24061" in v["segnale"], v
    # senza scheda, l'euristica lavora come prima
    assert valuta(pagina_romana)["esito"] == "dentro"
    assert valuta(pagina_romana, {})["esito"] == "dentro"

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
    # le laziali con recapiti in cache danno dentro (Il Fabbro Roma non li ha:
    # solo cellulari, che giustamente non sono un segnale geografico)
    non_lazio = [n for n in LAZIALI if n != "Il Fabbro Roma"
                 and esiti[n]["esito"] != "dentro"]
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
