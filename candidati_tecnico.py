"""Ricerca C del preventivo PREV-2026-06 (5/11): TECNICO-COMMERCIALE per
strutture edili (case in legno e acciaio, sistemi a secco), Roma e Lazio.
Stesso impianto e stessa tabella della selezione del geometra
(candidati_ricerca.py: regole di controllo, privacy e conservazione sono le
stesse); i profili entrano con posizione = 'tecnico_commerciale'.

    python candidati_tecnico.py --giro --tetto-eur 30 [--entro ISO]
    python candidati_tecnico.py --resoconto
    python candidati_tecnico.py --test

Due ricerche, in quest'ordine:
1. persone delle 30 aziende del file del committente (data/aziende_personale),
   per fascia di priorita', con i nomi alternativi delle Note;
2. per ruolo e zona, senza azienda.
Un giro alla volta (lucchetto dell'archivio), tetto unico Exa + Anthropic su
file, ora limite: si ferma pulito e riparte da dove era arrivato.
Nei log e nei file che restano solo numeri e nomi di aziende: i testi dei
profili si cancellano appena valutati, a fine giro la cache resta senza nomi.
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
import re
import sys

from agenti_ricerca import _exa, _righe_json, normalizza_linkedin
from candidati_ricerca import (CHIUSURA, MAX_CORPO, RE_ZONA, Posizione, _riscrivi, base,
                               controlla, entra, oggi, record)
from data.aziende_personale import AZIENDE, FASCE

CARTELLA = pathlib.Path(os.environ.get("CANDIDATI_TECNICO_CARTELLA")
                        or pathlib.Path(__file__).parent / "cache" / "candidati_tecnico")
RACCOLTA, FATTI, QUERY_FATTE, ESITI, SPESA, ERRORI = (
    CARTELLA / n for n in ("raccolta.jsonl", "fatti.jsonl", "query_fatte.jsonl",
                           "esiti.jsonl", "spesa.json", "schede_errori.jsonl"))
CARATTERI = 5000
SOLO_ZONA = "solo ruolo e zona"

CRITERI = (
    ("Disponibilità a nuove opportunità", "Solo se il profilo la dichiara (es. «Open to work»): nota, non filtro."),
    ("Zona geografica", "Roma, provincia di Roma e Lazio."),
    ("Ruolo", "Attuale o passato: tecnico-commerciale, commerciale tecnico, area manager, sales engineer, consulente tecnico, account per imprese e progettisti."),
    ("Formazione tecnica", "Geometra o CAT, perito, laurea in ingegneria o architettura."),
    ("Settore", "Case e strutture in legno o acciaio (anche LSF), sistemi a secco, materiali edili."),
    ("Aziende precedenti", "Produttori o distributori del settore."),
    ("Esperienza commerciale tecnica", "Almeno 3 anni, sommando le date dei ruoli."),
    ("Clienti seguiti", "Imprese edili, studi tecnici, progettisti, general contractor."),
    ("Progetti e capitolati", "Lettura di progetti e capitolati, preventivazione tecnica."),
    ("Consulenza pre-vendita", "Consulenza pre-vendita e supporto alla progettazione."),
    ("Portafoglio clienti", "Sviluppo e gestione del portafoglio clienti sul territorio."),
    ("Strumenti", "CAD, software di calcolo o di preventivazione, CRM."),
    ("Trasferte nel Lazio", "Si chiarisce al colloquio."),
    ("Tipo di rapporto", "Dipendente, partita IVA o agente: si chiarisce al colloquio."),
    ("Competenze in più", "Normative edilizie, efficienza energetica, protezione al fuoco."),
)
POS = Posizione("tecnico_commerciale", CRITERI, frozenset({13, 14}), (2, 3, 7),
                {n: a["regex"] for n, a in AZIENDE.items()})

ZONE = ("Roma", "Latina", "Frosinone", "Viterbo", "Rieti", "Lazio")
RUOLI = ("tecnico commerciale edilizia", "commerciale tecnico case in legno",
         "commerciale tecnico strutture in acciaio LSF", "area manager materiali edili",
         "sales engineer edilizia", "consulente tecnico sistemi a secco",
         "account manager per imprese e progettisti edilizia")

# filtro largo prima della chiamata (decide poi il modello)
RE_RUOLO = re.compile(r"commercial|sales|vendit|area manager|account|consulen|business develop|"
                      r"pre-?vendit|pre-?sales|agente", re.I)
RE_LAZIO = re.compile(RE_ZONA.pattern + r"|Lazio|Latium|Latina|Frosinone|Viterbo|Rieti|Aprilia|"
                      r"Cisterna|Terracina|Fondi|Formia|Gaeta|Cassino|Sora|Anagni|Alatri|Ceprano|"
                      r"Ferentino|Civita Castellana|Vetralla|Tarquinia|Montefiascone|Fara in Sabina", re.I)

PROMPT = """Valuti un profilo professionale pubblico per Carpenterie Laziali (produttore di persiane, grate, inferriate, cancelli e recinzioni in acciaio, con montaggi; sede a Guidonia Montecelio, Roma). Cerca un TECNICO-COMMERCIALE per strutture edili (case in legno e acciaio, sistemi a secco), su Roma e Lazio.

CRITERI (n. nome: requisito):
{criteri}

REGOLE:
- Per ogni criterio: esito "si", "no" o "da_verificare", con "evidenza" = una frase COPIATA ALLA LETTERA dal profilo (anche parziale, stessa ortografia) oppure null.
- "si" solo con l'evidenza. "no" solo se una frase del profilo dimostra il CONTRARIO (anche essa come evidenza). Un criterio che il profilo non puo' dimostrare e' "da_verificare", MAI "no".
- Criterio 1: "si" solo se il profilo DICHIARA di cercare lavoro o di essere aperto a nuove opportunita' (es. "Open to work"); altrimenti "da_verificare".
- Criterio 2: "si" se la localita' del profilo o del ruolo attuale e' nel Lazio (Roma, la sua provincia o un altro comune del Lazio; anche "Rome, Latium, Italy", "Greater Rome Metropolitan Area"), con quella frase come evidenza; "no" se e' fuori dal Lazio.
- Criterio 4: "si" solo se il profilo SCRIVE il diploma o la laurea (istituto, corso, titolo di studio).
- Criterio 7: somma le date dei ruoli commerciali tecnici. NON usare mai gli anni di studio.
- Criteri 13 e 14: sempre "da_verificare" (si chiariscono al colloquio).
- SOLO dati professionali: ruoli, aziende, date, formazione, competenze dichiarate, localita'. Mai eta' (nemmeno dedotta), foto, salute, famiglia, opinioni o altro di personale, in nessun campo.
- "disponibilita" e le evidenze: mai sussidi (NaSPI, cassa integrazione, disoccupazione), motivi personali, salute o famiglia. Della frase sulla disponibilita' copia SOLO la parte che dice che la persona e' disponibile.

NOME: dall'intestazione separa nome e cognome della persona (cognomi composti interi, ordine rovesciato riconosciuto, niente titoli o ruoli), usando SOLO parole dell'intestazione, in forma leggibile (Rossi, non ROSSI).

MESSAGGIO: il primo messaggio di contatto, in italiano, dando del Lei, scritto in prima persona da chi seleziona per Carpenterie Laziali (senza firmare ne' nominare il mittente). Inizia con "Buongiorno" seguito dal nome di battesimo. Parla SOLO dell'esperienza: personalizzalo su UN'esperienza concreta del profilo e spiega in breve la posizione (tecnico-commerciale per strutture edili, su Roma e Lazio). MAI accennare al fatto che la persona cerca lavoro o e' disponibile. Due o tre frasi brevi, MASSIMO {max_corpo} caratteri spazi compresi: e' un limite rigido. Niente saluti finali ne' frasi sulla privacy: la chiusura la aggiungiamo noi.

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
("persona": false per pagine di aziende o gruppi; "nel_ruolo": true solo se un ruolo attuale o precedente e' fra quelli del criterio 3; false se la persona ha avuto SOLO ruoli di cantiere, amministrativi o di magazzino.)"""


def query() -> list[tuple[str | None, str]]:
    """-> (azienda o None, testo). Prima le aziende per fascia, poi ruolo x zona."""
    out = []
    for fascia in FASCE:
        for nome, a in AZIENDE.items():
            if a["fascia"] != fascia:
                continue
            for n in a["nomi"]:
                out.append((nome, f"{a['ruoli'] or 'tecnico commerciale'} {n}"))
                out.append((nome, f"area manager o consulente tecnico {n}"))
    out += [(None, f"{r} {z}") for z in ZONE for r in RUOLI]
    return out


def candidabile(p: dict) -> bool:
    t = p.get("testo") or ""
    return len(t) > 300 and bool(RE_RUOLO.search(t)) and bool(RE_LAZIO.search(t))


def aziende_nel_testo(testo: str) -> list[str]:
    return [n for n, a in AZIENDE.items() if re.search(a["regex"], testo, re.I)]


def fascia_di(aziende: list[str]) -> str:
    fasce = [AZIENDE[a]["fascia"] for a in aziende]
    return next((f for f in FASCE if f in fasce), SOLO_ZONA)


def _aggiungi(f: pathlib.Path, righe: list[dict]) -> None:
    with f.open("a") as h:
        for x in righe:
            h.write(json.dumps(x, ensure_ascii=False) + "\n")


def _leggi(f: pathlib.Path) -> list[dict]:
    return [x for x in _righe_json(f) if x] if f.exists() else []


def raccogli(spesa, entro: str | None, log=print) -> bool:
    """Incrementale: ogni ricerca scrive subito e si segna fatta. -> True se completa."""
    import config
    import crediti
    import lucchetto
    chiave = os.environ["EXA_API_KEY"]
    fatte = {x["q"] for x in _leggi(QUERY_FATTE)}
    visti = {x["url"] for x in _leggi(RACCOLTA)} | {x["url"] for x in _leggi(FATTI)}
    lista = query()
    da_fare = [x for x in lista if x[1] not in fatte]
    log(f"raccolta: {len(lista)} ricerche, gia' fatte {len(lista) - len(da_fare)}")
    for azienda, q in da_fare:
        if spesa.finita() or lucchetto.scaduto(entro):
            log(f"STOP raccolta: {'tetto di spesa' if spesa.finita() else 'ora limite'} ({spesa.eur():.2f} EUR)")
            return False
        try:
            d = _exa(q, chiave, caratteri=CARATTERI)
        except Exception as e:  # noqa: BLE001
            log(f"  ricerca KO ({type(e).__name__}) [{azienda or SOLO_ZONA}]")
            continue
        costo = (d.get("costDollars") or {}).get("total", 0) or 0
        spesa.exa_usd += costo
        crediti.registra_spesa_exa(costo * config.USD_EUR)
        nuovi = []
        for res in d.get("results", []):
            u = normalizza_linkedin(res.get("url"))
            if u and u not in visti:
                visti.add(u)
                nuovi.append({"url": u, "nome": res.get("title") or "", "azienda": azienda,
                              "testo": (res.get("text") or "")[:CARATTERI], "trovato_il": oggi()})
        _aggiungi(RACCOLTA, nuovi)
        _aggiungi(QUERY_FATTE, [{"q": q, "azienda": azienda, "nuovi": len(nuovi), "usd": round(costo, 5)}])
        spesa.salva()
    return True


def archivio(sb) -> set[str]:
    """linkedin_url gia' in `candidati` (solo in memoria, mai su file)."""
    out, i = set(), 0
    while True:
        b = sb.table("candidati").select("linkedin_url").range(i, i + 999).execute().data
        out |= {normalizza_linkedin(r["linkedin_url"]) for r in b if r.get("linkedin_url")}
        if len(b) < 1000:
            return out
        i += 1000


def chiudi_cache(log=print) -> None:
    """Restano solo i testi ancora da valutare (giro fermato prima della fine);
    a giro finito la raccolta e l'elenco dei fatti restano vuoti."""
    fatti = {x["url"] for x in _leggi(FATTI)}
    resta = [p for p in _leggi(RACCOLTA) if p["url"] not in fatti and candidabile(p)]
    _riscrivi(RACCOLTA, resta)
    _riscrivi(FATTI, [])
    log(f"cache: restano {len(resta)} testi da valutare")


def giro(tetto_eur: float, entro: str | None, log=print) -> int:
    import classify
    import config
    import costi
    import db
    import lucchetto
    import main as ciclo
    from agenti_marchi import Spesa
    from anthropic import Anthropic

    h = lucchetto.prendi("candidati_tecnico.py", log)
    if h is None:
        return 1
    CARTELLA.mkdir(parents=True, exist_ok=True)
    spesa = Spesa(SPESA, tetto_eur)
    log(f"C tecnico-commerciale: tetto {tetto_eur:.2f} EUR, gia' spesi {spesa.eur():.2f} EUR, "
        f"ora limite {entro or '-'}")
    completa = raccogli(spesa, entro, log)

    sb = db.client()
    gia = archivio(sb)
    fatti = {x["url"] for x in _leggi(FATTI)}
    coda = [p for p in _leggi(RACCOLTA) if p["url"] not in fatti]
    log(f"analisi: {len(coda)} profili raccolti da vedere, in archivio {len(gia)} candidati")
    criteri = "\n".join(f"{i}. {n}: {r}" for i, (n, r) in enumerate(CRITERI, 1))
    client = Anthropic(max_retries=2)
    tot = costi.nuovo_ciclo()
    conta, serie = collections.Counter(), ("", 0)
    for k, p in enumerate(coda, 1):
        if spesa.finita() or lucchetto.scaduto(entro):
            log(f"STOP analisi: {'tetto di spesa' if spesa.finita() else 'ora limite'} ({spesa.eur():.2f} EUR)")
            completa = False
            break
        if k % 25 == 0:
            log(f"  [{k}/{len(coda)}] {dict(conta)} — {spesa.eur():.2f} EUR")
        aziende = aziende_nel_testo(p["testo"])
        esito = {"azienda_query": p.get("azienda"), "aziende": aziende, "esito": "non_candidabile"}
        if not candidabile(p):
            pass
        elif p["url"] in gia:
            esito["esito"] = "gia_in_archivio"
        else:
            try:
                r = client.messages.create(
                    model=config.MODELLO, max_tokens=3000, temperature=0,
                    timeout=config.TIMEOUT_ANTHROPIC_S,
                    messages=[{"role": "user", "content": PROMPT.format(
                        criteri=criteri, max_corpo=MAX_CORPO - 60,
                        intestazione=p["nome"], testo=p["testo"])}])
                costi.registra_analisi(tot, r.usage.input_tokens, r.usage.output_tokens)
                spesa.anth_ora = costi.costo_anthropic(tot["token_input"], tot["token_output"])
                d = classify.estrai_json(next(b.text for b in r.content if b.type == "text"))
                d.update(url=p["url"], nome=p["nome"], query=p.get("azienda") or SOLO_ZONA,
                         trovato_il=p.get("trovato_il") or oggi())
                controlla(d, p["testo"], POS)
                serie = ciclo.aggiorna_serie(serie, "")
            except Exception as e:  # noqa: BLE001
                serie = ciclo.aggiorna_serie(serie, type(e).__name__)
                log(f"  KO: {type(e).__name__}")
                spesa.salva()
                if serie[1] >= ciclo.MAX_ERRORI_ANALISI:
                    log("SALVAVITA: errori uguali di fila, giro interrotto")
                    completa = False
                    break
                continue
            esito["esito"] = "non_entra"
            if entra(d):
                rec = record(d, POS)
                esito.update(base=base(d, POS), disponibilita=bool(d.get("disponibilita")),
                             bozza=bool(rec["bozza_messaggio"]))
                try:
                    sb.table("candidati").insert(rec).execute()
                    esito["esito"] = "nuovo"
                    gia.add(p["url"])
                except Exception as e:  # noqa: BLE001
                    if "23505" in str(e) or "duplicate key" in str(e):
                        esito["esito"] = "gia_in_archivio"
                    else:
                        esito["esito"] = "errore_scrittura"
                        _aggiungi(ERRORI, [d])      # da riscrivere: si svuota dopo
                        log(f"  errore di scrittura: {type(e).__name__}")
        conta[esito["esito"]] += 1
        spesa.salva()
        _aggiungi(FATTI, [{"url": p["url"]}])
        _aggiungi(ESITI, [esito])
    spesa.salva()
    log(f"ESITI di questa sessione: {dict(conta)}")
    chiudi_cache(log)
    resoconto(log)
    log(f"ESITO: C {'COMPLETO' if completa else 'FERMATO (riparte da dove era arrivato)'}")
    del h
    return 0


def resoconto(log=print) -> dict:
    """Soli numeri, per fascia e per azienda (nome nel testo del profilo)."""
    import config
    es = _leggi(ESITI)
    trovati = [e for e in es if e["esito"] in ("nuovo", "gia_in_archivio")]
    per_az = {n: collections.Counter() for n in AZIENDE}
    per_fascia = {f: collections.Counter() for f in (*FASCE, SOLO_ZONA)}
    for e in trovati:
        for a in e["aziende"]:
            per_az[a][e["esito"]] += 1
        per_fascia[fascia_di(e["aziende"])][e["esito"]] += 1
    q = _leggi(QUERY_FATTE)
    raccolti = collections.Counter()
    for x in q:
        raccolti[x["azienda"] or SOLO_ZONA] += x["nuovi"]
    sp = json.loads(SPESA.read_text()) if SPESA.exists() else {}
    nuovi = [e for e in es if e["esito"] == "nuovo"]
    out = {
        "ricerche": len(q), "profili_raccolti": sum(raccolti.values()), "profili_visti": len(es),
        "esiti": dict(collections.Counter(e["esito"] for e in es)),
        "nuovi": len(nuovi), "nuovi_con_requisiti_base": sum(bool(e.get("base")) for e in nuovi),
        "nuovi_con_disponibilita_dichiarata": sum(bool(e.get("disponibilita")) for e in nuovi),
        "nuovi_con_bozza": sum(bool(e.get("bozza")) for e in nuovi),
        "per_fascia": {f: {"nuovi": c["nuovo"], "gia_in_archivio": c["gia_in_archivio"]}
                       for f, c in per_fascia.items()},
        "per_azienda": {n: {"fascia": AZIENDE[n]["fascia"], "raccolti_dalle_sue_ricerche": raccolti[n],
                            "nuovi": c["nuovo"], "gia_in_archivio": c["gia_in_archivio"]}
                        for n, c in per_az.items()},
        "spesa": {"exa_usd": sp.get("exa_usd", 0), "anthropic_eur": sp.get("anthropic_eur", 0),
                  "totale_eur": round(sp.get("exa_usd", 0) * config.USD_EUR + sp.get("anthropic_eur", 0), 4)},
    }
    (CARTELLA / "resoconto.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    log(f"{'fascia':<34} nuovi arch.")
    for f, c in out["per_fascia"].items():
        log(f"{f:<34} {c['nuovi']:>5} {c['gia_in_archivio']:>5}")
    log(f"{'azienda':<38} racc. nuovi arch.")
    for n, c in out["per_azienda"].items():
        log(f"{n[:38]:<38} {c['raccolti_dalle_sue_ricerche']:>5} {c['nuovi']:>5} {c['gia_in_archivio']:>5}")
    log(f"totali: {json.dumps({k: v for k, v in out.items() if k not in ('per_fascia', 'per_azienda')})}")
    return out


if __name__ == "__main__":
    if "--test" in sys.argv:
        import tempfile
        lq = query()
        assert len(CRITERI) == 15 and len(lq) == len(set(q for _, q in lq)), len(lq)
        assert lq[0][0] in AZIENDE and AZIENDE[lq[0][0]]["fascia"] == FASCE[0]
        assert [AZIENDE[a]["fascia"] for a, _ in lq if a] == sorted(
            (AZIENDE[a]["fascia"] for a, _ in lq if a), key=FASCE.index)
        assert sum(1 for a, _ in lq if a is None) == len(ZONE) * len(RUOLI)
        assert any("BiHolz" in q for _, q in lq) and any("Legnotek" in q for _, q in lq)
        assert aziende_nel_testo("area manager presso Biolam Italia, prima in Kmark") == \
            ["Legnotek / Kmark", "Biolam Italia"]
        assert aziende_nel_testo("Pagano e figli, Aranova (Fiumicino), Martini dry") == []
        assert fascia_di(["Hilti Italia – Roma", "Technowood"]) == "Prima fascia"
        assert fascia_di([]) == SOLO_ZONA
        t = "Tecnico commerciale presso Technowood. Rome, Latium, Italy. " * 10
        assert candidabile({"testo": t}) and not candidabile({"testo": t.replace("Rome, Latium", "Milano")})
        assert not candidabile({"testo": "magazziniere a Roma " * 30})
        s = {"persona": True, "nel_ruolo": True, "nome": "Nome Cognome", "nome_proprio": "Nome", "cognome": "Cognome",
             "localita": "Rome, Latium, Italy", "messaggio": "Buongiorno Nome, ho visto Technowood.",
             "criteri": [{"n": 2, "esito": "si", "evidenza": "Rome, Latium, Italy"},
                         {"n": 3, "esito": "si", "evidenza": "Tecnico commerciale presso Technowood"},
                         {"n": 7, "esito": "si", "evidenza": "Tecnico commerciale"},
                         {"n": 13, "esito": "si", "evidenza": "Rome"},
                         {"n": 16, "esito": "si", "evidenza": "Rome"}]}
        assert controlla(s, t, POS) == 1 and base(s, POS)
        r = record({**s, "url": "u"}, POS)
        assert r["posizione"] == "tecnico_commerciale" and r["aziende_segnalate"] == ["Technowood"]
        assert r["criteri"][1]["criterio"] == "Ruolo" and r["bozza_messaggio"].endswith(CHIUSURA)
        with tempfile.TemporaryDirectory() as d:
            RACCOLTA, FATTI, ESITI, QUERY_FATTE, SPESA, CARTELLA = (
                pathlib.Path(d, n) for n in ("r", "f", "e", "q", "s", "."))
            _riscrivi(RACCOLTA, [{"url": u, "testo": t} for u in "abc"] + [{"url": "d", "testo": "x"}])
            _riscrivi(FATTI, [{"url": "a"}])
            chiudi_cache(log=lambda *_: None)
            assert [x["url"] for x in _leggi(RACCOLTA)] == ["b", "c"] and _leggi(FATTI) == []
            _riscrivi(ESITI, [{"esito": "nuovo", "aziende": ["Technowood"], "base": True},
                              {"esito": "gia_in_archivio", "aziende": []},
                              {"esito": "non_entra", "aziende": ["Hilti Italia – Roma"]}])
            _riscrivi(QUERY_FATTE, [{"q": "x", "azienda": "Technowood", "nuovi": 3, "usd": 0.02}])
            SPESA.write_text(json.dumps({"exa_usd": 1.0, "anthropic_eur": 2.0}))
            o = resoconto(log=lambda *_: None)
            assert o["per_fascia"]["Prima fascia"] == {"nuovi": 1, "gia_in_archivio": 0}
            assert o["per_fascia"][SOLO_ZONA]["gia_in_archivio"] == 1
            assert o["per_azienda"]["Hilti Italia – Roma"]["nuovi"] == 0
            assert o["per_azienda"]["Technowood"]["raccolti_dalle_sue_ricerche"] == 3
            assert o["nuovi_con_requisiti_base"] == 1 and o["spesa"]["totale_eur"] > 2.9
        print("ok")
        sys.exit(0)

    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).parent / ".env")
    if "--resoconto" in sys.argv:
        resoconto()
        sys.exit(0)
    if "--giro" in sys.argv:
        tetto = float(sys.argv[sys.argv.index("--tetto-eur") + 1])
        entro = sys.argv[sys.argv.index("--entro") + 1] if "--entro" in sys.argv else None
        sys.exit(giro(tetto, entro))
    print(f"MISURA: {len(query())} ricerche ({sum(1 for a, _ in query() if a)} per azienda), "
          f"criteri {len(CRITERI)}")
