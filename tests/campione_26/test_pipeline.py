"""Check minimo: parsing JSON, troncamento, costo. `python test_pipeline.py`"""

import tempfile
from pathlib import Path

import analyze
import fetch
import main
import prompts

# --- lettura CSV: separatore ',' o ';', a capo dentro le celle, righe vuote scartate ---
for sep in (",", ";"):
    csv_test = (
        f"nome{sep}url{sep}note\n"
        f'"Serramenti Lazio\n"{sep}https://x.it/{sep}nota\n'
        f"Officina Verdi{sep}{sep}solo Facebook\n"
        f"{sep}{sep}\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_test)
    righe = main.leggi_aziende(Path(f.name))
    assert len(righe) == 2, (sep, righe)
    assert righe[0] == {"nome": "Serramenti Lazio", "url": "https://x.it/"}, righe[0]
    assert righe[1]["url"] == ""  # niente sito -> NO_SITO
    Path(f.name).unlink()

# --- riprendere da risultati.csv: solo le righe OK, con numeri riconvertiti ---
intestazione = ",".join(main.COLONNE)
riga_ok = "Alfa,https://a.it,OK,ferro,SI,SI,TARGET,ALTA,motivo,segn,dubbi,grate,3,1000,50,0.05"
riga_ko = "Beta,https://b.it,FETCH_FALLITO," + "," * 8 + "0,0,0,0"
with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
    f.write(f"{intestazione}\n{riga_ok}\n{riga_ko}\n")
esistenti = main.carica_esistenti(Path(f.name))
assert set(esistenti) == {("Alfa", "https://a.it")}, esistenti  # i falliti si riprovano
assert esistenti[("Alfa", "https://a.it")]["token_input"] == 1000  # int, non "1000"
assert esistenti[("Alfa", "https://a.it")]["costo_stimato_eur"] == 0.05
assert main.carica_esistenti(Path(f.name + ".inesistente")) == {}
Path(f.name).unlink()

# --- parsing JSON della risposta LLM ---
assert analyze.estrai_json('{"a": 1}') == {"a": 1}
assert analyze.estrai_json('```json\n{"a": 1}\n```') == {"a": 1}
assert analyze.estrai_json('```\n{"a": 1}\n```') == {"a": 1}
assert analyze.estrai_json('Ecco il JSON:\n{"a": 1}\nfine') == {"a": 1}

# --- troncamento a N parole, righe intere ---
testo = "\n".join(f"riga {i} con cinque parole" for i in range(100))
assert len(fetch.tronca(testo, 20).split()) <= 20
assert fetch.tronca(testo, 10_000) == testo

# --- costo: 1M input + 1M output = (3 + 15) USD * 0.92 ---
assert abs(analyze.costo_eur(1_000_000, 1_000_000) - 18 * analyze.USD_EUR) < 1e-6
assert analyze.costo_eur(0, 0) == 0

# --- il prompt sostituisce il placeholder e conserva le graffe dello schema ---
p = prompts.costruisci("CONTENUTO_X")
assert "CONTENUTO_X" in p and "{contenuto}" not in p
assert '"classificazione"' in p

# --- scelta delle pagine interne: keyword, stesso dominio, no duplicati, max 4 ---
home = {
    "links": ["/prodotti", "https://x.it/chi-siamo", "/prodotti#top", "/contatti",
              "https://altro.it/azienda", "/a", "/lavorazioni", "/gallery", "/portfolio"],
    "testi": ["Prodotti", "Chi siamo", "Prodotti", "Contatti",
              "Azienda", "Le nostre realizzazioni", "Lavorazioni", "Gallery", "Portfolio"],
}
scelte = fetch._pagine_rilevanti(home, "https://x.it/")
assert len(scelte) == 4, scelte
assert "https://x.it/prodotti" in scelte          # link relativo risolto
assert "https://x.it/chi-siamo" in scelte
assert "https://x.it/a" in scelte                 # match sul testo del link
assert scelte.count("https://x.it/prodotti") == 1  # dedup, fragment ignorato
assert not any("altro.it" in s for s in scelte)   # dominio esterno escluso
assert not any("contatti" in s for s in scelte)   # nessuna keyword

# --- priorità: pagine prodotto prima delle generiche, blog/news in fondo ---
home2 = {
    "links": ["/blog/porte-blindate", "/chi-siamo", "/grate", "/servizi",
              "/news/cancelli", "/persiane", "/gallery"],
    "testi": ["Porte blindate", "Chi siamo", "Grate", "Servizi",
              "Cancelli", "Persiane", "Gallery"],
}
scelte2 = fetch._pagine_rilevanti(home2, "https://x.it/")
assert scelte2 == ["https://x.it/grate", "https://x.it/persiane",
                   "https://x.it/chi-siamo", "https://x.it/servizi"], scelte2

# --- analizza(): estrazione campi, token e costo da una risposta finta ---
class _Blocco:
    type, text = "text", '```json\n{"classificazione": "TARGET", "confidenza": "ALTA"}\n```'

class _Usage:
    input_tokens, output_tokens = 10_000, 500

class _FakeClient:
    class messages:
        @staticmethod
        def create(**_):
            return type("R", (), {"content": [_Blocco()], "usage": _Usage()})()

dati = analyze.analizza(_FakeClient(), "contenuto")
assert dati["classificazione"] == "TARGET"
assert dati["materiali_rilevati"] == ""      # campo mancante -> vuoto, non KeyError
assert set(analyze.CAMPI) <= set(dati)
assert dati["token_input"] == 10_000
assert dati["costo_stimato_eur"] == analyze.costo_eur(10_000, 500)

print("ok")
