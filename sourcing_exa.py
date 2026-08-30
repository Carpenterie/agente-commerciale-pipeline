"""Exa per significato (PRD §4): le 5 query del test, 25 risultati l'una.

API raw come nel test di sourcing: attenzione, testo/summary vanno DENTRO
`contents`, non top-level. Qui si escludono già exa.ai e i portali (lista
in config); il resto del dedup è compito di dedup.py.
"""

from __future__ import annotations

import json
import os
import urllib.request
from urllib.parse import urlparse

import config
import dedup


def _dominio(url: str) -> str:
    return urlparse(url).netloc.replace("www.", "").lower() if url else ""


def _normalizza(query: str, res: dict) -> dict:
    return {
        "fonte": "exa",
        "query": query,
        "nome": (res.get("title") or "").strip(),
        "sito": res.get("url") or "",
        "dominio": _dominio(res.get("url") or ""),
        "highlights": " | ".join(res.get("highlights") or []),
    }


def cerca(provincia_nome: str, log=print) -> list[dict]:
    """5 query per la provincia (per RM sono le stringhe validate dal test)."""
    chiave = os.environ["EXA_API_KEY"]
    righe = []
    for sagoma in config.QUERY_EXA:
        q = sagoma.format(provincia=provincia_nome)
        req = urllib.request.Request(
            "https://api.exa.ai/search",
            data=json.dumps({
                "query": q, "type": "auto",
                "numResults": config.EXA_NUM_RISULTATI,
                "contents": {"highlights": True},
            }).encode(),
            headers={"content-type": "application/json", "x-api-key": chiave},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            risultati = json.load(r).get("results", [])
        buone = [_normalizza(q, res) for res in risultati
                 if not dedup.e_portale(res.get("url") or "")]
        log(f"exa: {q} -> {len(risultati)} risultati, {len(buone)} dopo filtro portali")
        righe += buone
    return righe


if __name__ == "__main__":
    n = _normalizza("q", {"title": " Fabbro X ", "url": "https://www.fabbrox.it/chi-siamo",
                          "highlights": ["lavoriamo il ferro", "officina propria"]})
    assert n["dominio"] == "fabbrox.it" and n["nome"] == "Fabbro X"
    assert n["highlights"] == "lavoriamo il ferro | officina propria"
    assert dedup.e_portale("https://paginegialle.it") and dedup.e_portale("https://exa.ai/x")
    assert not dedup.e_portale("https://fabbrox.it")
    assert config.QUERY_EXA[0].format(provincia="Roma") == \
        "officina fabbro cancelli e inferriate in ferro provincia di Roma"  # stringa del test
    print("ok")
