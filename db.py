"""Scrittura su Supabase con service_role (PRD §10).

Schema letto dal DB reale il 2026-08-25: i nomi di colonna qui sono quelli
veri, non assunti. Gli enum sono in config e vanno rispettati carattere per
carattere — il modello risponde in MAIUSCOLO, il DB vuole minuscolo.

Regole del §10:
- upsert sugli indici unici (partita_iva, dominio): il conflitto NON è un
  errore, è il dedup che lavora — si logga e si prosegue;
- un fallimento su una singola azienda non ferma il ciclo;
- `esito_analisi` porta sempre il valore grezzo del modello, accanto a
  `classe` che è il giudizio commerciale;
- le aziende senza sito entrano comunque, con `esito_fetch`, i recapiti
  Maps e una motivazione onesta;
- riga in `cicli_ricerca` all'avvio, aggiornata alla fine.
"""

from __future__ import annotations

import os

import config

MOTIVAZIONE_NO_SITO = "nessuna fonte web disponibile — valutazione telefonica"
MOTIVAZIONE_FUORI = "fuori territorio"
# codice Postgres per violazione di vincolo unico: è il dedup, non un errore
CODICE_DUPLICATO = "23505"


def client():
    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    url = os.environ["SUPABASE_URL"].rstrip("/")
    if not url.startswith("http"):  # nel .env a volte finisce il solo project ref
        url = f"https://{url}.supabase.co"
    return create_client(url, os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def _enum(valore: str, valide: tuple[str, ...], default: str | None) -> str | None:
    """Normalizza al minuscolo e valida: fuori enum -> default (mai un
    valore inventato, Postgres lo rifiuterebbe)."""
    v = (valore or "").strip().lower()
    return v if v in valide else default


def _testo(valore) -> str | None:
    """'', 'null', 'None' -> None: il modello a volte scrive la parola."""
    v = str(valore or "").strip()
    return None if v.lower() in ("", "null", "none", "n/d", "nd") else v


def _lista(valore) -> list[str] | None:
    if isinstance(valore, list):
        voci = [str(v).strip() for v in valore if str(v).strip()]
    else:
        voci = [p.strip() for p in str(valore or "").split(";") if p.strip()]
    return voci or None


def _fornitura(categoria: str | None, officina: str | None = None) -> str | None:
    """Regola commerciale del cliente, non del modello (config).

    Chi produce compra il kit, chi non produce compra il prodotto finito:
    sono due linee dello stesso catalogo. Il serramentista è l'unico che si
    decide sull'officina, perché può stare da entrambe le parti.
    """
    if categoria == "serramentista":
        return {"si": "kit", "no": "prodotto_finito"}.get(officina or "")
    return config.FORNITURA_PER_CATEGORIA.get(categoria or "")


def _struttura(dipendenti: int | None) -> str | None:
    """Soglie UE standard, applicate solo se Openapi ha dato il dato."""
    if not dipendenti:
        return None
    if dipendenti < 10:
        return "micro"
    if dipendenti < 50:
        return "piccola"
    return "media" if dipendenti < 250 else "grande"


def verniciatura_interna(dati: dict) -> bool:
    """Indizi che l'azienda vernicia o zinca in casa (catalogo 2026-09).

    E' un SEGNALE, non un livello di fornitura: chi vernicia potrebbe
    volere l'assemblato grezzo, ma non sappiamo distinguerlo da chi ha
    l'officina completa e il sistema non deve inventarlo. Lo legge il
    commerciale e lo usa in trattativa.

    Attenzione alla precisione: "zincatura" e' il processo, ma un testo che
    dice "persiane in acciaio zincato" parla del MATERIALE. Il falso
    positivo qui costa poco (una riga in piu' in scheda, che il commerciale
    scarta leggendo), il falso negativo costa un argomento di vendita.
    """
    materiali = dati.get("materiali_rilevati")
    if isinstance(materiali, list):
        materiali = " ".join(str(m) for m in materiali)
    testo = f"{materiali or ''} {dati.get('motivazione') or ''}".lower()
    return any(i in testo for i in config.INDIZI_VERNICIATURA)


def riga_azienda(scheda: dict, dati: dict | None = None,
                 territorio: dict | None = None, anagrafica: dict | None = None,
                 segnali: list[dict] | None = None, classe: str = "indeterminato",
                 esito_fetch: str = "", ciclo_id: str | None = None,
                 pagine: int = 0, costo: float = 0.0) -> dict:
    """Costruisce la riga per `aziende`.

    `scheda`: dalla fonte (Maps/Exa). `dati`: risposta del modello, assente
    per chi non è stato classificato (senza sito, fuori territorio, fetch
    fallito). `anagrafica`: da Openapi. La sede del modello ha la
    precedenza su quella Maps: è letta dalla pagina contatti; quella di
    Openapi vince su entrambe, è la sede legale registrata.
    """
    dati = dati or {}
    anagrafica = anagrafica or {}

    if not dati and esito_fetch == "nessun_sito":
        motivazione = MOTIVAZIONE_NO_SITO
    elif (territorio or {}).get("esito") == "fuori":
        # anche quando l'analisi è stata pagata: la motivazione del modello
        # si conserva in coda, ma la riga resta marcata fuori territorio
        motivazione = f"{MOTIVAZIONE_FUORI} ({territorio.get('segnale', '')})".strip()
        propria = _testo(dati.get("motivazione"))
        if propria:
            motivazione = f"{motivazione}. {propria}"
    else:
        motivazione = _testo(dati.get("motivazione"))

    segnali_finali = list(segnali or [])
    # reputazione Google: non costa nulla e il commerciale la vede in scheda
    if scheda.get("recensioni") is not None:
        segnali_finali.append({"tipo": "reputazione_google",
                               "recensioni": scheda.get("recensioni"),
                               "punteggio": scheda.get("punteggio")})
    if scheda.get("chiusa_temporaneamente"):
        segnali_finali.append({
            "tipo": "chiusa_temporaneamente",
            "nota": "Google la dà temporaneamente chiusa: verificare prima di contattare"})
    if verniciatura_interna(dati):
        segnali_finali.append({"tipo": "verniciatura_interna",
                               "nota": config.NOTA_VERNICIATURA})
    if scheda.get("ex_cliente"):
        # il commerciale deve sapere che ci ha già lavorato
        segnali_finali.insert(0, scheda["ex_cliente"])
    if territorio:
        segnali_finali.append({"tipo": "territorio", "esito": territorio["esito"],
                               "segnale": territorio.get("segnale", "")})

    categoria = _enum(dati.get("categoria"), config.ENUM_CATEGORIA, None)
    officina = _enum(dati.get("capacita_officina"), config.ENUM_TERNARIO,
                     "non_determinabile")
    dominio = ""
    if scheda.get("sito"):
        import dedup

        # solo se identifica l'azienda: facebook.com no (indice unico)
        dominio = dedup.dominio_azienda(scheda["sito"])

    return {
        "ciclo_id": ciclo_id,
        "ragione_sociale": (scheda.get("nome") or "").strip(),
        "partita_iva": _testo(anagrafica.get("piva")),
        "dominio": dominio or None,
        "sito": _testo(scheda.get("sito")),
        # sede: Openapi (legale) > modello (pagina contatti) > Maps
        "comune": (_testo(anagrafica.get("sede_comune"))
                   or _testo(dati.get("sede_comune")) or _testo(scheda.get("comune"))),
        # sempre la sigla: vedi config.SIGLE_PROVINCE
        "provincia": config.sigla_provincia(
            _testo(anagrafica.get("sede_provincia"))
            or _testo(dati.get("sede_provincia")), log=print),
        "regione": _testo(dati.get("sede_regione")),
        "email_aziendale": _testo(dati.get("email_aziendale")),
        "telefono": _testo(dati.get("telefono")) or _testo(scheda.get("telefono")),
        "categoria": categoria,
        "lavora_acciaio": _enum(dati.get("lavora_acciaio"), config.ENUM_TERNARIO,
                                "non_determinabile"),
        "officina_propria": officina,
        "struttura": _struttura(anagrafica.get("dipendenti")),
        "n_dipendenti": anagrafica.get("dipendenti"),
        "materiali": _lista(dati.get("materiali_rilevati")),
        "classe": classe if classe in config.ENUM_CLASSE else "indeterminato",
        "confidenza": _enum(dati.get("confidenza"), config.ENUM_CONFIDENZA, "bassa"),
        "motivazione": motivazione,
        "segnali": segnali_finali or None,
        "prodotto_apertura": _testo(dati.get("prodotto_da_proporre")),
        "livello_fornitura": _fornitura(categoria, officina),
        # valore GREZZO del modello, accanto al giudizio commerciale `classe`
        "esito_analisi": _testo(dati.get("classificazione")),
        "stato": "da_lavorare",       # la pipeline non tocca il follow-up (§7 agg.)
        "n_contatti": 0,
        "prossima_azione": None,      # la valorizza l'app quando parte l'email
        "fonte": _testo(scheda.get("fonte")),
        "pagine_analizzate": pagine,
        "esito_fetch": _testo(esito_fetch),
        "costo_analisi_eur": round(costo, 6) if costo else 0,
    }


def scrivi_azienda(sb, riga: dict, log=print) -> str:
    """-> "inserita" | "duplicata" | "errore". Non solleva mai: un
    fallimento su una singola azienda non ferma il ciclo."""
    nome = riga.get("ragione_sociale", "?")
    try:
        sb.table("aziende").insert(riga).execute()
        log(f"  scritta: {nome} | {riga['fonte']} | {riga['esito_fetch']} | "
            f"{riga['esito_analisi'] or '-'} | {riga['classe']} | "
            f"{riga['confidenza']} | {riga['costo_analisi_eur']} EUR")
        return "inserita"
    except Exception as e:  # noqa: BLE001
        testo = str(e)
        if CODICE_DUPLICATO in testo or "duplicate key" in testo:
            log(f"  già presente (dedup): {nome} "
                f"[{riga.get('partita_iva') or riga.get('dominio') or '-'}]")
            return "duplicata"
        log(f"  ERRORE su {nome}: {type(e).__name__}: {testo[:200]}")
        return "errore"


def riferimenti_aziende(sb) -> list[dict]:
    """Righe già in `aziende` per il dedup (§4): servono dominio, P.IVA e
    ragione+comune — le senza-sito non hanno né dominio né P.IVA e solo
    ragione+comune le protegge dai duplicati."""
    r = sb.table("aziende").select(
        "ragione_sociale,partita_iva,dominio,comune").execute()
    return r.data or []


def esclusioni(sb) -> list[dict]:
    """Tutte le righe: `motivo` distingue chi esclude la ricerca (clienti
    attivi) da chi va solo marcato (ex clienti da riattivare)."""
    r = sb.table("esclusioni").select(
        "ragione_sociale,partita_iva,dominio,comune,motivo").execute()
    return r.data or []


def avvia_ciclo(sb, regione: str, note: str = "") -> str:
    r = sb.table("cicli_ricerca").insert(
        {"regione": regione, "note": note or None}).execute()
    return r.data[0]["id"]


def chiudi_ciclo(sb, ciclo_id: str, riepilogo: dict, n_trovate: int,
                 n_in_target: int, note: str = "") -> None:
    """`riepilogo` è quello di costi.riepilogo(). Le voci per fonte vanno
    nelle loro colonne dedicate: il report consumi è un obbligo contrattuale
    e non può dipendere dal parsing di un campo di testo."""
    from datetime import datetime, timezone

    sb.table("cicli_ricerca").update({
        "concluso_il": datetime.now(timezone.utc).isoformat(),
        "n_trovate": n_trovate,
        "n_analizzate": riepilogo["aziende_analizzate"],
        "n_in_target": n_in_target,
        "costo_eur": riepilogo["costo_totale_eur"],
        "costo_anthropic_eur": riepilogo["costo_anthropic_eur"],
        "costo_openapi_eur": riepilogo["costo_openapi_eur"],
        "costo_exa_eur": riepilogo["costo_exa_eur"],
        "costo_apify_eur": riepilogo["costo_apify_eur"],
        "note": note or None,
    }).eq("id", ciclo_id).execute()


if __name__ == "__main__":
    assert _enum("SI", config.ENUM_TERNARIO, "non_determinabile") == "si"
    assert _enum("ALTA", config.ENUM_CONFIDENZA, "bassa") == "alta"
    assert _enum("", config.ENUM_CONFIDENZA, "bassa") == "bassa"
    assert _enum("inventata", config.ENUM_CATEGORIA, None) is None
    assert _enum("Fabbro", config.ENUM_CATEGORIA, None) == "fabbro"
    assert _testo("null") is None and _testo(" x ") == "x" and _testo(None) is None
    assert _lista("ferro; acciaio") == ["ferro", "acciaio"]
    assert _lista(["ferro", ""]) == ["ferro"] and _lista("") is None
    assert _struttura(None) is None and _struttura(5) == "micro"
    assert _struttura(20) == "piccola" and _struttura(100) == "media"
    assert _struttura(300) == "grande"
    # livello_fornitura: regola commerciale per categoria
    assert _fornitura("fabbro") == "kit"
    assert _fornitura("showroom") == "prodotto_finito"
    assert _fornitura("impresa_edile") == "prodotto_finito"
    assert _fornitura("costruttore") == "prodotto_finito"
    # il serramentista si decide sull'officina: produce -> kit, non produce
    # -> prodotto finito, non determinabile -> nessuna proposta
    assert _fornitura("serramentista", "si") == "kit"
    assert _fornitura("serramentista", "no") == "prodotto_finito"
    assert _fornitura("serramentista", "non_determinabile") is None
    assert _fornitura("serramentista") is None
    # le altre categorie non guardano l'officina
    assert _fornitura("fabbro", "no") == "kit"
    assert _fornitura("ferramenta") is None and _fornitura(None) is None
    assert set(config.FORNITURA_PER_CATEGORIA) <= set(config.ENUM_CATEGORIA)
    assert set(config.FORNITURA_PER_CATEGORIA.values()) <= set(config.ENUM_FORNITURA)

    # azienda classificata, con arricchimento
    r = riga_azienda(
        {"nome": "Officina Rossi", "sito": "https://www.rossi.it/", "fonte": "maps",
         "telefono": "06 123", "comune": "Guidonia"},
        dati={"classificazione": "TARGET", "confidenza": "ALTA", "categoria": "fabbro",
              "lavora_acciaio": "SI", "capacita_officina": "SI",
              "materiali_rilevati": ["ferro", "acciaio"], "motivazione": "produce grate",
              "sede_comune": "Tivoli", "sede_provincia": "RM", "sede_regione": "Lazio",
              "email_aziendale": "info@rossi.it", "prodotto_da_proporre": "grate"},
        territorio={"esito": "lazio", "segnale": "cap 00019"},
        anagrafica={"piva": "01234567890", "dipendenti": 8, "sede_comune": "Tivoli"},
        segnali=[{"tipo": "annuncio_lavoro", "ruolo": "saldatore", "fonte": "u"}],
        classe="A", esito_fetch="OK", pagine=5, costo=0.0712)
    assert r["dominio"] == "rossi.it" and r["esito_analisi"] == "TARGET"
    assert r["classe"] == "A" and r["confidenza"] == "alta"
    assert r["lavora_acciaio"] == "si" and r["officina_propria"] == "si"
    assert r["struttura"] == "micro" and r["n_dipendenti"] == 8
    assert r["stato"] == "da_lavorare" and r["n_contatti"] == 0
    assert r["prossima_azione"] is None
    assert r["segnali"][0]["ruolo"] == "saldatore"
    assert r["segnali"][-1]["tipo"] == "territorio"
    assert r["livello_fornitura"] == "kit"  # categoria fabbro -> kit
    assert set(r) <= {  # nessuna colonna inventata rispetto allo schema reale
        "ciclo_id", "ragione_sociale", "partita_iva", "dominio", "sito", "comune",
        "provincia", "regione", "email_aziendale", "telefono", "categoria",
        "lavora_acciaio", "officina_propria", "struttura", "n_dipendenti",
        "materiali", "gamma", "classe", "confidenza", "motivazione", "segnali",
        "livello_fornitura", "prodotto_apertura", "leva_commerciale",
        "referente_nome", "referente_ruolo", "referente_email", "stato",
        "assegnato_a", "ultimo_contatto", "n_contatti", "prossima_azione",
        "fonte", "pagine_analizzate", "esito_fetch", "costo_analisi_eur",
        "esito_analisi"}

    # senza sito: entra comunque, con recapiti Maps e motivazione onesta
    s = riga_azienda({"nome": "Fabbro Bianchi", "sito": "", "fonte": "maps",
                      "telefono": "0774 456", "comune": "Tivoli",
                      "indirizzo": "Via X 1"},
                     esito_fetch="nessun_sito")
    assert s["motivazione"] == MOTIVAZIONE_NO_SITO
    assert s["classe"] == "indeterminato" and s["confidenza"] == "bassa"
    assert s["esito_analisi"] is None and s["telefono"] == "0774 456"
    assert s["comune"] == "Tivoli" and s["dominio"] is None

    # pagina social al posto del sito: il sito resta come recapito, il
    # dominio no (13 aziende su Facebook collasserebbero sull'indice unico)
    fb = riga_azienda({"nome": "Trianello il fabbro", "fonte": "maps",
                       "sito": "https://www.facebook.com/fabbroguidonia",
                       "telefono": "327 242 9410", "comune": "Guidonia"},
                      esito_fetch="nessun_sito")
    assert fb["dominio"] is None
    assert fb["sito"] == "https://www.facebook.com/fabbroguidonia"
    assert fb["motivazione"] == MOTIVAZIONE_NO_SITO

    # fuori territorio: registrata, non classificata (non si paga)
    f = riga_azienda({"nome": "Fabbro Como", "sito": "https://x.it", "fonte": "exa"},
                     territorio={"esito": "fuori", "segnale": "cap 22100"},
                     esito_fetch="OK")
    assert f["motivazione"].startswith(MOTIVAZIONE_FUORI) and "22100" in f["motivazione"]
    assert f["esito_analisi"] is None

    # fuori territorio scoperto DOPO l'analisi: esito grezzo conservato,
    # riga marcata fuori, classe non consegnabile
    post = riga_azienda(
        {"nome": "Porta sicura", "sito": "https://x.it", "fonte": "maps"},
        dati={"classificazione": "INDETERMINATO", "confidenza": "MEDIA",
              "motivazione": "tratta porte blindate", "sede_comune": "RODANO",
              "sede_provincia": "MI", "sede_regione": "Lombardia"},
        territorio={"esito": "fuori",
                    "segnale": "sede dichiarata dal sito: RODANO, MI (Lombardia), "
                               "fuori da Lazio"},
        segnali=[{"tipo": "fuori_territorio_sede_dichiarata", "regione": "Lombardia"}],
        classe="C", esito_fetch="OK")
    assert post["esito_analisi"] == "INDETERMINATO"       # conservato
    assert post["motivazione"].startswith(MOTIVAZIONE_FUORI)
    assert "RODANO" in post["motivazione"]
    assert "tratta porte blindate" in post["motivazione"]  # la sua motivazione resta
    # la classe NON viene declassata: dice quanto vale l'azienda, non dove
    # sta. Quando si aprirà la Lombardia va recuperata per classe.
    assert post["classe"] == "C"
    assert post["regione"] == "Lombardia"   # il filtro lo fa questo campo
    assert post["segnali"][0]["tipo"] == "fuori_territorio_sede_dichiarata"

    # ex cliente: marcato nei segnali, non escluso dai risultati
    exc = riga_azienda({"nome": "Officina Y", "fonte": "maps", "comune": "Tivoli",
                        "ex_cliente": {"tipo": "ex_cliente",
                                       "motivo": "ex cliente: Perso per prezzo",
                                       "riconosciuto_per": "ragione+comune"}},
                       dati={"classificazione": "TARGET", "confidenza": "ALTA"},
                       classe="A", esito_fetch="OK")
    assert exc["segnali"][0]["tipo"] == "ex_cliente"

    # provincia: in archivio va SEMPRE la sigla, mai il nome per esteso
    base = {"nome": "P", "fonte": "maps"}
    for dato, atteso in (("Roma", "RM"), ("roma", "RM"), ("RM", "RM"),
                         ("rm", "RM"), ("Frosinone", "FR"), ("Milano", "MI")):
        r_p = riga_azienda(base, dati={"classificazione": "TARGET",
                                       "confidenza": "ALTA",
                                       "sede_provincia": dato},
                           territorio=None, anagrafica={}, segnali=[],
                           classe="B", esito_fetch="OK", ciclo_id="c")
        assert r_p["provincia"] == atteso, (dato, r_p["provincia"])
    # una provincia che non conosciamo si lascia com'e' invece di indovinare
    r_p = riga_azienda(base, dati={"classificazione": "TARGET",
                                   "confidenza": "ALTA",
                                   "sede_provincia": "Oltrepo"},
                       territorio=None, anagrafica={}, segnali=[],
                       classe="B", esito_fetch="OK", ciclo_id="c")
    assert r_p["provincia"] == "Oltrepo"

    # verniciatura interna: segnale, mai livello_fornitura
    assert verniciatura_interna({"motivazione": "esegue verniciatura a polvere interna"})
    assert verniciatura_interna({"materiali_rilevati": ["ferro", "zincatura a caldo"]})
    assert not verniciatura_interna({"motivazione": "vende persiane in pvc"})
    assert not verniciatura_interna({})
    v = riga_azienda(
        {"nome": "V", "fonte": "maps", "comune": "Tivoli"},
        dati={"classificazione": "TARGET", "confidenza": "ALTA",
              "categoria": "fabbro", "capacita_officina": "SI",
              "materiali_rilevati": ["ferro"],
              "motivazione": "trattamenti interni: zincatura e verniciatura"},
        territorio=None, anagrafica={}, segnali=[], classe="A",
        esito_fetch="OK", ciclo_id="c")
    assert any(s["tipo"] == "verniciatura_interna" for s in v["segnali"])
    assert v["livello_fornitura"] != "assemblato_grezzo", \
        "la verniciatura NON assegna il livello di fornitura, e' solo un segnale"
    assert exc["classe"] == "A"          # resta un lead, con la sua classe
    assert exc["esito_analisi"] == "TARGET"

    # reputazione e chiusura temporanea finiscono nei segnali
    r = riga_azienda({"nome": "X", "fonte": "maps", "recensioni": 176,
                      "punteggio": 4.8, "chiusa_temporaneamente": True},
                     dati={"classificazione": "TARGET", "confidenza": "ALTA"},
                     classe="A", esito_fetch="OK")
    tipi = [s["tipo"] for s in r["segnali"]]
    assert "reputazione_google" in tipi and "chiusa_temporaneamente" in tipi
    rep = next(s for s in r["segnali"] if s["tipo"] == "reputazione_google")
    assert rep["recensioni"] == 176 and rep["punteggio"] == 4.8
    # senza recensioni (Exa non le ha) nessun segnale vuoto
    r2 = riga_azienda({"nome": "Y", "fonte": "exa"},
                      dati={"classificazione": "TARGET", "confidenza": "ALTA"},
                      classe="A", esito_fetch="OK")
    assert not any(s["tipo"] == "reputazione_google" for s in (r2["segnali"] or []))

    print("ok")
