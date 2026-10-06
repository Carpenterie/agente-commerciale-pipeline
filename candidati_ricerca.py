"""Selezione di un geometra o architetto di cantiere (sede a Guidonia
Montecelio): profili professionali pubblici da Exa, valutati sui 17
criteri del committente, nella tabella `candidati`. Lavoro separato da
aziende e agenti; stesso impianto di agenti_ricerca.py.

    python candidati_ricerca.py --raccogli          # ricerche mirate (QUERY)
    python candidati_ricerca.py --classifica 400    # valuta la coda
    python candidati_ricerca.py --scrivi            # nella tabella `candidati`
    python candidati_ricerca.py --conservazione [--prova]   # cron, 90 giorni

Regole del committente (privacy compresa):
- fonte SOLO Exa, profili pubblici: niente scraping LinkedIn, niente login;
- SOLO dati professionali: mai eta', foto, salute, famiglia, opinioni,
  nemmeno dedotti; l'eta' non si ricava dagli anni di studio; nella
  disponibilita' e nelle prove mai sussidi (NaSPI, cassa integrazione),
  motivi personali, salute o famiglia;
- "aperto a nuove opportunita'" solo se dichiarato: nota, non filtro; il
  messaggio non cita mai il fatto che la persona cerca lavoro;
- un criterio che il profilo non dimostra resta "da_verificare", mai "no";
  l'evidenza deve essere una frase del profilo (controllata qui sotto);
- nessun punteggio che escluda: prima chi ha zona, titolo e 3 anni
  (criteri 2, 3 e 7), poi per criteri verificati.
CONSERVAZIONE (l'unica eccezione alla regola "niente cancellazioni", la
impone la privacy): in tabella entrano solo persone nel ruolo e non fuori
zona; il testo di chi non entra si cancella subito dopo la valutazione;
chi non arriva al colloquio si cancella 90 giorni dopo l'ultimo
aggiornamento, e la stessa soglia vale per la cache (--conservazione).
I dati vivono in CANDIDATI_CARTELLA (default cache/candidati, fuori da git).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sys

from agenti_ricerca import (_exa, _righe_json, normalizza_linkedin,
                            parole_in_originale, separa_nome)

CARTELLA = pathlib.Path(os.environ.get("CANDIDATI_CARTELLA")
                        or pathlib.Path(__file__).parent / "cache" / "candidati")
RACCOLTA = CARTELLA / "raccolta.jsonl"
SCHEDE = CARTELLA / "schede.jsonl"
LUCCHETTO = CARTELLA / ".lucchetto"
GIORNI_CONSERVAZIONE = 90
# tetto del committente per la fase 2: 8 EUR in tutto
EXA_TETTO_USD = 0.6
ANTHROPIC_TETTO_EUR = 7.4

# Il pilota del 6/10 ha gia' fatto 14 ricerche su Roma (ruoli, competenze,
# aziende indicate). Qui solo le mirate sulla zona di Guidonia.
ZONE = ("Guidonia Montecelio", "Tivoli", "Monterotondo", "Mentana",
        "Fonte Nuova", "Roma est Tiburtina")
RUOLI = ("geometra di cantiere", "architetto di cantiere",
         "tecnico o responsabile di cantiere",
         "assistente di cantiere o tecnico di commessa edile")
QUERY = tuple(f"{r} {z}" for z in ZONE for r in RUOLI)

# segnale in piu', non filtro: vale SOLO il nome esatto ("ItC&E" non e' ITC)
RE_AZIENDE = {
    "Italiana Costruzioni": r"\bItaliana Costruzioni\b",
    "ITC Srl – Costruzioni Tecnologiche Integrate":
        r"\bITC\s+S\.?r\.?l\b|Costruzioni Tecnologiche Integrate",
    "Cobar": r"\bCobar\b", "Nessi & Majocchi": r"\bNessi\s*(?:&|e)\s*Majocchi\b",
    "SALC": r"\bSALC\b", "PICHLER projects": r"\bPichler\b",
    "Rubner Holzbau": r"\bRubner\b", "Ghella": r"\bGhella\b",
}

CRITERI = (
    ("Disponibilità a nuove opportunità", "Candidato che dichiara di cercare lavoro o una collaborazione."),
    ("Zona geografica", "Guidonia Montecelio, Roma e provincia."),
    ("Titolo professionale", "Geometra, architetto, tecnico, responsabile o assistente di cantiere, tecnico di commessa o site manager; ruoli attuali e precedenti."),
    ("Formazione", "Diploma di geometra/CAT oppure laurea in architettura."),
    ("Settore di provenienza", "Edilizia, costruzioni, ristrutturazioni, carpenteria strutturale, strutture metalliche e montaggi."),
    ("Aziende precedenti", "Imprese che eseguono lavori e gestiscono direttamente cantieri, squadre e subappaltatori."),
    ("Esperienza pertinente", "Gestione concreta di cantieri, almeno 3 anni (somma dalle date dei ruoli)."),
    ("Gestione operativa del cantiere", "Organizzazione e programmazione delle lavorazioni, controllo avanzamento, verifica esecuzione, gestione problemi."),
    ("Gestione dei subappaltatori", "Coordinamento ditte, sequenze e interferenze, scadenze, controllo dei lavori eseguiti."),
    ("Computi metrici", "Ricavare quantità da disegni e rilievi, redigere e verificare computi."),
    ("CAD 2D", "Uso operativo di AutoCAD o equivalente per elaborati e dettagli esecutivi."),
    ("Autonomia", "Segue le attività affidate, individua criticità, propone soluzioni, aggiorna il responsabile."),
    ("Presenza in cantiere", "Disponibilità concreta a lavorare sul posto e a fare sopralluoghi."),
    ("Spostamenti e trasferte", "Disponibilità compatibile con la localizzazione dei cantieri."),
    ("Esperienza contrattuale precedente", "Da dipendente o con partita IVA: entrambe valide."),
    ("Nuovo rapporto di lavoro", "Disponibilità all'assunzione o a collaborazione con partita IVA."),
    ("Competenze preferenziali", "Contabilità lavori, SAL, preventivi, confronto offerte, controllo costi, Excel, software per computi."),
)
# disponibilita' future: le dice solo il colloquio (13 non e' l'esperienza
# in cantiere passata, gia' contata nei criteri 7 e 8)
SOLO_COLLOQUIO = {13, 14, 16}
BASE = (2, 3, 7)    # zona, titolo, 3 anni: vanno in testa

CHIUSURA = ("Ho trovato il suo profilo pubblico su LinkedIn cercando questa figura "
            "nella zona di Roma. Conserviamo solo i dati professionali del profilo, "
            "per valutare questa posizione: se non è interessato li cancelliamo "
            "entro 90 giorni, e può chiederne la cancellazione in qualsiasi momento "
            "rispondendo a questo messaggio.")
MAX_MESSAGGIO = 600
MAX_CORPO = MAX_MESSAGGIO - len(CHIUSURA) - 1     # uno spazio fra corpo e chiusura

PROMPT = """Valuti un profilo professionale pubblico per Carpenterie Laziali (produttore di persiane, grate, inferriate, cancelli e recinzioni in acciaio, con montaggi; sede a Guidonia Montecelio, Roma). Cerca un GEOMETRA o ARCHITETTO DI CANTIERE.

CRITERI (n. nome: requisito):
{criteri}

REGOLE:
- Per ogni criterio: esito "si", "no" o "da_verificare", con "evidenza" = una frase COPIATA ALLA LETTERA dal profilo (anche parziale, stessa ortografia) oppure null.
- "si" solo con l'evidenza. "no" solo se una frase del profilo dimostra il CONTRARIO (anche essa come evidenza). Un criterio che il profilo non puo' dimostrare e' "da_verificare", MAI "no".
- Criterio 1: "si" solo se il profilo DICHIARA di cercare lavoro o di essere aperto a nuove opportunita'; altrimenti "da_verificare".
- Criterio 2: "si" se la localita' del profilo o del ruolo attuale e' Roma o un comune della sua provincia (anche "Rome, Latium, Italy", "Greater Rome Metropolitan Area"), con quella frase come evidenza; "no" se e' altrove.
- Criterio 4: "si" solo se il profilo SCRIVE il diploma o la laurea (istituto, corso, titolo di studio). Il ruolo "geometra" o "architetto" da solo non basta: "da_verificare".
- Criterio 7: somma le date dei ruoli di cantiere. NON usare mai gli anni di studio.
- Criteri 13, 14 e 16: sempre "da_verificare" (si chiariscono al colloquio).
- SOLO dati professionali: ruoli, aziende, date, formazione, competenze dichiarate, localita'. Mai eta' (nemmeno dedotta), foto, salute, famiglia, opinioni o altro di personale, in nessun campo.
- "disponibilita" e le evidenze: mai sussidi (NaSPI, cassa integrazione, disoccupazione), motivi personali, salute o famiglia. Della frase sulla disponibilita' copia SOLO la parte che dice che la persona e' disponibile (es. "attualmente sono in cerca di occupazione", senza il resto).

NOME: dall'intestazione separa nome e cognome della persona (cognomi composti interi, ordine rovesciato riconosciuto, niente titoli o ruoli), usando SOLO parole dell'intestazione, in forma leggibile (Rossi, non ROSSI).

MESSAGGIO: il primo messaggio di contatto, in italiano, dando del Lei, scritto in prima persona da chi seleziona per Carpenterie Laziali (senza firmare ne' nominare il mittente). Inizia con "Buongiorno" seguito dal nome di battesimo. Parla SOLO dell'esperienza: personalizzalo su UN'esperienza concreta del profilo e spiega in breve la posizione (geometra/architetto di cantiere, sede a Guidonia Montecelio). MAI accennare al fatto che la persona cerca lavoro o e' disponibile. Due o tre frasi brevi, MASSIMO {max_corpo} caratteri spazi compresi: e' un limite rigido. Niente saluti finali ne' frasi sulla privacy: la chiusura la aggiungiamo noi.

INTESTAZIONE: {intestazione}

PROFILO (testo pubblico):
{testo}

Rispondi SOLO con JSON:
{{"persona": true|false, "nel_ruolo": true|false,
 "nome_proprio": "... o null", "cognome": "...",
 "localita": "... o null", "sintesi": "max 60 parole, solo dati professionali",
 "disponibilita": "frase copiata dal profilo o null",
 "criteri": [{{"n": 1, "esito": "si|no|da_verificare", "evidenza": "... o null"}}],
 "messaggio": "..."}}
("persona": false per pagine di aziende o gruppi; "nel_ruolo": ruolo attuale o precedente fra quelli del criterio 3.)"""

RE_RUOLO = re.compile(r"geometr|architett|cantiere|site manager|commessa|"
                      r"construction|direttore lavori|direzione lavori", re.I)
RE_ZONA = re.compile(r"\bRoma\b|\bRome\b|Guidonia|Tivoli|Monterotondo|Fonte Nuova|"
                     r"Mentana|Fiumicino|Pomezia|Ciampino|Frascati|Velletri|"
                     r"Civitavecchia|Ladispoli|Cerveteri|Anzio|Nettuno|Ardea|"
                     r"Marino|Albano|Colleferro|Palestrina|Zagarolo|Bracciano|"
                     r"Subiaco|Castel Madama|Villa Adriana|Setteville|Sant'Angelo Romano", re.I)
RE_FORMAZIONE = re.compile(r"diplom|laure|istitut|universit|politecnic|\bCAT\b|\bITG\b|"
                           r"scuola|degree|bachelor|master|accademia|facolt|corso di studi", re.I)
# fuori da disponibilita', prove e sintesi
RE_SENSIBILE = re.compile(r"naspi|cassa integrazione|\bcig\b|disoccupa|sussidi|indennit|"
                          r"\bin mobilit|liste? di mobilit|"   # la mobilita' del lavoro
                          r"malatti|salute|invalidit|\b104\b|categorie protette|famigli|"
                          r"\bfigli|gravidanz|maternit|paternit|\blutto\b|"
                          r"motivi (?:personali|familiari|di salute)", re.I)
# il messaggio parla solo dell'esperienza, mai della ricerca di lavoro
RE_CERCA_LAVORO = re.compile(r"in cerca|cerca(?:ndo)? (?:di )?(?:un )?(?:nuov[oa] )?"
                             r"(?:lavoro|occupazione|impiego)|open to work|"
                             r"nuove opportunit|apert[oa] a |disoccup|naspi|"
                             r"senza (?:lavoro|occupazione)", re.I)


def _norm(t: str | None) -> str:
    return re.sub(r"\s+", " ", (t or "").replace("’", "'")).strip().casefold()


def oggi() -> str:
    return dt.date.today().isoformat()


def controlla(scheda: dict, testo: str) -> int:
    """Le regole che il modello puo' sbagliare, rifatte nel codice.
    -> quanti esiti ha riportato a "da_verificare"."""
    corpo, corretti = _norm(testo), 0
    lazio = re.search(r"Lazio|Latium", scheda.get("localita") or "", re.I)
    for c in scheda.get("criteri") or []:
        ev = _norm(c.get("evidenza")).strip(" .\"'«»")
        if RE_SENSIBILE.search(ev):
            c["evidenza"], ev = None, ""
        n, esito = c.get("n"), c.get("esito")
        torna = (
            # un "si" o un "no" senza frase LETTERALE del profilo
            (esito in ("si", "no") and (len(ev) < 4 or ev not in corpo))
            or (n in SOLO_COLLOQUIO and esito != "da_verificare")
            or (n == 4 and esito == "si" and not RE_FORMAZIONE.search(ev))
            # il modello non conosce i 121 comuni della provincia (il 6/10
            # ha messo Lariano fuori zona): nel Lazio il "no" non lo decide lui
            or (n == 2 and esito == "no" and lazio))
        if torna:
            c["esito"], corretti = "da_verificare", corretti + 1
        if n in SOLO_COLLOQUIO:
            c["evidenza"] = None
    # della disponibilita' resta solo la parte prima del riferimento sensibile
    # ("in cerca di occupazione in NaSPI" -> "in cerca di occupazione")
    disp = re.sub(r"(?:\s+(?:in|con|e|per|causa|a causa di|dovut[oa] a))+\s*$", "",
                  RE_SENSIBILE.split(scheda.get("disponibilita") or "")[0].rstrip(" ,;:-(")
                  ).strip(" -–•") if scheda.get("disponibilita") else ""
    scheda["disponibilita"] = disp if len(disp) >= 12 and _norm(disp).strip(" .\"'«»") in corpo else None
    scheda["sintesi"] = " ".join(f for f in re.split(r"(?<=\.)\s+", scheda.get("sintesi") or "")
                                 if not RE_SENSIBILE.search(f)) or None
    scheda["aziende_segnalate"] = [a for a, r in RE_AZIENDE.items() if re.search(r, testo, re.I)]
    corpo_msg = (scheda.get("messaggio") or "").strip()
    if (RE_CERCA_LAVORO.search(corpo_msg) or RE_SENSIBILE.search(corpo_msg)
            or len(corpo_msg) > MAX_CORPO):
        scheda["messaggio"] = None      # meglio nessuna bozza che una sbagliata
    nome, cognome = scheda.get("nome_proprio"), scheda.get("cognome")
    if not cognome or not parole_in_originale(scheda.get("nome") or "", nome, cognome):
        sep = separa_nome(scheda.get("nome"))
        nome, cognome = sep[:2] if sep else (None, (scheda.get("nome") or "").split(" - ")[0].strip())
    scheda["nome_proprio"], scheda["cognome"] = nome, cognome
    return corretti


def esiti(scheda: dict) -> dict:
    return {c.get("n"): c.get("esito") for c in scheda.get("criteri") or []}


def verificati(scheda: dict) -> int:
    return sum(e == "si" for e in esiti(scheda).values())


def base(scheda: dict) -> bool:
    return all(esiti(scheda).get(n) == "si" for n in BASE)


def ordine(scheda: dict) -> tuple:
    return (not base(scheda), -verificati(scheda))


def entra(scheda: dict) -> bool:
    """In tabella solo persone nel ruolo e non fuori zona."""
    return bool(scheda.get("persona") and scheda.get("nel_ruolo")
                and esiti(scheda).get(2) != "no")


def messaggio(scheda: dict) -> str | None:
    corpo = (scheda.get("messaggio") or "").strip()
    return f"{corpo} {CHIUSURA}" if corpo else None


def _riscrivi(percorso: pathlib.Path, righe: list[dict]) -> None:
    tmp = percorso.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in righe))
    tmp.replace(percorso)


def raccogli(log=print) -> None:
    chiave = os.environ["EXA_API_KEY"]
    visti = {c["url"] for f in (RACCOLTA, SCHEDE) if f.exists()
             for c in _righe_json(f) if c}
    speso = 0.0
    with RACCOLTA.open("a") as f:
        for i, q in enumerate(QUERY, 1):
            if speso >= EXA_TETTO_USD:
                log(f"TETTO Exa raggiunto ({speso:.2f} USD): fermo a {i-1}/{len(QUERY)}")
                break
            try:
                d = _exa(q, chiave, caratteri=5000)
            except Exception as e:  # noqa: BLE001
                log(f"  query KO ({type(e).__name__}): {q[:50]}")
                continue
            speso += (d.get("costDollars") or {}).get("total", 0) or 0
            n = 0
            for res in d.get("results", []):
                u = normalizza_linkedin(res.get("url"))
                if not u or u in visti:
                    continue
                visti.add(u)
                n += 1
                f.write(json.dumps({"url": u, "nome": res.get("title") or "",
                                    "testo": (res.get("text") or "")[:5000],
                                    "query": q, "trovato_il": oggi()},
                                   ensure_ascii=False) + "\n")
            log(f"  {n:>2} nuovi  {q}")
    log(f"RACCOLTA: Exa {speso:.3f} USD")


def in_coda() -> list[dict]:
    """Profili da valutare: ruolo e zona nominati nel testo (filtro largo:
    "Roma" esce anche da un'universita' romana, decide poi il modello)."""
    fatte = {c["url"] for c in _righe_json(SCHEDE) if c} if SCHEDE.exists() else set()
    return [c for c in _righe_json(RACCOLTA) if c and c["url"] not in fatte
            and RE_RUOLO.search(c["testo"]) and RE_ZONA.search(c["testo"])
            and len(c["testo"]) > 300]


def classifica(quante: int, log=print) -> None:
    import classify
    import config
    import costi
    import main as ciclo
    from anthropic import Anthropic

    coda = in_coda()
    log(f"in coda: {len(coda)} — questa tranche: {min(quante, len(coda))}")
    criteri = "\n".join(f"{i}. {n}: {r}" for i, (n, r) in enumerate(CRITERI, 1))
    client = Anthropic(max_retries=1)
    tot = costi.nuovo_ciclo()
    serie, corretti, tenute, scartate = ("", 0), 0, 0, 0
    valutate = set()
    with SCHEDE.open("a") as f:
        for c in coda[:quante]:
            if costi.costo_anthropic(tot["token_input"], tot["token_output"]) >= ANTHROPIC_TETTO_EUR:
                log("TETTO Anthropic raggiunto: tranche fermata")
                break
            try:
                r = client.messages.create(
                    model=config.MODELLO, max_tokens=3000, temperature=0,
                    timeout=config.TIMEOUT_ANTHROPIC_S,
                    messages=[{"role": "user", "content": PROMPT.format(
                        criteri=criteri, max_corpo=MAX_CORPO - 60,
                        intestazione=c["nome"], testo=c["testo"])}])
                costi.registra_analisi(tot, r.usage.input_tokens, r.usage.output_tokens)
                d = classify.estrai_json(next(b.text for b in r.content if b.type == "text"))
                d.update(url=c["url"], nome=c["nome"], query=c["query"],
                         trovato_il=c.get("trovato_il") or oggi())
                corretti += controlla(d, c["testo"])
                serie = ciclo.aggiorna_serie(serie, "")
            except Exception as e:  # noqa: BLE001
                serie = ciclo.aggiorna_serie(serie, type(e).__name__)
                log(f"  KO: {type(e).__name__}")
                if serie[1] >= ciclo.MAX_ERRORI_ANALISI:
                    log("SALVAVITA: errori uguali di fila, tranche interrotta")
                    break
                continue
            valutate.add(c["url"])
            if entra(d):
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
                tenute += 1
            else:
                scartate += 1
    log(f"tenute {tenute}, non entrano {scartate}; esiti riportati a da_verificare: {corretti}")
    sfoltisci(valutate, log)
    costi.stampa(tot, log=log)


def sfoltisci(valutate: set, log=print) -> None:
    """Nella raccolta resta SOLO la coda ancora da valutare: i testi di chi
    e' stato valutato (o non e' nemmeno candidabile) si cancellano subito.
    Gli scartati vanno tolti per url: non stando in SCHEDE, in_coda() da
    sola li riterrebbe ancora da valutare (6/10: 85 rimasti in cache)."""
    resta = [c for c in in_coda() if c["url"] not in valutate]
    prima = sum(1 for c in _righe_json(RACCOLTA) if c)
    _riscrivi(RACCOLTA, resta)
    log(f"raccolta: tolti {prima - len(resta)} testi, ne restano {len(resta)} da valutare")


def record(s: dict) -> dict:
    nomi = dict(enumerate((n for n, _ in CRITERI), 1))
    criteri = [{"n": c.get("n"), "criterio": nomi.get(c.get("n")),
                "esito": c.get("esito"), "evidenza": c.get("evidenza")}
               for c in sorted(s.get("criteri") or [], key=lambda c: c.get("n") or 0)]
    return {
        "nome": s.get("nome_proprio"), "cognome": s.get("cognome"),
        "linkedin_url": s["url"], "localita": s.get("localita"),
        "sintesi": s.get("sintesi"), "criteri": criteri,
        "criteri_verificati": verificati(s), "requisiti_base": base(s),
        "aziende_segnalate": s.get("aziende_segnalate") or None,
        "nota_disponibilita": s.get("disponibilita"),
        "bozza_messaggio": messaggio(s), "trovato_il": s.get("trovato_il") or oggi(),
    }


def scrivi(log=print) -> None:
    """Insert puro (linkedin_url unico fa da dedup). Le schede scritte
    escono dalla cache: da li' in poi vale solo la tabella."""
    import db
    sb = db.client()
    restano, inserite, doppie, errori = [], 0, 0, 0
    for s in _righe_json(SCHEDE):
        if not s:
            continue
        try:
            sb.table("candidati").insert(record(s)).execute()
            inserite += 1
        except Exception as e:  # noqa: BLE001
            if "23505" in str(e) or "duplicate key" in str(e):
                doppie += 1
            else:
                errori += 1
                restano.append(s)
                if errori <= 3:
                    log(f"  errore: {str(e)[:160]}")
    _riscrivi(SCHEDE, restano)
    log(f"scrittura: inserite {inserite}, doppie {doppie}, errori {errori} (restano in cache)")


def conservazione(prova: bool, log=print) -> None:
    """Il cron giornaliero. In tabella: chi non e' mai arrivato al colloquio
    e non e' aggiornato da 90 giorni. In cache: le righe trovate da 90."""
    import db
    soglia = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=GIORNI_CONSERVAZIONE)
    sb = db.client()
    q = (lambda t: t.eq("arrivato_colloquio", False).lt("aggiornato_il", soglia.isoformat()))
    if prova:
        tabella = q(sb.table("candidati").select("id", count="exact")).execute().count or 0
    else:
        tabella = len(q(sb.table("candidati").delete()).execute().data or [])
    cache = 0
    for f in (RACCOLTA, SCHEDE):
        if f.exists():
            righe = [r for r in _righe_json(f) if r]
            tenute = [r for r in righe if (r.get("trovato_il") or "") > soglia.date().isoformat()]
            cache += len(righe) - len(tenute)
            if not prova:
                _riscrivi(f, tenute)
    log(f"{dt.datetime.now():%Y-%m-%d %H:%M} conservazione {GIORNI_CONSERVAZIONE} giorni"
        f"{' — PROVA, nessuna cancellazione' if prova else ''}: "
        f"candidati {'da togliere' if prova else 'tolti'} {tabella}, "
        f"righe di cache {'da togliere' if prova else 'tolte'} {cache}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        assert len(CRITERI) == 17 and MAX_CORPO > 250 and len(QUERY) == 24, MAX_CORPO
        testo = ("Mario Rossi - geometra di cantiere presso Ghella. ItC&E SRL. Rome, Latium, Italy. "
                 "Attualmente sono in cerca di occupazione in NaSPI. "
                 "Diploma di geometra, Istituto Tecnico. Lavoro sempre in cantiere.")
        s = {"nome": "Mario ROSSI - Geometra", "nome_proprio": "Mario", "cognome": "Rossini",
             "localita": "Lariano, Latium, Italy", "persona": True, "nel_ruolo": True,
             "sintesi": "Geometra di cantiere da 10 anni. Percepisce la NaSPI.",
             "criteri": [{"n": 2, "esito": "no", "evidenza": "Rome, Latium, Italy"},
                         {"n": 3, "esito": "si", "evidenza": "geometra di  cantiere"},
                         {"n": 4, "esito": "si", "evidenza": "geometra di cantiere"},
                         {"n": 5, "esito": "no", "evidenza": "frase inventata"},
                         {"n": 7, "esito": "si", "evidenza": None},
                         {"n": 13, "esito": "si", "evidenza": "Lavoro sempre in cantiere"}],
             "disponibilita": "Attualmente sono in cerca di occupazione in NaSPI",
             "messaggio": "Buongiorno Mario, ho visto che è in cerca di lavoro."}
        assert controlla(s, testo) == 5
        assert esiti(s) == {2: "da_verificare", 3: "si", 4: "da_verificare", 5: "da_verificare",
                            7: "da_verificare", 13: "da_verificare"}, esiti(s)
        assert s["criteri"][-1]["evidenza"] is None and verificati(s) == 1 and not base(s)
        assert s["disponibilita"] == "Attualmente sono in cerca di occupazione", s["disponibilita"]
        assert s["messaggio"] is None and messaggio(s) is None
        assert RE_SENSIBILE.search("Attualmente in mobilità.") and not RE_SENSIBILE.search("Disponibile a trasferte")
        assert s["sintesi"] == "Geometra di cantiere da 10 anni."
        assert s["aziende_segnalate"] == ["Ghella"], s["aziende_segnalate"]
        assert (s["nome_proprio"], s["cognome"]) == ("Mario", "Rossi"), s["cognome"]
        assert entra(s) and not entra({**s, "criteri": [{"n": 2, "esito": "no"}]})
        ok = {"criteri": [{"n": n, "esito": "si"} for n in BASE]}
        assert sorted([s, ok], key=ordine)[0] is ok
        assert record({**s, "url": "u"})["criteri"][0]["criterio"] == "Zona geografica"
        b = {"messaggio": "Buongiorno Ugo, ho visto i suoi cantieri.", "criteri": []}
        assert controlla(b, "x") == 0 and messaggio(b).endswith("rispondendo a questo messaggio.")
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            RACCOLTA, SCHEDE = pathlib.Path(t, "r.jsonl"), pathlib.Path(t, "s.jsonl")
            riga = {"testo": "geometra di cantiere a Roma " * 20, "nome": "", "query": ""}
            _riscrivi(RACCOLTA, [{**riga, "url": u} for u in "abcd"])
            _riscrivi(SCHEDE, [{"url": "a"}])
            sfoltisci({"a", "b"}, log=lambda *_: None)
            assert [c["url"] for c in _righe_json(RACCOLTA)] == ["c", "d"]
        print("ok")
        sys.exit(0)

    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).parent / ".env")
    CARTELLA.mkdir(parents=True, exist_ok=True)
    # UN SOLO processo per volta (lezione del 29/9 sugli agenti)
    import fcntl
    _lucchetto = LUCCHETTO.open("w")
    try:
        fcntl.flock(_lucchetto, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("ESITO: un altro candidati_ricerca e' gia' in esecuzione — esco")
        sys.exit(1)
    if "--raccogli" in sys.argv:
        raccogli()
    if "--classifica" in sys.argv:
        classifica(int(sys.argv[sys.argv.index("--classifica") + 1]))
    if "--scrivi" in sys.argv:
        scrivi()
    if "--conservazione" in sys.argv:
        conservazione(prova="--prova" in sys.argv)
