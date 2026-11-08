"""Marchi dei mandati degli agenti (richiesta del committente, 8/10):
colonna `agenti.mandati_marchi`, PRIORITA' e non filtro. Solo marchi
DICHIARATI dall'agente (profilo) o dal marchio (pagina rete vendita), con
la frase copiata alla lettera e controllata qui; mai dedotti.

    python agenti_marchi.py --marchi Finstral,Internorm,Isolcasa --regioni Lazio,Toscana --misura
    python agenti_marchi.py --marchi ... --regioni ... --cache FILE --scrivi
    python agenti_marchi.py --marchi ... --cache FILE --senza-ricerca --scrivi   # solo la cache
    opzioni: --sagome 1|2, --senza-nazionali, --senza-agenzie (per dividere il giro
    in tranche dentro i tetti; AGENTI_MARCHI_CARTELLA diversa per ogni tranche)
    python agenti_marchi.py --pilota --regioni ... --scrivi --tetto-eur 30 --entro ISO
        # pilota B1 (5/11): le 30 aziende di data/marchi_pilota, lucchetto
        # dell'archivio, tetto unico Exa+Anthropic, ripresa dopo un'interruzione

--cache: profili gia' raccolti (jsonl url/nome/testo) da rivalutare.
Per ogni profilo: gia' in tabella -> solo i marchi (update della colonna,
unione con quelli che c'erano); non in tabella -> classificazione completa
(prompt v4 di agenti_ricerca) + marchi, e se pertinente entra.
Agenzie di rappresentanza dal loro sito (le pagine "rete vendita" dei
marchi non elencano agenti: tolte l'8/10): abbinate con certezza (nome,
regione e provincia/citta' o recapito) -> marchi sulla scheda esistente;
abbinamento solo probabile -> scheda separata con "possibile doppione di
<id>"; nessuno -> scheda separata (fonte sito_agenzia). Nessuna cancellazione; nomi di persone solo nei dati.
I file di lavoro stanno in CARTELLA (fuori da git) e si svuotano a fine giro.
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
import re
import sys
import unicodedata

from agenti_ricerca import (PROMPT_V4, _exa, _righe_json, normalizza_linkedin,
                            record_scheda)
from data.marchi_agenti import CONTESTO, CONTESTO_CARATTERI, MARCHI
from data.marchi_b2 import B2, riservate
from data.marchi_pilota import PILOTA, PROFILI_GRANDE

# le 321 di B2: le 5 con un nome di persona stanno solo sul server
B2_TUTTE = {**B2, **riservate()}
# regole di tutti i marchi noti; il giro usa solo quelli che gli si passano
TUTTI = {**MARCHI, **PILOTA, **B2_TUTTE}

CARTELLA = pathlib.Path(os.environ.get("AGENTI_MARCHI_CARTELLA")
                        or pathlib.Path(__file__).parent / "cache" / "agenti_marchi")
STATI = ("attuale", "passato", "non_chiaro")
SAGOME = ("agente plurimandatario serramenti {m} {r}",
          "agente di commercio {m} finestre {r}")
EXA_TETTO_USD = 1.0
ANTHROPIC_TETTO_EUR = 4.0


def _descrizione(marchi: list[str]) -> str:
    if not marchi:
        return "- (nessun marchio dell'elenco compare nel testo: \"marchi\" resta vuoto)"
    elenco = "\n".join(
        f"- {m}" + (f" (nome: {TUTTI[m]['nome_ricerca']})" if TUTTI[m].get("nome_ricerca") else "")
        + (f" (sito: {TUTTI[m]['dominio']})" if TUTTI[m]["dominio"] else "")
        + (" — CONCORRENTE" if TUTTI[m].get("concorrente") else "")
        + (" — nome generico: vale SOLO se il profilo lo lega a serramenti, finestre, "
           "infissi, porte, grate, persiane o ai loro accessori" if TUTTI[m]["generico"] else "")
        for m in marchi)
    if any(TUTTI[m].get("nome_ricerca") for m in marchi):
        elenco += '\nNella chiave "marchio" scrivi esattamente il primo nome della riga, senza la parentesi.'
    if any(TUTTI[m].get("concorrente") for m in marchi):
        elenco += ("\nECCEZIONE: i marchi segnati CONCORRENTE sono concorrenti del committente: per loro "
                   "NON vale la frase qui sotto sui marchi non concorrenti. Riporta comunque il mandato "
                   "nella chiave marchi, con lo stato giusto (attuale, passato, non_chiaro).")
    return elenco


def presenti(marchi: list[str], testo: str) -> list[str]:
    """I soli marchi il cui nome compare nel testo: al modello si passano
    questi (5/11: con decine di marchi il prompt crescerebbe a ogni chiamata,
    e un marchio che non compare non puo' comunque avere un'evidenza)."""
    t = _norm(testo)
    return [m for m in marchi if re.search(TUTTI[m]["regex"], t)]


REGOLE_MARCHI = """MARCHI DA CERCARE (produttori di serramenti):
{marchi}
Per ogni marchio di questo elenco che il profilo DICHIARA di rappresentare o di aver rappresentato come agente, rappresentante o agenzia (non come dipendente del produttore, non come cliente o installatore):
- "stato": "attuale" se il mandato e' in corso, "passato" se concluso, "non_chiaro" se il profilo non lo dice;
- "evidenza": la frase COPIATA ALLA LETTERA dal profilo che lo dichiara.
Niente deduzioni: un marchio compatibile coi prodotti trattati ma non nominato NON si scrive. Nessun marchio fuori dall'elenco.
I marchi di questo elenco NON sono concorrenti: il committente vuole i loro agenti. Un loro mandato non rende mai agente_di_concorrente=true. Se uno di questi marchi produce anche persiane, grate o inferriate (in acciaio o di sicurezza), metti conflitto stato="da_verificare" con il marchio e il motivo nel dettaglio."""

PROMPT_SOLO_MARCHI = REGOLE_MARCHI + """

PROFILO (testo pubblico):
{testo}

Rispondi SOLO con JSON: {{"marchi": [{{"marchio": "...", "stato": "attuale|passato|non_chiaro", "evidenza": "..."}}]}}"""

def _norm(t: str | None) -> str:
    t = unicodedata.normalize("NFKD", (t or "").replace("’", "'"))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().casefold()


def nel_settore(marchio: str, testo: str) -> bool:
    """Per i marchi dal nome generico: il nome compare vicino a una parola
    dei serramenti, o il testo cita il dominio del marchio."""
    d = TUTTI[marchio]
    if not d["generico"]:
        return True
    t = _norm(testo)
    if d["dominio"] and d["dominio"] in t:
        return True
    return any(re.search(d.get("contesto", CONTESTO), t[max(0, m.start() - CONTESTO_CARATTERI):m.end() + CONTESTO_CARATTERI])
               for m in re.finditer(d["regex"], t))


def controlla(marchi: list, testo: str, ammessi: list[str], fonte: str, url: str) -> list[dict]:
    """Solo marchi dell'elenco, stato valido, evidenza LETTERALE nel testo
    che nomina davvero il marchio, e per i generici il contesto serramenti.
    Il resto si scarta."""
    corpo, buoni = _norm(testo), []
    per_nome = {_norm(m): m for m in ammessi}
    for x in marchi or []:
        m = per_nome.get(_norm(x.get("marchio")))
        ev = (x.get("evidenza") or "").strip()
        if not m or len(_norm(ev)) < 6 or _norm(ev) not in corpo \
                or not re.search(TUTTI[m]["regex"], _norm(ev)) or not nel_settore(m, testo):
            continue
        stato = x.get("stato") if x.get("stato") in STATI else "non_chiaro"
        buoni.append({"marchio": m, "stato": stato, "fonte": fonte, "url": url, "evidenza": ev[:300]})
    return buoni


CONCORRENTI = r"\blfs\b|ecomet|decoral"


def correggi_conflitto(d: dict) -> dict:
    """Un mandato con un marchio della lista non e' un conflitto (8/10): se il
    modello ha segnato concorrente per uno di loro, e il dettaglio non nomina
    un concorrente vero, diventa "da_verificare" e l'agente resta."""
    c = d.get("conflitto") or {}
    dett = _norm(c.get("dettaglio"))
    della_lista = any(re.search(v["regex"], dett) for v in TUTTI.values() if not v.get("concorrente"))
    concorrente = re.search(CONCORRENTI, dett) or any(
        re.search(v["regex"], dett) for v in TUTTI.values() if v.get("concorrente"))
    if della_lista and not concorrente \
            and (d.get("agente_di_concorrente") or c.get("stato") == "attuale"):
        d["agente_di_concorrente"] = False
        d["conflitto"] = {"stato": "da_verificare",
                          "dettaglio": f"marchio della lista del committente: {c.get('dettaglio') or ''}"[:300]}
    return d


RANGO_CONFLITTO = {None: 0, "nessuno": 0, "passato": 1, "da_verificare": 2, "attuale": 3}


def conflitto_da_concorrenti(trovati: list[dict], presente: str | None = None) -> dict:
    """B2, regola del 5/11: un mandato ATTUALE con un concorrente e' un
    conflitto, uno PASSATO resta recuperabile. Si sale e basta: un conflitto
    gia' piu' grave non si tocca. -> i campi da scrivere (o {})."""
    conc = [x for x in trovati if TUTTI[x["marchio"]].get("concorrente")]
    if not conc:
        return {}
    stati = {x["stato"] for x in conc}
    stato = "attuale" if "attuale" in stati else "da_verificare" if "non_chiaro" in stati else "passato"
    if RANGO_CONFLITTO[stato] <= RANGO_CONFLITTO.get(presente, 0):
        return {}
    nomi = ", ".join(sorted({x["marchio"] for x in conc if x["stato"] == {"da_verificare": "non_chiaro"}.get(stato, stato)}))
    campi = {"conflitto_stato": stato, "conflitto_dettaglio": f"mandato {stato} con concorrente: {nomi}"[:300]}
    if stato == "attuale":
        campi["agente_di_concorrente"] = True
    return campi


def prompt_classifica(testo: str, marchi: list[str] | None = None) -> str:
    """Il prompt v4 della ricerca agenti piu' l'estrazione dei marchi, nella
    stessa chiamata (9/10: anche nei giri normali, senza query in piu').
    `marchi` None: i 14 marchi del committente; [] : nessuno (5/11)."""
    marchi = list(MARCHI) if marchi is None else marchi
    prompt = PROMPT_V4.replace('"nota": "max 20 parole"}}', '"nota": "max 20 parole", '
                               '"marchi": [{{"marchio": "...", "stato": "...", "evidenza": "..."}}]}}')
    return (prompt.format(testo=testo) + "\n\n" + REGOLE_MARCHI.format(marchi=_descrizione(marchi))
            + '\nMetti i marchi nella chiave "marchi" dello stesso JSON.')


def marchi_della_scheda(d: dict, testo: str, url: str, marchi: list[str] | None = None) -> list:
    """Dopo la classificazione: marchi controllati (evidenza letterale,
    contesto dei generici) e conflitto corretto. Modifica `d`."""
    correggi_conflitto(d)
    return controlla(d.pop("marchi", None), testo, list(MARCHI) if marchi is None else marchi,
                     "profilo", url)


def unisci(vecchi: list | None, nuovi: list) -> list:
    """Un marchio per fonte: il nuovo aggiorna quello della stessa fonte."""
    tenuti = {(x["marchio"], x["fonte"]): x for x in vecchi or []}
    for x in nuovi:
        tenuti[(x["marchio"], x["fonte"])] = x
    return list(tenuti.values())


def _tel(t) -> str:
    return re.sub(r"\D", "", t or "")[-9:]


def stesso_posto_o_recapito(ag: dict, r: dict) -> bool:
    """Provincia o citta' in comune, oppure lo stesso telefono, email o sito."""
    import config
    zona = _norm(f"{ag.get('zona') or ''} {ag.get('citta') or ''}")
    sigle = {(config.sigla_provincia(x) or "").upper() for x in re.split(r"[,;/]| e ", zona) if x.strip()}
    prov_r = {str(p).upper() for p in r.get("province_coperte") or []}
    if sigle & prov_r:
        return True
    citta_r = _norm(r.get("residenza")).split(",")[0].strip()
    if citta_r and len(citta_r) > 2 and citta_r in zona:
        return True
    if _tel(ag.get("telefono")) and _tel(ag.get("telefono")) == _tel(r.get("telefono")):
        return True
    if (ag.get("email") or "").strip() and _norm(ag.get("email")) == _norm(r.get("email")):
        return True
    return False


def abbinamento(nome: str, regione: str, righe: list[dict], ag: dict | None = None) -> tuple[str, dict | None]:
    """Agente dal sito di un marchio contro la tabella. -> ("certo"|"possibile"
    |"nessuno", riga). Certo: stesso nome completo, stessa regione E (8/10,
    i nomi comuni) provincia/citta' o un recapito in comune. Possibile: stesso
    nome senza quella conferma, o stesso cognome e stessa iniziale."""
    n = _norm(nome)
    parole = n.split()
    for r in righe:
        if _norm(r.get("nome_completo")) == n and regione and regione == r.get("regione_prevalente") \
                and stesso_posto_o_recapito(ag or {}, r):
            return "certo", r
    for r in righe:
        rn = _norm(r.get("nome_completo"))
        if rn == n:
            return "possibile", r
        rp = rn.split()
        if len(parole) >= 2 and len(rp) >= 2 and parole[-1] == rp[-1] and parole[0][:1] == rp[0][:1]:
            return "possibile", r
    return "nessuno", None


def _chiama(client, prompt: str, tot: dict, max_tokens: int = 900) -> dict:
    import classify
    import config
    import costi
    r = client.messages.create(model=config.MODELLO, max_tokens=max_tokens, temperature=0,
                               timeout=config.TIMEOUT_ANTHROPIC_S,
                               messages=[{"role": "user", "content": prompt}])
    costi.registra_analisi(tot, r.usage.input_tokens, r.usage.output_tokens)
    return classify.estrai_json(next(b.text for b in r.content if b.type == "text"))


def raccogli(marchi: list[str], regioni: list[str], visti: set, log=print,
             sagome: int = 2, nazionali: bool = True,
             gia_fatte: tuple = ()) -> tuple[list[dict], float]:
    chiave = os.environ["EXA_API_KEY"]
    query = [s.format(m=m, r=r) for m in marchi if m not in gia_fatte
             for r in regioni for s in SAGOME[:sagome]]
    if nazionali:
        query += [f"agente o rappresentante {m} serramenti Italia" for m in marchi]
    nuovi, speso = [], 0.0
    for q in query:
        if speso >= EXA_TETTO_USD:
            log(f"TETTO Exa ({speso:.2f} USD): fermo")
            break
        try:
            d = _exa(q, chiave)
        except Exception as e:  # noqa: BLE001
            log(f"  query KO ({type(e).__name__})")
            continue
        speso += (d.get("costDollars") or {}).get("total", 0) or 0
        for res in d.get("results", []):
            u = normalizza_linkedin(res.get("url"))
            if u and u not in visti:
                visti.add(u)
                nuovi.append({"url": u, "nome": res.get("title") or "",
                              "testo": (res.get("text") or "")[:2500], "query": q})
    log(f"raccolta: {len(query)} query, {len(nuovi)} profili nuovi, Exa {speso:.3f} USD")
    import config, crediti
    crediti.registra_spesa_exa(speso * config.USD_EUR)
    return nuovi, speso


PROMPT_AGENZIA = """Pagina web pubblica. Rispondi se e' il sito di un'AGENZIA DI RAPPRESENTANZA o di un agente di commercio (chi rappresenta produttori e vende per loro ai rivenditori o alle imprese) — NON un produttore, NON un rivenditore o showroom che vende al cliente finale, NON un ente o un'associazione (es. un'agenzia di certificazione).
Se lo e': il nome dell'agenzia, la zona coperta, le province (sigle) se scritte, telefono ed email se ci sono, le aziende rappresentate come scritte nella pagina.
""" + REGOLE_MARCHI + """

PAGINA ({url}):
{testo}

Rispondi SOLO con JSON: {{"agenzia": true|false, "nome": "...", "zona": "...", "province": [], "telefono": "...", "email": "...", "rappresentate": [], "marchi": [{{"marchio": "...", "stato": "attuale|passato|non_chiaro", "evidenza": "..."}}]}}"""

SAGOME_AGENZIE = ("agenzia di rappresentanza serramenti aziende rappresentate {m}",
                  "rappresentanze infissi e porte marchi rappresentati {m}")


def pagine_agenzie(marchi: list[str], log=print) -> tuple[list[dict], float]:
    """Siti di agenzie di rappresentanza che nominano un nostro marchio
    (ricerca web Exa, non people). Fuori LinkedIn e i siti dei marchi."""
    import urllib.request
    chiave, viste, pagine, speso = os.environ["EXA_API_KEY"], set(), [], 0.0
    domini_marchi = [d["dominio"] for d in MARCHI.values() if d["dominio"]]
    for q in [s.format(m=m) for m in marchi for s in SAGOME_AGENZIE]:
        req = urllib.request.Request(
            "https://api.exa.ai/search",
            data=json.dumps({"query": q, "type": "auto", "numResults": 10,
                             "contents": {"text": {"maxCharacters": 6000}}}).encode(),
            headers={"content-type": "application/json", "x-api-key": chiave})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.load(r)
        except Exception as e:  # noqa: BLE001
            log(f"  agenzie KO ({type(e).__name__})")
            continue
        speso += (d.get("costDollars") or {}).get("total", 0) or 0
        for res in d.get("results", []):
            u, t = res.get("url") or "", res.get("text") or ""
            dom = re.sub(r"^https?://(www\.)?", "", u).split("/")[0].lower()
            if not dom or dom in viste or "linkedin.com" in dom or any(x in dom for x in domini_marchi):
                continue
            if re.search(r"rappresentanz|agenzia|mandant|aziende rappresentate|plurimandat", t, re.I) \
                    and any(re.search(MARCHI[m]["regex"], _norm(t)) and nel_settore(m, t) for m in marchi):
                viste.add(dom)
                pagine.append({"url": u, "dominio": dom, "testo": t})
    log(f"siti di agenzie candidati: {len(pagine)} — Exa {speso:.3f} USD")
    import config, crediti
    crediti.registra_spesa_exa(speso * config.USD_EUR)
    return pagine, speso


def scheda_agenzia(d: dict, url: str, marchi_trovati: list) -> dict:
    """Riga di `agenti` per un'agenzia trovata dal suo sito."""
    import config
    prov = [p for p in ((config.sigla_provincia(x) or "").upper() for x in d.get("province") or [])
            if len(p) == 2]
    return {"nome_completo": d.get("nome"), "ragione_sociale": d.get("nome"),
            "classificazione": "da_valutare", "conflitto_stato": "da_verificare",
            "agente_di_concorrente": False, "zona_da_confermare": not prov,
            "province_coperte": prov or None, "residenza": d.get("zona"),
            "telefono": (d.get("telefono") or None), "email": (d.get("email") or None),
            "mandati_attuali": d.get("rappresentate") or None, "fonte": "sito_agenzia",
            "note": f"agenzia di rappresentanza dal suo sito: {url}",
            "mandati_marchi": marchi_trovati or None}


def giro(marchi: list[str], regioni: list[str], cache: str, scrivi: bool, log=print,
         senza_ricerca: bool = False, sagome: int = 2, nazionali: bool = True,
         agenzie: bool = True, gia_fatte: tuple = ()) -> None:
    import config
    import costi
    import db
    from agenti_ricerca import _regione_di, completa_nomi
    from anthropic import Anthropic

    CARTELLA.mkdir(parents=True, exist_ok=True)
    sb = db.client()
    righe, i = [], 0
    while True:
        b = (sb.table("agenti").select("id,nome_completo,linkedin_url,regione_prevalente,mandati_marchi,"
                                       "province_coperte,residenza,telefono,email")
             .range(i, i + 999).execute().data)
        righe += b
        if len(b) < 1000:
            break
        i += 1000
    per_url = {normalizza_linkedin(r["linkedin_url"]): r for r in righe if r.get("linkedin_url")}
    profili = [p for p in _righe_json(pathlib.Path(cache))] if cache else []
    profili = [p for p in profili if p and any(re.search(MARCHI[m]["regex"], _norm(p.get("testo")))
                                                for m in marchi)]
    visti = set(per_url) | {normalizza_linkedin(p["url"]) for p in profili}
    cerca = scrivi and not senza_ricerca
    # raccolta e pagine su file: una ripartenza non ripaga Exa (8/10, la
    # prova si e' bloccata a meta' e la raccolta stava solo in memoria)
    f_racc, f_pag, f_fatti = (CARTELLA / "raccolta.jsonl", CARTELLA / "pagine.jsonl",
                              CARTELLA / "fatti.jsonl")
    if cerca and f_racc.exists():
        nuovi, speso_exa = [x for x in _righe_json(f_racc) if x], 0.0
        pagine, speso_p = [x for x in _righe_json(f_pag) if x] if f_pag.exists() else [], 0.0
        log(f"raccolta ripresa da {f_racc.name}: {len(nuovi)} profili, {len(pagine)} pagine")
    else:
        nuovi, speso_exa = (raccogli(marchi, regioni, visti, log, sagome, nazionali, gia_fatte)
                            if cerca and (regioni or nazionali) else ([], 0.0))
        pagine, speso_p = pagine_agenzie(marchi, log) if cerca and agenzie else ([], 0.0)
        if cerca:
            f_racc.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in nuovi))
            f_pag.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in pagine))
    fatti = {x["url"] for x in _righe_json(f_fatti) if x} if f_fatti.exists() else set()
    tutti = profili + nuovi
    in_tab = sum(normalizza_linkedin(p["url"]) in per_url for p in tutti)
    log(f"profili da valutare: {len(tutti)} (in tabella {in_tab}, da classificare {len(tutti) - in_tab})")
    if not scrivi:
        n_q = len(marchi) * len(regioni) * len(SAGOME) + len(marchi)
        log(f"MISURA: {n_q} query Exa (~{n_q * 0.017:.2f} USD), poi ~{n_q * 20 // 2} profili nuovi stimati")
        return

    tot = costi.nuovo_ciclo()
    client = Anthropic(max_retries=1)
    descr = _descrizione(marchi)
    esiti = collections.Counter()
    per_marchio, per_stato = collections.Counter(), collections.Counter()
    for k, p in enumerate(tutti, 1):
        if costi.costo_anthropic(tot["token_input"], tot["token_output"]) >= ANTHROPIC_TETTO_EUR:
            log("TETTO Anthropic: fermo")
            break
        u = normalizza_linkedin(p["url"])
        if u in fatti:
            continue
        if k % 10 == 0:
            log(f"  [{k}/{len(tutti)}] {dict(esiti)}")
        with f_fatti.open("a") as f:
            f.write(json.dumps({"url": u}) + "\n")
        try:
            if u in per_url:
                d = _chiama(client, PROMPT_SOLO_MARCHI.format(marchi=descr, testo=p["testo"]), tot, 500)
                trovati = controlla(d.get("marchi"), p["testo"], marchi, "profilo", u)
                if trovati:
                    r = per_url[u]
                    sb.table("agenti").update({"mandati_marchi": unisci(r.get("mandati_marchi"), trovati)}
                                              ).eq("id", r["id"]).execute()
                    esiti["esistenti con marchi"] += 1
            else:
                d = _chiama(client, prompt_classifica(p["testo"], marchi), tot, 900)
                trovati = marchi_della_scheda(d, p["testo"], u, marchi)
                if d.get("pertinente") not in ("si", "da_valutare"):
                    esiti["non pertinenti"] += 1
                    continue
                rec = record_scheda({**d, "url": u, "nome": p["nome"], "query": p.get("query", "")})
                rec["mandati_marchi"] = trovati or None
                sb.table("agenti").insert(rec).execute()
                esiti["agenti nuovi"] += 1
                esiti["agenti nuovi con marchi"] += bool(trovati)
            for x in trovati:
                per_marchio[x["marchio"]] += 1
                per_stato[x["stato"]] += 1
        except Exception as e:  # noqa: BLE001
            esiti["errori"] += 1
            if "23505" in str(e) or "duplicate key" in str(e):
                esiti["gia' presenti (dedup)"] += 1
            else:
                log(f"  errore: {type(e).__name__}: {str(e)[:120]}")

    for pg in pagine:
        if pg["url"] in fatti:
            continue
        with f_fatti.open("a") as f:
            f.write(json.dumps({"url": pg["url"]}) + "\n")
        try:
            d = _chiama(client, PROMPT_AGENZIA.format(marchi=descr, url=pg["url"],
                                                      testo=pg["testo"][:6000]), tot, 1200)
        except Exception as e:  # noqa: BLE001
            log(f"  agenzia {pg['dominio']}: {type(e).__name__}")
            continue
        if not d.get("agenzia") or not (d.get("nome") or "").strip():
            esiti["siti non di agenzie"] += 1
            continue
        trovati = controlla(d.get("marchi"), pg["testo"], marchi, "sito_agenzia", pg["url"])
        if not trovati:
            esiti["agenzie senza marchi dichiarati"] += 1
            continue
        regione = _regione_di({"province_coperte": d.get("province") or [], "residenza": d.get("zona") or ""})
        regione = regione if regione in config.REGIONI else ""
        tipo, r = abbinamento(d["nome"], regione, righe, {"zona": d.get("zona"), "telefono": d.get("telefono"),
                                                          "email": d.get("email")})
        if tipo == "certo":
            sb.table("agenti").update({"mandati_marchi": unisci(r.get("mandati_marchi"), trovati)}
                                      ).eq("id", r["id"]).execute()
            esiti["agenzie gia' in tabella, marchi aggiunti"] += 1
        else:
            rec = scheda_agenzia(d, pg["url"], trovati)
            rec["regione_prevalente"] = regione or None
            if r:
                rec["note"] += f"; possibile doppione di {r['id']} ({r['nome_completo']})"
            sb.table("agenti").insert(rec).execute()
            esiti["agenzie nuove"] += 1
            esiti["possibili doppioni"] += bool(r)
        for x in trovati:
            per_marchio[x["marchio"]] += 1
            per_stato[x["stato"]] += 1

    if esiti["agenti nuovi"] or esiti["agenzie nuove"]:
        completa_nomi(log)
    log(f"\nESITI: {dict(esiti)}")
    log(f"per marchio: {dict(per_marchio)}")
    log(f"per stato: {dict(per_stato)}")
    log(f"Exa {speso_exa + speso_p:.3f} USD")
    costi.stampa(tot, log=log)


class Spesa:
    """Spesa del giro su file (Exa + Anthropic in EUR): il tetto vale anche
    dopo una ripresa, non solo dentro un processo."""

    def __init__(self, file: pathlib.Path, tetto_eur: float, tetto_exa_eur: float | None = None,
                 tetto_anthropic_eur: float | None = None):
        self.file, self.tetto = file, tetto_eur
        self.tetto_exa, self.tetto_anth = tetto_exa_eur, tetto_anthropic_eur
        self.fermo = None       # (codice di uscita, motivo): credito o errori, non il tetto
        d = json.loads(file.read_text()) if file.exists() else {}
        self.exa_usd, self.anth_prima = d.get("exa_usd", 0.0), d.get("anthropic_eur", 0.0)
        self.anth_ora = 0.0

    def eur(self) -> float:
        import config
        return self.exa_usd * config.USD_EUR + self.anth_prima + self.anth_ora

    def exa_eur(self) -> float:
        import config
        return self.exa_usd * config.USD_EUR

    def superato(self) -> str | None:
        """Quale tetto e' stato raggiunto, o None."""
        if self.eur() >= self.tetto:
            return f"tetto totale {self.tetto:.2f} EUR"
        if self.tetto_exa is not None and self.exa_eur() >= self.tetto_exa:
            return f"tetto Exa {self.tetto_exa:.2f} EUR"
        if self.tetto_anth is not None and self.anth_prima + self.anth_ora >= self.tetto_anth:
            return f"tetto Anthropic {self.tetto_anth:.2f} EUR"
        return None

    def finita(self) -> bool:
        return self.superato() is not None

    def salva(self) -> None:
        self.file.write_text(json.dumps({"exa_usd": round(self.exa_usd, 6),
                                         "anthropic_eur": round(self.anth_prima + self.anth_ora, 6)}))


def query_pilota(marchi: list[str], regioni: list[str]) -> list[tuple[str, str, str]]:
    """-> (marchio, tipo, query). Come l'8/10: una sagoma per regione, la
    nazionale e due ricerche di agenzie; le grandi solo la nazionale."""
    out = []
    for m in marchi:
        nome = TUTTI[m].get("nome_ricerca") or m
        if not TUTTI[m].get("grande"):
            out += [(m, "persone", SAGOME[0].format(m=nome, r=r)) for r in regioni]
        out.append((m, "persone", f"agente o rappresentante {nome} serramenti Italia"))
        if not TUTTI[m].get("grande"):
            out += [(m, "agenzie", s.format(m=nome)) for s in SAGOME_AGENZIE]
    return out


def _exa_web(q: str, chiave: str) -> dict:
    import urllib.request
    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=json.dumps({"query": q, "type": "auto", "numResults": 10,
                         "contents": {"text": {"maxCharacters": 6000}}}).encode(),
        headers={"content-type": "application/json", "x-api-key": chiave})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def _aggiungi(f: pathlib.Path, righe: list[dict]) -> None:
    with f.open("a") as h:
        for x in righe:
            h.write(json.dumps(x, ensure_ascii=False) + "\n")


def a_turno(righe: list[dict]) -> list[dict]:
    """Un profilo per azienda a giro: se il tetto ferma l'analisi, nessuna
    azienda resta senza profili valutati (l'ordine e' stabile: ripresa ok)."""
    gruppi = collections.defaultdict(list)
    for x in righe:
        gruppi[x["marchio"]].append(x)
    out, k = [], 0
    while len(out) < len(righe):
        out += [g[k] for g in gruppi.values() if k < len(g)]
        k += 1
    return out


def raccogli_pilota(marchi: list[str], regioni: list[str], visti: set, spesa: Spesa,
                    entro: str | None, log=print) -> bool:
    """Raccolta INCREMENTALE: ogni ricerca scrive subito i risultati e si
    segna fatta; una ripartenza riprende dalla successiva. -> True se completa."""
    import config
    import crediti
    import lucchetto
    chiave = os.environ["EXA_API_KEY"]
    f_racc, f_pag, f_q = CARTELLA / "raccolta.jsonl", CARTELLA / "pagine.jsonl", CARTELLA / "query_fatte.jsonl"
    fatte = {x["q"] for x in _righe_json(f_q) if x} if f_q.exists() else set()
    per_marchio = collections.Counter(x["marchio"] for x in _righe_json(f_racc) if x) \
        if f_racc.exists() else collections.Counter()
    viste_pag = {x["dominio"] for x in _righe_json(f_pag) if x} if f_pag.exists() else set()
    domini_marchi = [d["dominio"] for d in TUTTI.values() if d["dominio"]]
    lista = query_pilota(marchi, regioni)
    da_fare = [x for x in lista if x[2] not in fatte]
    log(f"raccolta: {len(lista)} ricerche, gia' fatte {len(lista) - len(da_fare)}")
    ko_di_fila = 0
    for m, tipo, q in da_fare:
        if spesa.finita() or lucchetto.scaduto(entro):
            log(f"STOP raccolta: {spesa.superato() or 'ora limite'} ({spesa.eur():.2f} EUR)")
            return False
        grande = TUTTI[m].get("grande")
        try:
            d = _exa(q, chiave) if tipo == "persone" else _exa_web(q, chiave)
        except Exception as e:  # noqa: BLE001
            ko_di_fila += 1
            codice = getattr(e, "code", None)
            log(f"  ricerca KO ({type(e).__name__} {codice or ''}) [{m}]")
            if codice in (401, 402, 403):       # credito finito o chiave: non si insiste
                spesa.fermo = (4, f"Exa ha risposto {codice}: credito o chiave")
                return False
            if ko_di_fila >= 10:
                spesa.fermo = (1, "10 ricerche Exa fallite di fila")
                return False
            continue
        ko_di_fila = 0
        costo = (d.get("costDollars") or {}).get("total", 0) or 0
        spesa.exa_usd += costo
        crediti.registra_spesa_exa(costo * config.USD_EUR)
        nuovi = []
        for res in d.get("results", []):
            if tipo == "persone":
                if grande and per_marchio[m] >= PROFILI_GRANDE:
                    break
                u = normalizza_linkedin(res.get("url"))
                if u and u not in visti:
                    visti.add(u)
                    per_marchio[m] += 1
                    nuovi.append({"url": u, "nome": res.get("title") or "",
                                  "testo": (res.get("text") or "")[:2500], "marchio": m})
            else:
                u, t = res.get("url") or "", res.get("text") or ""
                dom = re.sub(r"^https?://(www\.)?", "", u).split("/")[0].lower()
                if not dom or dom in viste_pag or "linkedin.com" in dom \
                        or any(x in dom for x in domini_marchi):
                    continue
                if re.search(r"rappresentanz|agenzia|mandant|aziende rappresentate|plurimandat", t, re.I) \
                        and re.search(TUTTI[m]["regex"], _norm(t)) and nel_settore(m, t):
                    viste_pag.add(dom)
                    nuovi.append({"url": u, "dominio": dom, "testo": t, "marchio": m})
        _aggiungi(f_racc if tipo == "persone" else f_pag, nuovi)
        _aggiungi(f_q, [{"q": q, "marchio": m, "tipo": tipo, "nuovi": len(nuovi),
                         "usd": round(costo, 5)}])
        spesa.salva()
    return True


def pilota(marchi: list[str], regioni: list[str], tetto_eur: float, entro: str | None,
           log=print, tetto_exa_eur: float | None = None, tetto_anthropic_eur: float | None = None,
           etichetta: str = "pilota") -> int:
    """Pilota B1 (5/11). Una sola chiamata per profilo, con i soli marchi
    che compaiono nel testo; esiti per azienda su file (solo numeri)."""
    import config
    import costi
    import db
    import lucchetto
    import main as ciclo
    from agenti_ricerca import _regione_di, completa_nomi
    from anthropic import Anthropic

    if (CARTELLA / "completato").exists():
        log(f"ESITO: {etichetta} gia' completato: niente da fare")
        return 0
    h = lucchetto.prendi("agenti_marchi.py", log)
    if h is None:
        return 1
    CARTELLA.mkdir(parents=True, exist_ok=True)
    spesa = Spesa(CARTELLA / "spesa.json", tetto_eur, tetto_exa_eur, tetto_anthropic_eur)
    log(f"{etichetta}: {len(marchi)} aziende, regioni {', '.join(regioni)}, tetto {tetto_eur:.2f} EUR "
        f"(Exa {tetto_exa_eur}, Anthropic {tetto_anthropic_eur}), gia' spesi {spesa.eur():.2f} EUR")

    def fine(completa: bool) -> int:
        """0 completo, 3 tetto o ora limite, 4 credito o chiave (non si
        ripete da solo), 1 guasto passeggero (riparte)."""
        if spesa.fermo:
            log(f"ESITO: {etichetta} FERMATO — {spesa.fermo[1]}")
            return spesa.fermo[0]
        if completa:
            (CARTELLA / "completato").write_text("1")
            log(f"ESITO: {etichetta} COMPLETO")
            return 0
        log(f"ESITO: {etichetta} FERMATO — {spesa.superato() or 'ora limite'}, si riprende rilanciando")
        return 3
    sb = db.client()
    righe, i = [], 0
    while True:
        b = (sb.table("agenti").select("id,nome_completo,linkedin_url,regione_prevalente,mandati_marchi,"
                                       "province_coperte,residenza,telefono,email,conflitto_stato")
             .range(i, i + 999).execute().data)
        righe += b
        if len(b) < 1000:
            break
        i += 1000
    per_url = {normalizza_linkedin(r["linkedin_url"]): r for r in righe if r.get("linkedin_url")}
    f_racc, f_pag, f_fatti, f_esiti = (CARTELLA / "raccolta.jsonl", CARTELLA / "pagine.jsonl",
                                       CARTELLA / "fatti.jsonl", CARTELLA / "esiti.jsonl")
    # gia' in archivio = in tabella PRIMA del pilota: si fissa alla prima partenza
    f_prima = CARTELLA / "in_archivio_prima.json"
    if not f_prima.exists():
        f_prima.write_text(json.dumps(sorted(per_url)))
    prima = set(json.loads(f_prima.read_text()))
    visti = set()
    if f_racc.exists():
        visti = {x["url"] for x in _righe_json(f_racc) if x}
    # anche gli agenti gia' in tabella si raccolgono: possono avere un mandato
    # con una di queste aziende (solo la chiamata dei marchi, se il nome compare)
    completa = raccogli_pilota(marchi, regioni, visti, spesa, entro, log)
    if spesa.fermo:
        return fine(False)

    fatti = {x["url"] for x in _righe_json(f_fatti) if x} if f_fatti.exists() else set()
    tutti = a_turno([x for x in _righe_json(f_racc) if x] if f_racc.exists() else [])
    pagine = a_turno([x for x in _righe_json(f_pag) if x] if f_pag.exists() else [])
    client = Anthropic(max_retries=2)
    tot = costi.nuovo_ciclo()
    esiti = collections.Counter()
    serie = ("", 0)

    def costo_ora() -> None:
        spesa.anth_ora = costi.costo_anthropic(tot["token_input"], tot["token_output"])
        spesa.salva()

    for k, p in enumerate(tutti, 1):
        u = p["url"]
        if u in fatti:
            continue
        if spesa.finita() or lucchetto.scaduto(entro):
            log(f"STOP analisi: {spesa.superato() or 'ora limite'} ({spesa.eur():.2f} EUR)")
            completa = False
            break
        if k % 20 == 0:
            log(f"  [{k}/{len(tutti)}] {dict(esiti)} — {spesa.eur():.2f} EUR")
        pres = presenti(marchi, p["testo"])
        esito = {"marchio_query": p["marchio"], "marchi": [], "in_archivio": u in prima, "nuovo": False}
        try:
            if u in per_url:
                if pres:
                    d = _chiama(client, PROMPT_SOLO_MARCHI.format(marchi=_descrizione(pres),
                                                                  testo=p["testo"]), tot, 500)
                    trovati = controlla(d.get("marchi"), p["testo"], pres, "profilo", u)
                    if trovati:
                        r = per_url[u]
                        r["mandati_marchi"] = unisci(r.get("mandati_marchi"), trovati)
                        campi = conflitto_da_concorrenti(trovati, r.get("conflitto_stato"))
                        sb.table("agenti").update({"mandati_marchi": r["mandati_marchi"], **campi}
                                                  ).eq("id", r["id"]).execute()
                        esiti["esistenti con marchi"] += 1
                        esiti["conflitti da concorrente aggiornati"] += bool(campi)
                    esito["marchi"] = [{"marchio": x["marchio"], "stato": x["stato"]} for x in trovati]
                else:
                    esiti["esistenti senza marchi nel testo (nessuna chiamata)"] += 1
            else:
                d = _chiama(client, prompt_classifica(p["testo"], pres), tot, 900)
                trovati = marchi_della_scheda(d, p["testo"], u, pres)
                esito["marchi"] = [{"marchio": x["marchio"], "stato": x["stato"]} for x in trovati]
                if d.get("pertinente") not in ("si", "da_valutare"):
                    esiti["non pertinenti"] += 1
                    esito["marchi"] = []       # non entra: non conta come agente trovato
                else:
                    rec = record_scheda({**d, "url": u, "nome": p["nome"], "query": p["marchio"]})
                    rec["mandati_marchi"] = trovati or None
                    rec.update(conflitto_da_concorrenti(trovati, rec.get("conflitto_stato")))
                    sb.table("agenti").insert(rec).execute()
                    esiti["agenti nuovi"] += 1
                    esito["nuovo"] = True
        except Exception as e:  # noqa: BLE001
            if "23505" in str(e) or "duplicate key" in str(e):
                esiti["gia' presenti (dedup)"] += 1
            else:
                esiti["errori"] += 1
                stato_http = getattr(e, "status_code", None)
                log(f"  errore: {type(e).__name__} {stato_http or ''}")     # mai il testo: puo' contenere nomi
                costo_ora()
                # il profilo non si segna fatto: una ripresa lo rifa'
                if stato_http in (401, 403) or "credit balance" in str(e).lower():
                    spesa.fermo = (4, "Anthropic: credito o chiave")
                    completa = False
                    break
                serie = ciclo.aggiorna_serie(serie, type(e).__name__)
                if serie[1] >= ciclo.MAX_ERRORI_ANALISI:
                    spesa.fermo = (1, f"{serie[1]} errori uguali di fila ({serie[0]})")
                    completa = False
                    break
                continue
        serie = ("", 0)
        costo_ora()
        _aggiungi(f_fatti, [{"url": u}])
        _aggiungi(f_esiti, [esito])

    for pg in pagine:
        if spesa.fermo:
            break
        if pg["url"] in fatti:
            continue
        if spesa.finita() or lucchetto.scaduto(entro):
            completa = False
            break
        pres = presenti(marchi, pg["testo"])
        esito = {"marchio_query": pg["marchio"], "marchi": [], "in_archivio": False, "nuovo": False,
                 "agenzia": True}
        try:
            d = _chiama(client, PROMPT_AGENZIA.format(marchi=_descrizione(pres), url=pg["url"],
                                                      testo=pg["testo"][:6000]), tot, 1200)
            trovati = controlla(d.get("marchi"), pg["testo"], pres, "sito_agenzia", pg["url"]) \
                if d.get("agenzia") and (d.get("nome") or "").strip() else []
            if not d.get("agenzia"):
                esiti["siti non di agenzie"] += 1
            elif not trovati:
                esiti["agenzie senza marchi dichiarati"] += 1
            else:
                regione = _regione_di({"province_coperte": d.get("province") or [],
                                       "residenza": d.get("zona") or ""})
                regione = regione if regione in config.REGIONI else ""
                tipo, r = abbinamento(d["nome"], regione, righe,
                                      {"zona": d.get("zona"), "telefono": d.get("telefono"),
                                       "email": d.get("email")})
                esito["marchi"] = [{"marchio": x["marchio"], "stato": x["stato"]} for x in trovati]
                if tipo == "certo":
                    sb.table("agenti").update({"mandati_marchi": unisci(r.get("mandati_marchi"), trovati),
                                               **conflitto_da_concorrenti(trovati, r.get("conflitto_stato"))}
                                              ).eq("id", r["id"]).execute()
                    esiti["agenzie gia' in tabella, marchi aggiunti"] += 1
                    esito["in_archivio"] = True
                else:
                    rec = scheda_agenzia(d, pg["url"], trovati)
                    rec["regione_prevalente"] = regione or None
                    if r:
                        rec["note"] += f"; possibile doppione di {r['id']}"
                    rec.update(conflitto_da_concorrenti(trovati, rec.get("conflitto_stato")))
                    sb.table("agenti").insert(rec).execute()
                    esiti["agenzie nuove"] += 1
                    esiti["possibili doppioni"] += bool(r)
                    esito["nuovo"] = True
        except Exception as e:  # noqa: BLE001
            esiti["errori"] += 1
            log(f"  agenzia: {type(e).__name__}")
        costo_ora()
        _aggiungi(f_fatti, [{"url": pg["url"]}])
        _aggiungi(f_esiti, [esito])

    if esiti["agenti nuovi"] or esiti["agenzie nuove"]:
        completa_nomi(log)
    costo_ora()
    log(f"\nESITI di questa sessione: {dict(esiti)}")
    log(f"spesa del giro: Exa {spesa.exa_usd:.3f} USD, Anthropic {spesa.anth_prima + spesa.anth_ora:.2f} EUR, "
        f"totale {spesa.eur():.2f} EUR su {tetto_eur:.2f}")
    resoconto(marchi, log)
    return fine(completa)


def resoconto(marchi: list[str], log=print) -> dict:
    """Per azienda, solo numeri: profili raccolti dalle sue ricerche e agenti
    (persone o agenzie) con un suo mandato attuale/passato, nuovi o gia' in archivio."""
    f_esiti, f_racc = CARTELLA / "esiti.jsonl", CARTELLA / "raccolta.jsonl"
    esiti = [x for x in _righe_json(f_esiti) if x] if f_esiti.exists() else []
    racc = collections.Counter(x["marchio"] for x in _righe_json(f_racc) if x) \
        if f_racc.exists() else collections.Counter()
    tab = {m: collections.Counter() for m in marchi}
    for e in esiti:
        for x in e["marchi"]:
            if x["marchio"] not in tab:
                continue
            c = tab[x["marchio"]]
            c["agenti"] += 1
            c[x["stato"]] += 1
            c["nuovi" if e["nuovo"] else "gia_in_archivio"] += 1
    out = {"per_azienda": {m: {"profili_raccolti": racc[m], **tab[m]} for m in marchi},
           "profili_valutati": len(esiti),
           "agenti_nuovi_totali": sum(e["nuovo"] for e in esiti),
           "agenti_con_mandato": sum(bool(e["marchi"]) for e in esiti),
           "agenti_con_mandato_nuovi": sum(bool(e["marchi"]) and e["nuovo"] for e in esiti)}
    (CARTELLA / "resoconto.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    log(f"{'azienda':<18}{'racc.':>6}{'agenti':>7}{'att.':>5}{'pass.':>6}{'n.c.':>5}{'nuovi':>6}{'arch.':>6}")
    for m, v in out["per_azienda"].items():
        log(f"{m[:17]:<18}{v['profili_raccolti']:>6}{v.get('agenti', 0):>7}{v.get('attuale', 0):>5}"
            f"{v.get('passato', 0):>6}{v.get('non_chiaro', 0):>5}{v.get('nuovi', 0):>6}"
            f"{v.get('gia_in_archivio', 0):>6}")
    log(f"profili valutati {out['profili_valutati']}, agenti nuovi in tabella {out['agenti_nuovi_totali']}, "
        f"con mandato {out['agenti_con_mandato']} (nuovi {out['agenti_con_mandato_nuovi']})")
    return out


if __name__ == "__main__":
    if "--test" in sys.argv:
        testo = "Agente plurimandatario: mandato FINSTRAL per il Lazio. In passato agente Internorm."
        ok = controlla([{"marchio": "Finstral", "stato": "attuale", "evidenza": "mandato FINSTRAL per il Lazio"},
                        {"marchio": "internorm", "stato": "boh", "evidenza": "In passato agente Internorm"},
                        {"marchio": "Isolcasa", "stato": "attuale", "evidenza": "frase inventata"},
                        {"marchio": "Schuco", "stato": "attuale", "evidenza": "Agente plurimandatario"},
                        {"marchio": "Nurith", "stato": "attuale", "evidenza": "Agente plurimandatario"}],
                       testo, ["Finstral", "Internorm", "Isolcasa", "Nurith"], "profilo", "u")
        assert [(x["marchio"], x["stato"]) for x in ok] == [("Finstral", "attuale"),
                                                           ("Internorm", "non_chiaro")], ok
        u = unisci([{"marchio": "Finstral", "fonte": "profilo", "stato": "passato"}],
                   [{"marchio": "Finstral", "fonte": "profilo", "stato": "attuale"},
                    {"marchio": "Finstral", "fonte": "sito_marchio", "stato": "attuale"}])
        assert len(u) == 2 and {x["stato"] for x in u} == {"attuale"}
        tab = [{"id": "1", "nome_completo": "Ottavio Ferlini", "regione_prevalente": "Lazio"},
               {"id": "2", "nome_completo": "Remo Scalzati", "regione_prevalente": "Toscana"}]
        assert abbinamento("OTTAVIO FERLINI", "Lazio", tab)[0] == "possibile"   # nome comune: non basta
        tab[0].update(province_coperte=["RM", "LT"], telefono="06 1234567")
        assert abbinamento("OTTAVIO FERLINI", "Lazio", tab, {"zona": "Latina"})[0] == "certo"
        assert abbinamento("Ottavio Ferlini", "Lazio", tab, {"zona": "Viterbo", "telefono": "+39 061234567"})[0] == "certo"
        assert abbinamento("Ottavio Ferlini", "Lazio", tab, {"zona": "Viterbo"})[0] == "possibile"
        d = correggi_conflitto({"agente_di_concorrente": True,
                                "conflitto": {"stato": "attuale", "dettaglio": "agente Finstral, fa anche persiane"}})
        assert d["agente_di_concorrente"] is False and d["conflitto"]["stato"] == "da_verificare"
        d = correggi_conflitto({"agente_di_concorrente": True,
                                "conflitto": {"stato": "attuale", "dettaglio": "agente LFS e Finstral"}})
        assert d["agente_di_concorrente"] is True     # un concorrente vero resta tale
        assert abbinamento("Ottavio Ferlini", "Toscana", tab) == ("possibile", tab[0])
        assert abbinamento("R. Scalzati", "Lazio", tab)[0] == "possibile"
        assert abbinamento("Ugo Tamburro", "Lazio", tab) == ("nessuno", None)
        assert "nome generico" in _descrizione(["SPI"]) and "finstral.com" in _descrizione(["Finstral"])
        assert nel_settore("SPI", "Agente plurimandatario: finestre in PVC SPI e porte")
        assert not nel_settore("SPI", "Responsabile SPI (Servizio Prevenzione Infortuni) presso ASL")
        assert nel_settore("Uniform", "mandati: vedi uniform.it")
        assert not nel_settore("Uniform", "Agente divise e uniform per ristoranti")
        assert nel_settore("Internorm", "qualsiasi testo")
        r = scheda_agenzia({"nome": "Rappresentanze Ferlini", "province": ["Roma", "LT"],
                            "rappresentate": ["Internorm"], "telefono": ""}, "https://x.it",
                           [{"marchio": "Internorm"}])
        assert r["province_coperte"] == ["RM", "LT"] and r["fonte"] == "sito_agenzia" \
            and r["telefono"] is None and r["agente_di_concorrente"] is False
        # --- B2: agenti dei concorrenti, tetti per servizio ---
        assert len(B2) == 316 and not set(B2) & (set(PILOTA) | set(MARCHI))
        att = [{"marchio": "Xecur", "stato": "attuale"}]
        pas = [{"marchio": "Xecur", "stato": "passato"}]
        nc = [{"marchio": "Xecur", "stato": "non_chiaro"}]
        no = [{"marchio": "Oknoplast", "stato": "attuale"}]
        assert conflitto_da_concorrenti(att, "nessuno")["agente_di_concorrente"] is True
        assert conflitto_da_concorrenti(att, "nessuno")["conflitto_stato"] == "attuale"
        p_ = conflitto_da_concorrenti(pas, "nessuno")
        assert p_["conflitto_stato"] == "passato" and "agente_di_concorrente" not in p_
        assert conflitto_da_concorrenti(nc, "passato")["conflitto_stato"] == "da_verificare"
        assert conflitto_da_concorrenti(pas, "attuale") == {} and conflitto_da_concorrenti(no) == {}
        assert conflitto_da_concorrenti(att, "attuale") == {}
        assert "CONCORRENTE" in _descrizione(["Xecur"]) and "ECCEZIONE" in _descrizione(["Xecur"])
        assert "CONCORRENTE" not in _descrizione(["Oknoplast"])
        c0 = correggi_conflitto({"agente_di_concorrente": True,
                                 "conflitto": {"stato": "attuale", "dettaglio": "mandato Xecur"}})
        assert c0["agente_di_concorrente"] is True          # un concorrente vero resta conflitto
        c1 = correggi_conflitto({"agente_di_concorrente": True,
                                 "conflitto": {"stato": "attuale", "dettaglio": "mandato Oknoplast"}})
        assert c1["agente_di_concorrente"] is False
        assert query_pilota(["Posa"], ["Lazio"])[0][2] == "agente plurimandatario serramenti Posa S.p.A. serramenti Lazio"
        assert not presenti(["Posa"], "posa in opera di serramenti") and presenti(["Posa"], "agente Posa S.p.A.")
        import tempfile as _t
        with _t.TemporaryDirectory() as tmp:
            sp = Spesa(pathlib.Path(tmp, "s.json"), 100.0, 10.0, 50.0)
            assert sp.superato() is None
            sp.exa_usd = 20.0
            assert "Exa" in sp.superato() and sp.finita()
            sp.exa_usd, sp.anth_ora = 0.0, 50.0
            assert "Anthropic" in sp.superato()
        # --- pilota B1 (5/11) ---
        assert len(PILOTA) == 30 and sum(d["grande"] for d in PILOTA.values()) == 5
        assert not set(PILOTA) & set(MARCHI)
        # al modello solo i marchi che compaiono nel testo
        t = "Agente plurimandatario: porte FerreroLegno e maniglie Colfert. Ex agente Schüco."
        assert presenti(list(PILOTA), t) == ["Schüco", "FerreroLegno", "Colfert"]
        assert presenti(list(PILOTA), "agente di commercio settore alimentare") == []
        p0 = prompt_classifica("testo", [])
        assert "nessun marchio dell'elenco" in p0 and "Finstral" not in p0
        assert "Finstral" in prompt_classifica("testo")          # giri normali: i 14 di sempre
        assert "Colfert" in prompt_classifica("testo", ["Colfert"]) and "Finstral" not in \
            prompt_classifica("testo", ["Colfert"])
        # generici: serve il contesto della filiera
        assert nel_settore("Scrigno", "agente controtelai Scrigno per il Lazio")
        assert not nel_settore("Scrigno", "il mio scrigno di ricordi")
        assert nel_settore("Olivari", "rappresento maniglie Olivari")
        assert not nel_settore("Olivari", "studio legale Olivari")
        ok = controlla([{"marchio": "Colfert", "stato": "attuale", "evidenza": "maniglie Colfert"},
                        {"marchio": "Schüco", "stato": "passato", "evidenza": "Ex agente Schüco"}],
                       t, ["Colfert", "Schüco"], "profilo", "u")
        assert [(x["marchio"], x["stato"]) for x in ok] == [("Colfert", "attuale"), ("Schüco", "passato")]
        # ricerche: le grandi solo la nazionale, le altre regioni + nazionale + 2 agenzie
        q = query_pilota(["Schüco", "Colfert"], ["Lazio", "Toscana"])
        assert [x for x in q if x[0] == "Schüco"] == [("Schüco", "persone",
                                                       "agente o rappresentante Schüco serramenti Italia")]
        assert [x[1] for x in q if x[0] == "Colfert"] == ["persone"] * 3 + ["agenzie"] * 2
        # la spesa resta su file: dopo una ripresa il tetto conta anche il gia' speso
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp, "spesa.json")
            sp = Spesa(f, 1.0)
            sp.exa_usd, sp.anth_ora = 0.5, 0.3
            sp.salva()
            sp2 = Spesa(f, 1.0)
            assert abs(sp2.eur() - (0.5 * 0.92 + 0.3)) < 1e-6 and not sp2.finita()
            sp2.anth_ora = 0.3
            assert sp2.finita()
        assert [x["n"] for x in a_turno([{"marchio": "A", "n": 1}, {"marchio": "A", "n": 2},
                                         {"marchio": "B", "n": 3}])] == [1, 3, 2]
        # resoconto: solo numeri, per azienda
        with tempfile.TemporaryDirectory() as tmp:
            CARTELLA = pathlib.Path(tmp)
            _aggiungi(CARTELLA / "raccolta.jsonl", [{"url": "a", "marchio": "Colfert"}] * 3)
            _aggiungi(CARTELLA / "esiti.jsonl", [
                {"marchio_query": "Colfert", "marchi": [{"marchio": "Colfert", "stato": "attuale"}],
                 "in_archivio": False, "nuovo": True},
                {"marchio_query": "Colfert", "marchi": [{"marchio": "Colfert", "stato": "passato"}],
                 "in_archivio": True, "nuovo": False},
                {"marchio_query": "Colfert", "marchi": [], "in_archivio": False, "nuovo": True}])
            out = resoconto(["Colfert"], log=lambda *_: None)
            c = out["per_azienda"]["Colfert"]
            assert (c["profili_raccolti"], c["agenti"], c["attuale"], c["passato"], c["nuovi"],
                    c["gia_in_archivio"]) == (3, 2, 1, 1, 1, 1)
            assert out["agenti_nuovi_totali"] == 2 and out["agenti_con_mandato_nuovi"] == 1
        print("ok")
        sys.exit(0)

    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).parent / ".env")
    arg = lambda k: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else ""
    if "--b2" in sys.argv:
        regioni_b2 = [r.strip() for r in arg("--regioni").split(",") if r.strip()]
        if len(B2_TUTTE) != 321:
            print(f"ESITO: elenco B2 incompleto ({len(B2_TUTTE)} su 321): manca cache/b2_riservate.json — non parto")
            sys.exit(4)
        if "--scrivi" not in sys.argv:
            print(f"MISURA: {len(query_pilota(list(B2_TUTTE), regioni_b2))} ricerche Exa, "
                  f"{sum(bool(d['concorrente']) for d in B2_TUTTE.values())} concorrenti")
            sys.exit(0)
        sys.exit(pilota(list(B2_TUTTE), regioni_b2, float(arg("--tetto-eur")), arg("--entro") or None,
                        lambda m: print(m, flush=True), float(arg("--tetto-exa-eur")),
                        float(arg("--tetto-anthropic-eur")), "B2"))
    if "--pilota" in sys.argv:
        if "--scrivi" not in sys.argv:
            print(f"MISURA: {len(query_pilota(list(PILOTA), [r for r in arg('--regioni').split(',') if r]))}"
                  " ricerche Exa; con --scrivi --tetto-eur N il giro parte")
            sys.exit(0)
        sys.exit(pilota(list(PILOTA), [r.strip() for r in arg("--regioni").split(",") if r.strip()],
                        float(arg("--tetto-eur")), arg("--entro") or None,
                        lambda m: print(m, flush=True)))
    giro([m.strip() for m in arg("--marchi").split(",") if m.strip()],
         [r.strip() for r in arg("--regioni").split(",") if r.strip()],
         arg("--cache"), "--scrivi" in sys.argv, senza_ricerca="--senza-ricerca" in sys.argv,
         sagome=int(arg("--sagome") or 2), nazionali="--senza-nazionali" not in sys.argv,
         agenzie="--senza-agenzie" not in sys.argv,
         gia_fatte=tuple(x.strip() for x in arg("--gia-fatte").split(",") if x.strip()))
