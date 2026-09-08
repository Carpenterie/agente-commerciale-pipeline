"""Chi in archivio e' un cliente attivo del committente? (diagnostica)

Applica il confronto permissivo di `dedup` alle righe GIA' scritte, senza
rianalizzare e senza spendere: il dato e' tutto in tabella.

Serve due scopi:
  1. elencare le aziende da togliere dall'archivio perche' sono clienti
     attivi che il match esatto non aveva riconosciuto;
  2. elencare i clienti dell'elenco il cui nome e' troppo corto per un
     confronto affidabile — non si tira a indovinare, li verifica il
     committente in sessione di revisione.

    python clienti_ambigui.py                 # elenco, non scrive
    python clienti_ambigui.py --scarta        # mette stato='scartato'
"""

from __future__ import annotations

import sys

import config
import db
import dedup


def carica(sb, cicli: list[str] | None = None) -> list[dict]:
    righe, off = [], 0
    while True:
        q = sb.table("aziende").select(
            "id,ragione_sociale,comune,classe,sito,stato,ciclo_id,motivazione")
        if cicli:
            q = q.in_("ciclo_id", cicli)
        b = q.range(off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            return righe
        off += 1000


SPIEGA = {
    "ragione+comune": "ragione sociale e comune coincidono",
    "nome contenuto (stesso comune)": "stesso comune",
    "nome contenuto (comune diverso: INCERTO)": "comune diverso, INCERTO: da verificare",
}


def motivo_scarto(criterio: str, sorgente: dict) -> str:
    """Perche' e' stata scartata e con chi ha fatto match: serve al
    committente per verificarla in sessione, e a chi legge fra sei mesi."""
    nome = (sorgente.get("ragione_sociale") or "?").strip()
    return (f"SCARTATA: possibile cliente attivo, corrisponde a {nome} "
            f"({SPIEGA.get(criterio, criterio)})")


def main() -> int:
    scarta = "--scarta" in sys.argv
    sb = db.client()

    elenco = db.esclusioni(sb)
    attivi = [r for r in elenco
              if (r.get("motivo") or "").strip().lower() == config.MOTIVO_CLIENTE_ATTIVO]
    righe = carica(sb)
    rif = dedup.riferimenti(attivi)
    print(f"clienti attivi in elenco: {len(attivi)}")
    print(f"aziende in archivio:      {len(righe)}\n")

    colpite = []
    for r in righe:
        s = {"nome": r["ragione_sociale"], "comune": r.get("comune"),
             "sito": r.get("sito")}
        criterio, sorgente = dedup.cerca_riferimento(s, rif, permissivo=True)
        if criterio:
            colpite.append((r, criterio, sorgente))

    print(f"DA TOGLIERE: {len(colpite)}\n")
    for r, criterio, sorgente in colpite:
        print(f"  {r['ragione_sociale'][:34]:<36}({str(r.get('comune'))[:13]:<15})"
              f" {r['classe']:<14} <- {(sorgente.get('ragione_sociale') or '')[:26]:<28}"
              f" [{criterio}]")

    ambigui = dedup.nomi_ambigui(attivi)
    print(f"\nDA VERIFICARE A MANO COL COMMITTENTE: {len(ambigui)} clienti attivi "
          f"con nome troppo corto (< {dedup.MIN_NOME_PERMISSIVO} caratteri "
          f"normalizzato)")
    for a in ambigui:
        print(f"  {(a.get('ragione_sociale') or '')[:34]:<36}"
              f"{str(a.get('comune') or '-')[:16]:<18}"
              f"'{dedup.norm_ragione(a.get('ragione_sociale') or '')}'")

    if not scarta:
        print("\n(prova: nessuna scrittura. Rilancia con --scarta)")
        return 0
    for r, criterio, sorgente in colpite:
        sb.table("aziende").update({
            "stato": "scartato",
            # in testa alla motivazione, non al posto: l'analisi e' pagata e
            # serve se il committente dice che il match era sbagliato
            "motivazione": motivo_scarto(criterio, sorgente) + " — "
                           + (r.get("motivazione") or ""),
        }).eq("id", r["id"]).execute()
    print(f"\n{len(colpite)} aziende messe in stato 'scartato', "
          f"con il motivo e il nome del cliente in testa alla motivazione.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
