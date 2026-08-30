"""Costanti, soglie ed elenchi comuni (PRD §4-§7).

I valori vengono dai test di sourcing e classificazione già validati:
non cambiarli senza motivo (e senza rilanciare il regression, §8).
Le chiavi API stanno in .env, mai qui.
"""

import os as _os

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
