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
# Senza timeout esplicito una risposta che non arriva blocca il processo per
# sempre: il 2026-09-15 un giro di rianalisi e' rimasto fermo 89 minuti su
# una sola chiamata, con 6 secondi di CPU e il socket in ESTAB. Di notte il
# cron sarebbe rimasto appeso allo stesso modo, senza che nessuno lo sapesse.
# 180 secondi sono larghi per una pagina da 15.000 parole ma finiti.
TIMEOUT_ANTHROPIC_S = 180

# --- Sourcing Maps via Apify (§4, dal test comparato) ---
ATTORE_MAPS = "compass/crawler-google-places"  # store Apify: "Google Maps Scraper"
CATEGORIE_MAPS = ("fabbro", "serramenti in ferro", "carpenteria metallica")
MAX_RISULTATI_PER_QUERY = 20
# Ricerche DENSE (9/10): se una ricerca riempie i 20 posti con almeno 15
# schede della provincia cercata, la zona e' tagliata e si ripete con 60.
# Nella Toscana erano 23 ricerche su 361: di solito Maps riempie i 20 posti
# con aziende lontane, e allargare tutto costerebbe senza trovare niente.
SOGLIA_RICERCA_DENSA = 15
MAX_RISULTATI_ALLARGATA = 60
LINGUA_MAPS = "it"
PAESE_MAPS = "it"   # senza, l'attore geolocalizza dagli USA (Rome, NY)

# --- Regioni attive (§1): il Lazio dal primo ciclo, le altre cinque dal
# 2026-10-07 (costi approvati dal committente). Fuori dal Lazio Claudia
# vende sia prodotto finito sia kit: la distanza non penalizza nessuno, e
# il territorio e' "dentro" in TUTTE le regioni attive, qualunque sia la
# provincia del ciclo. Per ogni regione: province (sigla -> nome per Exa),
# prefissi CAP (le prime due cifre) e prefissi telefonici dei fissi.
# Aprire una regione = aggiungerla qui + i suoi comuni in data/comuni.py.
REGIONI = {
    "Lazio": {
        "province": {"RM": "Roma", "LT": "Latina", "FR": "Frosinone",
                     "RI": "Rieti", "VT": "Viterbo"},
        "cap": ("00", "01", "02", "03", "04"),
        # 0765/0766 sono laziali ma condivisi o incerti: non in lista
        "tel": ("06", "0746", "0761", "0771", "0772", "0773", "0774",
                "0775", "0776"),
    },
    "Toscana": {
        "province": {"FI": "Firenze", "PO": "Prato", "PT": "Pistoia",
                     "LU": "Lucca", "MS": "Massa-Carrara", "PI": "Pisa",
                     "LI": "Livorno", "AR": "Arezzo", "SI": "Siena",
                     "GR": "Grosseto"},
        "cap": ("50", "51", "52", "53", "54", "55", "56", "57", "58", "59"),
        # 0187 (Lunigiana) e' condiviso con La Spezia: non in lista
        "tel": ("055", "050", "0564", "0565", "0566", "0571", "0572", "0573",
                "0574", "0575", "0577", "0578", "0583", "0584", "0585",
                "0586", "0587", "0588"),
    },
    "Campania": {
        "province": {"NA": "Napoli", "CE": "Caserta", "SA": "Salerno",
                     "AV": "Avellino", "BN": "Benevento"},
        "cap": ("80", "81", "82", "83", "84"),
        "tel": ("081", "089", "0823", "0824", "0825", "0827", "0828",
                "0974", "0975"),
    },
    "Puglia": {
        "province": {"BA": "Bari", "BT": "Barletta-Andria-Trani",
                     "FG": "Foggia", "BR": "Brindisi", "LE": "Lecce",
                     "TA": "Taranto"},
        # 75 e' Matera (Basilicata): non in lista
        "cap": ("70", "71", "72", "73", "74", "76"),
        "tel": ("080", "099", "0831", "0832", "0833", "0836", "0881",
                "0882", "0883", "0884", "0885"),
    },
    "Abruzzo": {
        "province": {"AQ": "L'Aquila", "CH": "Chieti", "PE": "Pescara",
                     "TE": "Teramo"},
        "cap": ("64", "65", "66", "67"),
        "tel": ("085", "0861", "0862", "0863", "0864", "0871", "0872",
                "0873"),
    },
    "Marche": {
        "province": {"AN": "Ancona", "PU": "Pesaro e Urbino", "MC": "Macerata",
                     "AP": "Ascoli Piceno", "FM": "Fermo"},
        "cap": ("60", "61", "62", "63"),
        "tel": ("071", "0721", "0722", "0731", "0732", "0733", "0734",
                "0735", "0736", "0737"),
    },
}
PROVINCE = {s: n for r in REGIONI.values() for s, n in r["province"].items()}
REGIONE_DI = {s: nome for nome, r in REGIONI.items() for s in r["province"]}
SIGLE_ATTIVE = tuple(PROVINCE)
REGIONI_ATTIVE = tuple(REGIONI)

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
    # forme storiche e alias (le soppresse sarde -> chi le ha assorbite)
    "sulcis iglesiente": "SU", "carbonia-iglesias": "SU",
    "carbonia iglesias": "SU", "medio campidano": "SU",
    "olbia-tempio": "SS", "olbia tempio": "SS", "ogliastra": "NU",
    # 'Provincia della Spezia' spogliata del prefisso lascia 'spezia'
    "spezia": "SP", "aquila": "AQ",
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
    r"^(provincia\s+autonoma\s+di\s+|provincia\s+regionale\s+di\s+|"
    r"provincia\s+di\s+|provincia\s+dell['’]|provincia\s+del(la|lo)?\s+|"
    r"citt[aà]\s+metropolitana\s+di\s+|libero\s+consorzio\s+comunale\s+di\s+)",
    re.IGNORECASE)
# Province SOPPRESSE: le quattro sarde abolite nel 2016 arrivano ancora
# dalle schede Maps, sia come sigla ("CI") sia per esteso ("Provincia del
# Sulcis Iglesiente"). Si normalizzano alla provincia che le ha assorbite:
# una sigla storica non deve passare per valida ne' per ignota.
SIGLE_STORICHE = {"CI": "SU", "VS": "SU", "OT": "SS", "OG": "NU"}
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
        return SIGLE_STORICHE.get(v.upper(), v.upper())
    nudo = _CODA_PROVINCIA.sub("", _PREFISSI_PROVINCIA.sub("", v)).strip()
    if len(nudo) == 2:
        return SIGLE_STORICHE.get(nudo.upper(), nudo.upper())
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
# Exa a provincia (12/10, misurato): 0,2-1,0 EUR (sourcing + segnali sulle
# TARGET). Il controllo pre-provincia chiede questo residuo nel registro.
STIMA_EXA_PROVINCIA_EUR = 1.5

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
PREFISSI_CAP_ATTIVI = tuple(c for r in REGIONI.values() for c in r["cap"])
# i piu' lunghi prima: "0571" va riconosciuto prima di un eventuale "05"
PREFISSI_TEL_ATTIVI = tuple(sorted({t for r in REGIONI.values() for t in r["tel"]},
                                   key=lambda t: (-len(t), t)))
# prefissi telefonici forti di altre regioni (grandi città): solo questi
# possono produrre `fuori`. Un prefisso non in nessuna delle due liste
# non è un segnale: si resta `incerto` (es. 0765/0766, Lazio non in lista).
# Si tolgono da soli quelli delle regioni attive (055, 071, 080, 081).
PREFISSI_TEL_FUORI = tuple(p for p in (
    "02", "010", "011", "030", "031", "035", "039", "040", "041", "045",
    "049", "051", "055", "059", "070", "071", "080", "081", "090", "091", "095",
) if not p.startswith(PREFISSI_TEL_ATTIVI))

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
# Quali classi arricchire con la visura Openapi (P.IVA, sede, dipendenti).
# TUTTE, dal 2026-09-22 con l'ok del cliente: la restrizione ad ("A",)
# dell'8/9 era una scelta di costo sul ciclo Roma, e ha lasciato B e C
# senza visura (dipendenti al 3% e 2% contro il 26% delle A) — pareggiate
# a mano il 22/9 sulle righe con P.IVA in scheda. Costo della regola sui
# cicli mensili: ~10-20 EUR/mese di voce Openapi in piu', dentro i consumi
# ordinari. Non e' una scelta di codice: il filtro sta in
# arricchimento.da_arricchire, e con l'aggancio per nome valgono le regole
# prudenti di arricchimento.decidi().
CLASSI_DA_ARRICCHIRE = ("A", "B", "C")
# VISURE (Openapi): variante 2, scelta del cliente l'8/10 — visure su A e
# B, ricerca per nome (senza P.IVA nel sito) solo per le A, nessuna visura
# sulle C. (La variante 1, scartata, era ("A","B","C") per entrambe.)
# CLASSI_DA_ARRICCHIRE resta per il ripasso email.
CLASSI_VISURA = ("A", "B")
CLASSI_VISURA_PER_NOME = ("A",)

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
# I fornitori del committente non sono prospect: gli vendono, non comprano.
# Erano una categoria che non esisteva, e uno (Codognola Serramenti) e'
# finito in elenco. Il committente fornisce la lista.
MOTIVO_FORNITORE = "fornitore"
# Chi porta uno di questi motivi esce dalla ricerca; tutto il resto sono ex
# clienti, che si marcano e restano. Il confronto era `== MOTIVO_CLIENTE_ATTIVO`
# in tre punti: un motivo nuovo sarebbe finito fra gli ex e avrebbe MARCATO
# il committente invece di escluderlo.
MOTIVI_CHE_ESCLUDONO = (MOTIVO_CLIENTE_ATTIVO, MOTIVO_COMMITTENTE,
                        MOTIVO_FORNITORE)


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
# Forma CANONICA verificata il 2026-09-23: risponde 200 diretta; senza
# www (e in http) fa 301 verso questa. Nelle email va quella che non
# fa redirect.
SITO_EMAIL = "https://www.carpenterielaziali.it"
# Link usati dai due testi del catalogo. Vuoti finche' non arrivano: la
# frase che li conterrebbe sparisce, mai un segnaposto in chiaro.
# versione leggera, 3 MB invece di 29: un allegato da 29 MB rimbalza su
# molte caselle aziendali
LINK_CATALOGO = ("https://pvxzrfthfhbhslxhjihu.supabase.co/storage/v1/object/"
                 "public/catalogo%20pubblico/Catalogo-Carpenterie-Laziali.pdf")
# Funzione di tracciamento click (Lovable, 2026-09-21): registra il click
# in `click_catalogo` e reindirizza al PDF. Il link nelle bozze e'
# PER-AZIENDA: base + id. Vuota -> si torna al PDF diretto.
LINK_TRACCIAMENTO = "https://commercialecarpenterie.lovable.app/api/public/catalogo?a="
LINK_PRENOTAZIONE = ""    # es. "cal.com/carpenterielaziali/10min"
# Parole che non devono MAI comparire in una bozza: il PDF vieta di citare
# gli annunci di lavoro, e la guida vieta claim su tempi e certificazioni.
# La lista elenca ESEMPI, non e' esaustiva: la regola del cliente vieta i
# claim sui tempi di consegna, e ogni modo nuovo di dirlo va aggiunto qui.
# "immediata", "in tempi brevi" e "subito disponibile" arrivano dal
# 2026-09-16, da una bozza generata che diceva "la fornitura e' immediata".
# Categorie Google palesemente fuori settore: la voce del sourcing che ne
# porta una NON entra in archivio (main la esclude come le chiuse, con
# conteggio nel log). Conservativo per costruzione: si confronta la
# CATEGORIA dichiarata da Google, non il nome — "Fabbro Barbieri Andrea"
# ha categoria "Fabbro" e passa; un salone si chiama come vuole ma la
# categoria dice "Parrucchiere". I dubbi restano dentro: qui solo
# l'inequivocabile.
CATEGORIE_FUORI_SETTORE = (
    "parrucchier", "barbier", "barber", "acconciatur", "estetist", "bellezza",
    "nail", "solarium", "tatua", "tattoo", "ristorant", "pizzeri",
    "trattoria", "osteria", "gelateri", "pasticceri", "panifici",
    "panetteri", "macelleri", "caffetteri", "tabacch", "farmaci",
    "dentist", "odontoiatr", "veterinari", "fisioterap", "palestra",
    "gioielleri", "profumeri", "lavanderi", "autoscuol", "supermercat",
    "alimentari", "abbigliament", "parruc",
    # dai dubbi risolti il 29/9: mestieri che non comprano ne' rivendono
    "idraulic", "riscaldament", "condizionament", "rottam", "noleggio",
)


# L'elenco ESATTO delle categorie giudicate fuori settore nella revisione
# del 2026-09-29 (criterio del cliente: "puo' comprare o rivendere
# carpenteria metallica e serramenti?"). Congela la decisione voce per
# voce, dove le parole chiave qui sopra non arrivano. DENTRO per scelta
# esplicita, quindi MAI qui: Falegname, Duplicazione chiavi, Bricolage,
# Automazione (cancelli), Appaltatore, casseforti/scaffalature/utensili,
# ascensori, trattori agricoli, le categorie opache (Ufficio aziendale,
# Negozio, Laboratorio...) e i PRESCRITTORI (ingegneri, architetti,
# designer): non comprano ma prescrivono — seme del tema architetti.
CATEGORIE_FUORI_ESATTE = (
    'Agenzia di noleggio gru', 'Agriturismo',
    'Alimentari', 'Alloggio turistico',
    'Appartamento', 'Artista',
    'Attrazione turistica', 'Autodemolitore',
    'Azienda di autotrasporti', 'Azienda informatica',
    'Banca', 'Barbiere',
    'Bed & Breakfast', 'Benzinaio',
    'Calzolaio', 'Casa di campagna',
    'Casa per vacanze', 'Casalinghi',
    'Castello', 'Centralina telefonica',
    'Centro commerciale', 'Centro di riciclaggio',
    'Centro diagnostico', 'Centro informazioni turistiche',
    'Centro oculistico', 'Chiesa',
    'Chiesa cattolica', 'Cioccolateria',
    'Clinica dentale', 'Clinica medica',
    'Commercialista', "Commercialista abilitato all'esercizio della professione",
    'Compravendita rottami', 'Concessionario auto',
    'Consulente aziendale', 'Consulente del lavoro',
    'Copisteria', 'Ditta specializzata in impianti di riscaldamento',
    'Ditta specializzata in telecomunicazioni', 'Elettricista',
    'Erboristeria', 'Fisioterapista',
    'Fornaio', 'Fornitore di impianti di riscaldamento',
    'Gioielleria', 'Gioielliere',
    'Hotel', 'Idraulico',
    'Impianto depurazione acque', 'Installatore di impianti di condizionamento',
    'Istituto religioso', 'Macelleria',
    'Medico di famiglia', 'Mercato',
    'Mercato degli agricoltori', 'Municipio',
    'Museo', 'Negozio di antiquariato',
    'Negozio di biciclette', 'Negozio di forniture per hotel',
    "Negozio di fuochi d'artificio", 'Negozio di occhiali da sole',
    'Negozio di pneumatici', 'Negozio di prodotti agricoli',
    'Negozio per animali', 'Noleggio carrelli elevatori',
    'Officina autoriparazioni', 'Officina di riparazioni per camion',
    'Officina per la riparazione di moto', 'Organizzatore di eventi',
    'Organizzazione non profit', 'Ospedale',
    'Ospedale privato', 'Parcheggio gratuito',
    'Poligono di tiro', 'Progettista grafico',
    'Psicoterapeuta', 'Punto di riferimento storico',
    'Ristorante', 'Ristorante italiano',
    'Salone da parrucchiere', 'Santuario',
    'Servizi di trasporto', 'Servizio componenti elettrici per auto',
    'Servizio di gestione dei rifiuti', 'Servizio di pulizia di edifici',
    'Servizio di riparazione di pianoforti', 'Servizio di spedizione',
    'Servizio di stampa digitale', 'Servizio di traino',
    'Servizio per fosse biologiche', 'Servizio taxi',
    'Servizio traslochi', 'Sindacato',
    'Stamperia', 'Stamperia commerciale',
    'Stazione ferroviaria', 'Studio legale',
    'Tabaccheria', 'Tipografia digitale',
    'Toelettatura di animali domestici', 'Villa',
    'fermata trasporto pubblico',
    # enti pubblici, sanitari, scolastici e religiosi (7/10, "non clienti":
    # il commerciale non deve scrivergli). Quelli gia' visti in archivio
    # (Municipio, Ospedale, Clinica medica, Chiesa...) stanno sopra; qui le
    # categorie Google degli stessi tipi non ancora incontrate. NON qui:
    # 'Carcere' e 'Camera dell'artigianato', che in archivio etichettano un
    # fabbro e due serramentisti veri.
    'Ufficio comunale', 'Ufficio governativo', 'Ufficio pubblico',
    'Azienda sanitaria locale', 'Casa di cura', 'Casa di riposo',
    'Residenza per anziani', 'Poliambulatorio', 'Ambulatorio medico',
    'Laboratorio di analisi mediche', 'Pronto soccorso',
    'Scuola', 'Scuola primaria', 'Scuola secondaria', 'Scuola elementare',
    'Scuola media', 'Scuola superiore', 'Scuola materna', 'Asilo nido',
    'Liceo', 'Università', 'Biblioteca',
    'Parrocchia', 'Monastero', 'Convento', 'Abbazia', 'Basilica', 'Cattedrale',
    'Ufficio postale', 'Stazione di polizia', 'Stazione dei carabinieri',
    'Caserma', 'Tribunale', 'Prefettura', 'Questura', 'Cimitero',
    # dalla revisione dell'8/11 sull'archivio (committente): le categorie
    # estranee che il filtro lasciava passare. NON qui 'Pittura': in archivio
    # etichetta una metallurgica vera, e le categorie vaghe (Ufficio
    # aziendale, Produttore, Negozio): quelle restano dentro.
    'Agenzia di assicurazioni', 'Agenzia di design', 'Agenzia di pubblicità',
    'Agenzia funebre', 'Agenzia gestione affitti brevi', 'Agenzia per escursioni',
    'Alloggio', 'Appartamenti', 'Area di servizio', 'Area per passeggiate',
    'Arma dei Carabinieri', 'Asilo per cani diurno', 'Assistenza computer', 'Associazione',
    'Associazione / Organizzazione', 'Associazione artistica', 'Autocarrozziere',
    'Autoriparatore', 'Avvocato', 'Azienda agricola biologica', 'Azienda avicola',
    'Azienda vinicola', 'Bar caffè', 'Base militare', 'Birrificio', 'Broker finanziario',
    'Caffè', 'Call Center', 'Calzaturificio', 'Campo da calcio', 'Cappella', 'Carrozzeria',
    'Cartoleria', 'Casa', 'Casa di alta moda', 'Casa farmaceutica', 'Caseificio',
    'Cash and carry', 'Centro culturale', 'Centro di consulenza per i consumatori',
    'Centro di formazione', 'Centro di riabilitazione', 'Centro estetico', 'Centro medico',
    'Centro per la revisione tecnica delle auto', 'Chirurgo plastico', 'Circolo sociale',
    'Clinica di medicina dello sport', 'Complesso residenziale',
    'Concessionario di barche', 'Concessionario Hyundai', 'Concessionario Infiniti',
    'Concessionario moto', 'Concessionario scooter', 'Condominio',
    'Consulente finanziario', 'Consulente fiscale', 'Cucina italiana meridionale',
    'Deposito di materiali di recupero', 'Dermatologo', 'Destinazione religiosa', 'Diner',
    'Discarica per rifiuti speciali', 'DJ', 'Editore', 'Enoteca', 'Fabbrica di automobili',
    'Fabbricanti di barche', 'Fattoria', "Fermata dell'autobus", 'Fiorista', 'Fondazione',
    'Fontana di acqua potabile', "Fornaio all'ingrosso", 'Fornitore di accessori nautici',
    'Fornitore di attrezzatura per telecomunicazioni',
    'Fornitore di componenti elettronici', 'Gastronomia', 'Giardiniere',
    'Giardino pubblico', 'Grossista di carni', 'Hotel Resort', 'Hub di interscambio',
    'Impresa di organizzazione di eventi', 'Impresa di pulizie',
    'Laboratorio di serigrafia', 'Laboratorio per la riparazione di articoli elettronici',
    'Lavorazione di frutta e verdura', 'Libreria', 'Lodge', 'Manifattura tessile',
    'Meccanico', 'Meccanico e assistenza automobili', 'Medico', 'Mulino',
    "Museo all'aperto", "Museo d'arte", 'Museo storico locale',
    'Negozio di accessori di moda', 'Negozio di articoli per il giardinaggio',
    "Negozio di articoli per l'arte", 'Negozio di articoli per la decorazione di torte',
    'Negozio di articoli per la pesca', 'Negozio di articoli sportivi',
    'Negozio di biancheria', 'Negozio di cannabis', 'Negozio di computer',
    'Negozio di elettrodomestici', 'Negozio di elettronica',
    'Negozio di forniture ippiche', 'Negozio di forniture militari',
    'Negozio di generi vari', 'Negozio di macchine da cucire',
    'Negozio di magliette personalizzate', 'Negozio di materassi', 'Negozio di pianoforti',
    'Negozio di ricambi per auto', 'Negozio di ricambi per auto usati',
    'Negozio di scarpe', 'Negozio di strumenti a percussione',
    'Negozio di telefoni cellulari', 'Negozio di timbri in gomma', 'Negozio di vini',
    'Notaio', 'Notaio pubblico', 'Nutrizionista', 'Officina per la riparazione di barche',
    'Oleificio', 'Organizzatore di mostre', 'Organizzazione di volontariato', 'Ottico',
    'Parco', 'Parco giochi', 'Pelletteria', 'Piazza', 'Porticciolo turistico',
    'Produttore di alimentari', 'Produttore di alimenti',
    'Produttore di articoli elettronici', 'Produttore di maglieria',
    'Produttore di ricambi per auto', 'Produttore di tappeti',
    'Produzione distillati e liquori', "Punto d'interesse culturale", 'Punto panoramico',
    'Residence', 'Rifugio di montagna', 'Rilegatore', 'Riserva naturale', 'Ristopub',
    "Rivenditore d'oro", 'Rivenditore di auto', 'Rivenditore di auto usate', 'Sala giochi',
    'Sarto', 'Sartoria su misura', 'Scuola di educazione generale', 'Scuola di kung fu',
    'Scuola professionale', 'Servizi di chiaroveggenza', 'Servizi legali',
    'Servizio agricolo', 'Servizio di amministrazione immobiliare',
    'Servizio di contabilità', 'Servizio di produzione di video', 'Servizio di pulizia',
    'Servizio di raccolta rifiuti', 'Servizio di recupero dati', 'Servizio di ricamo',
    'Servizio di riparazione di bilance', 'Servizio di riparazione di elettrodomestici',
    'Servizio di riparazione di televisioni', 'Servizio di sgombero case', 'Sito storico',
    'Società immobiliare residenziale', 'Spa', 'Spedizioni e corrispondenza',
    'Stabilimento balneare', 'Stazione della metropolitana', 'Tappezziere',
    'Tappezziere per auto', 'Terme', "Ufficio dell'amministrazione comunale", 'Vivaio',
    'Web designer',
)


def fuori_settore_maps(categoria: str | None) -> bool:
    """La categoria Google e' palesemente estranea al settore?"""
    c = (categoria or "").strip().lower()
    if not c:
        return False            # vecchi sourcing senza il campo: si tiene
    # prima dell'eccezione sui produttori: l'elenco esatto e' una decisione
    # voce per voce ("Produttore di alimenti" e' deciso, le parole chiave no)
    if any(c == e.lower() for e in CATEGORIE_FUORI_ESATTE):
        return True
    if "produttore" in c or "produzione" in c or "fabbrica" in c:
        # chi PRODUCE non e' mai palesemente estraneo: "Produttore di
        # arredi per negozi e supermercati" conteneva "supermercat" ed era
        # un falso positivo (caso reale del 28/9). I dubbi restano dentro.
        return False
    if c == "bar":              # parola intera: "sbarre" non e' un bar
        return True
    return any(k in c for k in CATEGORIE_FUORI_SETTORE)


# Regole dell'8/11 per chi non ha una categoria Google (lista commerciale,
# Exa) e per l'analisi del sito. Conservative: una parola del settore nel
# testo basta a tenere la riga ("Hotel del ferro battuto" resta); il cognome
# Fabbri da solo non e' un mestiere estraneo.
_SETTORE = re.compile(
    r"\bferr[oaie]\b|ferramenta|\bfabbr[oi]\b|fabbrer|serram|infiss|carpent|metall|acciai|allumin"
    r"|\bedil|costruz|cancell|inferr|\bgrat[ae]\b|\bporte\b|portoni|finestr|persian|blindat"
    r"|saldat|tornit|zanzar|tapparell|avvolgib|vetr|\blegn|falegn|recinz|ringhier|lamier"
    r"|serratur|sicurezza", re.I)
_MESTIERI_ESTRANEI = (
    r"pasticceri|gelateri|panifici|panetteri|ristorant|pizzeri|trattoria|osteria|macelleri"
    r"|onoranze funebri|pompe funebri|impresa funebre|agenzia funebre"
    r"|\bhotel\b|albergo|agriturismo|parrucchier|centro estetico|istituto di bellezza|farmacia"
    r"|studio (?:legale|dentistico|medico|notarile)|\bnotaio\b|\bavvocat|commercialist"
    r"|carrozzeria|autofficina|gommista|parrocchia")
_NOME_ESTRANEO = re.compile(_MESTIERI_ESTRANEI, re.I)
_ATTIVITA_ESTRANEA = re.compile(
    _MESTIERI_ESTRANEI + r"|bed (?:and|&) breakfast|\bb&b\b|casa vacanze|struttura ricettiva"
    r"|azienda agricola|azienda vinicola|autoriparazion|concessionari[oa] (?:auto|moto)"
    r"|tipografia|stampa digitale|agenzia (?:immobiliare|di viaggi|di pubblicit|web)"
    r"|sviluppo software|centro medico|clinica|associazione|ente pubblico|\bcomune di\b|\bscuola\b", re.I)
MOTIVO_ANALISI_SITO = "fuori contesto (analisi sito)"


def fuori_settore_nome(nome: str | None) -> bool:
    """Lista commerciale ed Exa non hanno la categoria Google: decide il
    mestiere scritto nel nome, se non c'e' anche una parola del settore."""
    return bool(_NOME_ESTRANEO.search(nome or "")) and not _SETTORE.search(nome or "")


def fuori_settore_scheda(scheda: dict) -> bool:
    """Il filtro d'ingresso: la categoria Google se c'e', altrimenti il nome."""
    if (scheda.get("categoria_maps") or "").strip():
        return fuori_settore_maps(scheda["categoria_maps"])
    return fuori_settore_nome(scheda.get("nome"))


def attivita_estranea(dati: dict | None) -> bool:
    """L'analisi del sito mostra un'attivita' chiaramente diversa? Solo
    NON_TARGET e solo se la riga dell'attivita' nomina un mestiere estraneo
    senza alcuna parola del settore: nel dubbio la riga resta."""
    d = dati or {}
    a = d.get("attivita_prevalente") or ""
    return (d.get("classificazione") == "NON_TARGET" and bool(_ATTIVITA_ESTRANEA.search(a))
            and not _SETTORE.search(a))


# Soglie del controllo crediti PRE-giro (crediti.py). Stime dai cicli
# misurati: sourcing di una provincia 2,4-4,7 USD Apify; visure di un
# ciclo (A/B/C nuove, ~60-100 teste) 6-10 EUR Openapi.
STIMA_APIFY_CICLO_USD = 5.0
STIMA_OPENAPI_CICLO_EUR = 8.0
# Apify (9/10): il TETTO RIGIDO di una run (max_total_charge_usd) e' il
# massimo di schede che puo' restituire (ricerche x risultati) per il costo
# a scheda MISURATO in Toscana (20,22 USD su ~6.700 schede = 0,0030), piu'
# l'avvio. Una provincia parte solo se il residuo del periodo copre il suo
# tetto piu' APIFY_MARGINE_USD (decisione del committente: il piano non va
# oltre 100 USD/mese, e una provincia che non ci sta si fa dopo il rinnovo).
APIFY_USD_SCHEDA_MISURATO = 0.0030
APIFY_USD_AVVIO = 0.30
APIFY_MARGINE_USD = 2.0
# Openapi: visure ~0,10 EUR l'una, in proporzione alle A/B del ciclo.
# Misurato: RM 14,50, le altre del Lazio 4,40-7,10. Le tre grandi come RM.
STIMA_OPENAPI_GRANDI_EUR = 15.0
PROVINCE_GRANDI = ("RM", "NA", "FI", "BA")


def tetto_apify_usd(n_ricerche: int, per_ricerca: int = MAX_RISULTATI_PER_QUERY) -> float:
    """Tetto rigido di una run Maps: tutte le schede possibili al costo misurato."""
    return round(APIFY_USD_AVVIO + n_ricerche * per_ricerca * APIFY_USD_SCHEDA_MISURATO, 2)


def stima_openapi_eur(provincia: str) -> float:
    return STIMA_OPENAPI_GRANDI_EUR if provincia in PROVINCE_GRANDI \
        else STIMA_OPENAPI_CICLO_EUR

VIETATE_EMAIL = ("saldator", "annuncio", "assunzione", "cercate", "offerta di lavoro",
                 "garantiam", "certificat", "risparmi", "sconto", "24 ore",
                 "48 ore", "consegna rapida", "prezzi imbattibili",
                 "immediata", "in tempi brevi", "subito disponibile")


if __name__ == "__main__":
    # revisione dell'8/11
    for c_ in ("Agenzia funebre", "Carrozzeria", "Produttore di alimenti", "Negozio di elettronica"):
        assert fuori_settore_maps(c_), c_
    for c_ in ("Fabbro", "Produttore", "Ufficio aziendale", "Negozio", "Pittura", "Falegname",
               "Produttore di arredi per negozi e supermercati", "Carcere"):
        assert not fuori_settore_maps(c_), c_
    assert fuori_settore_nome("Pasticceria Dolce Vita") and fuori_settore_nome("Onoranze Funebri Alfa")
    assert not fuori_settore_nome("Fabbri Srl") and not fuori_settore_nome("Hotel del ferro battuto")
    assert not fuori_settore_nome("Bar Sport") and not fuori_settore_nome("Alfa Spa") and not fuori_settore_nome(None)
    assert fuori_settore_scheda({"fonte": "exa", "nome": "Ristorante Alfa"})
    assert not fuori_settore_scheda({"nome": "Ristorante Alfa", "categoria_maps": "Fabbro"})   # Google vince
    assert fuori_settore_scheda({"nome": "Fabbri", "categoria_maps": "Agenzia funebre"})
    nt = {"classificazione": "NON_TARGET"}
    assert attivita_estranea({**nt, "attivita_prevalente": "Studio legale civilista"})
    assert not attivita_estranea({**nt, "attivita_prevalente": "Carpenteria pesante per Oil&Gas"})
    assert not attivita_estranea({**nt, "attivita_prevalente": "Scuola di saldatura e carpenteria"})
    assert not attivita_estranea({"classificazione": "TARGET", "attivita_prevalente": "Studio legale"})
    assert not attivita_estranea(None) and not attivita_estranea(nt)
    # i tre formati sfuggiti allo sweep del 21/9 (menu Province dell'app)
    assert sigla_provincia("CI") == "SU"
    assert sigla_provincia("Provincia autonoma di Trento") == "TN"
    assert sigla_provincia("Provincia del Sulcis Iglesiente") == "SU"
    assert sigla_provincia("Provincia della Spezia") == "SP"
    assert sigla_provincia("OT") == "SS" and sigla_provincia("og") == "NU"
    assert sigla_provincia("Città metropolitana di Roma Capitale") == "RM"
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
    assert fuori_settore_maps("Parrucchiere") and fuori_settore_maps("Barber shop")
    assert fuori_settore_maps("Salone di bellezza") and fuori_settore_maps("bar")
    assert fuori_settore_maps("Ristorante italiano")
    assert not fuori_settore_maps("Fabbro") and not fuori_settore_maps("Carpenteria metallica")
    assert not fuori_settore_maps("")   # vecchi sourcing senza campo: dentro
    assert not fuori_settore_maps(None)
    assert not fuori_settore_maps("Barriere e sbarre")  # 'bar' solo parola intera
    # chi produce non e' mai fuori: il caso reale Artigiana 2m
    assert not fuori_settore_maps("Produttore di arredi per negozi e supermercati")
    # i dubbi risolti dal cliente il 29/9
    assert fuori_settore_maps("Idraulico") and fuori_settore_maps("Compravendita rottami")
    assert fuori_settore_maps("Noleggio carrelli elevatori")
    assert fuori_settore_maps("Villa") and fuori_settore_maps("Servizio taxi")
    assert not fuori_settore_maps("Automazione e robotica")   # cancelli
    assert not fuori_settore_maps("Appaltatore")
    for ente in ("Municipio", "Ufficio comunale", "Ospedale", "Casa di cura", "Scuola",
                 "Chiesa cattolica", "Parrocchia", "Istituto religioso", "Liceo"):
        assert fuori_settore_maps(ente), ente
    assert not fuori_settore_maps("Carcere") and not fuori_settore_maps("Camera dell'artigianato")
    assert not fuori_settore_maps("Ingegnere") and not fuori_settore_maps("Architetto")
    assert not fuori_settore_maps("Negozio di casseforti")
    assert not fuori_settore_maps("Installazione e manutenzione ascensori")
    assert not fuori_settore_maps("Ufficio aziendale")
    assert esclude(MOTIVO_FORNITORE) and esclude(" Fornitore ")
    assert esclude(" Cliente Attivo ")          # il file e' compilato a mano
    assert not esclude(f"{MOTIVO_EX_CLIENTE}: perso per prezzo")
    assert not esclude("") and not esclude(None)
    print("ok")
