"""Marchi dei mandati degli agenti (richiesta del committente, 8/10):
colonna `agenti.mandati_marchi`, PRIORITA' e non filtro. Solo marchi
DICHIARATI dall'agente (profilo) o dal marchio (pagina rete vendita), con
la frase copiata alla lettera e controllata qui; mai dedotti.

    python agenti_marchi.py --marchi Finstral,Internorm,Isolcasa --regioni Lazio,Toscana --misura
    python agenti_marchi.py --marchi ... --regioni ... --cache FILE --scrivi
    python agenti_marchi.py --marchi ... --cache FILE --senza-ricerca --scrivi   # solo la cache

--cache: profili gia' raccolti (jsonl url/nome/testo) da rivalutare.
Per ogni profilo: gia' in tabella -> solo i marchi (update della colonna,
unione con quelli che c'erano); non in tabella -> classificazione completa
(prompt v4 di agenti_ricerca) + marchi, e se pertinente entra.
Agenti presi dalla pagina di un marchio: abbinati con certezza (stesso nome
e stessa regione) -> il marchio va sulla scheda esistente; abbinamento solo
probabile -> scheda separata con nota "possibile doppione di <id>"; nessuno
-> scheda separata. Nessuna cancellazione; nomi di persone solo nei dati.
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
from data.marchi_agenti import MARCHI

CARTELLA = pathlib.Path(os.environ.get("AGENTI_MARCHI_CARTELLA")
                        or pathlib.Path(__file__).parent / "cache" / "agenti_marchi")
STATI = ("attuale", "passato", "non_chiaro")
SAGOME = ("agente plurimandatario serramenti {m} {r}",
          "agente di commercio {m} finestre {r}")
EXA_TETTO_USD = 1.0
ANTHROPIC_TETTO_EUR = 4.0


def _descrizione(marchi: list[str]) -> str:
    return "\n".join(f"- {m}" + (f" (sito: {MARCHI[m]['dominio']})" if MARCHI[m]["dominio"] else "")
                     + (" — nome generico: vale SOLO se il profilo lo lega a serramenti, finestre, "
                        "infissi o porte" if MARCHI[m]["generico"] else "") for m in marchi)


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

PROMPT_PAGINA = """Pagina pubblica del sito del produttore di serramenti {marchio}. Elenca SOLO gli AGENTI o le AGENZIE di vendita (rete commerciale del produttore) che la pagina nomina, con la zona. NON rivenditori, showroom, installatori, dealer o partner commerciali che vendono al cliente finale, NON dipendenti interni.
Per ognuno: "nome" come scritto, "zona" (regioni o province), "citta" se c'e', "telefono", "email", "sito" se la pagina li riporta, "evidenza" = frase copiata alla lettera dalla pagina.

PAGINA:
{testo}

Rispondi SOLO con JSON: {{"agenti": [{{"nome": "...", "zona": "...", "citta": "...", "telefono": "...", "email": "...", "sito": "...", "evidenza": "..."}}]}}"""


def _norm(t: str | None) -> str:
    t = unicodedata.normalize("NFKD", (t or "").replace("’", "'"))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().casefold()


def controlla(marchi: list, testo: str, ammessi: list[str], fonte: str, url: str) -> list[dict]:
    """Solo marchi dell'elenco, stato valido, evidenza LETTERALE nel testo
    che nomina davvero il marchio. Il resto si scarta."""
    corpo, buoni = _norm(testo), []
    per_nome = {_norm(m): m for m in ammessi}
    for x in marchi or []:
        m = per_nome.get(_norm(x.get("marchio")))
        ev = (x.get("evidenza") or "").strip()
        if not m or len(_norm(ev)) < 6 or _norm(ev) not in corpo \
                or not re.search(MARCHI[m]["regex"], _norm(ev)):
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
    della_lista = any(re.search(v["regex"], dett) for v in MARCHI.values())
    if della_lista and not re.search(CONCORRENTI, dett) \
            and (d.get("agente_di_concorrente") or c.get("stato") == "attuale"):
        d["agente_di_concorrente"] = False
        d["conflitto"] = {"stato": "da_verificare",
                          "dettaglio": f"marchio della lista del committente: {c.get('dettaglio') or ''}"[:300]}
    return d


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


def raccogli(marchi: list[str], regioni: list[str], visti: set, log=print) -> tuple[list[dict], float]:
    chiave = os.environ["EXA_API_KEY"]
    query = [s.format(m=m, r=r) for m in marchi for r in regioni for s in SAGOME]
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
    return nuovi, speso


def pagine_rete(marchi: list[str], log=print) -> tuple[list[dict], float]:
    """Le pagine pubbliche "rete vendita / agenti" dei siti dei marchi."""
    import urllib.request
    chiave, pagine, speso = os.environ["EXA_API_KEY"], [], 0.0
    for m in marchi:
        dom = MARCHI[m]["dominio"]
        if not dom:
            continue
        req = urllib.request.Request(
            "https://api.exa.ai/search",
            data=json.dumps({"query": f"{m} serramenti rete vendita agenti di zona Italia",
                             "type": "auto", "numResults": 5,
                             "contents": {"text": {"maxCharacters": 8000}}}).encode(),
            headers={"content-type": "application/json", "x-api-key": chiave})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.load(r)
        except Exception as e:  # noqa: BLE001
            log(f"  pagine {m} KO ({type(e).__name__})")
            continue
        speso += (d.get("costDollars") or {}).get("total", 0) or 0
        for res in d.get("results", []):
            if dom in (res.get("url") or "").lower() and re.search(
                    r"agent|rete vendita|rete commerciale|area manager", (res.get("text") or ""), re.I):
                pagine.append({"marchio": m, "url": res["url"], "testo": res.get("text") or ""})
    log(f"pagine rete vendita dei marchi: {len(pagine)} — Exa {speso:.3f} USD")
    return pagine, speso


def giro(marchi: list[str], regioni: list[str], cache: str, scrivi: bool, log=print,
         senza_ricerca: bool = False) -> None:
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
        nuovi, speso_exa = raccogli(marchi, regioni, visti, log) if cerca else ([], 0.0)
        pagine, speso_p = pagine_rete(marchi, log) if cerca else ([], 0.0)
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
                prompt = PROMPT_V4.replace('"nota": "max 20 parole"}}', '"nota": "max 20 parole", '
                                           '"marchi": [{{"marchio": "...", "stato": "...", "evidenza": "..."}}]}}')
                d = _chiama(client, prompt.format(testo=p["testo"]) + "\n\n" + REGOLE_MARCHI.format(marchi=descr)
                            + '\nMetti i marchi nella chiave "marchi" dello stesso JSON.', tot, 900)
                trovati = controlla(d.get("marchi"), p["testo"], marchi, "profilo", u)
                d = correggi_conflitto(d)
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
        try:
            d = _chiama(client, PROMPT_PAGINA.format(marchio=pg["marchio"], testo=pg["testo"][:8000]), tot, 1500)
        except Exception as e:  # noqa: BLE001
            log(f"  pagina {pg['url']}: {type(e).__name__}")
            continue
        for ag in d.get("agenti") or []:
            ev = (ag.get("evidenza") or "").strip()
            if not ag.get("nome") or _norm(ev) not in _norm(pg["testo"]):
                continue
            regione = _regione_di({"province_coperte": [], "residenza": ag.get("zona") or ""})
            regione = regione if regione in config.REGIONI else ""
            marchio = [{"marchio": pg["marchio"], "stato": "attuale", "fonte": "sito_marchio",
                        "url": pg["url"], "evidenza": ev[:300]}]
            tipo, r = abbinamento(ag["nome"], regione, righe, ag)
            if tipo == "certo":
                sb.table("agenti").update({"mandati_marchi": unisci(r.get("mandati_marchi"), marchio)}
                                          ).eq("id", r["id"]).execute()
                esiti["dal sito del marchio, abbinati"] += 1
            else:
                nota = (f"agente dal sito {pg['marchio']} ({ag.get('zona') or 'zona n.d.'})"
                        + (f"; possibile doppione di {r['id']} ({r['nome_completo']})" if r else ""))
                sb.table("agenti").insert({
                    "nome_completo": ag["nome"], "classificazione": "da_valutare",
                    "conflitto_stato": "da_verificare", "agente_di_concorrente": False,
                    "zona_da_confermare": not regione, "regione_prevalente": regione or None,
                    "residenza": ag.get("zona"), "note": nota, "fonte": "sito_marchio",
                    "mandati_marchi": marchio}).execute()
                esiti["dal sito del marchio, schede nuove"] += 1
                esiti["possibili doppioni"] += bool(r)
            per_marchio[pg["marchio"]] += 1
            per_stato["attuale"] += 1

    if esiti["agenti nuovi"] or esiti["dal sito del marchio, schede nuove"]:
        completa_nomi(log)
    log(f"\nESITI: {dict(esiti)}")
    log(f"per marchio: {dict(per_marchio)}")
    log(f"per stato: {dict(per_stato)}")
    log(f"Exa {speso_exa + speso_p:.3f} USD")
    costi.stampa(tot, log=log)


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
        assert "nome generico" in _descrizione(["SPI"]) and "finstral" in _descrizione(["Finstral"])
        print("ok")
        sys.exit(0)

    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).parent / ".env")
    arg = lambda k: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else ""
    giro([m.strip() for m in arg("--marchi").split(",") if m.strip()],
         [r.strip() for r in arg("--regioni").split(",") if r.strip()],
         arg("--cache"), "--scrivi" in sys.argv, senza_ricerca="--senza-ricerca" in sys.argv)
