# PRD — Pipeline di produzione
### Repository `agente-commerciale-pipeline` · da eseguire con Claude Code
### Tutte le scelte qui dentro derivano da test già eseguiti: non sono opinioni, non cambiarle senza motivo

---

## 1. Contesto

Sistema di lead intelligence per Carpenterie Laziali (produttore di serramenti in acciaio a incastro, senza saldatura). La pipeline trova aziende del territorio, capisce cosa fanno, le classifica secondo criteri validati e le scrive su Supabase. Un'app Lovable (repo separato, già esistente) le mostra ai commerciali.

**Cosa è già stato validato, e questa pipeline deve solo industrializzare:**
- *Classificazione:* test su 26 aziende reali, accordo >90% con verifica manuale, regole raffinate su casi veri
- *Sourcing:* test comparato su provincia di Roma → **Google Maps (via Apify) + Exa**, sovrapposizione 7/205, Tavily scartata
- *Costo:* ~€0,06/azienda misurato
- *Fatto strutturale:* ~25% delle aziende reali non ha un sito leggibile → si registrano comunque con i recapiti Maps, senza classificarle

**Perimetro del primo ciclo:** regione Lazio, provincia per provincia partendo da Roma. Obiettivo contrattuale: 200-300 aziende analizzate.

## 2. Cosa NON fare

- NON usare Tavily (scartata da test)
- NON usare Lovable, edge functions o webhook: la pipeline è un processo batch autonomo
- NON creare tabelle nuove su Supabase: lo schema esiste, adattarsi a quello
- NON inviare email, NON toccare Gmail: fuori perimetro pipeline
- NON parallelizzare oltre 3-4 fetch simultanei: siti di artigiani, gentilezza obbligatoria
- NON classificare aziende presenti in `esclusioni` o già in `aziende` (dedup prima, non dopo)
- NON modificare il prompt di classificazione senza rilanciare il regression test (§8)
- NON lanciare il ciclo completo prima del report costi (§9): è un obbligo contrattuale

## 3. Struttura del repository

```
agente-commerciale-pipeline/
├── main.py                  # CLI: orchestrazione di un ciclo
├── config.py                # costanti, soglie, elenchi comuni
├── sourcing_maps.py         # Apify Google Maps per comune
├── sourcing_exa.py          # Exa per significato
├── dedup.py                 # normalizzazione + esclusioni + già visti
├── fetch.py                 # crawl4ai con cache su disco
├── territorio.py            # filtro geografico euristico pre-classificazione
├── classify.py              # chiamata modello + parsing JSON robusto
├── prompts.py               # IL prompt (§7) — file sacro
├── arricchimento.py         # Openapi, solo classe A/B
├── segnali_lavoro.py        # annunci di lavoro, solo classe A/B
├── db.py                    # Supabase service_role: cicli, aziende, attivita
├── costi.py                 # contatore token/€ per azienda e per ciclo
├── data/comuni_lazio.py     # comuni per provincia (primi ~20 per popolazione)
├── tests/campione_26/       # il regression test (CSV + cache già esistenti)
├── .env.example  .gitignore # .env MAI committato
└── README.md
```

CLI: `python main.py --provincia RM --limite 50 --dry-run` (dry-run: tutto tranne la scrittura su Supabase). Senza `--limite`: ciclo pieno sulla provincia.

## 4. Sourcing (validato — replicare, non reinventare)

**Maps (rete di base):** attore Apify `compass/crawler-google-places`, query = categoria × comune, categorie: `fabbro`, `serramenti in ferro`, `carpenteria metallica`. Max 20 risultati per query, lingua it. Salvare SEMPRE: nome, sito, telefono, indirizzo, comune. **Le aziende senza sito NON si scartano**: entrano in DB con `esito_fetch='nessun_sito'`, classe `indeterminato`, confidenza `bassa`, motivazione "nessuna fonte web disponibile — valutazione telefonica" e i recapiti Maps. Sono un quarto del mercato: il commerciale li vede comunque.

**Exa (precisione semantica):** `exa.search(q, type="auto", num_results=25, contents={"highlights": True})`. Query dal test (5, in config). Attenzione: **testo/summary dentro `contents`**, non top-level. Escludere il dominio `exa.ai` e i portali (lista in config, già estesa con pinterest/europages/pgcasa/leroymerlin).

**Dedup (in quest'ordine):** dominio normalizzato (no www) → P.IVA quando nota → ragione sociale normalizzata + comune per chi non ha né l'uno né l'altra. Poi filtro `esclusioni` (clienti attuali) e filtro "già in `aziende`" (i cicli successivi non ripagano chi c'è già).

## 5. Filtro territorio (nato dal test: 9 errori Exa su 9 erano geografia)

Prima di classificare, euristica gratuita sulla homepage già in cache:
- segnali POSITIVI Lazio: CAP `00xxx/01xxx/02xxx/03xxx/04xxx`, nomi province e capoluoghi (Roma, Latina, Frosinone, Rieti, Viterbo), prefissi 06/0774/0773/0776/0746/0761
- segnali NEGATIVI forti: capoluoghi e CAP di altre regioni nella pagina contatti
- esito: `lazio` / `fuori` / `incerto`. `fuori` → si registra con motivazione "fuori territorio", NON si classifica (non si paga). `incerto` → si classifica, e il modello estrae la sede (§7)

## 6. Fetch (dal prototipo, con le correzioni)

crawl4ai; cache su disco per dominio (`cache/<dominio>/`), riuso totale tra esecuzioni. Homepage + fino a 4 pagine interne scelte per keyword nei link: `prodotti, servizi, lavorazioni, chi-siamo, azienda, realizzazioni, lavori, gallery, portfolio` **+ i nomi prodotto: `grate, persiane, cancelli, inferriate, recinzioni, blindat, sicurezza, portoni, ringhiere, ferro, acciaio, contatti`** (la mancanza di questi ha causato l'errore Paterno nel test). Timeout 30s, 1 retry, poi `FETCH_FALLITO` e avanti. Testo concatenato, tetto ~15.000 parole.

## 7. Classificazione — il prompt di produzione

Modello: `claude-sonnet-4-6`, chiave da `.env` (`ANTHROPIC_API_KEY` — sviluppo sulla TUA chiave, produzione su quella del cliente "agenti commerciali": si cambia solo il .env). Risposta SOLO JSON. Registrare token in/out per azienda.

Base: il prompt del test (già in `tests/campione_26/`) con QUESTE integrazioni obbligatorie:

```
DEFINIZIONI DEL CLIENTE (vincolanti):
- FABBRO: lavora SOLO acciaio e ferro (cancelli, scale, inferriate, grate).
- SERRAMENTISTA: tratta serramenti in tutti i materiali (PVC, alluminio,
  legno); produce o rivende; acquista persiane e grate a completamento.

CAMPI AGGIUNTIVI DA ESTRARRE nel JSON:
  "sede_comune", "sede_provincia", "sede_regione"  (dalla pagina contatti;
     null se assenti — MAI dedotti dal nome o dal dominio)
  "email_aziendale", "telefono"  (se presenti nel sito)
  "categoria": "fabbro" | "serramentista" | "showroom" | "impresa_edile" |
     "costruttore" | "artigiano" | "montatore" | "ferramenta" | "altro"

REGOLE (in ordine, si applica la prima che corrisponde):
1. TARGET: lavora acciaio/ferro e serramenti, grate o cancelli sono linea attiva.
2. TARGET: officina propria + vende serramenti di sicurezza in altri materiali.
   La specializzazione in alluminio NON è MAI da sola motivo di esclusione.
   Vietato scrivere valutazioni come "difficilmente cambierà materiale".
3. NON_TARGET: solo PVC/alluminio/legno E rivenditore/installatore senza officina.
4. NON_TARGET: ferramenta e rivendite di materiali edili.
5. NON_TARGET: pronto intervento serrature senza produzione propria.
6. NON_TARGET: carpenteria strutturale/industriale pesante (Oil&Gas, navale,
   capannoni, serbatoi). ECCEZIONE: serramenti/grate/cancelli come linea di
   prodotto attiva → INDETERMINATO con nota.
7. INDETERMINATO: informazioni insufficienti. È una risposta corretta, non un fallimento.

CONFIDENZA: una sola pagina sotto le 400 parole → massimo MEDIA.
BASSA → classificazione INDETERMINATO salvo dichiarazioni esplicite.
Ogni motivazione cita elementi CONCRETI e verificabili delle pagine.
```

Mappatura classi → DB: TARGET+alta→`A`, TARGET+media→`B`, dubbi fondati→`C`, resto→`indeterminato`. La modulazione per dipendenti (fabbro con organico ampio ↓, serramentista con organico ampio =) si applica DOPO l'arricchimento, in `classify.py`, non nel prompt: il dato arriva da Openapi.

## 8. Regression test — il guardiano del prompt

`python -m tests.regression` → rilancia le 26 aziende dalla cache, confronta con le classificazioni validate, stampa le differenze. **Si esegue prima di ogni commit che tocca `prompts.py`.** Una classificazione validata che cambia = ci si ferma e si capisce perché. La cache rende il costo ~zero.

## 9. Arricchimento, segnali, costi

**Openapi (solo classe A e B):** endpoint anagrafica base — P.IVA, denominazione, sede, dipendenti quando disponibile. Prime 30/mese gratuite, poi €0,05: su 60-80 A/B per ciclo sono pochi euro. Dopo l'arricchimento: applica la modulazione dipendenti (§7) e il dedup su P.IVA.

**Annunci di lavoro (solo classe A e B):** una query Exa per azienda: `"<ragione sociale>" (assunzione OR cercasi OR "offerta di lavoro") (saldatore OR operaio OR carpentiere OR magazziniere)`. Risultato positivo (domini indeed/infojobs/subito/bakeca o pagina lavora-con-noi) → voce nel campo `segnali`: `{"tipo":"annuncio_lavoro","ruolo":"saldatore","fonte":"<url>"}`. Il saldatore pesa più di tutti: è l'argomento di vendita del prodotto.

**Costi:** ogni azienda scrive `costo_analisi_eur` (token × prezzi correnti del modello, letti dalla documentazione, non inventati). Il ciclo aggiorna `cicli_ricerca` con totali e costo. **Prima del ciclo pieno: esecuzione su 30 aziende → report per Claudia** (costo medio, proiezione su 300, proiezione mensile) → si prosegue solo dopo il suo ok. Obbligo contrattuale, art. 6.5/12.

## 10. Scrittura su Supabase

`service_role` da `.env`. Ogni ciclo: riga in `cicli_ricerca` all'avvio, aggiornata alla fine. Upsert aziende rispettando gli indici unici (P.IVA, dominio) — il conflitto NON è un errore, è il dedup che lavora: si logga e si prosegue. Un fallimento su un'azienda non ferma il ciclo. Log per azienda: nome, fonte, esito, classe, confidenza, costo.

## 11. Sequenza di esecuzione (nell'ordine, senza saltare)

1. `esclusioni`: caricare l'elenco clienti di Claudia appena arriva (script `carica_esclusioni.py` da un Excel/CSV: ragione sociale, P.IVA se c'è, dominio se c'è)
2. `--provincia RM --limite 30 --dry-run` → controllo manuale dell'output
3. Stessa cosa senza dry-run → 30 aziende vere in Supabase → **aprire l'app Lovable e verificare che si vedano** (primo collaudo dell'integrazione)
4. Report costi → invio a Claudia → attesa ok
5. Ciclo pieno provincia di Roma
6. Verifica manuale di 10 schede a caso
7. **Email di consegna formale del primo elenco** (attiva i termini contrattuali)
8. Altre province del Lazio nei giorni successivi
9. Deploy su Hetzner: rsync del repo, `.env` sul server (mai in git), cron settimanale documentato nel README. Prima del deploy e della consegna: **gitleaks** su tutto lo storico

## 12. Criteri di accettazione della pipeline

- Rilanciabile: due esecuzioni consecutive non creano duplicati
- Interrompibile: un crash a metà non lascia il ciclo in stato incoerente
- Le 26 del regression passano identiche
- `esclusioni` rispettate: nessun cliente attuale nell'output
- Ogni azienda in DB ha fonte, esito e costo tracciati
- Le aziende senza sito compaiono in app con recapiti e dicitura onesta
- README: setup, .env, comandi, cron — scritto per il te di fra tre mesi
