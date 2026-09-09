"""Porta il campo `provincia` dell'archivio alla sola sigla a due lettere.

Il modello restituiva `sede_provincia` a volte come sigla e a volte per
esteso, e in archivio finivano come valori distinti: il menu di filtro
dell'app mostrava "FR" e "Frosinone" come due voci, e chi ne sceglieva una
perdeva meta' delle aziende.

Da qui in avanti ci pensa `db.riga_azienda` (via `config.sigla_provincia`).
Questo comando sistema le righe gia' scritte, senza rianalizzare.

    python normalizza_province.py             # elenco, non scrive
    python normalizza_province.py --applica   # scrive
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

import config
import db
import dedup
from data import comuni_lazio


def indice_cache(cartella: str = "cache") -> dict:
    """Le schede Maps gia' scaricate, indicizzate per dominio e per
    nome+comune. La provincia sta in `state` e non e' una sigla: e' il nome
    amministrativo, che `config.sigla_provincia` sa convertire."""
    per_dom, per_nome = {}, {}
    for f in sorted(pathlib.Path(cartella).glob("sourcing_*.json")):
        for s in json.loads(f.read_text(encoding="utf-8")).get("schede", []):
            d = dedup.dominio_azienda(s.get("sito") or "")
            k = (dedup.norm_ragione(s.get("nome") or ""),
                 (s.get("comune") or "").strip().lower())
            if d:
                per_dom.setdefault(d, s)
            if k[0]:
                per_nome.setdefault(k, s)
    return {"dominio": per_dom, "nome": per_nome}


def dalla_cache(riga: dict, cache: dict) -> str | None:
    d = dedup.dominio_azienda(riga.get("dominio") or riga.get("sito") or "")
    k = (dedup.norm_ragione(riga.get("ragione_sociale") or ""),
         (riga.get("comune") or "").strip().lower())
    s = cache["dominio"].get(d) or cache["nome"].get(k)
    if not s:
        return None
    sigla = config.sigla_provincia(s.get("provincia"))
    return sigla if sigla and len(sigla) == 2 else None


def da_correggere(righe: list[dict], cache: dict | None = None) -> list[tuple[dict, str]]:
    """-> [(riga, sigla_nuova)] solo dove il valore cambia davvero.

    Due casi: un nome per esteso da convertire in sigla, oppure un campo
    VUOTO da ricavare dal comune. Le province gia' valorizzate non si
    toccano mai: il dato dal sito e' piu' specifico e potrebbe riferirsi a
    una sede diversa da quella della scheda Maps.
    """
    fuori = []
    for r in righe:
        vecchio = (r.get("provincia") or "").strip()
        if not vecchio:
            # prima la scheda Maps (anagrafica, 87% delle schede), poi il
            # comune: quest'ultimo serve alle sole righe Exa
            nuovo = (dalla_cache(r, cache) if cache else None) \
                or comuni_lazio.provincia_di(r.get("comune"))
            if nuovo:
                fuori.append((r, nuovo))
            continue
        nuovo = config.sigla_provincia(vecchio)
        if nuovo and nuovo != vecchio:
            fuori.append((r, nuovo))
    return fuori


def main() -> int:
    applica = "--applica" in sys.argv
    sb = db.client()
    righe, off = [], 0
    while True:
        b = sb.table("aziende").select("id,ragione_sociale,provincia,comune").range(
            off, off + 999).execute().data
        righe += b
        if len(b) < 1000:
            break
        off += 1000

    cache = indice_cache()
    print(f"schede Maps in cache: {len(cache['dominio'])} per dominio, "
          f"{len(cache['nome'])} per nome+comune")
    fuori = da_correggere(righe, cache)
    print(f"righe in archivio: {len(righe)}")
    print(f"da correggere:     {len(fuori)}\n")
    for (vecchio, nuovo), n in sorted(collections.Counter(
            ((r.get("provincia") or "(vuota, dal comune)", s)
             for r, s in fuori)).items(), key=lambda x: -x[1]):
        print(f"  {vecchio:<24} -> {nuovo}   {n:>4} righe")
    resta_vuota = [r for r in righe if not (r.get("provincia") or "").strip()
                   and not dalla_cache(r, cache)
                   and not comuni_lazio.provincia_di(r.get("comune"))]
    print(f"\n  restano senza provincia: {len(resta_vuota)}"
          f"  (di cui {sum(1 for r in resta_vuota if not (r.get('comune') or '').strip())}"
          f" senza nemmeno il comune)")

    # cio' che resta fuori tabella: va guardato, non corretto alla cieca
    ignoti = {(r.get("provincia") or "").strip() for r in righe
              if (r.get("provincia") or "").strip()
              and len((r.get("provincia") or "").strip()) != 2
              and (r.get("provincia") or "").strip().lower()
              not in config.SIGLE_PROVINCE}
    if ignoti:
        print(f"\n  NON in SIGLE_PROVINCE, lasciate invariate: {sorted(ignoti)}")

    if not fuori or not applica:
        if fuori:
            print("\n(prova: nessuna scrittura. Rilancia con --applica)")
        return 0
    for r, nuovo in fuori:
        sb.table("aziende").update({"provincia": nuovo}).eq("id", r["id"]).execute()
    print(f"\n{len(fuori)} righe corrette.")
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        righe = [{"provincia": "Roma"}, {"provincia": "RM"}, {"provincia": ""},
                 {"provincia": None}, {"provincia": "Frosinone"},
                 {"provincia": "Oltrepo"},
                 {"provincia": "", "comune": "Tivoli"},        # si popola
                 {"provincia": "", "comune": "Ariccia"},       # fuori tabella
                 {"provincia": "VT", "comune": "Roma"}]        # NON si tocca
        esiti = da_correggere(righe)
        assert [s for _, s in esiti] == ["RM", "FR", "RM"], esiti
        # la scheda Maps ha la precedenza sul comune, e il nome
        # amministrativo diventa sigla
        finta = {"dominio": {}, "nome": {("azienda x", "ariccia"):
                 {"provincia": "Città metropolitana di Roma Capitale"}}}
        r = {"provincia": "", "ragione_sociale": "Azienda X", "comune": "Ariccia"}
        assert dalla_cache(r, finta) == "RM"
        assert [s for _, s in da_correggere([r], finta)] == ["RM"]
        # una scheda senza `state` non inventa niente
        finta["nome"][("azienda x", "ariccia")] = {"provincia": ""}
        assert dalla_cache(r, finta) is None
        assert not any(r.get("provincia") == "VT" for r, _ in esiti), \
            "una provincia gia' valorizzata non si sovrascrive col comune"
        # una sigla gia' giusta non si riscrive, e l'ignota non si tocca
        assert not any(r.get("provincia") in ("RM", "Oltrepo") for r, _ in esiti)
        print("ok")
    else:
        sys.exit(main())
