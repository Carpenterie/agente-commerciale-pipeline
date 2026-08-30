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
```

Province: RM, LT, FR, RI, VT. `--dry-run` fa tutto tranne la scrittura su
Supabase. `--gratuite-openapi N` dichiara quante delle 30 chiamate Openapi
gratuite del mese sono ancora disponibili (sono mensili, non per ciclo).

Ogni modulo ha il suo check: `python <modulo>.py` stampa `ok`.
Il regression si esegue prima di ogni commit che tocca `prompts.py`. Una
classificazione validata che cambia = ci si ferma e si capisce perché.

## Come è fatta

`main.py` orchestra: sourcing (`sourcing_maps` + `sourcing_exa`) → `dedup`
(interno, poi esclusioni e già-visti) → `fetch` (cache su disco per dominio)
→ `territorio` (filtro geografico gratuito) → `classify` + `prompts` (il file
sacro) → `arricchimento` e `segnali_lavoro` solo su classe A/B → `db`.
`costi` conta token ed euro per azienda e per ciclo.

## Fuori territorio: due controlli, nessun declassamento

`territorio.py` filtra prima della classificazione (gratis, sui recapiti) e
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

Poiché così i TARGET sono la maggioranza (15 su 24 nel campione), la
**classe dice chi chiamare prima**, non se l'azienda è pertinente:

| classe | significato |
|---|---|
| A | segnale di bisogno rilevato (annuncio di lavoro), oppure officina accertata + confidenza alta |
| B | target senza segnali, confidenza alta o media |
| C | target incerto, o dubbio fondato (INDETERMINATO con confidenza alta/media) |
| indeterminato | il resto |

I segnali si cercano su **tutti** i TARGET (una query Exa, ~0,006 EUR),
perché decidono la classe A: cercarli solo su A/B sarebbe circolare.
Openapi resta sulle sole A/B: a 0,10 EUR a chiamata, su 180 target sarebbero
18 EUR a ciclo.

## Deploy su Hetzner

```bash
./deploy.sh utente@indirizzo-server            # dal Mac, non dal server
```

`deploy.sh` lancia gitleaks, poi rsync **escludendo `.env`, `cache/` e
`.venv/`**, e sul server crea il venv e installa chromium. Il `.env` sul
server si crea **a mano una volta sola** e non viaggia mai — né in git né
in rsync:

```bash
ssh utente@server 'cat > /opt/agente-commerciale-pipeline/.env && chmod 600 /opt/agente-commerciale-pipeline/.env'
# poi si incolla il contenuto e si chiude con Ctrl-D
```

Cron: copiare `cron.example` in `crontab -e`. È **mensile**, una provincia
al giorno dal 1° al 5. La cadenza mensile invece che settimanale è una
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

## Limiti noti
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
