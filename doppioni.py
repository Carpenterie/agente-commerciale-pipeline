"""Doppioni in archivio: il segnale `doppione` (con l'id della scheda che
resta) toglie la scheda dalle liste SENZA cancellarla e senza toccare lo
stato (via del committente, 2026-10-07). Nati soprattutto il 19-20/9,
quando il controllo "gia' in archivio" vedeva solo 1000 righe su 4185.

    python doppioni.py            # misura: gruppi, chi resta, chi esce
    python doppioni.py --scrivi   # segna le schede che escono
    python doppioni.py --stesso-recapito [--scrivi]   # segnale informativo
    python doppioni.py --test

Gruppi FORTI (si segnano): stessa P.IVA, stesso dominio, stessa ragione
sociale nello stesso comune (non un nome generico come "Fabbro"), stessa
email se c'e' anche un telefono o una parola del nome in comune.
Gruppi DEBOLI (solo elenco, quelli con almeno una A/B/C): solo telefono,
solo nome generico, sola email senza altro in comune.
Resta: la scheda gia' contattata, poi la classe piu' alta, poi quella con
email o sito, poi la piu' vecchia. Una scheda che uscirebbe ma porta dati
inseriti dalle persone (stato, recapiti del commerciale, assegnazione,
storico) NON si segna: va nell'elenco da guardare.
"""

from __future__ import annotations

import collections
import datetime
import re
import sys

import dedup

TIPO = "doppione"
# informativo (7/10): NON toglie dalle liste. Sui gruppi deboli con A/B/C e
# sui forti fermati dai dati delle persone: decide il commerciale
TIPO_INFO = "stesso_recapito"
PAROLE_GENERICHE = {
    "srl", "srls", "snc", "sas", "spa", "soc", "coop", "ditta", "della", "delle",
    "infissi", "serramenti", "fabbro", "fabbri", "ferro", "porte", "finestre",
    "roma", "home", "metal", "metalli", "carpenteria", "metallica", "costruzioni",
    "alluminio", "lavorazioni", "lavorazione", "officina", "group", "gruppo",
    "italia", "design", "sistemi", "service", "servizi"}
NOMI_GENERICI = {"fabbro", "fabbri", "serramenti", "infissi", "ferramenta", "officina",
                 "carpenteria", "carpenteria metallica", "lavorazione ferro", "saldatore",
                 "fabbro roma"}
RANGO_CLASSE = {"A": 0, "B": 1, "C": 2, "indeterminato": 3, None: 4}


def parole(nome: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", dedup.norm_ragione(nome or ""))
            if len(w) >= 4 and w not in PAROLE_GENERICHE}


def nome_generico(rag: str) -> bool:
    return rag in NOMI_GENERICI or (len(rag.split()) == 1 and len(rag) < 8)


def contattata(a: dict, storico: dict) -> bool:
    return a["stato"] == "contattato" or any(
        t == "email_inviata" for t in storico.get(a["id"], ()))


def dati_umani(a: dict, storico: dict) -> list[str]:
    """Cosa c'e' di inserito dalle persone su questa scheda."""
    d = []
    if a.get("stato") != "da_lavorare":
        d.append(f"stato {a.get('stato')}")
    for campo in ("email_commerciale", "telefono_commerciale", "assegnato_a",
                  "prossima_azione", "ultimo_contatto"):
        if (str(a.get(campo) or "")).strip():
            d.append(campo)
    if a.get("n_contatti"):
        d.append("n_contatti")
    if storico.get(a["id"]):
        d.append(f"storico ({len(storico[a['id']])} attivita')")
    return d


def chi_resta(gruppo: list[dict], storico: dict) -> dict:
    return min(gruppo, key=lambda a: (
        not contattata(a, storico), RANGO_CLASSE.get(a.get("classe"), 4),
        not ((a.get("email_commerciale") or a.get("email_aziendale") or a.get("sito") or "").strip()),
        a.get("creato_il") or ""))


def _tel(t: str | None) -> str:
    t = re.sub(r"\D", "", t or "")[-9:]
    return t if len(t) >= 8 else ""


def _email(a: dict) -> list[str]:
    return [e.strip().lower() for e in (a.get("email_aziendale"), a.get("email_commerciale"))
            if "@" in (e or "")]


def gruppi(righe: list[dict]) -> tuple[list[tuple[list[dict], set]], list[tuple[list[dict], set]]]:
    """-> (forti, deboli): liste di (righe, criteri)."""
    padre = {a["id"]: a["id"] for a in righe}

    def radice(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    per_id = {a["id"]: a for a in righe}
    forti_coppie, deboli_coppie = [], []
    indice = collections.defaultdict(list)
    for a in righe:
        p = dedup.norm_piva(a.get("partita_iva") or "")
        if p:
            indice[("piva", p)].append(a["id"])
        d = dedup.dominio_azienda(a.get("dominio") or a.get("sito") or "")
        if d:
            indice[("dominio", d)].append(a["id"])
        r, c = dedup.norm_ragione(a.get("ragione_sociale") or ""), dedup._norm_comune(a.get("comune") or "")
        if r and c:
            indice[("nome_generico" if nome_generico(r) else "ragione+comune", (r, c))].append(a["id"])
        if _tel(a.get("telefono")):
            indice[("telefono", _tel(a.get("telefono")))].append(a["id"])
        for e in _email(a):
            indice[("email", e)].append(a["id"])
    for (crit, _), ids in indice.items():
        ids = sorted(set(ids))
        for x in ids[1:]:
            y = ids[0]
            if crit == "email":
                a, b = per_id[x], per_id[y]
                stesso_tel = _tel(a.get("telefono")) and _tel(a.get("telefono")) == _tel(b.get("telefono"))
                if stesso_tel or parole(a["ragione_sociale"]) & parole(b["ragione_sociale"]):
                    forti_coppie.append((x, y, "email"))
                else:
                    deboli_coppie.append((x, y, "sola email"))
            elif crit in ("piva", "dominio", "ragione+comune"):
                forti_coppie.append((x, y, crit))
            else:
                deboli_coppie.append((x, y, crit))

    def componi(coppie):
        for x, y, _ in coppie:
            rx, ry = radice(x), radice(y)
            if rx != ry:
                padre[ry] = rx
        g, crit = collections.defaultdict(list), collections.defaultdict(set)
        for a in righe:
            g[radice(a["id"])].append(a)
        for x, _, c in coppie:
            crit[radice(x)].add(c)
        return [(v, crit[k]) for k, v in g.items() if len(v) > 1]

    forti = componi(forti_coppie)
    # i deboli si compongono sopra i forti: un gruppo debole e' tale solo se
    # unisce schede che i criteri forti non avevano gia' unito
    radici_forti = {a["id"]: radice(a["id"]) for a in righe}
    deboli_veri = [(x, y, c) for x, y, c in deboli_coppie if radici_forti[x] != radici_forti[y]]
    deboli = [(g, c) for g, c in componi(deboli_veri)
              if len({radici_forti[a["id"]] for a in g}) > 1]
    return forti, deboli


def segnale(tenuta: dict, criteri: set) -> dict:
    return {"tipo": TIPO, "di": tenuta["id"], "criterio": "+".join(sorted(criteri)),
            "segnale": f"doppione di '{tenuta['ragione_sociale']}' "
                       f"({'+'.join(sorted(criteri))}) — {datetime.date.today().isoformat()}"}


def in_comune(a: dict, b: dict) -> list[str]:
    c = []
    if _tel(a.get("telefono")) and _tel(a.get("telefono")) == _tel(b.get("telefono")):
        c.append(f"telefono {a.get('telefono')}")
    comuni = sorted(set(_email(a)) & set(_email(b)))
    c += [f"email {e}" for e in comuni]
    return c


def segnale_info(a: dict, gruppo: list[dict]) -> dict:
    altre = []
    for b in gruppo:
        if b["id"] != a["id"]:
            c = in_comune(a, b)
            altre.append({"id": b["id"], "nome": b["ragione_sociale"],
                          "in_comune": c or ["collegata tramite un'altra scheda del gruppo"]})
    testo = "; ".join(f"'{x['nome']}' ({', '.join(x['in_comune'])})" for x in altre)
    return {"tipo": TIPO_INFO, "altre": altre,
            "segnale": f"stesso recapito di altre schede, da verificare prima di "
                       f"scrivere: {testo} — {datetime.date.today().isoformat()}"}


def giro(scrivi: bool, log=print, info: bool = False) -> None:
    import db
    sb = db.client()

    def tutte(t, cols):
        out, i = [], 0
        while True:
            b = sb.table(t).select(cols).order("id").range(i, i + 999).execute().data
            out += b
            if len(b) < 1000:
                return out
            i += 1000

    righe = tutte("aziende", "id,ragione_sociale,partita_iva,dominio,sito,comune,telefono,"
                             "email_aziendale,email_commerciale,telefono_commerciale,classe,stato,"
                             "assegnato_a,prossima_azione,ultimo_contatto,n_contatti,segnali,"
                             "creato_il,bozza_generata,bozza_corpo")
    storico = collections.defaultdict(list)
    for x in tutte("attivita", "azienda_id,tipo"):
        storico[x["azienda_id"]].append(x["tipo"])
    forti, deboli = gruppi(righe)
    escono, da_guardare, gia = [], [], 0
    for g, crit in forti:
        tenuta = chi_resta(g, storico)
        for a in g:
            if a is tenuta:
                continue
            if any(s.get("tipo") == TIPO for s in a.get("segnali") or []):
                gia += 1
            elif dati_umani(a, storico):
                da_guardare.append((a, tenuta, crit, dati_umani(a, storico)))
            else:
                escono.append((a, tenuta, crit))
    abc = lambda g: any(a.get("classe") in ("A", "B", "C") for a in g)
    log(f"gruppi forti {len(forti)} (righe {sum(len(g) for g, _ in forti)}), "
        f"con A/B/C {sum(abc(g) for g, _ in forti)}; deboli {len(deboli)}, con A/B/C "
        f"{sum(abc(g) for g, _ in deboli)}")
    log(f"escono dalle liste: {len(escono)} (A/B/C {sum(a.get('classe') in ('A', 'B', 'C') for a, _, _ in escono)}, "
        f"con bozza {sum(bool(a.get('bozza_generata') or a.get('bozza_corpo')) for a, _, _ in escono)}); "
        f"da guardare (dati delle persone): {len(da_guardare)}; gia' segnate: {gia}")
    for a, t, crit in escono:
        if a.get("classe") in ("A", "B", "C"):
            log(f"  esce [{a['classe']}] {a['ragione_sociale'][:36]:<37} -> resta "
                f"[{t.get('classe')}] {t['ragione_sociale'][:36]} ({'+'.join(sorted(crit))})")
    log("\nDA GUARDARE (non segnate):")
    for a, t, crit, d in da_guardare:
        log(f"  [{a.get('classe')}, {a['stato']}] {a['ragione_sociale'][:34]:<35} ({a.get('comune') or '-'}) "
            f"-> resterebbe [{t.get('classe')}, {t['stato']}] {t['ragione_sociale'][:30]} "
            f"| {'+'.join(sorted(crit))} | {', '.join(d)}")
    log("\nDEBOLI CON A/B/C (solo elenco):")
    for g, crit in deboli:
        if abc(g):
            log(f"  {'+'.join(sorted(crit)):<14} " + " || ".join(
                f"{a['ragione_sociale'][:30]} [{a.get('classe')}, {a['stato']}, {a.get('comune') or '-'}]"
                for a in sorted(g, key=lambda a: a.get("creato_il") or "")))
    if info:
        # i gruppi deboli con A/B/C e i forti con una scheda fermata dai dati
        # delle persone: segnale su TUTTE le schede del gruppo
        fermi = {a["id"] for a, _, _, _ in da_guardare}
        bersagli = [g for g, _ in deboli if abc(g)] + \
                   [g for g, _ in forti if fermi & {a["id"] for a in g}]
        n = 0
        for g in bersagli:
            for a in g:
                s = segnale_info(a, g)
                log(f"  {a['ragione_sociale'][:34]:<35} {s['segnale'][:110]}")
                if not scrivi:
                    continue
                r = sb.table("aziende").select("segnali").eq("id", a["id"]).execute().data[0]
                if any(x.get("tipo") == TIPO_INFO for x in r.get("segnali") or []):
                    continue
                sb.table("aziende").update({"segnali": (r.get("segnali") or []) + [s]}
                                           ).eq("id", a["id"]).execute()
                n += 1
        log(f"\ngruppi {len(bersagli)}, schede {sum(len(g) for g in bersagli)}"
            + (f" — SEGNATE stesso_recapito: {n}" if scrivi else " (misura)"))
        return
    if scrivi:
        n = 0
        for a, t, crit in escono:
            r = sb.table("aziende").select("segnali").eq("id", a["id"]).execute().data[0]
            if any(s.get("tipo") == TIPO for s in r.get("segnali") or []):
                continue
            sb.table("aziende").update({"segnali": (r.get("segnali") or []) + [segnale(t, crit)]}
                                       ).eq("id", a["id"]).execute()
            n += 1
        log(f"\nSEGNATE doppione: {n}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        def r(i, nome, **k):
            return {"id": i, "ragione_sociale": nome, "comune": k.pop("comune", "Roma"),
                    "stato": k.pop("stato", "da_lavorare"), "classe": k.pop("classe", "indeterminato"),
                    "creato_il": k.pop("creato_il", f"2026-09-{10 + int(i[-1])}"), **k}
        righe = [r("a1", "CSM infissi Roma", email_aziendale="x@csm.it", telefono="06 1234567", classe="A",
                   stato="contattato"),
                 r("a2", "CSM infissi Ardea", email_aziendale="x@csm.it", telefono="061234567", classe="C"),
                 r("b1", "Ipla Srl", email_aziendale="studio@comune.it", classe="C"),
                 r("b2", "Mobili Mancini", email_aziendale="studio@comune.it", classe="C"),
                 r("c1", "Fabbro", comune="Rieti"), r("c2", "Fabbro", comune="Rieti"),
                 r("d1", "Alfam Srl", email_aziendale="info@alfam.it"),
                 r("d2", "ALFAM Industrial", email_aziendale="info@alfam.it", classe="A"),
                 r("e1", "Ferri Bianchi", sito="https://ferribianchi.it", telefono="0774 999888"),
                 r("e2", "Officina Rossi", telefono="0774999888", classe="B")]
        forti, deboli = gruppi(righe)
        f = sorted(sorted(a["id"] for a in g) for g, _ in forti)
        assert f == [["a1", "a2"], ["d1", "d2"]], f
        d = sorted(sorted(a["id"] for a in g) for g, _ in deboli)
        assert d == [["b1", "b2"], ["c1", "c2"], ["e1", "e2"]], d
        storico = {"a1": ["email_inviata"]}
        assert chi_resta([x for x in righe if x["id"] in ("a1", "a2")], storico)["id"] == "a1"
        assert chi_resta([x for x in righe if x["id"] in ("d1", "d2")], {})["id"] == "d2"   # la A
        assert dati_umani(righe[0], storico) == ["stato contattato", "storico (1 attivita')"]
        assert dati_umani(righe[1], {}) == []
        assert dati_umani({**righe[1], "email_commerciale": "a@b.it"}, {}) == ["email_commerciale"]
        s = segnale(righe[0], {"email"})
        assert s["tipo"] == TIPO and s["di"] == "a1" and "CSM infissi Roma" in s["segnale"]
        g = [x for x in righe if x["id"] in ("e1", "e2")]
        si = segnale_info(g[0], g)
        assert si["tipo"] == TIPO_INFO and si["altre"][0]["id"] == "e2"
        assert si["altre"][0]["in_comune"] == ["telefono 0774 999888"], si
        catena = [r("f1", "A", telefono="0611111111"), r("f2", "B", telefono="0611111111",
                  email_aziendale="z@z.it"), r("f3", "C", email_aziendale="z@z.it")]
        assert segnale_info(catena[0], catena)["altre"][1]["in_comune"] == \
            ["collegata tramite un'altra scheda del gruppo"]
        print("ok")
        sys.exit(0)

    from dotenv import load_dotenv
    load_dotenv()
    giro(scrivi="--scrivi" in sys.argv, info="--stesso-recapito" in sys.argv)
