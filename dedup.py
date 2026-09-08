"""Normalizzazione + dedup + esclusioni (PRD §4).

Ordine del dedup: dominio normalizzato -> P.IVA quando nota -> ragione
sociale normalizzata + comune. Poi filtro `esclusioni` (clienti attuali)
e filtro "già in aziende". Il confronto è sempre su valori normalizzati:
l'elenco di Claudia è compilato a mano e arriva con IT davanti alle P.IVA,
www davanti ai domini, maiuscole a caso.

Il matching per ragione sociale è prudente in una direzione sola: meglio
escludere un'azienda che forse è già cliente che consegnarne una che lo è
davvero. Ogni esclusione viene loggata con il criterio che l'ha decisa.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import config

# forme societarie della nucleo() validata nel test di sourcing
_FORME = (" S.R.L.S", " S.R.L.", " SRLS", " SRL", " S.A.S", " SAS",
          " SNC", " S.N.C.", " SPA", " S.P.A.", " & C.", " DI ", " GROUP")


def norm_ragione(nome: str) -> str:
    """Minuscole, niente forme societarie né punteggiatura."""
    n = (nome or "").upper()
    for forma in _FORME:
        n = n.replace(forma, " ")
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip().lower()


def norm_piva(piva: str) -> str:
    """Solo cifre (via spazi, punti, prefisso IT). Excel mangia lo zero
    iniziale delle P.IVA numeriche: 10 cifre -> riporto a 11.

    Un codice fiscale di persona fisica (16 caratteri alfanumerici) NON è
    una P.IVA: nell'elenco clienti ce ne sono 70 e estrarne le cifre
    produrrebbe chiavi false. Vale "" e si passa al match per ragione+comune.
    """
    grezzo = str(piva or "").strip().upper().removeprefix("IT")
    if re.fullmatch(r"[A-Z0-9]{16}", grezzo) and re.search(r"[A-Z]", grezzo):
        return ""
    p = re.sub(r"\D", "", grezzo)
    if len(p) == 10:
        p = p.zfill(11)
    return p if len(p) == 11 else ""


def norm_dominio(sito: str) -> str:
    """Niente protocollo, www, percorso, porta. Minuscolo."""
    s = (sito or "").strip().lower()
    if not s:
        return ""
    if "//" in s:
        s = urlparse(s).netloc or s.split("//", 1)[1]
    s = s.split("/", 1)[0].split(":", 1)[0]
    return s.removeprefix("www.")


def e_portale(sito: str) -> bool:
    """Il "sito" di una scheda Maps a volte è una pagina Facebook o un
    portale: scaricarla significa analizzare un login wall e pagare una
    classificazione su nulla. Vale come azienda senza sito."""
    return any(x in norm_dominio(sito) for x in config.PORTALI_ESCLUSI)


def dominio_azienda(sito: str) -> str:
    """Il dominio SOLO se identifica davvero l'azienda: 13 fabbri di Roma
    hanno la pagina Facebook al posto del sito e collasserebbero tutti su
    "facebook.com" (che in `aziende` è un indice unico)."""
    d = norm_dominio(sito)
    return "" if e_portale(d) else d


def _norm_comune(comune: str) -> str:
    return (comune or "").strip().lower()


def dedup_interno(schede: list[dict], log=print) -> list[dict]:
    """Unifica i risultati delle fonti nello stesso ciclo. Passare Maps
    prima di Exa: a parità di dominio resta la scheda coi recapiti."""
    visti, tenute = set(), []
    for s in schede:
        d = dominio_azienda(s.get("sito") or s.get("dominio") or "")
        p = norm_piva(s.get("piva") or "")
        if d:
            chiave = ("dom", d)
        elif p:
            chiave = ("piva", p)
        else:
            chiave = ("rag", norm_ragione(s.get("nome") or ""),
                      _norm_comune(s.get("comune") or ""))
        if chiave in visti:
            continue
        visti.add(chiave)
        tenute.append(s)
    log(f"dedup interno: {len(schede)} -> {len(tenute)} "
        f"({len(schede) - len(tenute)} doppioni)")
    return tenute


# Sotto questa lunghezza un nome normalizzato non identifica nessuno: "af",
# "z", "mcm" sono sottostringhe di mezzo archivio. Misurato sul ciclo Roma:
# con 8 il confronto permissivo toglie 7 aziende, esattamente come con 10 o
# 12 — la soglia non e' delicata, ma senza di essa i falsi positivi
# esplodono (24 clienti "trovati", quasi tutti artefatti).
MIN_NOME_PERMISSIVO = 8


def nome_confrontabile(nome_normalizzato: str) -> bool:
    """Il nome regge un confronto per sottostringa?"""
    return len(nome_normalizzato) >= MIN_NOME_PERMISSIVO


def nomi_ambigui(righe: list[dict]) -> list[dict]:
    """Le righe il cui nome e' troppo corto per un confronto affidabile.

    Non si tirano a indovinare: si consegnano al committente, che riconosce
    un suo cliente in trenta secondi guardando l'elenco.
    """
    fuori = []
    for r in righe:
        rag = norm_ragione(r.get("ragione_sociale") or r.get("nome") or "")
        if not nome_confrontabile(rag):
            fuori.append(r)
    return fuori


def riferimenti(righe: list[dict]) -> dict:
    """Indici di confronto da righe di `esclusioni` o di `aziende` (valori
    grezzi: si normalizza qui). Ogni chiave punta alla riga sorgente, che
    serve a marcare l'azienda con il suo stato commerciale."""
    rif = {"pive": {}, "domini": {}, "ragioni_comune": {},
           "ragioni_senza_comune": {}}
    for r in righe:
        p = norm_piva(r.get("piva") or r.get("partita_iva") or "")
        d = dominio_azienda(r.get("dominio") or r.get("sito") or "")
        rag = norm_ragione(r.get("ragione_sociale") or r.get("nome") or "")
        com = _norm_comune(r.get("comune") or "")
        if p:
            rif["pive"].setdefault(p, r)
        if d:
            rif["domini"].setdefault(d, r)
        if rag and com:
            rif["ragioni_comune"].setdefault((rag, com), r)
        elif rag:
            rif["ragioni_senza_comune"].setdefault(rag, r)
    rif["ragioni_con_comune"] = {rag for rag, _ in rif["ragioni_comune"]}
    # per il confronto permissivo: solo i nomi che reggono una sottostringa
    rif["nomi_lunghi"] = [
        (norm_ragione(r.get("ragione_sociale") or r.get("nome") or ""),
         _norm_comune(r.get("comune") or ""), r)
        for r in righe
        if nome_confrontabile(norm_ragione(
            r.get("ragione_sociale") or r.get("nome") or ""))]
    return rif


def cerca_riferimento(s: dict, rif: dict,
                      permissivo: bool = False) -> tuple[str | None, dict | None]:
    """-> (criterio che ha fatto match, riga sorgente) oppure (None, None).

    `permissivo` aggiunge il confronto per sottostringa sul nome. Va acceso
    SOLO per l'elenco clienti del committente (attivi ed ex): li' un match
    in piu' e' un errore economico piccolo, e uno in meno rompe una
    promessa contrattuale. Sul dedup "gia' in aziende" resta spento: due
    "Officina Y" in comuni diversi sono due aziende diverse, e scartarle
    farebbe perdere prospect a ogni ciclo.
    """
    p = norm_piva(s.get("piva") or "")
    if p and p in rif["pive"]:
        return "piva", rif["pive"][p]
    d = dominio_azienda(s.get("sito") or s.get("dominio") or "")
    if d and d in rif["domini"]:
        return "dominio", rif["domini"][d]
    rag = norm_ragione(s.get("nome") or "")
    if not rag:
        return None, None
    com = _norm_comune(s.get("comune") or "")
    if (rag, com) in rif["ragioni_comune"]:
        return "ragione+comune", rif["ragioni_comune"][(rag, com)]
    if rag in rif["ragioni_senza_comune"]:
        return "ragione (esclusione senza comune)", rif["ragioni_senza_comune"][rag]
    if not com and rag in rif["ragioni_con_comune"]:
        # la scheda non dichiara il comune: nel dubbio si esclude
        chiave = next(k for k in rif["ragioni_comune"] if k[0] == rag)
        return "ragione (comune non verificabile)", rif["ragioni_comune"][chiave]

    # Ultimo criterio, PERMISSIVO: sottostringa nei due versi. Serve perche'
    # l'insegna di Google Maps non coincide con la ragione sociale
    # dell'elenco clienti — "Show Room Comerci Serramenti" contro "COMERCI
    # SERRAMENTI", "Messina Serramenti di Messina Sergio" contro "MESSINA
    # SERGIO". Il match esatto ne agganciava 9 su 113 clienti attivi.
    # Il comune CONFERMA ma non vincola: comune diverso non esclude il
    # match, lo segnala incerto. E nel dubbio si esclude comunque — perdere
    # un prospect e' un'occasione mancata, consegnare un cliente attivo e'
    # una promessa rotta.
    if not permissivo or not nome_confrontabile(rag):
        return None, None
    for nome, comune_rif, riga in rif["nomi_lunghi"]:
        if rag in nome or nome in rag:
            if com and comune_rif and com == comune_rif:
                return "nome contenuto (stesso comune)", riga
            return "nome contenuto (comune diverso: INCERTO)", riga
    return None, None


def _criterio(s: dict, rif: dict, permissivo: bool = False) -> str | None:
    return cerca_riferimento(s, rif, permissivo)[0]


def filtra(schede: list[dict], rif: dict, etichetta: str, log=print,
           permissivo: bool = False) -> list[dict]:
    """Toglie le schede che matchano i riferimenti, loggando ognuna col criterio."""
    tenute = []
    for s in schede:
        criterio = _criterio(s, rif, permissivo)
        if criterio:
            log(f"escluso [{etichetta} / {criterio}]: {s.get('nome', '?')}"
                f" ({s.get('comune') or s.get('sito') or '-'})")
        else:
            tenute.append(s)
    log(f"filtro {etichetta}: {len(schede)} -> {len(tenute)}")
    return tenute


def marca(schede: list[dict], rif: dict, log=print,
          permissivo: bool = False) -> list[dict]:
    """NON toglie niente: annota su quali schede il committente ha già
    lavorato (ex clienti da riattivare). Il commerciale deve saperlo, ma
    l'azienda resta nei risultati."""
    marcate = 0
    for s in schede:
        criterio, riga = cerca_riferimento(s, rif, permissivo)
        if not criterio:
            continue
        s["ex_cliente"] = {
            "tipo": "ex_cliente",
            "motivo": (riga.get("motivo") or config.MOTIVO_EX_CLIENTE).strip(),
            "riconosciuto_per": criterio,
            "ragione_sociale_elenco": riga.get("ragione_sociale") or "",
        }
        marcate += 1
        log(f"ex cliente [{criterio}]: {s.get('nome', '?')} "
            f"({s['ex_cliente']['motivo']})")
    log(f"marcati come ex clienti: {marcate}/{len(schede)}")
    return schede


if __name__ == "__main__":
    zitto = lambda *a: None  # noqa: E731

    assert norm_ragione("F.LLI ROSSI S.R.L.") == "f lli rossi"
    assert norm_ragione("LM DI ROSSI FERNANDO") == "lm rossi fernando"
    assert norm_ragione("Carpenteria Bianchi & C. SNC") == "carpenteria bianchi"
    assert norm_piva("IT 01234567890") == "01234567890"
    assert norm_piva("1234567890") == "01234567890"  # zero iniziale mangiato da Excel
    assert norm_piva("") == ""
    # codici fiscali di persona fisica: non sono P.IVA, non fanno da chiave
    assert norm_piva("DLLCST60B22G659U") == ""
    assert norm_piva("RPNMRC89R29A123D") == ""
    assert norm_piva("123") == ""                    # spezzone: non identifica
    assert norm_dominio("https://www.fabbrox.it/chi-siamo?x=1") == "fabbrox.it"
    assert norm_dominio("WWW.FabbroX.IT") == "fabbrox.it"
    assert norm_dominio("") == ""
    assert e_portale("https://www.facebook.com/fabbroguidonia")
    assert e_portale("http://paginegialle.it/x") and not e_portale("https://rossi.it")
    assert not e_portale("")
    assert dominio_azienda("https://www.facebook.com/fabbroguidonia") == ""
    assert dominio_azienda("https://rossi.it/x") == "rossi.it"

    # due fabbri diversi, entrambi con pagina Facebook: restano due aziende
    social = [{"nome": "Fabbro Uno", "sito": "https://facebook.com/uno", "comune": "Roma"},
              {"nome": "Fabbro Due", "sito": "https://facebook.com/due", "comune": "Tivoli"}]
    assert len(dedup_interno(social, zitto)) == 2

    schede = [
        {"nome": "Fabbro X", "sito": "https://www.x.it/", "comune": "Roma"},
        {"nome": "FABBRO X SRL", "sito": "http://x.it", "comune": ""},   # stesso dominio
        {"nome": "Officina Y", "sito": "", "comune": "Tivoli"},
        {"nome": "OFFICINA Y snc", "sito": "", "comune": "Tivoli"},      # stessa ragione+comune
        {"nome": "Officina Y", "sito": "", "comune": "Pomezia"},         # altro comune: resta
    ]
    assert len(dedup_interno(schede, zitto)) == 3

    rif = riferimenti([
        {"ragione_sociale": "ALUSETTE SRL", "partita_iva": "IT 01234567890"},
        {"ragione_sociale": "PM Serramenti s.r.l.", "comune": "Latina"},
        {"ragione_sociale": "", "dominio": "https://www.cliente.it"},
    ])
    assert _criterio({"nome": "x", "piva": "01234567890"}, rif) == "piva"
    assert _criterio({"nome": "x", "sito": "http://cliente.it/home"}, rif) == "dominio"
    assert _criterio({"nome": "Alusette", "comune": "Anzio"}, rif) == \
        "ragione (esclusione senza comune)"
    assert _criterio({"nome": "PM SERRAMENTI", "comune": "Latina"}, rif) == "ragione+comune"
    assert _criterio({"nome": "PM Serramenti srl", "comune": ""}, rif) == \
        "ragione (comune non verificabile)"
    # comune diverso: dal 2026-09-08 NON esclude piu' il match, lo segnala
    # incerto — e nel dubbio si esclude comunque
    assert _criterio({"nome": "PM Serramenti", "comune": "Roma"}, rif, True) == \
        "nome contenuto (comune diverso: INCERTO)"
    # spento (default) il comune diverso non fa match: e' il dedup interno
    assert _criterio({"nome": "PM Serramenti", "comune": "Roma"}, rif) is None
    assert _criterio({"nome": "Fabbro Nuovo", "comune": "Roma"}, rif) is None

    # --- confronto permissivo: i casi veri del ciclo Roma
    rif_p = riferimenti([
        {"ragione_sociale": "COMERCI SERRAMENTI", "comune": "Roma"},
        {"ragione_sociale": "MESSINA SERGIO", "comune": "Guidonia"},
        {"ragione_sociale": "AF Srl", "comune": "Latina"},        # nome corto
    ])
    # l'insegna di Maps e' un sovrainsieme della ragione sociale
    assert _criterio({"nome": "Show Room Comerci Serramenti", "comune": "Roma"},
                     rif_p, True) == "nome contenuto (stesso comune)"
    # senza permissivo l'insegna di Maps non aggancia: e' il bug del 2026-09-08
    assert _criterio({"nome": "Show Room Comerci Serramenti", "comune": "Roma"},
                     rif_p) is None
    assert _criterio({"nome": "Messina Serramenti di Messina Sergio",
                      "comune": "Guidonia"}, rif_p, True) == \
        "nome contenuto (stesso comune)"
    # comune diverso: incerto, ma esce lo stesso
    assert _criterio({"nome": "Show Room Comerci Serramenti", "comune": "Tivoli"},
                     rif_p, True) == "nome contenuto (comune diverso: INCERTO)"
    # un nome corto continua a fare match ESATTO (ragione+comune): quello
    # e' affidabile. Cio' che non fa e' il match permissivo — "af" e'
    # sottostringa di mezzo archivio, e lì si fermerebbe tutto
    assert _criterio({"nome": "AF Srl", "comune": "Latina"}, rif_p) == "ragione+comune"
    assert _criterio({"nome": "Graffiti AF Roma", "comune": "Roma"}, rif_p, True) is None
    assert _criterio({"nome": "AF Srl", "comune": "Pomezia"}, rif_p, True) is None
    # e un'azienda che non c'entra resta dentro
    assert _criterio({"nome": "Carpenteria Bianchi", "comune": "Roma"},
                     rif_p, True) is None

    assert nome_confrontabile("comerci serramenti")
    assert not nome_confrontabile("af")
    assert not nome_confrontabile("mcm srl")     # 3 caratteri dopo la forma
    ambigui = nomi_ambigui([{"ragione_sociale": "AF Srl"},
                            {"ragione_sociale": "COMERCI SERRAMENTI"}])
    assert [a["ragione_sociale"] for a in ambigui] == ["AF Srl"]

    assert len(filtra(schede[:3], rif, "test", zitto)) == 3

    # ex clienti: si marcano, non si escludono
    rif_ex = riferimenti([{"ragione_sociale": "Officina Y", "comune": "Tivoli",
                           "motivo": "ex cliente: Perso per prezzo"}])
    da_marcare = [{"nome": "OFFICINA Y snc", "comune": "Tivoli"},
                  {"nome": "Altra Azienda", "comune": "Tivoli"}]
    marcate = marca(da_marcare, rif_ex, zitto)
    assert len(marcate) == 2, "marca() non deve togliere nessuno"
    assert marcate[0]["ex_cliente"]["motivo"] == "ex cliente: Perso per prezzo"
    assert marcate[0]["ex_cliente"]["riconosciuto_per"] == "ragione+comune"
    assert "ex_cliente" not in marcate[1]

    # aziende senza sito già in `aziende`: niente dominio né P.IVA, gli indici
    # unici del DB non le proteggono -> qui protegge ragione+comune
    rif_db = riferimenti([{"nome": "Officina Y", "comune": "Tivoli"}])
    assert _criterio({"nome": "OFFICINA Y S.N.C.", "sito": "", "comune": "Tivoli"},
                     rif_db) == "ragione+comune"
    assert filtra([{"nome": "Officina Y snc", "comune": "Tivoli"}],
                  rif_db, "già in aziende", zitto) == []
    assert len(filtra([{"nome": "Officina Y", "comune": "Pomezia"}],
                      rif_db, "già in aziende", zitto)) == 1  # altro comune: passa
    print("ok")
