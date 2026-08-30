# Pipeline di prova — classificazione serramentisti

Esperimento usa-e-getta: legge `aziende.csv`, scarica i siti, li fa valutare a
Claude Sonnet 4.6 e scrive `risultati.csv`.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/crawl4ai-setup            # scarica il browser headless (una volta sola)
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/python main.py
```

Input: `aziende.csv` con colonne `nome,url,note` (url vuoto → esito `NO_SITO`).
Le pagine scaricate finiscono in `cache/`: rilanciare l'analisi non ripaga il fetch
(per riscaricare tutto, svuota `cache/`). Check del codice: `.venv/bin/python test_pipeline.py`.
Prezzi in `analyze.py` ($3/$15 per M token) e cambio USD→EUR sono costanti da aggiornare a mano.
