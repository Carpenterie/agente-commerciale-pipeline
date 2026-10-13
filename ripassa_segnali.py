"""Ripassa SOLO i segnali di lavoro (Exa) e la classe delle aziende di un
ciclo la cui ricerca degli annunci e' fallita (12/10: Foggia, 37 aziende con
402 prima che il credito Exa finisse del tutto a Lecce). Niente fetch, niente
modello, niente visure, niente bozze.

    python ripassa_segnali.py --ciclo ID --nomi FILE [--scrivi]

La classe si ricalcola con classify.classe_db + modula_dipendenti. La
specializzazione esclusiva (che preclude la A) non e' nel database: una B
con officina SI e confidenza alta lo era per forza (o per organico) e resta
B; negli altri casi la promozione ad A si applica e si elenca da verificare.
Le C che diventano A non hanno la visura (variante 2): si elencano.
"""

from __future__ import annotations

import sys

import classify
import config
import costi
import crediti
import rimetti_dentro
import segnali_lavoro


def nuova_classe(r: dict, segnali: list[dict]) -> tuple[str, str]:
    """-> (classe, nota). Solo TARGET con annuncio cambiano."""
    if r.get("esito_analisi") != "TARGET" or not segnali:
        return r["classe"], ""
    if r["classe"] == "A":
        return "A", ""
    if (r["classe"] == "B" and (r.get("officina_propria") or "").lower() == "si"
            and (r.get("confidenza") or "").lower() == "alta"):
        return "B", "resta B: specializzazione esclusiva o organico ampio"
    c = classify.classe_db("TARGET", (r.get("confidenza") or "").upper(),
                           r.get("officina_propria") or "", segnali)
    c = classify.modula_dipendenti(c, r.get("categoria") or "", r.get("n_dipendenti"))
    nota = "specializzazione non verificabile" if c == "A" else ""
    if c == "A" and r["classe"] == "C":
        nota += "; senza visura (era C)"
    return c, nota


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(".env")
    import db
    arg = lambda k: sys.argv[sys.argv.index(k) + 1]
    ciclo, scrivi = arg("--ciclo"), "--scrivi" in sys.argv
    nomi = {x.strip() for x in open(arg("--nomi")) if x.strip()}
    sb = db.client()
    righe, i = [], 0
    while True:
        b = (sb.table("aziende").select("id,ragione_sociale,classe,esito_analisi,confidenza,"
                                        "officina_propria,categoria,n_dipendenti,segnali,"
                                        "dominio,provincia,motivazione")
             .eq("ciclo_id", ciclo).range(i, i + 999).execute().data)
        righe += b
        if len(b) < 1000:
            break
        i += 1000
    righe = [r for r in righe if (r["ragione_sociale"] or "").strip() in nomi]
    fuori = [r for r in righe if rimetti_dentro.fuori(r)]
    if fuori:   # 13/10: le schede fuori territorio non si ripassano
        print(f"saltate perche' fuori territorio: {len(fuori)}")
        righe = [r for r in righe if not rimetti_dentro.fuori(r)]
    print(f"righe del ciclo {ciclo[:8]} da ripassare: {len(righe)} (nomi nel file: {len(nomi)})")
    if not scrivi:
        print("(misura: niente cercato ne' scritto. Rilancia con --scrivi)")
        return 0
    problemi = crediti.controllo(serve_exa_eur=len(righe) * 0.01, sb=sb)
    if problemi:
        print("ESITO: ripasso NON partito — " + "; ".join(problemi))
        return 1
    totali, cambi = costi.nuovo_ciclo(), []
    for r in righe:
        segnali = segnali_lavoro.cerca(r["ragione_sociale"], dominio=r.get("dominio") or "",
                                       provincia=r.get("provincia") or "")
        costi.registra_exa(totali, ricerche=1, risultati=len(segnali))
        if segnali_lavoro.ESAURITO:
            print("ESITO: ripasso INTERROTTO — Exa esaurito di nuovo")
            break
        if not segnali:
            continue
        classe, nota = nuova_classe(r, segnali)
        vecchi = [s for s in (r["segnali"] or []) if s.get("tipo") != "annuncio_lavoro"]
        sb.table("aziende").update({"segnali": segnali + vecchi, "classe": classe}) \
            .eq("id", r["id"]).execute()
        cambi.append((r["ragione_sociale"], r["classe"], classe, nota))
    print(f"\ncon annunci di lavoro: {len(cambi)}")
    for nome, prima, dopo, nota in cambi:
        print(f"  {nome}: {prima} -> {dopo}" + (f" ({nota})" if nota else ""))
    crediti.registra_spesa_exa(costi.stampa(totali)["costo_exa_eur"])
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        ann = [{"tipo": "annuncio_lavoro", "ruolo": "saldatore"}]
        base = {"esito_analisi": "TARGET", "categoria": "serramentista", "n_dipendenti": None}
        assert nuova_classe({**base, "classe": "B", "confidenza": "alta",
                             "officina_propria": "no"}, ann)[0] == "A"
        assert nuova_classe({**base, "classe": "B", "confidenza": "alta",
                             "officina_propria": "si"}, ann)[0] == "B"      # era mono
        c, nota = nuova_classe({**base, "classe": "C", "confidenza": "media",
                                "officina_propria": "no"}, ann)
        assert c == "A" and "senza visura" in nota
        assert nuova_classe({**base, "classe": "C", "confidenza": "media",
                             "officina_propria": "no"}, [])[0] == "C"         # niente annuncio
        assert nuova_classe({**base, "esito_analisi": "NON_TARGET", "classe": "indeterminato",
                             "confidenza": "alta", "officina_propria": "si"}, ann)[0] == "indeterminato"
        fabbro = {**base, "categoria": "fabbro", "n_dipendenti": config.SOGLIA_ORGANICO_AMPIO + 1}
        assert nuova_classe({**fabbro, "classe": "C", "confidenza": "media",
                             "officina_propria": "no"}, ann)[0] == "B"        # organico ampio
        print("ok")
        sys.exit(0)
    sys.exit(main())
