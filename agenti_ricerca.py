"""Ricerca nazionale agenti plurimandatari (progetto rete vendita, ~25 EUR
approvati dal cliente il 2026-09-29). Tre canali, tutta Italia.

    python agenti_ricerca.py --raccogli            # Exa, 20 regioni
    python agenti_ricerca.py --classifica 400      # una tranche col modello
    python agenti_ricerca.py --giro-completo       # raccolta + tutte le tranche
    python agenti_ricerca.py --scrivi              # nella tabella `agenti`
    python agenti_ricerca.py --report

I dati vivono in cache/agenti/ (fuori da git come tutta la cache; niente
/tmp: contengono nomi di persone). Le regole di merito stanno nel PROMPT
v4, feedback del cliente sul pilota:
- gli agenti dei CONCORRENTI (LFS Security & Design, Ecomet, Decoral
  Sicurezza, altri produttori di grate/persiane blindate/combinati) sono
  profili RICERCATI: conflitto attuale segnalato e facile da ritrovare;
- semilavorati siderurgici (coil, travi, laminati) -> non pertinente:
  vendono ai commercianti di acciaio, non ai fabbri;
- verniciatura e trattamento metalli -> canale 1, segnale positivo:
  girano molte officine.
Tetti di spesa INTERNI (Exa non espone il saldo): EXA_TETTO_USD e
ANTHROPIC_TETTO_EUR fermano il giro; il salvavita delle dieci analisi
uguali (main.aggiorna_serie) ferma le cause esterne.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import urllib.request

CARTELLA = pathlib.Path(__file__).parent / "cache" / "agenti"
RACCOLTA = CARTELLA / "raccolta.jsonl"
SCHEDE = CARTELLA / "schede.jsonl"
EXA_TETTO_USD = 7.0
ANTHROPIC_TETTO_EUR = 18.0

REGIONI_ITALIA = (
    "Piemonte", "Valle d'Aosta", "Lombardia", "Trentino-Alto Adige",
    "Veneto", "Friuli-Venezia Giulia", "Liguria", "Emilia-Romagna",
    "Toscana", "Umbria", "Marche", "Lazio", "Abruzzo", "Molise",
    "Campania", "Puglia", "Basilicata", "Calabria", "Sicilia", "Sardegna")

SAGOME_REGIONE = (
    # generali, le migliori del pilota
    "agente plurimandatario ferramenta e accessori per serramenti {r}",
    "agente che vende a carpenterie metalliche e fabbri {r}",
    "agente plurimandatario finestre PVC e persiane alluminio {r}",
    "rappresentante zanzariere avvolgibili e frangisole {r}",
    "agente di commercio che visita rivenditori di infissi e showroom {r}",
    "agente plurimandatario forniture per l'edilizia imprese di costruzione {r}",
    "agente di commercio materiali edili per ristrutturazioni {r}",
    "rappresentante involucro edilizio e serramenti per imprese {r}",
    # canale 1 dedicate (hanno quadruplicato la resa nel pilota)
    "agente grossista di ferramenta per officine e fabbri {r}",
    "rappresentante cerniere e cardini per fabbri {r}",
    "agente attrezzature e utensili per carpenteria metallica {r}",
    # verniciatura e trattamento metalli: canale 1, girano officine
    "agente vernici in polvere e trattamento dei metalli {r}",
    "rappresentante impianti e prodotti di verniciatura per officine {r}",
    # agenti dei concorrenti: profili ricercati
    "agente di commercio grate persiane blindate e combinati {r}",
)
SAGOME_NAZIONALI = (
    "agente o rappresentante di LFS Security e Design grate e combinati",
    "agente o rappresentante Ecomet persiane e grate di sicurezza",
    "agente o rappresentante Decoral Sicurezza persiane blindate",
)

PROMPT_V4 = """Sei il recruiter commerciale di Carpenterie Laziali (produttore di persiane, grate, inferriate, cancelli e recinzioni in acciaio; vende kit da assemblare e prodotto finito). Cerchi AGENTI PLURIMANDATARI per tre canali.

REGOLA DEI CANALI (non esempi: il canale e' quello il cui elenco corrisponde ai mandati):
1 = fabbri/officine. Mandati: ferramenta e accessori per serramenti e persiane, cerniere, cardini, serrature, profili PER SERRAMENTI, tubolari, componenti metallici, attrezzature e materiali per la lavorazione, VERNICI IN POLVERE e impianti/prodotti di verniciatura e trattamento dei metalli (segnale positivo: girano molte officine).
2 = rivenditori/serramentisti/showroom. Mandati: finestre in PVC, persiane in alluminio, pergole, frangisole, zanzariere, avvolgibili.
3 = imprese di costruzione e ristrutturazione. Mandati: forniture per l'edilizia, pavimenti, involucro edilizio, serramenti per imprese, profili per cartongesso.

REGOLE DI MERITO:
- SEMILAVORATI SIDERURGICI (coil, travi, laminati mercantili, prodotti da treno): pertinente="no" — vendono ai commercianti di acciaio, non ai fabbri.
- AGENTI DEI CONCORRENTI: chi oggi rappresenta LFS Security & Design, Ecomet, Decoral Sicurezza o un altro produttore di grate, inferriate, persiane in acciaio/di sicurezza, combinati grata-persiana, cancelli o recinzioni e' un PROFILO RICERCATO: pertinente="si", conflitto stato="attuale" col marchio nel dettaglio, agente_di_concorrente=true.
- Per assegnare il canale ogni mandato va riportato a UNA voce degli elenchi; se NESSUN mandato corrisponde, canale_prevalente=null e pertinente="da_valutare".

REGOLA SU CHI E' AGENTE: solo agenti di commercio, rappresentanti e agenzie. Dipendente di un produttore: dipendente_produttore=true e pertinente="no". Responsabile o addetto vendite di rivendita/showroom/impresa: dipendente_rivendita_o_impresa=true e pertinente="no".

REGOLA DELLE NOTE: in ogni campo SOLO dati professionali. Mai eta', salute, famiglia o altro di personale, nemmeno dedotto.

REGOLA DELLA ZONA: province coperte = quelle dichiarate per l'attivita' di agenzia; la residenza a parte, serve quando le province mancano.

PROFILO (testo pubblico):
{testo}

Rispondi SOLO con JSON:
{{"pertinente": "si|no|da_valutare", "perche": "max 15 parole",
 "canale_prevalente": 1|2|3|null, "canali_secondari": [],
 "mandati_attuali": ["..."],
 "conflitto": {{"stato": "attuale|passato|nessuno|da_verificare", "dettaglio": "..."}},
 "agente_di_concorrente": true|false,
 "categorie_clienti": [{{"tipo": "...", "fonte": "trovato|dedotto|da_chiedere"}}],
 "province_coperte": [], "residenza": "... o null",
 "dipendente_produttore": true|false,
 "dipendente_rivendita_o_impresa": true|false,
 "nota": "max 20 parole"}}"""

RE_AGENTE = re.compile(r"agente|rappresentant|plurimandat|agenzia di", re.I)


def _exa(query: str, chiave: str, n: int = 20) -> dict:
    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=json.dumps({"query": query, "type": "auto", "category": "people",
                         "numResults": n,
                         "contents": {"text": {"maxCharacters": 2500}}}).encode(),
        headers={"content-type": "application/json", "x-api-key": chiave})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def raccogli(log=print) -> None:
    CARTELLA.mkdir(parents=True, exist_ok=True)
    chiave = os.environ["EXA_API_KEY"]
    visti = set()
    if RACCOLTA.exists():
        for riga in RACCOLTA.read_text().splitlines():
            visti.add(json.loads(riga)["url"])
    speso, nuovi = 0.0, 0
    query = [s.format(r=r) for r in REGIONI_ITALIA for s in SAGOME_REGIONE]
    query += list(SAGOME_NAZIONALI)
    with RACCOLTA.open("a") as f:
        for i, q in enumerate(query, 1):
            if speso >= EXA_TETTO_USD:
                log(f"TETTO Exa raggiunto ({speso:.2f} USD): raccolta fermata a {i-1}/{len(query)}")
                break
            try:
                d = _exa(q, chiave)
            except Exception as e:  # noqa: BLE001
                log(f"  query KO ({type(e).__name__}): {q[:50]}")
                continue
            speso += (d.get("costDollars") or {}).get("total", 0) or 0
            for res in d.get("results", []):
                u = (res.get("url") or "").split("?")[0]
                if not u or u in visti:
                    continue
                visti.add(u)
                nuovi += 1
                f.write(json.dumps({"url": u, "nome": res.get("title") or "",
                                    "testo": (res.get("text") or "")[:2500],
                                    "query": q}, ensure_ascii=False) + "\n")
            if i % 28 == 0:
                log(f"  [{i}/{len(query)}] profili unici: {len(visti)}, spesi {speso:.2f} USD", )
    log(f"RACCOLTA: {len(visti)} profili unici ({nuovi} nuovi) — Exa {speso:.2f} USD")


def classifica(quante: int, log=print) -> bool:
    """Una tranche. -> True se restano profili da classificare."""
    import classify
    import config
    import costi
    import main as ciclo
    from anthropic import Anthropic

    fatte = set()
    if SCHEDE.exists():
        for riga in SCHEDE.read_text().splitlines():
            fatte.add(json.loads(riga)["url"])
    coda = []
    for riga in RACCOLTA.read_text().splitlines():
        c = json.loads(riga)
        if c["url"] not in fatte and RE_AGENTE.search(c["testo"]) \
                and len(c["testo"]) > 300:
            coda.append(c)
    log(f"in coda: {len(coda)} — questa tranche: {min(quante, len(coda))}")
    if not coda:
        return False

    client = Anthropic(max_retries=1)
    tot = costi.nuovo_ciclo()
    serie = ("", 0)
    with SCHEDE.open("a") as f:
        for i, c in enumerate(coda[:quante], 1):
            costo = costi.costo_anthropic(tot["token_input"], tot["token_output"])
            if costo >= ANTHROPIC_TETTO_EUR:
                log(f"TETTO Anthropic raggiunto ({costo:.2f} EUR): tranche fermata")
                break
            try:
                r = client.messages.create(
                    model=config.MODELLO, max_tokens=700, temperature=0,
                    timeout=config.TIMEOUT_ANTHROPIC_S,
                    messages=[{"role": "user",
                               "content": PROMPT_V4.format(testo=c["testo"])}])
                d = classify.estrai_json(
                    next(b.text for b in r.content if b.type == "text"))
                costi.registra_analisi(tot, r.usage.input_tokens,
                                       r.usage.output_tokens)
                serie = ciclo.aggiorna_serie(serie, "")
                f.write(json.dumps({**d, "url": c["url"], "nome": c["nome"],
                                    "query": c["query"]},
                                   ensure_ascii=False) + "\n")
            except Exception as e:  # noqa: BLE001
                serie = ciclo.aggiorna_serie(serie, type(e).__name__)
                log(f"  KO {c['nome'][:26]}: {type(e).__name__}")
                if serie[1] >= ciclo.MAX_ERRORI_ANALISI:
                    log(f"SALVAVITA: {serie[1]} errori uguali di fila "
                        f"({serie[0]}), tranche interrotta")
                    break
            if i % 50 == 0:
                log(f"  [{i}]", )
    costi.stampa(tot, log=log)
    return len(coda) > quante


def _regione_di(s: dict) -> str:
    # la regione prevalente per numero di province; fallback residenza/query
    import collections
    import config as cfg
    conta = collections.Counter()
    for p in (s.get("province_coperte") or []):
        sig = (cfg.sigla_provincia(str(p)) or "").upper()
        for regione, sigle in _REGIONI_SIGLE.items():
            if sig in sigle:
                conta[regione] += 1
        for regione in _REGIONI_SIGLE:
            if regione.lower() in str(p).lower():
                conta[regione] += 1
    if conta:
        prime = conta.most_common(2)
        if len(prime) > 1 and prime[0][1] == prime[1][1] and len(conta) > 2:
            return "Multiregionali"
        return prime[0][0]
    testo = f"{s.get('residenza') or ''} {s.get('query') or ''}".lower()
    for regione in _REGIONI_SIGLE:
        if regione.lower() in testo:
            return regione
    return "Da determinare"


_REGIONI_SIGLE = {
    "Piemonte": {"TO", "VC", "NO", "CN", "AT", "AL", "BI", "VB"},
    "Valle d'Aosta": {"AO"},
    "Lombardia": {"MI", "BG", "BS", "CO", "CR", "MN", "PV", "SO", "VA", "LC", "LO", "MB"},
    "Trentino-Alto Adige": {"TN", "BZ"},
    "Veneto": {"VR", "VI", "BL", "TV", "VE", "PD", "RO"},
    "Friuli-Venezia Giulia": {"UD", "GO", "TS", "PN"},
    "Liguria": {"GE", "IM", "SP", "SV"},
    "Emilia-Romagna": {"BO", "PR", "RE", "MO", "PC", "FE", "RA", "FC", "RN"},
    "Toscana": {"FI", "AR", "GR", "LI", "LU", "MS", "PI", "PT", "PO", "SI"},
    "Umbria": {"PG", "TR"}, "Marche": {"AN", "AP", "FM", "MC", "PU"},
    "Lazio": {"RM", "LT", "FR", "VT", "RI"},
    "Abruzzo": {"AQ", "CH", "PE", "TE"}, "Molise": {"CB", "IS"},
    "Campania": {"NA", "AV", "BN", "CE", "SA"},
    "Puglia": {"BA", "BT", "BR", "FG", "LE", "TA"},
    "Basilicata": {"PZ", "MT"}, "Calabria": {"CZ", "CS", "KR", "RC", "VV"},
    "Sicilia": {"PA", "AG", "CL", "CT", "EN", "ME", "RG", "SR", "TP"},
    "Sardegna": {"CA", "NU", "OR", "SS", "SU"},
}


def scrivi(log=print) -> None:
    """Nella tabella `agenti` (creata a mano dal committente). Insert puro:
    linkedin_url unico fa da dedup, il conflitto e' il dedup che lavora."""
    import db
    sb = db.client()
    inserite = doppie = errori = 0
    for riga in SCHEDE.read_text().splitlines():
        s = json.loads(riga)
        if s.get("pertinente") not in ("si", "da_valutare"):
            continue
        c = s.get("conflitto") or {}
        record = {
            "nome_completo": s.get("nome"),
            "linkedin_url": s.get("url"),
            "canale_prevalente": s.get("canale_prevalente"),
            "canali_secondari": s.get("canali_secondari") or None,
            "classificazione": "pertinente" if s["pertinente"] == "si" else "da_valutare",
            "mandati_attuali": s.get("mandati_attuali") or None,
            "conflitto_stato": c.get("stato") or "da_verificare",
            "conflitto_dettaglio": c.get("dettaglio"),
            "agente_di_concorrente": bool(s.get("agente_di_concorrente")),
            "categorie_clienti": s.get("categorie_clienti") or None,
            "province_coperte": [str(x) for x in (s.get("province_coperte") or [])] or None,
            "regione_prevalente": _regione_di(s),
            "zona_da_confermare": not (s.get("province_coperte") or []),
            "residenza": s.get("residenza"),
            "note": s.get("nota"),
            "fonte": "exa",
        }
        try:
            sb.table("agenti").insert(record).execute()
            inserite += 1
        except Exception as e:  # noqa: BLE001
            if "23505" in str(e) or "duplicate key" in str(e):
                doppie += 1
            else:
                errori += 1
                if errori <= 3:
                    log(f"  errore su {s.get('nome', '?')[:30]}: {str(e)[:120]}")
    log(f"scrittura: inserite {inserite}, doppie {doppie}, errori {errori}")


def report(log=print) -> None:
    import collections
    per = collections.defaultdict(collections.Counter)
    concorrenti, tot, buone = [], 0, 0
    for riga in SCHEDE.read_text().splitlines():
        s = json.loads(riga)
        tot += 1
        if s.get("pertinente") not in ("si", "da_valutare"):
            continue
        buone += 1
        per[_regione_di(s)][s.get("canale_prevalente") or "-"] += 1
        if s.get("agente_di_concorrente"):
            concorrenti.append((s["nome"], (s.get("conflitto") or {}).get("dettaglio", "")))
    log(f"classificate {tot} — schede buone {buone}")
    log(f"{'regione':<24}{'c1':>5}{'c2':>5}{'c3':>5}{'da val.':>9}")
    for regione in sorted(per, key=lambda r: -sum(per[r].values())):
        c = per[regione]
        log(f"{regione:<24}{c.get(1, 0):>5}{c.get(2, 0):>5}{c.get(3, 0):>5}{c.get('-', 0):>9}")
    log(f"\nAGENTI DI CONCORRENTI: {len(concorrenti)}")
    for n, d in concorrenti[:15]:
        log(f"  {n[:36]:<38} {d[:60]}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        assert len(REGIONI_ITALIA) == 20
        assert len([s.format(r="X") for r in REGIONI_ITALIA for s in SAGOME_REGIONE]) == 280
        assert sum(len(v) for v in _REGIONI_SIGLE.values()) == 107, \
            sum(len(v) for v in _REGIONI_SIGLE.values())
        assert _regione_di({"province_coperte": ["TV", "VE", "PD", "UD"]}) == "Veneto"
        assert _regione_di({"province_coperte": [], "residenza": "Napoli, Campania"}) == "Campania"
        assert _regione_di({"province_coperte": ["MI", "TO"], "residenza": ""}) in ("Multiregionali", "Lombardia", "Piemonte")
        assert "conflitto stato=\"attuale\"" in PROMPT_V4 and "coil" in PROMPT_V4
        assert "VERNICI IN POLVERE" in PROMPT_V4
        print("ok")
        sys.exit(0)

    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).parent / ".env")
    import crediti

    if "--raccogli" in sys.argv or "--giro-completo" in sys.argv:
        problemi = crediti.controllo(serve_anthropic="--giro-completo" in sys.argv,
                                     serve_exa=True)
        if problemi:
            print("ESITO: ricerca NON partita — " + "; ".join(problemi))
            sys.exit(1)
        raccogli()
    if "--classifica" in sys.argv:
        n = int(sys.argv[sys.argv.index("--classifica") + 1]) \
            if sys.argv.index("--classifica") + 1 < len(sys.argv) \
            and sys.argv[sys.argv.index("--classifica") + 1].isdigit() else 400
        classifica(n)
    if "--giro-completo" in sys.argv:
        while classifica(400):
            print("--- tranche completata, si continua ---", flush=True)
    if "--scrivi" in sys.argv:
        scrivi()
    if "--report" in sys.argv:
        report()
