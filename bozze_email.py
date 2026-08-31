"""Generatore di BOZZE email dai testi approvati (PDF del 2026-08-31).

    python bozze_email.py --classe A --limite 20        # bozze per le classi A
    python bozze_email.py --azienda <uuid>              # una sola

NON invia niente e non tocca Gmail: il §2 del PRD lo mette fuori perimetro.
Produce testo da rileggere e inviare a mano (o dall'app).

Regole dei testi, tutte verificate dal self-check:
- un solo testo per azienda, scelto da categoria e livello di fornitura;
- le parti fra parentesi si compilano solo se il dato c'è: niente
  segnaposti vuoti nella bozza, la frase che li conteneva si toglie;
- gli annunci di lavoro NON si citano mai (servono a scegliere il testo,
  non a scriverlo);
- nessun claim su tempi, certificazioni o risparmi.
"""

from __future__ import annotations

import argparse
import sys

import config

APERTURA = "Buongiorno,"
CHIUSURA = "Un saluto,"

# id -> (quando si usa, oggetto, corpo). {materiali} è l'unico campo
# variabile: la frase che lo contiene sparisce se il dato manca.
TESTI = {
    "kit_officina": (
        "fabbro o carpenteria con officina propria — kit/semilavorato",
        "Fornitura componenti in acciaio",
        "produciamo persiane, grate, cancelli e recinzioni in acciaio, e forniamo\n"
        "anche il solo kit: i componenti arrivano tagliati, forati e già organizzati\n"
        "per l'assemblaggio.\n\n"
        "Chi ha officina propria lo usa per assorbire i periodi più carichi senza\n"
        "rinunciare alla lavorazione e al rapporto con il proprio cliente.\n\n"
        "Vi capita di avere commesse in cui potrebbe tornarvi utile?"),
    "finito_serramentista": (
        "serramentista o rivenditore senza officina — prodotto finito",
        "Persiane e grate in acciaio",
        "{frase_materiali}Noi produciamo persiane, grate, cancelli e recinzioni in\n"
        "acciaio e li forniamo finiti e verniciati, pronti alla posa.\n\n"
        "È il modo con cui diversi serramentisti completano la gamma quando arriva\n"
        "una richiesta in acciaio, senza doverla lavorare internamente.\n\n"
        "Vi capita di riceverne?"),
    "finito_showroom": (
        "showroom — prodotto finito",
        "Gamma serramenti in acciaio",
        "produciamo persiane, grate, cancelli e recinzioni in acciaio e li forniamo\n"
        "finiti, pronti da esporre e installare.\n\n"
        "Per uno showroom è un modo di rispondere alle richieste in acciaio senza\n"
        "gestire una produzione: il cliente resta vostro, noi restiamo dietro.\n\n"
        "Avete già un fornitore per questa parte della gamma?"),
    "commessa_edile": (
        "impresa edile o costruttore — prodotto finito per commessa",
        "Fornitura per cantieri",
        "produciamo persiane, grate, cancelli e recinzioni in acciaio e forniamo per\n"
        "commessa, anche interi immobili: un solo interlocutore per tutta la parte in\n"
        "acciaio, con tempi concordati sul cantiere.\n\n"
        "Avete cantieri in cui questa parte è ancora da assegnare?\n"
        "Se non segue lei gli acquisti, mi indica il collega di riferimento?"),
    "carico_produttivo": (
        "azienda con carico produttivo elevato (segnale di lavoro rilevato)",
        "Fornitura nei periodi di carico",
        "produciamo persiane, grate, cancelli e recinzioni in acciaio, anche in kit\n"
        "già tagliato e forato.\n\n"
        "Diversi fabbri ci usano nei periodi in cui la produzione è piena: prendono\n"
        "il semilavorato, assemblano e consegnano nei tempi senza dover aggiungere\n"
        "lavorazioni.\n\n"
        "Nei mesi più carichi potrebbe esservi utile?"),
    "follow_up": (
        "follow-up a 10 giorni dal primo contatto senza risposta",
        "Re: {oggetto_precedente}",
        "le avevo scritto qualche giorno fa a proposito di persiane, grate, cancelli\n"
        "e recinzioni in acciaio.\n\n"
        "Se non è il momento nessun problema: mi dica solo se preferisce che la\n"
        "ricontatti più avanti, oppure se è meglio lasciar perdere."),
    "ricontatto": (
        "ricontatto a distanza di mesi — massimo due volte, poi stop",
        "Prodotti in acciaio — Carpenterie Laziali",
        "le avevo scritto qualche mese fa: produciamo persiane, grate, cancelli e\n"
        "recinzioni in acciaio per aziende del settore, in kit o finiti.\n\n"
        "Le cose cambiano, quindi le riscrivo una volta: se oggi vi serve un\n"
        "fornitore per questa parte, sono a disposizione. Altrimenti non la\n"
        "disturbo oltre."),
    "ex_cliente": (
        "ex cliente da riattivare — sa già chi siamo",
        "Ci risentiamo",
        "abbiamo lavorato insieme in passato e da un po' non ci sentiamo.\n\n"
        "Abbiamo ampliato la gamma su persiane, grate, cancelli e recinzioni, con la\n"
        "possibilità di fornire il kit o il prodotto finito a seconda di come vi è\n"
        "più comodo.\n\n"
        "Se le fa piacere, mi dica come state messi adesso e vediamo se ha senso\n"
        "riprendere."),
}

# il follow-up chiude senza sito (è una riga sola, il sito l'ha già visto)
SENZA_SITO = ("follow_up", "ex_cliente")


def _ha_segnale(azienda: dict, tipo: str) -> bool:
    return any(s.get("tipo") == tipo for s in (azienda.get("segnali") or []))


def scegli_testo(azienda: dict) -> str:
    """Un solo testo per azienda. L'ordine è una precedenza, non una
    preferenza: un ex cliente non riceve MAI un testo da azienda nuova, e
    viceversa (PDF, nota al testo 8)."""
    if _ha_segnale(azienda, "ex_cliente"):
        return "ex_cliente"
    if _ha_segnale(azienda, "annuncio_lavoro"):
        return "carico_produttivo"

    categoria = (azienda.get("categoria") or "").strip()
    fornitura = (azienda.get("livello_fornitura") or "").strip()
    if categoria in ("impresa_edile", "costruttore"):
        return "commessa_edile"
    if categoria == "showroom":
        return "finito_showroom"
    if fornitura == "kit":
        return "kit_officina"
    if categoria in ("serramentista", "montatore", "artigiano") or fornitura == "prodotto_finito":
        return "finito_serramentista"
    return ""            # non abbastanza informazioni: nessuna bozza


def componi(azienda: dict, testo_id: str = "", oggetto_precedente: str = "") -> dict | None:
    """-> {'oggetto', 'corpo', 'testo_id', 'perche'} oppure None."""
    testo_id = testo_id or scegli_testo(azienda)
    if not testo_id:
        return None
    perche, oggetto, corpo = TESTI[testo_id]

    materiali = azienda.get("materiali") or []
    if isinstance(materiali, str):
        materiali = [m.strip() for m in materiali.split(";") if m.strip()]
    # la frase esiste solo se il dato esiste: niente "[materiali rilevati]"
    frase = (f"ho visto che trattate serramenti in {_elenco(materiali)}.\n"
             if materiali else "")
    corpo = corpo.replace("{frase_materiali}", frase)
    oggetto = oggetto.replace("{oggetto_precedente}", oggetto_precedente or oggetto)

    firma = [CHIUSURA]
    if config.FIRMA_EMAIL:
        firma.append(config.FIRMA_EMAIL)
    if config.SITO_EMAIL and testo_id not in SENZA_SITO:
        firma.append(f"— {config.SITO_EMAIL}")
    return {"testo_id": testo_id, "perche": perche, "oggetto": oggetto,
            "corpo": f"{APERTURA}\n{corpo}\n\n{' '.join(firma)}"}


def _elenco(voci: list[str]) -> str:
    voci = [v for v in voci if v]
    if len(voci) == 1:
        return voci[0]
    return ", ".join(voci[:-1]) + f" e {voci[-1]}"


def verifica(bozza: dict) -> list[str]:
    """Controlli che devono passare PRIMA che un testo arrivi a un'azienda."""
    problemi = []
    testo = f"{bozza['oggetto']}\n{bozza['corpo']}".lower()
    for parola in config.VIETATE_EMAIL:
        if parola in testo:
            problemi.append(f"parola vietata nel testo: '{parola}'")
    if "[" in bozza["corpo"] or "]" in bozza["corpo"]:
        problemi.append("segnaposto non compilato rimasto nel corpo")
    if "{" in bozza["corpo"] or "}" in bozza["corpo"]:
        problemi.append("campo template non sostituito")
    return problemi


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--classe", default="A", help="classe da lavorare (A, B, C)")
    p.add_argument("--limite", type=int, default=20)
    args = p.parse_args()

    import db

    sb = db.client()
    aziende = (sb.table("aziende").select("*").eq("classe", args.classe)
               .limit(args.limite).execute().data or [])
    print(f"{len(aziende)} aziende in classe {args.classe}\n")
    senza = 0
    for a in aziende:
        bozza = componi(a)
        if not bozza:
            senza += 1
            continue
        problemi = verifica(bozza)
        print("=" * 72)
        print(f"{a['ragione_sociale']}  [{bozza['testo_id']}: {bozza['perche']}]")
        print(f"Oggetto: {bozza['oggetto']}\n")
        print(bozza["corpo"])
        if problemi:
            print("\n!! DA NON INVIARE:", "; ".join(problemi))
    if senza:
        print(f"\n{senza} aziende senza bozza: categoria o fornitura non "
              "sufficienti a scegliere un testo")
    print("\nBozze da rileggere prima dell'invio. Questo comando non invia nulla.")
    return 0


if __name__ == "__main__" and "--test" in sys.argv:
    # 1. selezione: un solo testo, e le precedenze del PDF
    ex = {"segnali": [{"tipo": "ex_cliente"}], "categoria": "fabbro",
          "livello_fornitura": "kit"}
    assert scegli_testo(ex) == "ex_cliente", "ex cliente ha la precedenza su tutto"
    lavoro = {"segnali": [{"tipo": "annuncio_lavoro", "ruolo": "saldatore"}],
              "categoria": "fabbro", "livello_fornitura": "kit"}
    assert scegli_testo(lavoro) == "carico_produttivo"
    assert scegli_testo({"categoria": "fabbro", "livello_fornitura": "kit"}) == "kit_officina"
    assert scegli_testo({"categoria": "showroom"}) == "finito_showroom"
    assert scegli_testo({"categoria": "impresa_edile"}) == "commessa_edile"
    assert scegli_testo({"categoria": "costruttore"}) == "commessa_edile"
    assert scegli_testo({"categoria": "serramentista",
                         "livello_fornitura": "prodotto_finito"}) == "finito_serramentista"
    assert scegli_testo({"categoria": "", "livello_fornitura": ""}) == ""

    # 2. l'annuncio di lavoro sceglie il testo ma non entra MAI nel testo
    b = componi(lavoro)
    assert "saldator" not in b["corpo"].lower()
    assert not verifica(b), verifica(b)

    # 3. i campi fra parentesi: o compilati, o la frase sparisce
    con = componi({"categoria": "serramentista", "livello_fornitura": "prodotto_finito",
                   "materiali": ["alluminio", "pvc", "legno"]})
    assert "alluminio, pvc e legno" in con["corpo"]
    senza = componi({"categoria": "serramentista", "livello_fornitura": "prodotto_finito"})
    assert "ho visto che trattate" not in senza["corpo"]
    assert "[" not in senza["corpo"] and "{" not in senza["corpo"]
    assert not verifica(senza)

    # 4. nessun claim vietato in NESSUNO degli otto testi
    for tid in TESTI:
        b = componi({"categoria": "fabbro"}, testo_id=tid, oggetto_precedente="X")
        problemi = verifica(b)
        assert not problemi, (tid, problemi)

    # 5. firma vuota -> si chiude senza segnaposto, non con "[Firma]"
    b = componi({"categoria": "showroom"})
    assert "[Firma]" not in b["corpo"] and "[Sito]" not in b["corpo"]
    assert b["corpo"].rstrip().endswith("Un saluto,") or config.FIRMA_EMAIL

    # 6. il follow-up riprende l'oggetto del primo messaggio
    f = componi({"categoria": "fabbro"}, testo_id="follow_up",
                oggetto_precedente="Fornitura componenti in acciaio")
    assert f["oggetto"] == "Re: Fornitura componenti in acciaio"

    assert len(TESTI) == 8, "gli otto testi approvati"
    print("ok")
elif __name__ == "__main__":
    raise SystemExit(main())
