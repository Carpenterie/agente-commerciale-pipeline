# agente-commerciale-pipeline

Pipeline di lead intelligence per Carpenterie Laziali (vedi `PRD_pipeline_produzione.md`
sul Desktop). **In costruzione**: per ora esiste lo scheletro del repo e il regression
test sul campione validato di 26 aziende.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cp .env.example .env   # e compilare le chiavi
```

## Comandi

```bash
python main.py --provincia RM --limite 30 --dry-run   # prova senza scrivere
python main.py --provincia RM                          # ciclo pieno sulla provincia
python carica_esclusioni.py clienti.xlsx --dry-run     # esclusioni da Excel/CSV
python -m tests.regression                             # il guardiano del prompt
python -m tests.test_orchestrazione                    # flusso simulato, costo zero
python verifica_chiavi.py                              # le chiavi del .env rispondono?
```

Province: RM, LT, FR, RI, VT. `--dry-run` fa tutto tranne la scrittura su
Supabase. `--gratuite-openapi N` dichiara quante delle 30 chiamate Openapi
gratuite del mese sono ancora disponibili (sono mensili, non per ciclo).

Ogni modulo ha il suo check: `python <modulo>.py` stampa `ok`.
Il regression si esegue prima di ogni commit che tocca `prompts.py`. Una
classificazione validata che cambia = ci si ferma e si capisce perché.

## Perché la cache del campione sta in git

`tests/campione_26/cache/` contiene ~110 file JSON: sono le pagine dei 26
siti del campione, scaricate una volta e congelate. **Non sono spazzatura e
non vanno cancellate.** Il regression test (`python -m tests.regression`)
riclassifica quelle 26 aziende partendo da quelle pagine: senza, dovrebbe
riscaricare i siti — che nel frattempo cambiano — e non confronterebbe più
mele con mele. Con la cache in git il guardiano gira offline, su qualsiasi
macchina, a costo zero di rete e con un risultato riproducibile.

La cache di produzione (`/cache/` alla radice) è invece esclusa da git: è
volatile, cresce a ogni ciclo e il server ha la sua.

## Come è fatta

`main.py` orchestra: sourcing (`sourcing_maps` + `sourcing_exa`) → `dedup`
(interno, poi esclusioni e già-visti) → `fetch` (cache su disco per dominio)
→ `territorio` (CAP e provincia da Maps, euristica come ripiego) →
`classify` + `prompts` (il file sacro) → `segnali_lavoro` su tutti i TARGET
e `arricchimento` sulle sole A/B → `db`.
`costi` conta token ed euro per azienda e per ciclo.

## Fuori territorio: due controlli, nessun declassamento

Il segnale **primario** è il CAP (o la provincia) che Google Maps dichiara
sulla scheda: 93-95% valorizzato, è anagrafica e non deduzione, quindi
quando c'è decide da solo. Sotto, `territorio.py` filtra sui recapiti della
pagina — il ripiego per il 7% senza CAP e per Exa, che non ne ha mai — e
`territorio.verifica_sede()` ricontrolla dopo, sulla sede che il modello
legge dalla pagina contatti — un dato migliore dell'euristica sui prefissi.
Un'azienda che risulta di un'altra regione resta in DB con la **classe che
il modello le ha dato**: la classe dice quanto vale, non dove sta. A
filtrarla bastano il campo `regione` e il segnale
`fuori_territorio_sede_dichiarata` in cima a `segnali`. Quando si apriranno
altre regioni, quelle aziende sono già analizzate e pagate e si recuperano
per classe. `n_in_target` del ciclo invece le esclude: non sono il risultato
di un ciclo laziale.

## Perimetro commerciale e classi

Dal 2026-08-26 il criterio è "vende o installa serramenti al cliente
finale", non "lavora l'acciaio": rivenditori, showroom, montatori e chi
tratta solo alluminio o PVC sono target. Chi ha officina compra il kit, chi
non ce l'ha il prodotto finito — due linee dello stesso catalogo, che è
quello che decide `livello_fornitura`, non la classificazione.

Poiché così i TARGET sono la maggioranza (17 su 24 nel campione), la
**classe dice chi chiamare prima**, non se l'azienda è pertinente:

| classe | significato |
|---|---|
| A | una fra tre: segnale di bisogno (annuncio di lavoro), officina accertata + confidenza alta, oppure reputazione Google forte |
| B | target senza nessuna delle tre, confidenza alta o media |
| C | target incerto, o dubbio fondato (INDETERMINATO con confidenza alta/media) |
| indeterminato | il resto |

La **reputazione** (≥50 recensioni e ≥4,5 di punteggio, soglie in `config`)
concorre solo in positivo: sul campione di Roma il 42% delle aziende ha
cinque recensioni o meno perché lavora B2B, non perché è ferma — chi ne ha
poche non viene toccato.

I segnali si cercano su **tutti** i TARGET (una query Exa, ~0,006 EUR),
perché decidono la classe A: cercarli solo su A/B sarebbe circolare.
Openapi resta sulle classi in `config.CLASSI_DA_ARRICCHIRE`, oggi A e B:
restringere a `("A",)` taglia quella voce da ~27 a ~9 EUR sul ciclo completo.

## Deploy su Hetzner

```bash
./deploy.sh utente@indirizzo-server            # dal Mac, non dal server
```

`deploy.sh` lancia gitleaks, poi rsync **escludendo `.env`, `/cache/` e
`.venv/`** (la cache del campione invece viaggia: serve al regression), e sul server crea il venv e installa chromium. Il `.env` sul
server si crea **a mano una volta sola** e non viaggia mai — né in git né
in rsync:

```bash
ssh utente@server 'cat > /opt/agente-commerciale-pipeline/.env && chmod 600 /opt/agente-commerciale-pipeline/.env'
# poi si incolla il contenuto e si chiude con Ctrl-D
```

**Quando cambia una chiave** (il cliente rigenera un token, si passa a un
altro account) si lancia `python verifica_chiavi.py`: una chiamata minima
per servizio, nessuna run Apify e nessuna scrittura, qualche centesimo in
tutto. Va lanciato **anche sul server** — i due `.env` sono file distinti e
possono divergere, e il cron gira di notte. Esce con codice 1 se una non
risponde, quindi si può incatenare. Dice anche il piano Apify e il credito
residuo.

Cron: copiare `cron.example` in `crontab -e`. È **mensile**, una provincia
al giorno dal 1° al 5, **in ordine di densità: RM, LT, FR, VT, RI**. Il
piano Apify ha un tetto mensile rigido (~$19) e il ciclo completo gli arriva
vicino: se il credito finisse, così a saltare è Rieti — 15 comuni, la
provincia con meno aziende — invece di Viterbo, che ne ha di più e sarebbe
saltata solo per via dell'ordine alfabetico. Il riepilogo di fine ciclo
stampa il credito residuo in USD (non in euro: il tetto è in dollari, e
convertirlo a cambio fisso farebbe leggere margine dove non ce n'è). La cadenza mensile invece che settimanale è una
scelta di costo: il sourcing si ripaga a ogni giro ed è l'82% della spesa
(~66 EUR/mese a cadenza settimanale contro ~18 mensile).

**Rilancio a richiesta**, senza aspettare il cron:

```bash
ssh utente@server
cd /opt/agente-commerciale-pipeline
.venv/bin/python main.py --provincia RM --limite 30 --dry-run   # prova
.venv/bin/python main.py --provincia RM                          # scrive
.venv/bin/python main.py --provincia RM --sourcing-fresco        # forza Maps/Exa
```

Il sourcing resta in `cache/sourcing_<provincia>.json` per 24 ore: due
rilanci in giornata non lo ripagano. `cache/` non viene sincronizzata, il
server ha la sua.

## Bozze email

```bash
python bozze_email.py <uuid-azienda>
python bozze_email.py <uuid-azienda> --testo follow_up
```

Genera la bozza dagli otto testi approvati dal cliente (PDF del 2026-08-31).
**Una azienda per volta, su richiesta**: la bozza si produce quando il
commerciale apre la scheda, non in blocco su una lista — non esiste una
funzione che generi per liste, ed è deliberato.
**Non invia nulla e non tocca la casella email**: il §2 del PRD lo mette
fuori perimetro, il comando produce testo da rileggere. L'invio avviene
dall'app, dove il cliente ha collegato il connettore **Outlook** di Lovable.
La pipeline non sa quale provider ci sia dall'altra parte e non deve
saperlo: produce oggetto e corpo, il resto è dell'app.

Un solo testo per azienda, scelto in quest'ordine di precedenza:

| condizione | testo |
|---|---|
| segnale `ex_cliente` | *Ci risentiamo* — sa già chi siamo |
| segnale `annuncio_lavoro` | *Fornitura nei periodi di carico* |
| impresa edile o costruttore | *Fornitura per cantieri* (+ richiesta del referente) |
| showroom | *Gamma serramenti in acciaio* |
| `livello_fornitura = kit` | *Fornitura componenti in acciaio* |
| serramentista, montatore, artigiano | *Persiane e grate in acciaio* |

### La logica di scelta esiste in DUE posti — vanno allineati a mano

`bozze_email.py` nella pipeline, e l'app Lovable, che ha il suo pannello con
oggetto e corpo modificabili, la stessa scelta automatica, una tendina per
cambiare testo, il salvataggio in `attivita` e l'aggiornamento dello stato.
**La duplicazione è inevitabile** — l'app non esegue Python — ma non è
gratuita: chi cambia un testo o una regola **deve cambiarli in entrambi**,
altrimenti la stessa azienda riceve testi diversi a seconda di dove parte la
bozza, e nessuno se ne accorge finché non lo nota un cliente.

Cosa va tenuto allineato, in questo ordine di precedenza (è
`bozze_email.scegli_testo()`, riga per riga):

| # | condizione | testo |
|---|---|---|
| 1 | segnale `ex_cliente` | `ex_cliente` |
| 2 | segnale `annuncio_lavoro` | `carico_produttivo` |
| 3 | categoria `impresa_edile` o `costruttore` | `commessa_edile` |
| 4 | categoria `showroom` | `finito_showroom` |
| 5 | `livello_fornitura = kit` | `kit_officina` |
| 6 | categoria `serramentista`, `montatore`, `artigiano`, **oppure** `livello_fornitura = prodotto_finito` | `finito_serramentista` |
| 7 | nessuna delle precedenti | **nessuna bozza** |

L'ordine è una precedenza, non una preferenza: 1 e 2 vincono sulla categoria,
e la 5 viene prima della 6 perché un fabbro con officina è `kit` anche se la
categoria direbbe altro. La 7 non è un errore: senza informazioni sufficienti
non si scrive niente.

Oltre alle sette regole vanno allineati anche: i **testi** stessi (`TESTI`
in `bozze_email.py`, dal PDF del 2026-08-31), le **parole vietate**
(`config.VIETATE_EMAIL`), la regola per cui **le frasi con un dato mancante
spariscono** invece di lasciare un segnaposto, la **firma**
(`config.FIRMA_EMAIL`), e i tre testi che **non si scelgono mai da soli**.

Un ex cliente non riceve mai un testo da azienda nuova, e viceversa. Tre
testi **non si scelgono mai da soli** perché nascono da un fatto che il
sistema non vede — una risposta umana, il tempo trascorso — e si chiedono
per `testo_id`: `follow_up`, `ricontatto`, `risposta_interesse`.

Tre regole applicate dal codice e verificate dal self-check:
**l'annuncio di lavoro non compare mai nel testo** (sceglie il messaggio,
non lo scrive); i campi variabili o si compilano o la frase che li conteneva
sparisce — mai un `[segnaposto]` in una bozza; nessun claim su tempi,
certificazioni o risparmi (`config.VIETATE_EMAIL`).

Le email escono a nome dell'azienda (`FIRMA_EMAIL = "Carpenterie
Laziali"`), non del singolo commerciale: la casella è condivisa, quindi la
firma è una costante e non si legge da `assegnato_a`.

`LINK_CATALOGO` e `LINK_PRENOTAZIONE` sono vuoti in attesa del catalogo del
cliente. Finché lo sono: la frase che li conterrebbe **sparisce** (il
follow-up torna esattamente alla versione approvata) e `risposta_interesse`
non si produce affatto, perché è il testo che serve a mandare il catalogo.
`SITO_EMAIL` resta vuoto di proposito: in chiusura andrà il link al
catalogo, non al sito.

## Studio del territorio

```bash
psql < studio_territorio.sql        # una volta, crea la vista
python studio_territorio.py         # prospetto
python studio_territorio.py --csv   # per il cliente
```

Conteggi per provincia, categoria e classe, con il dettaglio di target,
senza-sito, segnali di lavoro ed ex clienti. **L'etichetta "Aziende
individuate e classificate dal sistema — non è un censimento del mercato"
è una colonna della vista** (`fonte_dato`), non una nota a piè di pagina:
viaggia coi dati e l'app la mostra per forza. Il numero dipende dalle query
di sourcing e dai comuni interrogati, non dal mercato reale.

## Manutenzione: il campione va arricchito

**Il campione delle 26 ha perso capacità discriminante.** Col perimetro
allargato del 2026-08-26 quasi tutte risultano TARGET (17 su 24), e i casi
che restano al confine oscillano: un guardiano che dice quasi sempre la
stessa cosa non protegge più granché.

Dopo il primo ciclo completo va **arricchito con 4-5 aziende che esercitano
i confini attuali**, cioè le distinzioni su cui il perimetro può sbagliare:

- ferramenta contro rivenditore al cliente finale (regola 5 contro regola 3);
- grossista o distributore ad altri operatori contro distributore che vende
  al finale (di nuovo regola 5, il caso più sottile);
- produttore concorrente strutturato contro potenziale cliente (regola 3
  applicata a chi produce già in proprio — è il caso Finstral).

Le pagine si scaricano una volta e restano in `tests/campione_26/cache/`:
il costo di ogni rilancio del regression **non cambia**, restano ~1,7 EUR
per run indipendentemente da quante aziende contiene il campione.

**Finstral e Loi Carpenterie sono i due casi permanentemente instabili del
campione.** Se il regression fallisce solo su questi due nomi, **non è una
regressione**: sono aziende sul confine, e a parità di prompt e
`temperature=0` oscillano fra TARGET e NON_TARGET. Loi ne ha attraversate
cinque durante l'evoluzione dei criteri; **Finstral ha dato tre esiti in tre
run consecutivi il 2026-09-07** — TARGET, NON_TARGET, TARGET — a parità di
prompt, di chiave e di cache. Ogni motivazione era difendibile.

Conseguenza pratica: **il gate sarà rosso su Finstral all'incirca una volta
su due**, qualunque valore si congeli. Il campione non ha oggi un modo di
risolverlo, e la strada non è un'eccezione nominale nel regression (già
tentata e ritirata, vedi Limiti noti): è arricchire il campione come descritto
sopra, così che il guardiano poggi su casi netti e non su due monetine.

Il sintomo che li riconosce è nella motivazione, non nell'esito: il modello
si contraddice in chiusura. *«Tuttavia, la presenza esplicita di "Grate e
Serramenti di sicurezza" … potrebbe far scattare la regola 1»* è un'esitazione,
il comportamento di un caso al confine. Una chiave o un account diversi non
producono esitazione: producono un'altra risposta, sicura.

**Il tempo per indagarli è già stato speso** — circa 30 EUR di rilanci del
regression — e restano incerti comunque. Chi li ritrova rossi fra sei mesi
li rivalidi e ricongeli, senza riaprire l'indagine: `--salva` rifà tutte e
24 le classificazioni, mentre correggere a mano le sole righe cambiate in
`risultati.csv` costa zero (il gate confronta solo `classificazione`).

## Limiti noti

- **Il numero di dipendenti esiste solo per chi deposita un bilancio.**
  Openapi lo espone in `balanceSheets.last.employees`, non come campo
  anagrafico: ditte individuali e società di persone — buona parte degli
  artigiani che cerchiamo — non ce l'hanno. Misurato su un ciclo reale:
  su 12 aziende A/B tentate, 4 agganciate in anagrafica (33%) e 2 con il
  dato dipendenti, cioè **circa una su sei**. La modulazione organico
  (§7: fabbro con organico ampio scende di classe) si applica quindi a una
  minoranza, e la sua assenza non è un errore.
- **L'aggancio in anagrafica riesce su circa un terzo delle A/B.** Le
  schede di Google Maps portano insegne commerciali ("Gruben Italia
  Security"), non ragioni sociali da visura, e `IT-search` cerca per
  sottostringa sulla denominazione registrata. Un fallback che ripulisce
  il nome è stato provato su 5 aziende non agganciate e ne ha recuperata
  1 (Lema Infissi 85, il cui nome in visura è "SOCIETA' A RESPONSABILITA'
  LIMITATA" per esteso): il tasso salirebbe dal 33% al 42%, sotto la
  soglia che ne giustificava l'adozione. Provata anche la variante
  conservativa — togliere le sole forme societarie abbreviate, lasciando
  il resto del nome — con lo stesso esito: 4 nomi su 5 non contengono
  alcuna forma societaria, quindi restano invariati e falliscono per un
  motivo diverso (l'insegna di Maps non è una sottostringa della
  denominazione registrata). **Non implementato**, il 33% è il limite.
- **Infissi Torelli è il terzo caso della famiglia Romana/Faler/Torelli** —
  aziende con dichiarazioni di produzione ("realizziamo inferriate, grate,
  persiane blindate") e identità da showroom (250 mq, marchi terzi in
  evidenza). Il giudizio resta al commerciale. Torelli è anche il caso più
  instabile del campione: a parità di prompt e `temperature=0` oscilla tra
  NON_TARGET e INDETERMINATO da un run all'altro (l'API non è
  bit-deterministica e il sito è genuinamente ambiguo). Se il regression
  fallisce **solo** su Torelli, rilanciarlo prima di indagare: probabile
  oscillazione, non drift del prompt.
- Ritocchi al prompt tentati e **ritirati** (non riproporli senza motivo
  nuovo): delimitare la regola AZIENDA MISTA con "entrambe le condizioni
  sono necessarie" — non stabilizzava Torelli e in più spostava Romana
  (→TARGET), Loi (→INDETERMINATO) e soprattutto CMA (→NON_TARGET, con una
  motivazione che introduceva un ragionamento mai richiesto dal prompt,
  "è un concorrente diretto, bassa probabilità di conversione").

- L'API Imprese di Openapi citata nel PRD §9 è stata deprecata il 31/12/2025.
  `arricchimento.py` usa la Company API che l'ha sostituita, endpoint
  `IT-advanced` (il livello minimo che include il numero di dipendenti).
  Il prezzo è cambiato: listino agosto 2026 = 30 chiamate/mese gratuite,
  poi **€0,10+IVA** a consumo, non €0,05 come stimato nel PRD (€0,028 solo
  con piano annuale da 1M chiamate). Il report costi §9 deve usare €0,10.

## Vincoli noti (non "aggiornare" senza leggere qui)

- **`anthropic==0.120.2`** — l'SDK 1.x ha rimosso `temperature` da
  `messages.create()` (TypeError lato client). La classificazione usa
  `temperature=0`, necessaria al determinismo del regression test: senza,
  i casi al confine tra le regole flappano tra un run e l'altro. Non alzare
  la major finché la classificazione dipende da `temperature=0`.
- **`playwright==1.61.0`** — playwright ≥1.62 non supporta più macOS 12
  ("does not support chromium on mac12"): 1.61 è l'ultima che gira sul Mac
  di sviluppo. Browser: chromium v1228.
- **`cryptography<49`** — la 49 non ha wheel per macOS x86_64/py3.12: senza
  il pin, pip tenta la build da sorgente (Rust + openssl) e fallisce.
