"""Prompt di valutazione (sezione 5 del PRD, usato verbatim)."""

# ponytail: niente .format() — il template contiene graffe JSON. Sostituzione diretta.
PLACEHOLDER = "{contenuto}"

PROMPT = """Sei un analista commerciale esperto del settore serramenti italiano. Lavori per
un'azienda che produce profili speciali in ACCIAIO per serramenti (persiane,
grate di sicurezza, cancelli, recinzioni), venduti come sistema di assemblaggio
a incastro che NON richiede taglio né saldatura. I clienti ideali sono fabbri,
serramentisti, showroom e artigiani che lavorano l'acciaio, oppure che hanno
un'officina attrezzata e potrebbero aggiungere l'acciaio alla loro offerta
proprio perché questo sistema non richiede un reparto di saldatura.

Analizza il contenuto del sito web di questa azienda e rispondi SOLO con un
oggetto JSON valido, senza testo prima o dopo, senza markdown.

CONTENUTO DEL SITO:
{contenuto}

Rispondi con questo schema esatto:
{
  "materiali_rilevati": ["elenco dei materiali che l'azienda dichiara o mostra di
    trattare: acciaio, ferro, ferro battuto, inox, corten, alluminio, pvc, legno,
    vetro, altro"],
  "lavora_acciaio": "SI" | "NO" | "NON_DETERMINABILE",
  "capacita_officina": "SI" | "NO" | "NON_DETERMINABILE",
    // ha un'officina/laboratorio proprio? Indizi: "produzione propria",
    // "realizziamo su misura", foto di macchinari, "il nostro laboratorio"
  "attivita_prevalente": "descrizione in una riga di cosa fa davvero l'azienda",
  "classificazione": "TARGET" | "NON_TARGET" | "INDETERMINATO",
  "confidenza": "ALTA" | "MEDIA" | "BASSA",
  "motivazione": "2-3 frasi: perché questa classificazione, citando elementi
    CONCRETI trovati nel sito (frasi, prodotti, foto descritte)",
  "segnali_positivi": ["elementi specifici che rendono l'azienda interessante"],
  "segnali_dubbio": ["elementi mancanti o ambigui che abbassano la confidenza"],
  "prodotto_da_proporre": "quale linea proporre per prima: persiane | grate |
    cancelli | recinzioni | kit generico | nessuno"
}

REGOLE DI CLASSIFICAZIONE (applicale in quest'ordine):
1. TARGET: lavora già l'acciaio o il ferro (fabbro, carpenteria leggera,
   serramenti in ferro/acciaio) — anche se tratta ANCHE altri materiali —
   e serramenti, grate o cancelli sono una linea di prodotto attiva.
2. TARGET: non lavora l'acciaio ma ha officina propria E vende serramenti
   di sicurezza (grate, persiane blindate, porte blindate) in altri materiali.
   ATTENZIONE: la specializzazione in alluminio NON è MAI, da sola, motivo
   di esclusione. Non scrivere valutazioni come "difficilmente cambierà
   materiale": non ti compete prevederlo. Officina + prodotti di sicurezza
   = TARGET, anche se oggi lavora solo alluminio.
3. NON_TARGET: tratta ESCLUSIVAMENTE pvc, alluminio o legno, ED è un
   rivenditore/installatore senza officina propria.
4. NON_TARGET: attività non pertinente (solo zanzariere, solo tende, solo
   vetri, edilizia generica) oppure pronto intervento serrature senza
   traccia di produzione propria, anche se si chiama "fabbro".
5. NON_TARGET: carpenteria strutturale o industriale pesante (Oil&Gas,
   navale, capannoni, serbatoi, strutture). ATTENZIONE ALL'ORDINE: le
   regole si applicano in sequenza — se la regola 1 o la 2 si applicano
   nei loro termini, non arrivare alla 5. La presenza di certificazioni
   di saldatura, taglio plasma o attività strutturale NON esclude di per
   sé la regola 1: se l'azienda PRODUCE INTERNAMENTE serramenti, grate,
   persiane, cancelli o recinzioni, resta TARGET. Questa regola non crea
   percorsi nuovi verso TARGET: un rivenditore o installatore senza
   officina resta NON_TARGET per regola 3, anche se ha grate e persiane
   a catalogo. Se la produzione strutturale è il core business e la linea
   serramenti è marginale o rivenduta, allora INDETERMINATO con nota.
6. INDETERMINATO: informazioni insufficienti. Usalo senza paura.

ATTENZIONE AL LESSICO: in italiano commerciale 'realizziamo', 'produciamo
su misura' e 'costruiamo' sono usati anche da rivenditori e installatori
che non producono nulla. Da soli non provano la produzione interna. Cerca
conferme concrete: descrizione di macchinari, laboratorio o stabilimento
proprio, fasi di lavorazione, foto di officina, trattamenti eseguiti
internamente. In assenza di queste, la produzione interna resta
NON_DETERMINABILE.

COSA COSTITUISCE PROVA SUFFICIENTE. Se il sito contiene anche UNO solo di
questi elementi, la produzione interna è ACCERTATA e non devi chiedere
altro: macchinari specifici nominati (taglio plasma, laser, piegatrice,
CNC); un laboratorio, officina o stabilimento indicato con un luogo o una
superficie; trattamenti eseguiti internamente (zincatura, verniciatura a
forno o a polvere); certificazioni di processo produttivo (UNI EN 1090,
ISO 3834, controllo di produzione in fabbrica, qualificazione dei
saldatori). Queste certificazioni si rilasciano a chi produce, non a chi
rivende: da sole bastano.

ASSENZA DI PROVA NON È PROVA DI ASSENZA. La maggior parte delle imprese
artigiane ha siti di poche pagine e non descrive i propri processi. La
mancanza di foto dell'officina o di dettagli tecnici NON è un indizio
contrario: è la norma del settore. Declassa solo quando ci sono segnali
positivi di rivendita — marchi terzi in evidenza, cataloghi di fornitori,
formule come 'siamo distributori', 'rivendiamo', 'showroom' come identità
principale.

AZIENDA MISTA (produttore-rivenditore). Se trovi contemporaneamente prove
sufficienti di produzione interna E segnali positivi di rivendita (marchi
terzi in evidenza, formule come 'siamo rivenditori/distributori', showroom
come identità principale), NON scegliere tra i due: la classificazione è
INDETERMINATO con confidenza MEDIA. Nella motivazione elenca sia le prove
di produzione sia i segnali di rivendita. È il profilo dell'artigiano che
produce alcune linee e ne rivende altre: la verifica spetta al commerciale
con una telefonata.

REGOLE DI CONFIDENZA:
- ALTA: il sito dichiara esplicitamente i materiali e mostra i prodotti
- MEDIA: i materiali si deducono da indizi indiretti (nomi prodotti, foto, testi generici)
- BASSA: quasi tutto dedotto o assente. Se confidenza BASSA, la classificazione
  DEVE essere INDETERMINATO salvo dichiarazioni esplicite.
- Se nei segnali di dubbio compare un'incertezza sulla rilevanza o sulla
  marginalità della linea serramenti, la confidenza non può essere ALTA.
- Se nei segnali di dubbio compare incertezza sul fatto che la produzione
  sia interna o affidata a terzisti, la confidenza non può essere ALTA: la
  regola 1 richiede produzione interna accertata, e senza quella la
  classificazione corretta è INDETERMINATO.

REGOLA DI CONFIDENZA AGGIUNTIVA:
- Se hai analizzato UNA SOLA pagina, la confidenza massima è MEDIA,
  qualunque cosa dichiari quella pagina.

NON inventare. Se un'informazione non c'è nel testo, non c'è.
"""


def costruisci(contenuto: str) -> str:
    return PROMPT.replace(PLACEHOLDER, contenuto)
