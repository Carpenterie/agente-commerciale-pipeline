"""Chiamata modello + parsing JSON robusto (PRD §7).

temperature=0: il regression (§8) richiede risposte ripetibili. Registra
token in/out e costo per azienda. La mappatura classi → DB e la modulazione
dipendenti (che si applica DOPO l'arricchimento Openapi) stanno qui, non
nel prompt.
"""

from __future__ import annotations

import json
import re

import config
import costi
import prompts

CAMPI = (
    "materiali_rilevati", "lavora_acciaio", "capacita_officina",
    "attivita_prevalente", "classificazione", "confidenza", "motivazione",
    "segnali_positivi", "segnali_dubbio", "prodotto_da_proporre",
    "sede_comune", "sede_provincia", "sede_regione",
    "email_aziendale", "telefono", "categoria",
)


def estrai_json(testo: str) -> dict:
    """Parsing tollerante: toglie eventuali fence ```json e testo attorno all'oggetto."""
    t = testo.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        inizio, fine = t.find("{"), t.rfind("}")
        if inizio == -1 or fine <= inizio:
            raise
        return json.loads(t[inizio:fine + 1])


def classifica(client, contenuto: str) -> dict:
    """Un tentativo + un retry. Solleva l'ultima eccezione se falliscono entrambi."""
    messaggio = [{"role": "user", "content": prompts.costruisci(contenuto)}]
    ultimo_errore: Exception | None = None

    for _ in range(2):
        try:
            risposta = client.messages.create(
                model=config.MODELLO, max_tokens=config.MAX_TOKENS_RISPOSTA,
                temperature=0, messages=messaggio,
            )
            testo = next(b.text for b in risposta.content if b.type == "text")
            dati = estrai_json(testo)
            dati = {c: dati.get(c, "") for c in CAMPI}
            dati["token_input"] = risposta.usage.input_tokens
            dati["token_output"] = risposta.usage.output_tokens
            dati["costo_analisi_eur"] = costi.costo_anthropic(
                risposta.usage.input_tokens, risposta.usage.output_tokens)
            return dati
        except Exception as e:  # noqa: BLE001 - include JSON malformato ed errori API
            ultimo_errore = e

    raise ultimo_errore  # type: ignore[misc]


def classe_db(classificazione: str, confidenza: str, officina: str = "",
              segnali: list | None = None) -> str:
    """Priorità commerciale, non pertinenza: col perimetro allargato
    (2026-08-26) i TARGET sono la maggioranza, quindi la classe deve dire
    CHI CHIAMARE PRIMA.

    - A: TARGET con un segnale di bisogno (annuncio di lavoro), oppure
      TARGET con officina accertata e confidenza alta — il profilo che
      compra kit e ordina in continuità. DUE vie e non tre: la classe A
      deve voler dire UNA cosa leggibile ("ha un bisogno visibile, o ha
      un'officina"), altrimenti il commerciale non sa cosa sta guardando.
    - B: TARGET senza segnali, confidenza alta o media
    - C: TARGET con confidenza bassa, o INDETERMINATO con confidenza
      alta o media (dubbio fondato)
    - indeterminato: il resto
    """
    if classificazione == "TARGET":
        if segnali:
            return "A"
        if officina.strip().upper() == "SI" and confidenza == "ALTA":
            return "A"
        return "B" if confidenza in ("ALTA", "MEDIA") else "C"
    if classificazione == "INDETERMINATO" and confidenza in ("ALTA", "MEDIA"):
        return "C"
    return "indeterminato"


def modula_dipendenti(classe: str, categoria: str, dipendenti: int | None) -> str:
    """§7, DOPO l'arricchimento: fabbro con organico ampio scende di una
    classe (probabile saldatura strutturata in casa), serramentista resta."""
    if (categoria == "fabbro" and dipendenti
            and dipendenti > config.SOGLIA_ORGANICO_AMPIO):
        return {"A": "B", "B": "C"}.get(classe, classe)
    return classe


if __name__ == "__main__":
    # Il prompt di produzione ha DIVERSO il blocco delle regole rispetto al
    # campione congelato: il 2026-08-26 il committente ha ridefinito il
    # perimetro commerciale (non più "lavora l'acciaio" ma "vende o installa
    # serramenti al cliente finale"). Il campione resta la baseline storica;
    # qui si verifica che il prompt di produzione sia completo e coerente.
    for pezzo in ("DEFINIZIONI DEL CLIENTE", "sede_comune", "sede_provincia",
                  "sede_regione", "email_aziendale", '"categoria"',
                  "MAI dedotto dal nome"):
        assert pezzo in prompts.PROMPT, pezzo
    # le 10 regole del perimetro commerciale, in ordine (la 9, sui portali
    # di intermediazione, e' del 2026-09-08)
    regole = prompts.PROMPT[prompts.PROMPT.index("REGOLE DI CLASSIFICAZIONE"):
                            prompts.PROMPT.index("ATTENZIONE AL LESSICO")]
    for n in range(1, 11):
        assert f"\n{n}. " in regole, f"manca la regola {n}"
    assert "aggregatori di preventivi" in regole
    assert regole.count("TARGET:") >= 8      # 4 TARGET + 4 NON_TARGET
    assert "vende o installa serramenti al cliente finale" in regole
    assert "INDETERMINATO: informazioni insufficienti" in regole
    # e le note interpretative restano quelle validate sul campione
    # la motivazione la legge il commerciale: niente numeri di regola ne'
    # etichette in maiuscolo dentro il testo
    assert "COME SCRIVERE LA MOTIVAZIONE" in prompts.PROMPT
    assert "Non citare mai i numeri delle regole" in prompts.PROMPT
    for nota in ("ATTENZIONE AL LESSICO", "COSA COSTITUISCE PROVA SUFFICIENTE",
                 "ASSENZA DI PROVA NON È PROVA DI ASSENZA", "AZIENDA MISTA"):
        assert nota in prompts.PROMPT, nota

    p = prompts.costruisci("CONTENUTO_X")
    assert "CONTENUTO_X" in p and "{contenuto}" not in p

    assert estrai_json('{"a": 1}') == {"a": 1}
    assert estrai_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert estrai_json('Ecco:\n{"a": 1}\nfine') == {"a": 1}

    # mappatura per PRIORITÀ: tabella completa
    annuncio = [{"tipo": "annuncio_lavoro", "ruolo": "saldatore"}]
    # A: un segnale di bisogno basta, qualunque sia la confidenza
    assert classe_db("TARGET", "MEDIA", "NO", annuncio) == "A"
    assert classe_db("TARGET", "BASSA", "NON_DETERMINABILE", annuncio) == "A"
    # A: officina accertata + confidenza alta, anche senza segnali
    assert classe_db("TARGET", "ALTA", "SI") == "A"
    assert classe_db("TARGET", "ALTA", "si") == "A"       # il modello varia il caso
    # B: TARGET senza segnali
    assert classe_db("TARGET", "ALTA", "NO") == "B"       # niente officina
    assert classe_db("TARGET", "ALTA", "NON_DETERMINABILE") == "B"
    assert classe_db("TARGET", "MEDIA", "SI") == "B"      # officina ma confidenza media
    assert classe_db("TARGET", "MEDIA") == "B"
    # la REPUTAZIONE non concorre piu' alla classe (rimossa il 2026-09-07):
    # resta nei segnali, visibile in scheda, ma non promuove nessuno. Un
    # rivenditore molto recensito e senza officina deve restare B.
    assert classe_db("TARGET", "ALTA", "NO") == "B"
    assert classe_db("TARGET", "MEDIA", "NO") == "B"
    assert "reputazione" not in classe_db.__doc__.lower(), \
        "la via 3 e' stata rimossa: non deve tornare nella docstring"

    # C: TARGET incerto, o dubbio fondato
    assert classe_db("TARGET", "BASSA", "SI") == "C"
    assert classe_db("INDETERMINATO", "MEDIA") == "C"
    assert classe_db("INDETERMINATO", "ALTA") == "C"
    # il resto
    assert classe_db("INDETERMINATO", "BASSA") == "indeterminato"
    assert classe_db("NON_TARGET", "ALTA", "SI", annuncio) == "indeterminato"
    assert classe_db("", "") == "indeterminato"

    # modulazione dipendenti: solo fabbro, solo sopra soglia, mai sotto C
    assert modula_dipendenti("A", "fabbro", 30) == "B"
    assert modula_dipendenti("B", "fabbro", 30) == "C"
    assert modula_dipendenti("C", "fabbro", 30) == "C"
    assert modula_dipendenti("A", "fabbro", 5) == "A"
    assert modula_dipendenti("A", "fabbro", None) == "A"
    assert modula_dipendenti("A", "serramentista", 30) == "A"

    # estrazione campi da una risposta finta: nuovi campi compresi
    class _Blocco:
        type, text = "text", ('{"classificazione": "TARGET", "confidenza": "ALTA",'
                              ' "sede_comune": "Tivoli", "categoria": "fabbro"}')

    class _Usage:
        input_tokens, output_tokens = 10_000, 500

    class _FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                assert kwargs["temperature"] == 0
                assert kwargs["model"] == config.MODELLO
                return type("R", (), {"content": [_Blocco()], "usage": _Usage()})()

    dati = classifica(_FakeClient(), "contenuto")
    assert dati["classificazione"] == "TARGET"
    assert dati["sede_comune"] == "Tivoli" and dati["categoria"] == "fabbro"
    assert dati["materiali_rilevati"] == ""  # campo mancante -> vuoto, non KeyError
    assert set(CAMPI) <= set(dati)
    assert dati["costo_analisi_eur"] == costi.costo_anthropic(10_000, 500)
    print("ok")
