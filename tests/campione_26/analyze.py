"""Una chiamata LLM per azienda: prompt -> JSON -> dict + token + costo."""

from __future__ import annotations

import json
import re

import prompts

MODELLO = "claude-sonnet-4-6"

# Prezzi Anthropic per Claude Sonnet 4.6 (docs: $3.00 / $15.00 per milione di token).
PREZZO_INPUT_USD_PER_TOKEN = 3.00 / 1_000_000
PREZZO_OUTPUT_USD_PER_TOKEN = 15.00 / 1_000_000
# ponytail: cambio fisso, non una chiamata a un servizio FX. Aggiornalo a mano se conta.
USD_EUR = 0.92

MAX_TOKENS = 2000

CAMPI = (
    "materiali_rilevati", "lavora_acciaio", "capacita_officina",
    "attivita_prevalente", "classificazione", "confidenza", "motivazione",
    "segnali_positivi", "segnali_dubbio", "prodotto_da_proporre",
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
        return json.loads(t[inizio : fine + 1])


def costo_eur(token_input: int, token_output: int) -> float:
    usd = token_input * PREZZO_INPUT_USD_PER_TOKEN + token_output * PREZZO_OUTPUT_USD_PER_TOKEN
    return round(usd * USD_EUR, 6)


def analizza(client, contenuto: str) -> dict:
    """Un tentativo + un retry. Solleva l'ultima eccezione se falliscono entrambi."""
    messaggio = [{"role": "user", "content": prompts.costruisci(contenuto)}]
    ultimo_errore: Exception | None = None

    for _ in range(2):
        try:
            risposta = client.messages.create(
                model=MODELLO, max_tokens=MAX_TOKENS, temperature=0, messages=messaggio
            )
            testo = next(b.text for b in risposta.content if b.type == "text")
            dati = estrai_json(testo)
            dati = {c: dati.get(c, "") for c in CAMPI}
            dati["token_input"] = risposta.usage.input_tokens
            dati["token_output"] = risposta.usage.output_tokens
            dati["costo_stimato_eur"] = costo_eur(
                risposta.usage.input_tokens, risposta.usage.output_tokens
            )
            return dati
        except Exception as e:  # noqa: BLE001 - include JSON malformato e errori API
            ultimo_errore = e

    raise ultimo_errore  # type: ignore[misc]
