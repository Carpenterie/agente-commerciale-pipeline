"""Carica l'elenco clienti di Claudia nella tabella `esclusioni` (PRD §11).

    python carica_esclusioni.py elenco.xlsx [--dry-run]

Regge un file compilato a mano, Excel o CSV: colonne in ordine libero
riconosciute dall'intestazione, colonne mancanti, celle vuote, maiuscole
incoerenti. In tabella vanno i valori GREZZI: la normalizzazione è compito
di dedup.py, al momento del confronto.

Colonne della tabella `esclusioni` su Supabase: ragione_sociale,
partita_iva, dominio, comune, motivo. Il `motivo` decide il comportamento:
"cliente attivo" esclude l'azienda dalla ricerca, "ex cliente: <stato>" la
lascia nei risultati marcandola (il commerciale sa che ci ha già lavorato).
La categoria viene caricata normalizzata ("Show room" e "Showroom" sono lo
stesso valore).

`--dry-run`: mostra cosa verrebbe caricato senza toccare Supabase.
"""

from __future__ import annotations

import csv
import os
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import config
import dedup

# la prima intestazione che contiene una di queste sottostringhe vince
COLONNE = {
    "ragione_sociale": ("ragion", "denominaz", "azienda", "nome", "cliente"),
    "partita_iva": ("iva", "vat", "codice fiscale"),
    "dominio": ("dominio", "sito", "web", "url"),
    "comune": ("comune", "citta", "città", "localita", "località"),
    "stato": ("stato",),
    "categoria": ("categoria", "tipo azienda"),
}
# quante colonne note deve avere una riga per essere l'intestazione: i file
# compilati a mano hanno righe di titolo sopra (questo ne ha due)
MIN_COLONNE_INTESTAZIONE = 3
# senza queste il file si carica lo stesso: `stato` mancante significa
# elenco di soli clienti attuali (si esclude tutto: è la scelta prudente)
COLONNE_OPZIONALI = ("stato", "categoria")


def leggi_xlsx(percorso):
    """Foglio 1 come lista di dict, header dalla prima riga (dal test di
    sourcing, validato: sostituisce pandas/openpyxl)."""
    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    z = zipfile.ZipFile(percorso)
    condivise = []
    if "xl/sharedStrings.xml" in z.namelist():
        condivise = ["".join(t.text or "" for t in si.iter(NS + "t"))
                     for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    righe = []
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(NS + "row"):
        celle = {}
        for c in row.iter(NS + "c"):
            col = re.match(r"[A-Z]+", c.get("r")).group()
            v, inline = c.find(NS + "v"), c.find(NS + "is")
            if v is not None:
                celle[col] = condivise[int(v.text)] if c.get("t") == "s" else (v.text or "")
            elif inline is not None:
                celle[col] = "".join(t.text or "" for t in inline.iter(NS + "t"))
        righe.append(celle)
    return _da_intestazione(righe)


def _da_intestazione(righe: list[dict]) -> list[dict]:
    """Trova la riga di intestazione (non sempre è la prima: qui ci sono due
    righe di titolo sopra) e restituisce le righe dati come dict."""
    for i, riga in enumerate(righe[:20]):
        if len(_mappa_colonne(riga.values())) >= MIN_COLONNE_INTESTAZIONE:
            return [{nome: r.get(col, "") for col, nome in riga.items()}
                    for r in righe[i + 1:]]
    return []


def leggi_csv(percorso):
    """Separatore ',' o ';' (Excel in locale italiano esporta ';')."""
    with open(percorso, encoding="utf-8-sig", newline="") as f:
        prima = f.readline()
        f.seek(0)
        sep = ";" if prima.count(";") > prima.count(",") else ","
        return list(csv.DictReader(f, delimiter=sep))


def _mappa_colonne(intestazioni) -> dict:
    """Il primo indizio che trova una colonna vince: l'ordine in COLONNE è
    una preferenza (per la categoria "Categoria" batte "Tipo azienda")."""
    mappa, intestazioni = {}, list(intestazioni)
    for campo, indizi in COLONNE.items():
        for indizio in indizi:
            trovata = next((h for h in intestazioni
                            if indizio in (h or "").strip().lower()), None)
            if trovata:
                mappa[campo] = trovata
                break
    return mappa


def _motivo(stato: str) -> str:
    """Il campo `motivo` distingue chi va escluso dalla ricerca da chi è un
    ex cliente da riattivare: `dedup` esclude solo i primi."""
    s = (stato or "").strip()
    if not s:
        # nessuno stato dichiarato: si tratta come cliente attuale ed esclude.
        # Meglio perdere un'azienda che consegnarne una già cliente.
        return config.MOTIVO_CLIENTE_ATTIVO
    if s.lower() in config.STATI_CLIENTE_ATTIVO:
        return config.MOTIVO_CLIENTE_ATTIVO
    return f"{config.MOTIVO_EX_CLIENTE}: {s}"


def _categoria(valore: str) -> str:
    """"Show room" e "Showroom" sono la stessa cosa scritta in due modi."""
    return config.CATEGORIE_CLIENTI_ALIAS.get((valore or "").strip().lower(), "")


def estrai(righe_grezze: list[dict]) -> tuple[list[dict], list[str]]:
    """-> (righe pronte per la tabella, anomalie da mostrare)."""
    if not righe_grezze:
        return [], ["file vuoto"]
    mappa = _mappa_colonne(righe_grezze[0].keys())
    anomalie = [f"colonna '{campo}' non trovata nelle intestazioni"
                for campo in COLONNE
                if campo not in mappa and campo not in COLONNE_OPZIONALI]
    if "stato" not in mappa:
        anomalie.append("nessuna colonna 'Stato commerciale': tutte le righe "
                        "valgono come clienti attivi ed escludono la ricerca")
    if "ragione_sociale" not in mappa:
        return [], anomalie + ["senza ragione sociale non si carica niente"]

    righe = []
    for i, r in enumerate(righe_grezze, 2):  # 2: la riga 1 è l'intestazione
        voce = {campo: (r.get(col) or "").strip()
                for campo, col in mappa.items()}
        if not any(voce.values()):
            continue  # riga lasciata vuota nel file
        if not (voce.get("ragione_sociale")
                or dedup.norm_piva(voce.get("partita_iva", ""))
                or dedup.norm_dominio(voce.get("dominio", ""))):
            anomalie.append(f"riga {i}: nessun identificativo utilizzabile, saltata")
            continue
        voce["motivo"] = _motivo(voce.pop("stato", ""))
        voce["categoria_normalizzata"] = _categoria(voce.pop("categoria", ""))
        righe.append(voce)
    return righe, anomalie


def main() -> int:
    argomenti = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry_run = "--dry-run" in sys.argv
    if len(argomenti) != 1:
        print(__doc__)
        return 2
    percorso = Path(argomenti[0])
    grezze = leggi_xlsx(percorso) if percorso.suffix.lower() == ".xlsx" else leggi_csv(percorso)
    righe, anomalie = estrai(grezze)

    from collections import Counter

    for a in anomalie:
        print(f"ATTENZIONE: {a}")

    attivi = [r for r in righe if config.esclude(r["motivo"])]
    ex = [r for r in righe if not config.esclude(r["motivo"])]
    print(f"\n{len(righe)} righe lette dal file")
    print(f"  {len(attivi):>4} da ESCLUDERE dalla ricerca (motivo '{config.MOTIVO_CLIENTE_ATTIVO}')")
    print(f"  {len(ex):>4} ex clienti: caricati ma NON esclusi, compaiono marcati")
    print("\nmotivi:")
    for motivo, n in Counter(r["motivo"] for r in righe).most_common():
        print(f"  {n:>4}  {motivo}")
    print("\ncategorie normalizzate:")
    for cat, n in Counter(r["categoria_normalizzata"] or "(vuota)"
                          for r in righe).most_common():
        print(f"  {n:>4}  {cat}")
    identificativi = Counter(
        "P.IVA" if dedup.norm_piva(r.get("partita_iva", "")) else
        ("ragione+comune" if r.get("comune") else "solo ragione")
        for r in attivi)
    print("\ncome verranno riconosciuti i", len(attivi), "da escludere:")
    for k, n in identificativi.most_common():
        print(f"  {n:>4}  {k}")
    print("\nprime 5 righe da escludere:")
    for r in attivi[:5]:
        print(f"  {r.get('ragione_sociale', '?')[:44]:<45} "
              f"piva={dedup.norm_piva(r.get('partita_iva', '')) or '-':<12} "
              f"comune={r.get('comune') or '-':<22} {r['motivo']}")
    print("\nprime 3 righe ex cliente:")
    for r in ex[:3]:
        print(f"  {r.get('ragione_sociale', '?')[:44]:<45} "
              f"comune={r.get('comune') or '-':<22} {r['motivo']}")
    if not righe:
        return 1
    if dry_run:
        print("\n--dry-run: niente scritto su Supabase")
        return 0

    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv(Path(__file__).parent / ".env")
    sb = create_client(os.environ["SUPABASE_URL"],
                       os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    COLONNE_TABELLA = ("ragione_sociale", "partita_iva", "dominio", "comune",
                       "motivo", "categoria")
    da_scrivere = [{**{c: r[c] for c in COLONNE_TABELLA if c in r},
                    "categoria": r.get("categoria_normalizzata") or None}
                   for r in righe]
    sb.table("esclusioni").insert(da_scrivere).execute()
    print(f"\nCaricate {len(righe)} righe in esclusioni "
          f"({len(attivi)} escludono la ricerca, {len(ex)} solo marcate)")
    return 0


if __name__ == "__main__" and "--test" in sys.argv:
    import tempfile

    contenuto = (
        "Nome Azienda;P. IVA;Sito web;Città\n"
        "ALUSETTE SRL;IT 01234567890;www.alusette.it;Roma\n"
        ";;;\n"
        "PM Serramenti s.r.l.;;;LATINA\n"
        ";;solo-dominio.it;\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                     encoding="utf-8") as f:
        f.write(contenuto)
    righe, anomalie = estrai(leggi_csv(f.name))
    Path(f.name).unlink()
    assert len(righe) == 3, righe
    assert righe[0]["ragione_sociale"] == "ALUSETTE SRL"
    assert righe[0]["partita_iva"] == "IT 01234567890"  # grezzo: normalizza dedup
    assert righe[1]["comune"] == "LATINA"
    assert righe[2]["dominio"] == "solo-dominio.it"     # senza ragione: resta, ha il dominio
    assert righe[0]["motivo"] == config.MOTIVO_CLIENTE_ATTIVO  # senza stato: esclude
    assert any("Stato commerciale" in a for a in anomalie), anomalie
    # file senza P.IVA e con intestazioni diverse
    righe2, anomalie2 = estrai([{"Cliente": "X Srl", "Comune": "Rieti"}])
    assert righe2[0]["ragione_sociale"] == "X Srl" and righe2[0]["comune"] == "Rieti"
    assert any("partita_iva" in a for a in anomalie2)
    assert any("dominio" in a for a in anomalie2)

    # file con lo stato: solo Attivo e Fidelizzato escludono
    con_stato = [
        {"Nome Azienda": "A srl", "Città": "Roma", "Stato commerciale": "Attivo",
         "Categoria": "Show room"},
        {"Nome Azienda": "B srl", "Città": "Tivoli", "Stato commerciale": "Fidelizzato",
         "Categoria": "Serramenti"},
        {"Nome Azienda": "C srl", "Città": "Anzio", "Stato commerciale": "Non attivo",
         "Categoria": "Fabbro"},
        {"Nome Azienda": "D srl", "Città": "Rieti", "Stato commerciale": "Perso per prezzo",
         "Categoria": ""},
    ]
    righe3, _ = estrai(con_stato)
    motivi = [r["motivo"] for r in righe3]
    assert motivi[0] == motivi[1] == config.MOTIVO_CLIENTE_ATTIVO, motivi
    assert motivi[2] == "ex cliente: Non attivo", motivi
    assert motivi[3] == "ex cliente: Perso per prezzo", motivi
    # "Show room" e "Serramenti" sono gli stessi valori di showroom/serramentista
    assert [r["categoria_normalizzata"] for r in righe3] == \
        ["showroom", "serramentista", "fabbro", ""]
    print("ok")
elif __name__ == "__main__":
    raise SystemExit(main())
