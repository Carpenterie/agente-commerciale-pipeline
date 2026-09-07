"""Riporta in B le aziende arrivate in classe A per la sola REPUTAZIONE.

La terza via alla classe A (reputazione Google forte) e' stata rimossa il
2026-09-07 — vedi il commento in `config.py`. Le righe scritte prima
portano ancora la classe vecchia: questo script le riallinea usando i dati
gia' in tabella, senza rianalizzare niente e senza spendere.

Tocca SOLO le A che non soddisfano nessuna delle due vie rimaste. Un'azienda
con segnale di lavoro o con officina accertata + confidenza alta resta A.

    python riallinea_classi.py                 # elenco, non scrive
    python riallinea_classi.py --applica       # scrive
    python riallinea_classi.py --ciclo <uuid>  # solo un ciclo
"""

from __future__ import annotations

import sys

import config  # noqa: F401  - imposta SSL_CERT_FILE
import db


def via_rimasta(riga: dict) -> str:
    """-> la via per cui la riga e' ancora A, o "" se nessuna."""
    if any(s.get("tipo") == "annuncio_lavoro" for s in (riga.get("segnali") or [])):
        return "segnale di lavoro"
    if riga.get("officina_propria") == "si" and riga.get("confidenza") == "alta":
        return "officina + confidenza alta"
    return ""


def da_riallineare(righe: list[dict]) -> list[dict]:
    return [r for r in righe if r.get("classe") == "A" and not via_rimasta(r)]


def main() -> int:
    applica = "--applica" in sys.argv
    ciclo = ""
    if "--ciclo" in sys.argv:
        ciclo = sys.argv[sys.argv.index("--ciclo") + 1]

    sb = db.client()
    righe, offset = [], 0
    while True:
        q = sb.table("aziende").select(
            "id,ragione_sociale,classe,confidenza,officina_propria,categoria,segnali")
        if ciclo:
            q = q.eq("ciclo_id", ciclo)
        blocco = q.eq("classe", "A").range(offset, offset + 999).execute().data
        righe += blocco
        if len(blocco) < 1000:
            break
        offset += 1000

    fuori = da_riallineare(righe)
    print(f"aziende in classe A: {len(righe)}"
          + (f" (ciclo {ciclo[:8]})" if ciclo else " (tutti i cicli)"))
    print(f"da riportare in B:   {len(fuori)}\n")

    for r in fuori:
        rep = next((s for s in (r.get("segnali") or [])
                    if s.get("tipo") == "reputazione_google"), {})
        print(f"  {r['ragione_sociale'][:38]:<40} {r.get('categoria') or '-':<14}"
              f" off={r.get('officina_propria'):<18}"
              f" {rep.get('recensioni', '-')} rec")

    if not fuori:
        print("niente da fare.")
        return 0
    if not applica:
        print(f"\n(prova: nessuna scrittura. Rilancia con --applica)")
        return 0

    for r in fuori:
        sb.table("aziende").update({"classe": "B"}).eq("id", r["id"]).execute()
    print(f"\n{len(fuori)} aziende riportate in classe B.")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        annuncio = [{"tipo": "annuncio_lavoro", "ruolo": "saldatore"}]
        rep = [{"tipo": "reputazione_google", "recensioni": 111, "punteggio": 4.9}]
        # resta A: ha il segnale, anche senza officina
        assert via_rimasta({"segnali": annuncio, "officina_propria": "no"})
        # resta A: officina accertata e confidenza alta
        assert via_rimasta({"officina_propria": "si", "confidenza": "alta"})
        # NON resta A: solo reputazione (il caso Allutek)
        assert not via_rimasta({"segnali": rep, "officina_propria": "non_determinabile",
                                "confidenza": "alta"})
        # officina si ma confidenza media: non bastava nemmeno prima
        assert not via_rimasta({"officina_propria": "si", "confidenza": "media"})
        assert not via_rimasta({})
        # il filtro tocca solo le A
        righe = [{"classe": "A", "segnali": rep, "confidenza": "alta"},
                 {"classe": "A", "segnali": annuncio},
                 {"classe": "B", "segnali": rep, "confidenza": "alta"}]
        assert len(da_riallineare(righe)) == 1
        print("ok")
    else:
        sys.exit(main())
