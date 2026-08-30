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
    return rif


def cerca_riferimento(s: dict, rif: dict) -> tuple[str | None, dict | None]:
    """-> (criterio che ha fatto match, riga sorgente) oppure (None, None)."""
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
    return None, None


def _criterio(s: dict, rif: dict) -> str | None:
    return cerca_riferimento(s, rif)[0]


def filtra(schede: list[dict], rif: dict, etichetta: str, log=print) -> list[dict]:
    """Toglie le schede che matchano i riferimenti, loggando ognuna col criterio."""
    tenute = []
    for s in schede:
        criterio = _criterio(s, rif)
        if criterio:
            log(f"escluso [{etichetta} / {criterio}]: {s.get('nome', '?')}"
                f" ({s.get('comune') or s.get('sito') or '-'})")
        else:
            tenute.append(s)
    log(f"filtro {etichetta}: {len(schede)} -> {len(tenute)}")
    return tenute


def marca(schede: list[dict], rif: dict, log=print) -> list[dict]:
    """NON toglie niente: annota su quali schede il committente ha già
    lavorato (ex clienti da riattivare). Il commerciale deve saperlo, ma
    l'azienda resta nei risultati."""
    marcate = 0
    for s in schede:
        criterio, riga = cerca_riferimento(s, rif)
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
    assert _criterio({"nome": "PM Serramenti", "comune": "Roma"}, rif) is None  # altro comune
    assert _criterio({"nome": "Fabbro Nuovo", "comune": "Roma"}, rif) is None

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
