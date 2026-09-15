"""Generatore di BOZZE email dai testi approvati (PDF del 2026-08-31).

    python bozze_email.py <uuid-azienda>
    python bozze_email.py <uuid-azienda> --testo follow_up

UNA AZIENDA PER VOLTA, su richiesta: la bozza si produce quando il
commerciale apre la scheda, non in blocco su una lista. Non esiste una
funzione che generi per liste, ed è deliberato — vedi README.

NON invia niente e non tocca la casella email: il §2 del PRD lo mette fuori
perimetro. Produce oggetto e corpo da rileggere e inviare a mano, o dall'app
(che ha il connettore Outlook). Qui il provider non conta: se un giorno la
casella cambiasse di nuovo, questo file resterebbe com'e'.

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
import re
import sys

import classify
import config
import prompts

APERTURA = "Buongiorno,"
CHIUSURA = "Un saluto,"
# I testi APPROVATI vanno da 52 a 66 parole (misurati). Una prima finestra
# larga (45-95) lasciava passare bozze da 86 parole: il 50% piu' lunghe,
# venticinque secondi di lettura contro diciassette. Su un'email letta dal
# telefono quella differenza e' fra leggerla e saltarla, quindi la finestra
# e' stretta sui testi veri. Firma e link non contano. I testi approvati non
# passano da questi controlli: sono approvati per definizione.
PAROLE_MIN, PAROLE_MAX = 50, 70
# Solo questi ruoli autorizzano "Buongiorno <nome>": un magazziniere o un
# tecnico non si salutano per nome in una prima email.
RUOLI_SALUTABILI = ("titolare", "socio", "responsabile commerciale",
                    "amministratore", "fondatore", "socio fondatore")

# id -> (quando si usa, oggetto, corpo). {materiali} è l'unico campo
# variabile: la frase che lo contiene sparisce se il dato manca.
TESTI = {
    "kit_officina": (
        "fabbro o carpenteria con officina propria — kit/semilavorato",
        "Fornitura componenti in acciaio",
        "produciamo persiane, grate, cancelli e recinzioni in acciaio, e forniamo\n"
        "anche il solo kit: i componenti arrivano tagliati, forati e già organizzati\n"
        "per l'assemblaggio.\n\n"
        "Chi ha officina propria lo usa per assorbire i periodi più carichi: una\n"
        "persiana si assembla in circa quaranta minuti, senza misurazioni e senza\n"
        "sfridi da smaltire.\n\n"
        "Vi capita di avere commesse in cui potrebbe tornarvi utile?"),
    "finito_serramentista": (
        "serramentista o rivenditore senza officina — prodotto finito",
        "Persiane e grate in acciaio",
        "{frase_materiali}Noi produciamo persiane, grate, cancelli e recinzioni in\n"
        "acciaio e li forniamo finiti e verniciati, pronti alla posa — oppure\n"
        "assemblati grezzi, se preferite gestire voi la verniciatura.\n\n"
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
        "Il sistema a incastro riduce la necessità di manodopera specializzata:\n"
        "diversi fabbri lo usano nei periodi in cui la produzione è piena, per\n"
        "assemblare e consegnare nei tempi senza aggiungere lavorazioni.\n\n"
        "Nei mesi più carichi potrebbe esservi utile?"),
    "follow_up": (
        "follow-up a 10 giorni dal primo contatto senza risposta",
        "Re: {oggetto_precedente}",
        "le avevo scritto qualche giorno fa a proposito di persiane, grate, cancelli\n"
        "e recinzioni in acciaio.\n"
        "{frase_catalogo}\n"
        "Se non è il momento nessun problema: mi dica solo se preferisce che la\n"
        "ricontatti più avanti, oppure se è meglio lasciar perdere."),
    "risposta_interesse": (
        "risposta a chi ha manifestato interesse — SOLO su richiesta esplicita",
        "Catalogo e prossimi passi",
        "grazie del riscontro.\n"
        "{frase_catalogo_esteso}"
        "{frase_prenotazione}"),
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
# testi che nascono da un fatto che il sistema NON vede (una risposta umana,
# il tempo trascorso): si chiedono per testo_id, non si scelgono mai da soli
SOLO_SU_RICHIESTA = ("follow_up", "ricontatto", "risposta_interesse")


def _ha_segnale(azienda: dict, tipo: str) -> bool:
    return any(s.get("tipo") == tipo for s in (azienda.get("segnali") or []))


def scegli_testo(azienda: dict) -> str:
    """Un solo testo per azienda. L'ordine è una precedenza, non una
    preferenza: un ex cliente non riceve MAI un testo da azienda nuova, e
    viceversa (PDF, nota al testo 8).

    ATTENZIONE: queste stesse regole esistono anche nell'app Lovable, che
    non esegue Python. Chi ne cambia una qui deve cambiarla anche là,
    altrimenti la stessa azienda riceve testi diversi a seconda di dove
    parte la bozza. Elenco di cosa allineare nel README, sezione
    "La logica di scelta esiste in DUE posti".
    """
    categoria = (azienda.get("categoria") or "").strip()
    fornitura = (azienda.get("livello_fornitura") or "").strip()

    if _ha_segnale(azienda, "ex_cliente"):
        return "ex_cliente"
    # Il LIVELLO ha la precedenza sul segnale di lavoro: `carico_produttivo`
    # parla di kit gia' tagliato, e a chi compra il prodotto finito il kit
    # non si propone. Il segnale sceglie il testo solo quando il livello e'
    # `kit` o non assegnato. Difetto trovato il 2026-09-15: sette aziende di
    # classe A ricevevano un testo che contraddiceva la propria scheda.
    if _ha_segnale(azienda, "annuncio_lavoro") and fornitura != "prodotto_finito":
        return "carico_produttivo"
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

    # i link vivono in config: se mancano, sparisce la frase intera
    catalogo, prenotazione = config.LINK_CATALOGO, config.LINK_PRENOTAZIONE
    if testo_id == "risposta_interesse" and not catalogo:
        return None      # e' il testo che serve a mandare il catalogo
    corpo = corpo.replace("{frase_catalogo}", (
        f"\nLe lascio comunque il nostro catalogo, così ce l'ha se dovesse\n"
        f"servirle: {catalogo}.\n" if catalogo else ""))
    corpo = corpo.replace("{frase_catalogo_esteso}", (
        f"\nLe allego il catalogo aggiornato: trova le linee complete di persiane,\n"
        f"grate, cancelli e recinzioni, con le versioni in kit e finite.\n"
        f"{catalogo}\n" if catalogo else ""))
    corpo = corpo.replace("{frase_prenotazione}", (
        f"\nSe le è comodo, in una chiamata di dieci minuti le mostro quale\n"
        f"configurazione ha senso per il vostro lavoro e come funziona l'ordine.\n"
        f"{prenotazione}\n" if prenotazione else ""))

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


def accorcia(corpo: str, massimo: int = 0, minimo: int = 0) -> str:
    """Toglie FRASI dal centro finche' il corpo non rientra nella finestra.

    Il modello non sa contare le parole: gli si chiede 60 e ne scrive 82.
    Tagliare qui e' deterministico. Si tolgono le frasi dall'ultima verso
    l'alto, ma mai: l'apertura (e' l'aggancio a quell'azienda), la domanda
    finale (e' il solo invito a rispondere), e mai fino a scendere sotto il
    minimo — un corpo di 41 parole non e' piu' una email, e' un appunto.
    Si taglia per FRASI e non per paragrafi: togliere un paragrafo intero
    porta via l'argomento commerciale insieme al dettaglio di troppo.
    """
    massimo = massimo or PAROLE_MAX
    minimo = minimo or PAROLE_MIN
    testa, _, resto = corpo.strip().partition("\n")
    frasi = [f.strip() for f in re.split(r"(?<=[.!?])\s+", resto) if f.strip()]
    if not frasi:
        return corpo.strip()
    coda = frasi[-1] if "?" in frasi[-1] else ""
    centro = frasi[:-1] if coda else frasi[:]

    def parole(lista):
        return len(" ".join([testa] + lista + ([coda] if coda else [])).split())

    while parole(centro) > massimo and len(centro) > 1:
        if parole(centro[:-1]) < minimo:
            break          # meglio due parole di troppo che un'email monca
        centro.pop()
    pezzi = [testa]
    if centro:
        pezzi.append("\n" + " ".join(centro))
    if coda:
        pezzi.append("\n" + coda)
    return "\n".join(pezzi).strip()


def _chiudi(corpo: str) -> str:
    """Catalogo e firma li mette il programma, non il modello: sono le due
    cose che non devono mai dipendere da come e' andata la generazione."""
    pezzi = [corpo.rstrip()]
    if config.LINK_CATALOGO:
        pezzi.append(f"\nLe lascio il nostro catalogo: {config.LINK_CATALOGO}")
    firma = [CHIUSURA]
    if config.FIRMA_EMAIL:
        firma.append(config.FIRMA_EMAIL)
    pezzi.append(f"\n{' '.join(firma)}")
    return "\n".join(pezzi)


def _elenco(voci: list[str]) -> str:
    voci = [v for v in voci if v]
    if len(voci) == 1:
        return voci[0]
    return ", ".join(voci[:-1]) + f" e {voci[-1]}"


def _senza_accessori(corpo: str) -> str:
    """Il corpo SCRITTO, senza catalogo ne' firma.

    Non bastava togliere gli URL: la frase che li introduce e la firma
    valgono nove parole, e contarle faceva scartare per lunghezza bozze che
    stavano nella finestra. Le mette il programma, non il modello: non sono
    testo su cui giudicare.
    """
    righe = [r for r in corpo.split("\n")
             if "Le lascio il nostro catalogo" not in r
             and not r.strip().startswith(CHIUSURA)]
    corpo = "\n".join(righe)
    for link in (config.LINK_CATALOGO, config.LINK_PRENOTAZIONE):
        if link:
            corpo = corpo.replace(link, "")
    return corpo


def verifica(bozza: dict, forma: bool = False) -> list[str]:
    """Controlli che devono passare PRIMA che un testo arrivi a un'azienda.

    `forma=True` aggiunge i vincoli di lunghezza, domanda unica e firma:
    valgono per le bozze GENERATE, non per i testi approvati, che sono
    approvati cosi' come sono.
    """
    problemi = []
    testo = f"{bozza['oggetto']}\n{bozza['corpo']}".lower()
    for parola in config.VIETATE_EMAIL:
        if parola in testo:
            problemi.append(f"parola vietata nel testo: '{parola}'")
    if "[" in bozza["corpo"] or "]" in bozza["corpo"]:
        problemi.append("segnaposto non compilato rimasto nel corpo")
    if "{" in bozza["corpo"] or "}" in bozza["corpo"]:
        problemi.append("campo template non sostituito")
    if not forma:
        return problemi
    corpo = _senza_accessori(bozza["corpo"])
    parole = len([x for x in corpo.split() if x.strip()])
    if not PAROLE_MIN <= parole <= PAROLE_MAX:
        problemi.append(f"lunghezza fuori limite: {parole} parole "
                        f"(attese {PAROLE_MIN}-{PAROLE_MAX})")
    if corpo.count("?") != 1:
        problemi.append(f"deve esserci UNA sola domanda, trovate {corpo.count('?')}")
    if config.FIRMA_EMAIL and config.FIRMA_EMAIL not in bozza["corpo"]:
        problemi.append("manca la firma")
    return problemi


def _scheda_per_modello(azienda: dict) -> str:
    """Solo i campi che servono a personalizzare: dare tutta la riga
    inviterebbe a citare dati che in una prima email non si citano."""
    segnali = [s.get("nota") or s.get("tipo", "")
               for s in (azienda.get("segnali") or [])
               # l'annuncio di lavoro NON si passa nemmeno al modello: non
               # puo' citare cio' che non sa
               if s.get("tipo") not in ("annuncio_lavoro", "territorio",
                                        "reputazione_google")]
    campi = [
        ("azienda", azienda.get("ragione_sociale")),
        ("comune", azienda.get("comune")),
        ("categoria", azienda.get("categoria")),
        ("materiali trattati", ", ".join(azienda.get("materiali") or [])),
        ("linee a catalogo", ", ".join(azienda.get("gamma") or [])),
        ("officina propria", azienda.get("officina_propria")),
        ("livello di fornitura adatto", azienda.get("livello_fornitura")),
        ("prodotto da proporre", azienda.get("prodotto_apertura")),
        ("argomento di vendita", azienda.get("leva_commerciale")),
        ("segnali dal sito", "; ".join(str(x) for x in segnali[:4])),
    ]
    ruolo = (azienda.get("referente_ruolo") or "").strip().lower()
    if azienda.get("referente_nome") and ruolo in RUOLI_SALUTABILI:
        campi.append(("referente", f"{azienda['referente_nome']} ({ruolo})"))
    return "\n".join(f"- {k}: {v}" for k, v in campi if v)


def genera(azienda: dict, client, testo_id: str = "",
           oggetto_precedente: str = "", log=print) -> dict | None:
    """Bozza PERSONALIZZATA sulla scheda, con ripiego sul testo approvato.

    Il modello non scrive da zero: riceve il testo approvato come traccia e
    lo adatta. Se la bozza che torna non passa `verifica(forma=True)` si
    usa il testo fisso — un testo approvato vale piu' di uno personalizzato
    ma fuori regola.
    """
    fissa = componi(azienda, testo_id=testo_id,
                    oggetto_precedente=oggetto_precedente)
    if fissa is None:
        return None

    richiesta = prompts.PROMPT_BOZZA.format(
        scheda=_scheda_per_modello(azienda),
        oggetto=fissa["oggetto"], corpo=fissa["corpo"])
    try:
        risposta = client.messages.create(
            model=config.MODELLO, max_tokens=1000, temperature=0,
            timeout=config.TIMEOUT_ANTHROPIC_S,
            messages=[{"role": "user", "content": richiesta}])
        testo = next(b.text for b in risposta.content if b.type == "text")
        dati = classify.estrai_json(testo)
    except Exception as e:  # noqa: BLE001 - il ripiego non e' un errore
        log(f"bozza generata non riuscita ({type(e).__name__}): uso il testo fisso")
        return {**fissa, "generata": False}

    corpo = (dati.get("corpo") or "").strip()
    if not corpo:
        return {**fissa, "generata": False}
    # il modello sfora spesso: si taglia qui invece di buttare la bozza
    corpo = accorcia(corpo)
    bozza = {**fissa, "oggetto": (dati.get("oggetto") or fissa["oggetto"]).strip(),
             "corpo": _chiudi(corpo), "generata": True}
    problemi = verifica(bozza, forma=True)
    if problemi:
        log(f"bozza generata scartata ({'; '.join(problemi)}): uso il testo fisso")
        return {**fissa, "generata": False}
    return bozza


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bozza email per UNA azienda. Non genera in blocco.")
    p.add_argument("azienda", help="uuid della scheda in `aziende`")
    p.add_argument("--testo", default="", choices=sorted(TESTI) or None,
                   help="forza un testo (follow_up, ricontatto...); "
                        "senza, lo sceglie da categoria e fornitura")
    p.add_argument("--oggetto-precedente", default="",
                   help="per il follow-up: l'oggetto del primo messaggio")
    args = p.parse_args()

    import db

    righe = (db.client().table("aziende").select("*")
             .eq("id", args.azienda).limit(1).execute().data)
    if not righe:
        print(f"nessuna azienda con id {args.azienda}")
        return 1
    a = righe[0]

    if args.fisso:
        bozza = componi(a, args.testo, args.oggetto_precedente)
    else:
        from anthropic import Anthropic

        # max_retries=1: il default ne fa due, che sommate al ripiego
        # allungano l'attesa senza aggiungere niente
        bozza = genera(a, Anthropic(max_retries=1), args.testo,
                       args.oggetto_precedente)
    if not bozza:
        print(f"{a['ragione_sociale']}: nessuna bozza.\n"
              "Categoria e livello di fornitura non bastano a scegliere un "
              "testo: la scheda va letta a mano.")
        return 1

    come = "personalizzata sulla scheda" if bozza.get("generata") \
        else "testo approvato, non personalizzato"
    print(f"{a['ragione_sociale']}  [{bozza['testo_id']}: {bozza['perche']}]")
    print(f"  {come}")
    print(f"Oggetto: {bozza['oggetto']}\n")
    print(bozza["corpo"])
    problemi = verifica(bozza)
    if problemi:
        print("\n!! DA NON INVIARE:", "; ".join(problemi))
        return 1
    print("\nBozza da rileggere prima dell'invio. Questo comando non invia nulla.")
    return 0


if __name__ == "__main__" and "--test" in sys.argv:
    # 1. selezione: un solo testo, e le precedenze del PDF
    ex = {"segnali": [{"tipo": "ex_cliente"}], "categoria": "fabbro",
          "livello_fornitura": "kit"}
    assert scegli_testo(ex) == "ex_cliente", "ex cliente ha la precedenza su tutto"
    # il livello vince sul segnale di lavoro: a chi compra finito niente kit
    annuncio = [{"tipo": "annuncio_lavoro", "ruolo": "saldatore"}]
    assert scegli_testo({"segnali": annuncio, "categoria": "fabbro",
                         "livello_fornitura": "kit"}) == "carico_produttivo"
    assert scegli_testo({"segnali": annuncio, "categoria": "fabbro"}) == "carico_produttivo"
    assert scegli_testo({"segnali": annuncio, "categoria": "showroom",
                         "livello_fornitura": "prodotto_finito"}) == "finito_showroom"
    assert scegli_testo({"segnali": annuncio, "categoria": "impresa_edile",
                         "livello_fornitura": "prodotto_finito"}) == "commessa_edile"
    assert scegli_testo({"segnali": annuncio, "categoria": "serramentista",
                         "livello_fornitura": "prodotto_finito"}) == "finito_serramentista"
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

    # 4. nessun claim vietato in NESSUNO dei testi, con e senza i link
    _cat, _pren = config.LINK_CATALOGO, config.LINK_PRENOTAZIONE
    for cat, pren in (("", ""), ("catalogo.pdf", "cal.com/x")):
        config.LINK_CATALOGO, config.LINK_PRENOTAZIONE = cat, pren
        for tid in TESTI:
            b = componi({"categoria": "fabbro"}, testo_id=tid, oggetto_precedente="X")
            if b is None:
                continue      # risposta_interesse senza catalogo: non si produce
            problemi = verifica(b)
            assert not problemi, (tid, cat, problemi)
    config.LINK_CATALOGO, config.LINK_PRENOTAZIONE = _cat, _pren

    # 4b. gli argomenti dal catalogo (2026-09), nei tre testi riscritti.
    # Sono affermazioni DEL CLIENTE, quindi utilizzabili: non sono claim
    # nostri su tempi o certificazioni. Fuori restano i tempi di consegna
    # (il catalogo stesso li dichiara indicativi) e i nomi dei modelli, che
    # sono una scelta estetica del cliente finale.
    # `steso`: le frasi vanno cercate senza gli a capo dell'impaginazione,
    # altrimenti una riformattazione romperebbe i test senza cambiare nulla
    steso = lambda s: " ".join(s.split())  # noqa: E731
    kit = steso(componi({"categoria": "fabbro", "livello_fornitura": "kit"})["corpo"])
    assert "circa quaranta minuti" in kit, "il numero e' l'argomento del testo 1"
    assert "senza misurazioni e senza sfridi da smaltire" in kit
    ser = steso(componi({"categoria": "serramentista",
                         "livello_fornitura": "prodotto_finito"})["corpo"])
    assert "oppure assemblati grezzi" in ser, "il terzo livello e' nel testo 2"
    assert "gestire voi la verniciatura" in ser
    car = steso(componi({"categoria": "fabbro"},
                        testo_id="carico_produttivo")["corpo"])
    assert "riduce la necessità di manodopera specializzata" in car
    # ...e nel testo 5 NON si nomina mai l'annuncio che lo ha fatto scegliere
    for parola in ("annunc", "saldator", "assunzion", "cercate", "offerta di lavoro"):
        assert parola not in car.lower(), parola
    # i tempi di CONSEGNA restano fuori da tutti i testi
    for tid in TESTI:
        b = componi({"categoria": "fabbro"}, testo_id=tid, oggetto_precedente="X")
        if b is None:
            continue
        for vietata in ("24 ore", "48 ore", "consegna rapida", "consegniamo in"):
            assert vietata not in b["corpo"].lower(), (tid, vietata)

    # 4c. gli altri CINQUE testi non sono stati toccati: restano approvati
    assert "pronti da esporre e installare" in steso(TESTI["finito_showroom"][2])
    assert "un solo interlocutore" in steso(TESTI["commessa_edile"][2])
    assert "abbiamo lavorato insieme in passato" in steso(TESTI["ex_cliente"][2])

    # catalogo e firma non contano come testo scritto
    b_acc = {"oggetto": "x", "corpo": _chiudi("Buongiorno,\nUna frase.\n\nDomanda?")}
    assert len(_senza_accessori(b_acc["corpo"]).split()) == 4, \
        _senza_accessori(b_acc["corpo"])

    # il taglio a valle: toglie le frasi centrali, mai la domanda ne' l'apertura
    lungo = ("Buongiorno,\nPrima frase di apertura che aggancia proprio questa "
             "azienda con un dettaglio suo. Seconda frase con l'argomento "
             "commerciale centrale. Terza frase con un dettaglio in piu' che "
             "si puo' togliere senza perdere nulla.\n\nVi capita di riceverne?")
    corto = accorcia(lungo, massimo=30, minimo=10)
    assert corto.startswith("Buongiorno,") and corto.rstrip().endswith("?"), corto
    assert "Terza frase" not in corto, "toglie dall'ultima, non dalla prima"
    assert "Prima frase" in corto, "l'apertura non si tocca mai"
    # non scende sotto il minimo: meglio due parole di troppo che un'email monca
    assert "Seconda frase" in accorcia(lungo, massimo=5, minimo=25)
    # se e' gia' corto non tocca niente
    breve = "Buongiorno,\nUna frase breve.\n\nDomanda?"
    intatto = accorcia(breve, massimo=50)
    assert "Una frase breve." in intatto and intatto.endswith("Domanda?")
    assert len(intatto.split()) == len(breve.split()), "non deve togliere parole"
    assert TESTI["ex_cliente"][1] == "Ci risentiamo"

    # 5. firma vuota -> si chiude senza segnaposto, non con "[Firma]"
    b = componi({"categoria": "showroom"})
    assert "[Firma]" not in b["corpo"] and "[Sito]" not in b["corpo"]
    assert b["corpo"].rstrip().endswith("Un saluto,") or config.FIRMA_EMAIL

    # 6. il follow-up riprende l'oggetto del primo messaggio
    f = componi({"categoria": "fabbro"}, testo_id="follow_up",
                oggetto_precedente="Fornitura componenti in acciaio")
    assert f["oggetto"] == "Re: Fornitura componenti in acciaio"

    # --- i due testi del catalogo ---
    salvati = (config.LINK_CATALOGO, config.LINK_PRENOTAZIONE)

    # senza link: il follow-up torna alla versione approvata, intatta
    config.LINK_CATALOGO = config.LINK_PRENOTAZIONE = ""
    f = componi({"categoria": "fabbro"}, testo_id="follow_up",
                oggetto_precedente="Fornitura componenti in acciaio")
    assert "catalogo" not in f["corpo"].lower(), f["corpo"]
    assert "le avevo scritto qualche giorno fa" in f["corpo"]
    assert not verifica(f)
    # e la risposta-interesse non si produce affatto: serve a mandare il catalogo
    assert componi({"categoria": "fabbro"}, testo_id="risposta_interesse") is None

    # con i link: entrambe le frasi compaiono, nessun segnaposto
    config.LINK_CATALOGO = "carpenterielaziali.it/catalogo.pdf"
    config.LINK_PRENOTAZIONE = "cal.com/carpenterielaziali/10min"
    f = componi({"categoria": "fabbro"}, testo_id="follow_up",
                oggetto_precedente="X")
    assert config.LINK_CATALOGO in f["corpo"] and not verifica(f)
    r = componi({"categoria": "fabbro"}, testo_id="risposta_interesse")
    assert config.LINK_CATALOGO in r["corpo"]
    assert config.LINK_PRENOTAZIONE in r["corpo"]
    assert "grazie del riscontro" in r["corpo"]
    assert not verifica(r), verifica(r)

    # solo il catalogo: la frase della chiamata sparisce, niente segnaposto
    config.LINK_PRENOTAZIONE = ""
    r = componi({"categoria": "fabbro"}, testo_id="risposta_interesse")
    assert "dieci minuti" not in r["corpo"] and not verifica(r)
    config.LINK_CATALOGO, config.LINK_PRENOTAZIONE = salvati

    # i testi che nascono da un fatto invisibile al sistema non si autoscelgono
    for tid in SOLO_SU_RICHIESTA:
        assert scegli_testo({"categoria": "fabbro", "livello_fornitura": "kit"}) != tid

    # 8 approvati (con follow_up aggiornato al catalogo, non aggiunto) + la
    # risposta a chi mostra interesse
    assert len(TESTI) == 9, sorted(TESTI)
    print("ok")
elif __name__ == "__main__":
    raise SystemExit(main())
