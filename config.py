"""Costanti, soglie ed elenchi comuni (PRD §4-§7).

I valori vengono dai test di sourcing e classificazione già validati:
non cambiarli senza motivo (e senza rilanciare il regression, §8).
Le chiavi API stanno in .env, mai qui.
"""

import os as _os
import re

# Il Python di python.org non installa i certificati CA: senza questo, ogni
# chiamata HTTPS fatta con urllib (Exa, Openapi) fallisce con
# CERTIFICATE_VERIFY_FAILED. Stessa soluzione del test di sourcing.
if not _os.environ.get("SSL_CERT_FILE"):
    try:
        import certifi as _certifi

        _os.environ["SSL_CERT_FILE"] = _certifi.where()
    except ImportError:  # pragma: no cover
        if _os.path.exists("/etc/ssl/cert.pem"):
            _os.environ["SSL_CERT_FILE"] = "/etc/ssl/cert.pem"

# --- Modello e costi (§7) ---
MODELLO = "claude-sonnet-4-6"
# Prezzi Anthropic per Claude Sonnet 4.6 (docs: $3.00 / $15.00 per milione di token)
PREZZO_INPUT_USD_PER_TOKEN = 3.00 / 1_000_000
PREZZO_OUTPUT_USD_PER_TOKEN = 15.00 / 1_000_000
# ponytail: cambio fisso, non una chiamata a un servizio FX. Aggiornalo a mano se conta.
USD_EUR = 0.92
MAX_TOKENS_RISPOSTA = 2000

# --- Sourcing Maps via Apify (§4, dal test comparato) ---
ATTORE_MAPS = "compass/crawler-google-places"  # store Apify: "Google Maps Scraper"
CATEGORIE_MAPS = ("fabbro", "serramenti in ferro", "carpenteria metallica")
MAX_RISULTATI_PER_QUERY = 20
LINGUA_MAPS = "it"
PAESE_MAPS = "it"   # senza, l'attore geolocalizza dagli USA (Rome, NY)

PROVINCE = {"RM": "Roma", "LT": "Latina", "FR": "Frosinone",
            "RI": "Rieti", "VT": "Viterbo"}
REGIONE_CICLO = "Lazio"   # perimetro del primo ciclo (§1)

# Il modello restituisce `sede_provincia` a volte come sigla ("RM") e a
# volte per esteso ("Roma"); Google Maps mette in `state` il nome
# amministrativo completo ("Provincia di Latina", "Città metropolitana di
# Roma Capitale") e solo nel 6% dei casi la sigla. In archivio finivano come
# valori DISTINTI e il menu di filtro dell'app mostrava piu' voci per la
# stessa provincia, con le aziende divise fra loro. Si scrive sempre la sigla.
#
# PERCHE' QUESTA TABELLA E' SICURA E NON VA MANTENUTA: le province italiane
# sono un elenco CHIUSO di 107 voci. Non cresce aprendo Puglia o Lombardia —
# ci sono gia' — e cambia solo con una legge dello Stato, cosa che accade
# una volta ogni molti anni. E' l'opposto di una tabella di comuni, che
# sarebbe 8.000 voci da estendere regione per regione: quella strada e'
# stata valutata e scartata proprio per questo (vedi README, Province).
# Se una provincia mancasse, il valore resta com'e' e viene loggato: nessuna
# sigla inventata.
SIGLE_PROVINCE = {
    # Abruzzo
    "l'aquila": "AQ", "aquila": "AQ", "chieti": "CH", "pescara": "PE",
    "teramo": "TE",
    # Basilicata
    "matera": "MT", "potenza": "PZ",
    # Calabria
    "catanzaro": "CZ", "cosenza": "CS", "crotone": "KR",
    "reggio calabria": "RC", "vibo valentia": "VV",
    # Campania
    "avellino": "AV", "benevento": "BN", "caserta": "CE", "napoli": "NA",
    "salerno": "SA",
    # Emilia-Romagna
    "bologna": "BO", "ferrara": "FE", "forlì-cesena": "FC",
    "forli-cesena": "FC", "modena": "MO", "parma": "PR", "piacenza": "PC",
    "ravenna": "RA", "reggio emilia": "RE", "rimini": "RN",
    # Friuli-Venezia Giulia
    "gorizia": "GO", "pordenone": "PN", "trieste": "TS", "udine": "UD",
    # Lazio
    "frosinone": "FR", "latina": "LT", "rieti": "RI", "roma": "RM",
    "viterbo": "VT",
    # Liguria
    "genova": "GE", "imperia": "IM", "la spezia": "SP", "savona": "SV",
    # Lombardia
    "bergamo": "BG", "brescia": "BS", "como": "CO", "cremona": "CR",
    "lecco": "LC", "lodi": "LO", "mantova": "MN", "milano": "MI",
    "monza e della brianza": "MB", "monza e brianza": "MB", "pavia": "PV",
    "sondrio": "SO", "varese": "VA",
    # Marche
    "ancona": "AN", "ascoli piceno": "AP", "fermo": "FM", "macerata": "MC",
    "pesaro e urbino": "PU",
    # Molise
    "campobasso": "CB", "isernia": "IS",
    # Piemonte
    "alessandria": "AL", "asti": "AT", "biella": "BI", "cuneo": "CN",
    "novara": "NO", "torino": "TO", "verbano-cusio-ossola": "VB",
    "vercelli": "VC",
    # Puglia
    "bari": "BA", "barletta-andria-trani": "BT", "brindisi": "BR",
    "foggia": "FG", "lecce": "LE", "taranto": "TA",
    # Sardegna
    "cagliari": "CA", "nuoro": "NU", "oristano": "OR", "sassari": "SS",
    "sud sardegna": "SU",
    # Sicilia
    "agrigento": "AG", "caltanissetta": "CL", "catania": "CT", "enna": "EN",
    "messina": "ME", "palermo": "PA", "ragusa": "RG", "siracusa": "SR",
    "trapani": "TP",
    # Toscana
    "arezzo": "AR", "firenze": "FI", "grosseto": "GR", "livorno": "LI",
    "lucca": "LU", "massa-carrara": "MS", "massa e carrara": "MS",
    "pisa": "PI", "pistoia": "PT", "prato": "PO", "siena": "SI",
    # Trentino-Alto Adige
    "bolzano": "BZ", "trento": "TN",
    # Umbria
    "perugia": "PG", "terni": "TR",
    # Valle d'Aosta
    "aosta": "AO", "valle d'aosta": "AO",
    # Veneto
    "belluno": "BL", "padova": "PD", "rovigo": "RO", "treviso": "TV",
    "venezia": "VE", "verona": "VR", "vicenza": "VI",
}

# "Provincia di X", "Città metropolitana di X Capitale", "Libero consorzio
# comunale di X": Maps usa tutte queste forme. Il nome vero e' quello che
# resta togliendole.
_PREFISSI_PROVINCIA = re.compile(
    r"^(provincia\s+di\s+|provincia\s+dell['’]|provincia\s+del\s+|"
    r"citt[aà]\s+metropolitana\s+di\s+|libero\s+consorzio\s+comunale\s+di\s+)",
    re.IGNORECASE)
_CODA_PROVINCIA = re.compile(r"\s+capitale$", re.IGNORECASE)


def sigla_provincia(valore: str | None, log=None) -> str | None:
    """-> sigla a due lettere. Un valore sconosciuto torna invariato.

    Accetta sia la sigla, sia il nome nudo, sia le forme amministrative di
    Google Maps ("Città metropolitana di Roma Capitale" -> RM).
    """
    v = (valore or "").strip()
    if not v:
        return None
    if len(v) == 2:
        return v.upper()
    nudo = _CODA_PROVINCIA.sub("", _PREFISSI_PROVINCIA.sub("", v)).strip()
    if len(nudo) == 2:
        return nudo.upper()
    sigla = SIGLE_PROVINCE.get(nudo.lower())
    if sigla:
        return sigla
    if log:
        log(f"provincia '{v}' non in SIGLE_PROVINCE: lasciata invariata")
    return v


# --- Sourcing Exa (§4, le 5 query del test) ---
QUERY_EXA = (
    "officina fabbro cancelli e inferriate in ferro provincia di {provincia}",
    "serramentista che produce persiane e grate di sicurezza {provincia}",
    "carpenteria metallica leggera lavorazione ferro provincia di {provincia}",
    "produzione persiane blindate e grate su misura {provincia}",
    "fabbro artigiano lavorazione ferro battuto {provincia} e provincia",
)
EXA_NUM_RISULTATI = 25

# --- Portali e domini da escludere (dal test, lista già estesa) ---
PORTALI_ESCLUSI = (
    "paginegialle", "paginebianche", "facebook", "instagram", "linkedin",
    "youtube", "subito.it", "amazon", "ebay", "wikipedia", "virgilio",
    "misterimprese", "cylex", "trovaimpresa", "houzz", "habitissimo",
    "instapro", "prontopro", "edilnet", "yelp", "tripadvisor", "google.",
    "pinterest", "europages", "pgcasa", "leroymerlin",
    "exa.ai", "tavily.com", "apify.com",  # i motori restituiscono se stessi
)

# Portali di INTERMEDIAZIONE trovati nel primo ciclo Roma (2026-09-08):
# raccolgono contatti e li girano agli artigiani, non producono niente.
# Tenuti separati dai social perche' i due casi NON si trattano allo stesso
# modo: un'azienda vera il cui unico sito e' una pagina Facebook resta in
# archivio (sito debole, azienda reale), un portale no.
# Elencati per DOMINIO e non per forma del nome perche' la forma non
# distingue: "gratedisicurezza-roma.it" e' intermediazione,
# "carpenteriabianchini.it" e' un'azienda vera. La distinzione sta nel
# merito, e per i cicli futuri la fa la regola 9 del prompt; questa lista
# chiude solo i sei che erano gia' passati.
PORTALI_INTERMEDIAZIONE = (
    "archisio.it", "fabbro.roma.it", "ristrutturazione.roma.it",
    "gratedisicurezza-roma.it", "emergenza-fabbro.it", "assisitop.it",
)
PORTALI_ESCLUSI = PORTALI_ESCLUSI + PORTALI_INTERMEDIAZIONE

# --- Filtro territorio (§5) ---
PREFISSI_CAP_LAZIO = ("00", "01", "02", "03", "04")
PREFISSI_TEL_LAZIO = ("06", "0746", "0761",
                      "0771", "0772", "0773", "0774", "0775", "0776")
# prefissi telefonici forti di altre regioni (grandi città): solo questi
# possono produrre `fuori`. Un prefisso non in nessuna delle due liste
# non è un segnale: si resta `incerto` (es. 0765/0766, Lazio non in lista).
PREFISSI_TEL_FUORI = (
    "02", "010", "011", "030", "031", "035", "039", "040", "041", "045",
    "049", "051", "055", "059", "070", "071", "080", "081", "090", "091", "095",
)

# --- Fetch (§6) ---
MAX_FETCH_SIMULTANEI = 3  # siti di artigiani, gentilezza obbligatoria (§2)
MAX_PAGINE_INTERNE = 4
MAX_PAROLE = 15_000
TIMEOUT_FETCH_MS = 30_000

# --- Mappatura classi → DB (§7) ---
# TARGET+alta→A, TARGET+media→B, dubbi fondati→C, resto→indeterminato.
# La logica sta in classify.py; i valori validi sono in ENUM_CLASSE (in fondo).
# "organico ampio" per la modulazione dipendenti (§7): fabbro sopra soglia
# scende di una classe (probabile reparto saldatura strutturato).
# ponytail: soglia a stima, da tarare coi primi dati Openapi reali.
SOGLIA_ORGANICO_AMPIO = 15

# --- Arricchimento Openapi (§9) ---
# L'API Imprese del PRD è stata deprecata il 31/12/2025: la sostituisce la
# Company API. IT-advanced è il livello minimo che include i dipendenti.
ENDPOINT_OPENAPI = "IT-advanced"
# Listino agosto 2026: 30 chiamate/mese gratuite, poi €0,10+IVA a consumo
# (€0,028 solo con piano annuale da 1M chiamate). Il PRD stimava €0,05:
# il report costi (§9) usa questo valore, non quello del PRD.
COSTO_OPENAPI_EUR = 0.10
CHIAMATE_OPENAPI_GRATUITE_MESE = 30
# Quali classi arricchire. Il §9 dice A e B.
# ATTENZIONE al risparmio atteso: il "circa due terzi" scritto qui prima
# nasceva da un campione piccolo ed e' FALSO. Misurato sul ciclo Roma del
# 2026-09-07, 194 aziende: A=55, B=20 — le A sono il 73% delle A+B, non il
# 40%. Restringere ad ("A",) taglia Openapi del 27%, non di due terzi.
# Openapi serve a P.IVA, sede e dipendenti: sulle classi escluse la
# modulazione organico non si applica e la scheda resta senza P.IVA.
CLASSI_DA_ARRICCHIRE = ("A",)

# --- Reputazione Google (dalla scheda Maps) ---
# ATTENZIONE: dal 2026-09-07 queste soglie NON assegnano piu' la classe A.
# Restano solo a documentare cosa sia una reputazione forte; il dato finisce
# nei `segnali` ed e' visibile in scheda, ma non concorre alla priorita'.
#
# Perche' e' stata tolta (misurato sul ciclo Roma, 64 aziende in classe A):
# 12 ci arrivavano per la sola reputazione, e NESSUNA DELLE 12 aveva
# officina accertata — erano showroom e rivenditori di PVC e alluminio
# (Oknoplast, Allutek, "Nostra Casa Infissi in PVC" con 380 recensioni).
# Il numero di recensioni misura la visibilita' verso il consumatore, non la
# qualita' del prospect: un fabbro B2B non ne riceve per ragioni
# strutturali. La soglia selezionava quindi un capo solo del perimetro.
# Non erano prospect sbagliati — dopo il cambio di perimetro chi vende al
# cliente finale e' target — ma sono da PRODOTTO FINITO, non da kit, e
# stanno bene in B.
# La ragione di fondo: la classe A deve voler dire UNA cosa leggibile
# ("ha un bisogno visibile, oppure ha un'officina"). Con tre vie diventava
# "una di tre cose diverse" e il commerciale non sapeva cosa guardava.
# NON REINTRODURRE senza rifare questa misura.
#
# Soglie sui dati reali: 50 recensioni è l'ultimo quintile (19% del
# campione), 4.5 è un punteggio solido senza essere raro.
SOGLIA_RECENSIONI_FORTE = 50
SOGLIA_PUNTEGGIO_FORTE = 4.5

# --- Verniciatura interna: indizio per l'ASSEMBLATO GREZZO (catalogo 2026-09) ---
# Il catalogo descrive tre livelli, non due: kit semilavorato, assemblato
# grezzo e prodotto finito. Il grezzo e' "la soluzione ideale per chi vuole
# gestire autonomamente la verniciatura".
# NON si assegna `livello_fornitura`: non sappiamo distinguere in modo
# affidabile chi ha solo la verniciatura da chi ha l'officina completa, e
# il sistema non deve inventare un'assegnazione che non puo' provare.
# Si aggiunge solo un segnale, che il commerciale legge in scheda e usa in
# trattativa. Misurato sull'archivio Roma: 42 aziende su 1169, 38 delle
# quali in classe A.
INDIZI_VERNICIATURA = ("verniciatura a polvere", "verniciatura a forno",
                       "zincatura", "impianto di verniciatura")
NOTA_VERNICIATURA = "può interessare l'assemblato grezzo"

# --- Segnali di lavoro (§9) ---
# Ordine = priorità. Il saldatore pesa più di tutti: è la figura che il
# cliente ha indicato come in via di sparizione ed è l'argomento di vendita
# del prodotto (sistema a incastro che non richiede saldatura). Gli altri
# seguono nell'ordine del PRD.
RUOLI_ANNUNCI = ("saldatore", "operaio", "carpentiere", "magazziniere")
# radici esplicite per il match su plurali e femminili: derivarle a codice
# è fragile (operaio -> operai, ma carpentiere -> carpentier)
# "saldat" copre anche "addetto alla saldatura", formulazione frequentissima
# negli annunci: la radice si applica solo a risultati già filtrati per
# portale o pagina lavora-con-noi, quindi non pesca chi fa saldatura e basta
RADICI_ANNUNCI = {"saldatore": "saldat", "operaio": "operai",
                  "carpentiere": "carpentier", "magazziniere": "magazzinier"}
DOMINI_ANNUNCI = ("indeed", "infojobs", "subito", "bakeca")
# una pagina "lavora con noi" sul sito aziendale vale come annuncio
PERCORSI_ANNUNCI = ("lavora-con-noi", "lavora_con_noi", "lavoraconnoi",
                    "lavora con noi", "posizioni-aperte", "careers")

# --- Prezzi delle fonti esterne (§9) ---
# Letti dalla documentazione ad agosto 2026, non stimati. Vanno nel report
# consumi al cliente come voci DISTINTE, non aggregate.
# Exa: $7 / 1k ricerche + $1 / 1k pagine per tipo di contenuto (noi: highlights)
PREZZO_EXA_RICERCA_USD = 0.007
PREZZO_EXA_PAGINA_USD = 0.001
# Apify compass/crawler-google-places: "from $1.50 / 1,000 scraped places".
# È il prezzo base: sui piani superiori scende. Verificare sul piano reale
# dell'account prima del report costi.
PREZZO_APIFY_SCHEDA_USD = 0.0015

# --- Elenco clienti del committente (§11) ---
# Solo questi stati escludono l'azienda dalla ricerca: gli altri sono ex
# clienti da riattivare, si caricano ma restano nei risultati marcati.
STATI_CLIENTE_ATTIVO = ("attivo", "fidelizzato")
MOTIVO_CLIENTE_ATTIVO = "cliente attivo"
MOTIVO_EX_CLIENTE = "ex cliente"
# L'azienda committente stessa: la pipeline l'ha trovata a Roma e
# classificata A, correttamente — non poteva sapere che era lei. Non e' un
# cliente, quindi ha un motivo suo, ma ESCLUDE come loro.
MOTIVO_COMMITTENTE = "azienda committente"
# Chi porta uno di questi motivi esce dalla ricerca; tutto il resto sono ex
# clienti, che si marcano e restano. Il confronto era `== MOTIVO_CLIENTE_ATTIVO`
# in tre punti: un motivo nuovo sarebbe finito fra gli ex e avrebbe MARCATO
# il committente invece di escluderlo.
MOTIVI_CHE_ESCLUDONO = (MOTIVO_CLIENTE_ATTIVO, MOTIVO_COMMITTENTE)


def esclude(motivo: str | None) -> bool:
    """Il motivo di `esclusioni` toglie l'azienda dalla ricerca?"""
    return (motivo or "").strip().lower() in MOTIVI_CHE_ESCLUDONO
# lo stesso valore scritto in due modi nel file compilato a mano
CATEGORIE_CLIENTI_ALIAS = {
    "show room": "showroom", "showroom": "showroom",
    "serramenti": "serramentista", "serramentista": "serramentista",
    "fabbro": "fabbro", "artigiano": "artigiano", "costruttore": "costruttore",
    "impresa edile": "impresa_edile", "studio tecnico": "altro",
    "mediatore imm.": "altro", "architetto": "altro",
}

# --- Enum Postgres (letti dallo schema reale il 2026-08-25) ---
# Postgres rifiuta qualunque stringa non compresa: questi valori devono
# corrispondere carattere per carattere. Nota: il modello risponde in
# MAIUSCOLO ("SI", "ALTA"), il DB vuole minuscolo.
ENUM_CATEGORIA = ("fabbro", "serramentista", "showroom", "impresa_edile",
                  "costruttore", "artigiano", "montatore", "ferramenta", "altro")
ENUM_TERNARIO = ("si", "no", "non_determinabile")
ENUM_CLASSE = ("A", "B", "C", "indeterminato")
ENUM_CONFIDENZA = ("alta", "media", "bassa")
ENUM_DIMENSIONE = ("micro", "piccola", "media", "grande")
ENUM_FORNITURA = ("kit", "assemblato_grezzo", "prodotto_finito")
ENUM_STATO = ("da_lavorare", "contattato", "ricontattato", "in_trattativa",
              "cliente", "scartato", "da_chiamare", "nessuna_risposta")

# Livello di fornitura per categoria: NON è un giudizio del modello, è una
# decisione commerciale del cliente misurata sui suoi 30 clienti attuali.
# Il serramentista è l'unico ambivalente (dipende dall'officina) e resta
# null, come le categorie su cui il cliente non si è pronunciato.
FORNITURA_PER_CATEGORIA = {
    "fabbro": "kit",
    "showroom": "prodotto_finito",
    "impresa_edile": "prodotto_finito",
    "costruttore": "prodotto_finito",
}

# --- Bozze email (testi approvati dal cliente, PDF del 2026-08-31) ---
# La firma e il sito sono dati del MITTENTE: si compilano una volta qui.
# Se restano vuoti, il generatore chiude senza firma invece di lasciare
# un segnaposto in chiaro nella bozza.
# Le email escono a nome dell'azienda, non del singolo commerciale: la
# casella e' condivisa, quindi la firma e' una costante e non si legge da
# `assegnato_a`.
FIRMA_EMAIL = "Carpenterie Laziali"
# In chiusura andra' il link al CATALOGO, non al sito: si compila quando il
# cliente lo manda. Finche' e' vuoto, la chiusura resta la sola firma.
SITO_EMAIL = ""
# Link usati dai due testi del catalogo. Vuoti finche' non arrivano: la
# frase che li conterrebbe sparisce, mai un segnaposto in chiaro.
LINK_CATALOGO = ("https://pvxzrfthfhbhslxhjihu.supabase.co/storage/v1/object/"
                 "public/catalogo%20pubblico/Catalogo%20Carpenterie%20Laziali.pdf")
LINK_PRENOTAZIONE = ""    # es. "cal.com/carpenterielaziali/10min"
# Parole che non devono MAI comparire in una bozza: il PDF vieta di citare
# gli annunci di lavoro, e la guida vieta claim su tempi e certificazioni.
VIETATE_EMAIL = ("saldator", "annuncio", "assunzione", "cercate", "offerta di lavoro",
                 "garantiam", "certificat", "risparmi", "sconto", "24 ore",
                 "48 ore", "consegna rapida", "prezzi imbattibili")


if __name__ == "__main__":
    # le province italiane sono 107: se questo numero cambia, e' cambiata
    # una legge dello Stato, non un dato di questo progetto
    assert len(set(SIGLE_PROVINCE.values())) == 107, len(set(SIGLE_PROVINCE.values()))
    assert sigla_provincia("Città metropolitana di Roma Capitale") == "RM"
    assert sigla_provincia("Provincia di Latina") == "LT"
    assert sigla_provincia("Provincia dell'Aquila") == "AQ"
    assert sigla_provincia("Città Metropolitana di Bari") == "BA"   # M maiuscola
    assert sigla_provincia("Monza e della Brianza") == "MB"
    assert sigla_provincia("Roma") == "RM" and sigla_provincia("roma") == "RM"
    assert sigla_provincia("RM") == "RM" and sigla_provincia("rm") == "RM"
    assert sigla_provincia("Provincia di RM") == "RM"
    # una provincia sconosciuta resta com'e': mai una sigla inventata
    assert sigla_provincia("Oltrepo") == "Oltrepo"
    assert sigla_provincia("") is None and sigla_provincia(None) is None
    # le cinque del Lazio, che sono il perimetro di oggi
    for nome, sigla in (("Roma", "RM"), ("Latina", "LT"), ("Frosinone", "FR"),
                        ("Rieti", "RI"), ("Viterbo", "VT")):
        assert sigla_provincia(f"Provincia di {nome}") == sigla
        assert sigla in PROVINCE

    assert esclude(MOTIVO_CLIENTE_ATTIVO) and esclude(MOTIVO_COMMITTENTE)
    assert esclude(" Cliente Attivo ")          # il file e' compilato a mano
    assert not esclude(f"{MOTIVO_EX_CLIENTE}: perso per prezzo")
    assert not esclude("") and not esclude(None)
    print("ok")
