"""Ricerca nazionale agenti plurimandatari (progetto rete vendita, ~25 EUR
approvati dal cliente il 2026-09-29). Tre canali, tutta Italia.

    python agenti_ricerca.py --raccogli            # Exa, 20 regioni
    python agenti_ricerca.py --classifica 400      # una tranche col modello
    python agenti_ricerca.py --giro-completo       # raccolta + tutte le tranche
    python agenti_ricerca.py --scrivi              # nella tabella `agenti`
    python agenti_ricerca.py --report
    python agenti_ricerca.py --nomi                # nome/cognome mancanti

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
import unicodedata
import urllib.request

CARTELLA = pathlib.Path(__file__).parent / "cache" / "agenti"
RACCOLTA = CARTELLA / "raccolta.jsonl"
SCHEDE = CARTELLA / "schede.jsonl"
LUCCHETTO = CARTELLA / ".lucchetto"
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


def _righe_json(percorso: pathlib.Path):
    """Un record per riga, spezzando SOLO su newline: splitlines() taglia
    anche su U+2028/U+2029, che i testi LinkedIn contengono (erano loro i
    "23 illeggibili" del 29/9, non il doppio avvio). None per riga rotta."""
    with percorso.open() as f:
        for riga in f:
            try:
                yield json.loads(riga)
            except ValueError:
                yield None


def normalizza_linkedin(url: str | None) -> str | None:
    """Canonica per il dedup: via sottodominio (it./www.), parametri,
    frammento e slash finale."""
    u = (url or "").strip().split("#")[0].split("?")[0].rstrip("/")
    if not u:
        return None
    return re.sub(r"^https?://(?:[a-z]{2}\.|www\.)?linkedin\.com",
                  "https://linkedin.com", u, flags=re.I)


# Nome e cognome separati (richiesta di Claudia, 30/9: ordine per cognome,
# «Cognome Nome»). La regola chiude solo i casi certi; completa_nomi() passa
# gli altri al modello. nome_completo non si tocca mai.
PARTICELLE = {"de", "di", "del", "della", "dello", "delle", "dei", "degli",
              "delli", "da", "dal", "dalla", "dalle", "dai", "d'", "dell'",
              "lo", "la", "le", "li", "san", "santo", "santa", "van", "von"}
RE_DITTA = re.compile(r"rappresentanz|agenzia|agency|\bs\.?r\.?l|\bsnc\b|"
                      r"\bsas\b|\bs\.?p\.?a\b|commercio|infissi|\bagente\b|"
                      r"rappresentante", re.I)
RE_TITOLO = re.compile(r"^(?:arch|ing|geom|dott|dr|avv|rag|per|p\.i)\.\s+", re.I)
RE_INIZIALE = re.compile(r"^[A-Za-z]\.$")


def _leggibile(parola: str) -> str:
    """MAIUSCOLO o minuscolo -> Iniziale (anche dopo l'apostrofo); le
    parole gia' in forma mista restano come le ha scritte l'agente."""
    if not (parola.isupper() or parola.islower()) or RE_INIZIALE.match(parola):
        return parola
    return re.sub(r"(^|['-])(\w)", lambda m: m.group(1) + m.group(2).upper(),
                  parola.lower())


def separa_nome(nome_completo: str | None) -> tuple[str, str, bool] | None:
    """(nome, cognome, certo). certo=False e' una PROPOSTA da far verificare
    al modello: due parole semplici, dove l'ordine non si deduce ("Ferlini
    Ottavio", "TAMBURRO ARMANDO": in tabella ce ne sono). None: decide il modello."""
    t = re.split(r"\s+[-|–]\s+|\|", nome_completo or "")[0]
    t = RE_TITOLO.sub("", re.sub(r"[^\w\s'.-]", " ", t)).strip()
    parole = t.split()
    if len(parole) < 2 or RE_DITTA.search(t) or "(" in (nome_completo or ""):
        return None
    iniziali = [bool(RE_INIZIALE.match(w)) for w in parole]
    certo = True
    if len(parole) == 2 and iniziali == [False, True]:          # "Ottavio T."
        nome, cognome = parole[:1], parole[1:]
    elif any(iniziali):
        return None
    else:
        maiu = [w.isupper() for w in parole]
        if any(maiu) and not all(maiu):
            # "Ottavio FERLINI", "FERLINI Ottavio": il blocco MAIUSCOLO e' il
            # cognome, ma solo se sta tutto a un capo
            k = maiu.index(True)
            blocco = maiu[k:].count(True)
            if not all(maiu[k:k + blocco]) or any(maiu[k + blocco:]):
                return None
            if k == 0:
                cognome, nome = parole[:blocco], parole[blocco:]
            elif k + blocco == len(parole):
                nome, cognome = parole[:k], parole[k:]
            else:
                return None
        else:
            basse = [w.lower() for w in parole]
            pos = [i for i, w in enumerate(basse) if w in PARTICELLE]
            if pos:
                # "Ugo Di Vettore", "Ottavio Remo Di Scalzo": particella
                # seguita da UNA parola sola; in testa o altrove -> modello
                k = pos[0]
                if k == 0 or k != len(parole) - 2 or len(pos) > 1:
                    return None
                nome, cognome = parole[:k], parole[k:]
            elif len(parole) == 2:
                nome, cognome, certo = parole[:1], parole[1:], False
            else:
                return None   # 3+ parole senza appigli: nome doppio? ditta?
    return (" ".join(map(_leggibile, nome)), " ".join(map(_leggibile, cognome)),
            certo)


PROMPT_NOMI = """Per ciascun profilo LinkedIn di un agente di commercio
italiano separa NOME e COGNOME della persona. Regole:
- cognomi composti interi (De Vettore, Di Scalzo Ferlini, D'Arpino, Lo Tamburro);
- nomi doppi interi (Maria Grazia, Gian Luca, Francesco Saverio);
- riconosci l'ordine rovesciato (COGNOME Nome, o cognome prima del nome);
- togli titoli, regione, ruolo, ragione sociale ("Rappresentanze", "Srl");
- se c'e' una ditta con dentro una persona ("Edil X di Ferlini Ottavio") usa la persona;
- se non c'e' nessuna persona riconoscibile: nome null e cognome = SOLO il
  nome distintivo della ditta, senza forma giuridica (Srl, Snc, Sas, S.r.l.)
  e senza parole generiche o descrittive (Rappresentanze, Agenzia, Studio,
  Edili, Infissi PVC, Legno, Alluminio...): "VELTRAS RAPPRESENTANZE SRL" ->
  "Veltras", "Agenzia Orbimex" -> "Orbimex", "Studio Quadrifer" ->
  "Quadrifer", "Lunaria Infissi PVC - LEGNO" -> "Lunaria"; le sigle restano
  in maiuscolo ("KTR Rappresentanze" -> "KTR");
- usa SOLO parole che compaiono nel nome_completo: niente da aggiungere,
  correggere o completare;
- se c'e' solo l'iniziale del cognome ("Ottavio T.") il cognome e' "T.".
Scrivi in forma leggibile (Rossi, non ROSSI).
Alcuni profili hanno gia' una "proposta": se e' giusta NON riportarli.
Rispondi SOLO per i profili senza proposta o con la proposta sbagliata,
e SOLO con il JSON, senza ragionamento prima o dopo: {{"risultati": [{{"id": "...", "nome": "... o null",
"cognome": "..."}}]}}

Profili:
{elenco}"""


def _parole(testo: str | None) -> set[str]:
    """Le parole di un nome, senza maiuscole, accenti e apostrofi."""
    t = unicodedata.normalize("NFKD", (testo or "").casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return set(re.findall(r"[a-z0-9]+", re.sub(r"['’]", "", t)))


def parole_in_originale(nome_completo: str, nome: str | None, cognome: str | None) -> bool:
    """Nome e cognome fatti solo di parole del nome_completo: il modello
    divide e ripulisce, non inventa ne' corregge."""
    return _parole(nome) | _parole(cognome) <= _parole(nome_completo)


def completa_nomi(log=print) -> None:
    """Riempie nome/cognome delle righe che ancora non li hanno: prima la
    regola, poi il modello a blocchi di 100 per i casi incerti. Solo update
    di queste due colonne."""
    import classify
    import config
    import costi
    import db
    from anthropic import Anthropic

    sb = db.client()
    righe, i = [], 0
    while True:
        # le agenzie di rappresentanza (fonte sito_agenzia, 8/10) restano senza
        # nome e cognome: l'app ordina per cognome e un'agenzia non ne ha uno
        blocco = (sb.table("agenti").select("id,nome_completo")
                  .is_("cognome", "null").or_("fonte.is.null,fonte.neq.sito_agenzia")
                  .range(i, i + 999).execute().data)
        righe += blocco
        if len(blocco) < 1000:
            break
        i += 1000
    certi, incerti, proposte = {}, [], {}
    for r in righe:
        esito = separa_nome(r["nome_completo"])
        if esito and esito[2]:
            certi[str(r["id"])] = esito[:2]
        else:
            incerti.append(r)
            if esito:
                proposte[str(r["id"])] = esito[:2]
    log(f"senza cognome: {len(righe)} — regola certa {len(certi)}; al modello "
        f"{len(incerti)} ({len(proposte)} con proposta da verificare, "
        f"{len(incerti) - len(proposte)} da risolvere)")

    tot = costi.nuovo_ciclo()
    client = Anthropic(max_retries=2)
    corrette, falliti = 0, set()
    for j in range(0, len(incerti), 100):
        pezzo = incerti[j:j + 100]
        elenco = "\n".join(json.dumps(
            {"id": str(r["id"]), "nome_completo": r["nome_completo"],
             "proposta": dict(zip(("nome", "cognome"), proposte[str(r["id"])]))
             if str(r["id"]) in proposte else None},
            ensure_ascii=False) for r in pezzo)
        attesi = {str(x["id"]) for x in pezzo}
        try:
            r = client.messages.create(
                model=config.MODELLO, max_tokens=4000, temperature=0,
                timeout=config.TIMEOUT_ANTHROPIC_S,
                messages=[{"role": "user", "content": PROMPT_NOMI.format(elenco=elenco)}])
            costi.registra_analisi(tot, r.usage.input_tokens, r.usage.output_tokens)
            testo = next(b.text for b in r.content if b.type == "text")
            # il 30/9 il modello ha ragionato prima del JSON citando le
            # proposte fra graffe: si parte dall'ultimo {"risultati"
            risultati = classify.estrai_json(
                testo[max(testo.rfind('{"risultati"'), 0):])["risultati"]
        except Exception as e:  # noqa: BLE001
            # blocco perso: le sue proposte NON valgono come confermate
            log(f"  blocco {j // 100 + 1} illeggibile ({type(e).__name__}): resta da fare")
            falliti |= attesi
            continue
        originali = {str(x["id"]): x["nome_completo"] for x in pezzo}
        for x in risultati:
            id_ = str(x.get("id"))
            if id_ in attesi and (x.get("cognome") or "").strip():
                nome, cognome = (x.get("nome") or "").strip() or None, x["cognome"].strip()
                if not parole_in_originale(originali[id_], nome, cognome):
                    # scartata; e la proposta, se c'era, non vale piu' come confermata
                    log(f"  SCARTATA, parole non nell'originale: {originali[id_]!r} -> "
                        f"nome={nome!r} cognome={cognome!r}")
                    falliti.add(id_)
                    continue
                certi[id_] = (nome, cognome)
                corrette += id_ in proposte
    for id_, proposta in proposte.items():
        if id_ not in falliti:
            certi.setdefault(id_, proposta)     # non corretta dal modello = giusta
    log(f"proposte corrette dal modello: {corrette}")
    mancano = [r for r in righe if str(r["id"]) not in certi]
    for id_, (nome, cognome) in certi.items():
        sb.table("agenti").update({"nome": nome, "cognome": cognome}).eq("id", id_).execute()
    log(f"scritte {len(certi)}; rimaste senza cognome {len(mancano)}"
        + "".join(f"\n  {r['nome_completo']}" for r in mancano[:10]))
    costi.stampa(tot, log=log)


def _exa(query: str, chiave: str, n: int = 20, caratteri: int = 2500) -> dict:
    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=json.dumps({"query": query, "type": "auto", "category": "people",
                         "numResults": n,
                         "contents": {"text": {"maxCharacters": caratteri}}}).encode(),
        headers={"content-type": "application/json", "x-api-key": chiave})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def raccogli(log=print) -> None:
    CARTELLA.mkdir(parents=True, exist_ok=True)
    chiave = os.environ["EXA_API_KEY"]
    visti = set()
    if RACCOLTA.exists():
        for c in _righe_json(RACCOLTA):
            if c:
                visti.add(normalizza_linkedin(c["url"]))
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
                u = normalizza_linkedin(res.get("url"))
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
        fatte = {c["url"] for c in _righe_json(SCHEDE) if c}
    coda, scartate = [], 0
    for c in _righe_json(RACCOLTA):
        if c is None:
            scartate += 1     # riga davvero rotta (scrittura interrotta)
            continue
        if c["url"] not in fatte and RE_AGENTE.search(c["testo"]) \
                and len(c["testo"]) > 300:
            coda.append(c)
    if scartate:
        log(f"righe illeggibili saltate: {scartate}")
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
                # dal 9/10 la stessa chiamata estrae anche i marchi della lista
                # del committente (agenti_marchi): nessuna query in piu'
                import agenti_marchi
                r = client.messages.create(
                    model=config.MODELLO, max_tokens=900, temperature=0,
                    timeout=config.TIMEOUT_ANTHROPIC_S,
                    messages=[{"role": "user",
                               "content": agenti_marchi.prompt_classifica(c["testo"])}])
                d = classify.estrai_json(
                    next(b.text for b in r.content if b.type == "text"))
                d["mandati_marchi"] = agenti_marchi.marchi_della_scheda(
                    d, c["testo"], normalizza_linkedin(c["url"])) or None
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


def record_scheda(s: dict) -> dict:
    """La scheda classificata -> riga della tabella `agenti` (anche per
    agenti_marchi.py)."""
    c = s.get("conflitto") or {}
    return {
        "nome_completo": s.get("nome"),
        "linkedin_url": normalizza_linkedin(s.get("url")),
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
        "mandati_marchi": s.get("mandati_marchi") or None,
    }


def scrivi(log=print) -> None:
    """Nella tabella `agenti` (creata a mano dal committente). Insert puro:
    linkedin_url unico fa da dedup, il conflitto e' il dedup che lavora."""
    import db
    sb = db.client()
    inserite = doppie = errori = 0
    for s in _righe_json(SCHEDE):
        if not s or s.get("pertinente") not in ("si", "da_valutare"):
            continue
        record = record_scheda(s)
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
    completa_nomi(log)   # i casi incerti della regola li chiude il modello


def report(log=print) -> None:
    import collections
    per = collections.defaultdict(collections.Counter)
    concorrenti, tot, buone = [], 0, 0
    for s in _righe_json(SCHEDE):
        if not s:
            continue
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
        assert normalizza_linkedin("https://it.linkedin.com/in/x?trk=p") == "https://linkedin.com/in/x"
        assert normalizza_linkedin("http://www.linkedin.com/in/x/") == "https://linkedin.com/in/x"
        assert normalizza_linkedin("https://linkedin.com/in/x#r") == "https://linkedin.com/in/x"
        assert normalizza_linkedin(None) is None
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as t:
            t.write('{"url": "a", "testo": "riga con \u2028 dentro"}\n{rotta\n')
        _prova = list(_righe_json(pathlib.Path(t.name)))
        assert _prova[0] and _prova[0]["testo"] == "riga con \u2028 dentro" \
            and _prova[1] is None, _prova
        os.unlink(t.name)
        for dentro, fuori in [
                ("Ugo Di Vettore", ("Ugo", "Di Vettore")),
                ("Ottavio Remo Di Scalzo", ("Ottavio Remo", "Di Scalzo")),
                ("ARMANDO DELLE FRASCHE", ("Armando", "Delle Frasche")),
                ("remo del ventaglio", ("Remo", "Del Ventaglio")),
                ("Ottavio FERLINI", ("Ottavio", "Ferlini")),
                ("Ugo Remo TAMBURRO", ("Ugo Remo", "Tamburro")),
                ("Armando SAINT VETTORE", ("Armando", "Saint Vettore")),
                ("FERLINI Maria Grazia", ("Maria Grazia", "Ferlini")),
                ("Ottavio T.", ("Ottavio", "T.")),
                ("Remo SCALZATI ⭐", ("Remo", "Scalzati")),
                ("Ugo FERVI - Agente di commercio", ("Ugo", "Fervi")),
                ("Arch. Ottavio Di Frasca", ("Ottavio", "Di Frasca"))]:
            assert separa_nome(dentro) == (*fuori, True), (dentro, separa_nome(dentro))
        assert separa_nome("Ferlini Ottavio") == ("Ferlini", "Ottavio", False)
        assert separa_nome("TAMBURRO ARMANDO") == ("Tamburro", "Armando", False)
        assert separa_nome("ARMANDO D'ARPINO") == ("Armando", "D'Arpino", False)
        assert separa_nome("remo d'arpino") == ("Remo", "D'Arpino", False)
        assert parole_in_originale("Ugo D'arpino", "Ugo", "D'Arpino")
        assert parole_in_originale("TAMBURRO SRL", None, "Tamburro")
        assert parole_in_originale("Àrmando CÀ.FÈ.", "Armando", "Ca.Fe.")
        assert not parole_in_originale("Ugo D'arpino", "Ugo", "D'Arrigo")
        assert not parole_in_originale("Remo Ferlini", "Remo", "Ferlini Rossi")
        for incerto in ["Di Vettore Ugo", "Gian Remo Scalzati",
                        "Ferlini Tamburro Ugo", "Edilfer Di Remo Scalzati",
                        "UFT Ferlini Rappresentanze", "TAMBURRO SRL",
                        "Ferlini (Ottavio)", "Remo UF T.", "Ugo R. Scalzati",
                        "Edilvetro di Frasca Remo", "Ottavio Di Scalzo Ferlini", ""]:
            assert separa_nome(incerto) is None, (incerto, separa_nome(incerto))
        print("ok")
        sys.exit(0)

    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).parent / ".env")
    import crediti

    # UN SOLO processo per volta: il 29/9 un doppio avvio (ssh -f) ha fatto
    # leggere a un processo il file che l'altro stava ancora scrivendo.
    # flock si rilascia da solo alla morte del processo: niente lock stantii.
    import fcntl
    CARTELLA.mkdir(parents=True, exist_ok=True)
    _lucchetto = LUCCHETTO.open("w")
    try:
        fcntl.flock(_lucchetto, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("ESITO: un altro agenti_ricerca e' gia' in esecuzione — esco")
        sys.exit(1)

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
    if "--nomi" in sys.argv:
        completa_nomi()
