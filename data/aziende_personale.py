"""Ricerca C del preventivo PREV-2026-06 (5/11): le 30 aziende del file del
committente "Aziende per ricerca tecnici commerciali" (che resta fuori dal
repo: qui solo nomi, domini e fasce; mai recapiti).

Per ogni azienda:
- `fascia`: la "Priorita' ricerca" del file (si cerca in quest'ordine);
- `nomi`: i nomi da cercare, compresi gli alternativi della colonna Note;
- `regex`: il nome ESATTO nel testo del profilo (segnale, non filtro): per i
  nomi che sono anche cognomi o parole comuni serve la parola accanto;
- `ruoli`: le figure indicate nelle Note, se diverse da quelle standard.
La riga 13 ha nella ragione sociale un nome di persona: qui solo il cognome
con l'attivita', come sul dominio del sito.
"""

FASCE = ("Prima fascia", "Prima fascia – settori affini", "Seconda fascia",
         "Seconda fascia – settori affini", "Da riconfermare", "Aggiuntiva – fuori Lazio")


def _a(fascia: str, nomi: tuple, regex: str, dominio: str, ruoli: str | None = None) -> dict:
    return {"fascia": fascia, "nomi": nomi, "regex": regex, "dominio": dominio, "ruoli": ruoli}


_P, _PA, _S, _SA = FASCE[:4]

AZIENDE = {
    "Diro Case":                   _a(_P, ("Diro Case",), r"\bDiro\s*Case\b", "dirocase.it"),
    "Pagano Costruzioni in Legno": _a(_P, ("Pagano Costruzioni in Legno",),
                                      r"\bPagano\s+(?:Costruzioni|legno|case)\b|pagano\.it", "pagano.it"),
    "Legnotek / Kmark":            _a(_P, ("Kmark", "Legnotek"), r"\bLegnotek\b|\bK-?mark\b", "kmark.it"),
    "Technowood":                  _a(_P, ("Technowood",), r"\bTechnowood\b", "technowood.it"),
    "Libianchi":                   _a(_P, ("Libianchi",), r"\bLibianchi\b", "libianchi.it"),
    "Gruppo Aranova":              _a(_P, ("Gruppo Aranova legno",),
                                      r"\bGruppo\s+Aranova\b|\bAranova\s+(?:legno|case)\b|aranovalegno",
                                      "aranovalegno.it"),
    "Biolam Italia":               _a(_P, ("Biolam Italia", "BiHolz", "Xlam Italia"),
                                      r"\bBiolam\b|\bBiHolz\b|\bX-?Lam\s+Italia\b", "biolam.it"),
    "Bioedilizia Evoluta / BioEvo": _a(_P, ("Bioedilizia Evoluta", "BioEvo"),
                                       r"\bBioedilizia\s+Evoluta\b|\bBio-?Evo\b", "bioediliziaevoluta.it"),
    "Asso Strutture":              _a(_P, ("Asso Strutture",), r"\bAsso\s*Strutture\b", "assostrutture.it"),
    "Silvestri Legnami":           _a(_P, ("Silvestri Legnami",), r"\bSilvestri\s+Legnami\b",
                                      "silvestrilegnami.it"),
    "Edilegno":                    _a(_P, ("Edilegno",), r"\bEdilegno\b", "edilegnosrl.com"),
    "SA3 – Agostini Legnami":      _a(_P, ("Agostini Legnami",),
                                      r"\bAgostini\s+Legnami\b|\bSA3\s+(?:srl|s\.r\.l|legno)", "agostinilegnami.com"),
    "Gentili Costruzioni in Legno": _a(_S, ("Gentili costruzioni in legno Vetralla",),
                                       r"\bGentili\s+(?:costruzioni|legno|case)\b|gentilicostruzioniinlegno",
                                       "gentilicostruzioniinlegno.it"),
    "Martini Costruzioni":         _a(_S, ("Martini Costruzioni legno Frosinone",),
                                      r"\bMartini\s+(?:Costruzioni|legno)\b|martinilegno", "martinilegno.it"),
    "Lucan Case di Legno / Lucan Legnami": _a(_S, ("Lucan Case di Legno", "Lucan Legnami"),
                                              r"\bLucan\s+(?:Case|Legnami)\b|casedilegnolucan",
                                              "casedilegnolucan.it"),
    "Flavidar di Lucan":           _a(_S, ("Flavidar case in legno",), r"\bFlavidar\b", "flavidarcaseinlegno.it"),
    "Art Legnami":                 _a(_S, ("Art Legnami",), r"\bArt\s*Legnami\b", "artlegnami.it"),
    "Amore Legnami":               _a(_S, ("Amore Legnami",), r"\bAmore\s+Legnami\b", "amorelegnami.it"),
    "ADI Casette in Legno":        _a(_S, ("ADI Casette in Legno",), r"\bADI\s+Casette\b",
                                      "adicasetteinlegno.com"),
    "Celestini Legno":             _a("Da riconfermare", ("Celestini Legno",), r"\bCelestini\s+Legno\b", ""),
    "Ottagono – Dal Pozzo Group":  _a("Aggiuntiva – fuori Lazio", ("Ottagono Dal Pozzo Group",),
                                      r"\bDal\s+Pozzo\s+Group\b|ottagono\.design|\bOttagono\s+(?:design|LSF)\b",
                                      "ottagono.design"),
    "Zampetti Distribuzione":      _a(_PA, ("Zampetti Distribuzione",), r"\bZampetti\b",
                                      "zampettidistribuzione.it",
                                      "commerciale esterno, tecnico commerciale o consulente sistemi a secco"),
    "BigMat Edilnovelli":          _a(_PA, ("BigMat Edilnovelli",), r"\bEdilnovelli\b", "edilnovelli.bigmat.it"),
    "Gruppo Colamariani & Poduti": _a(_PA, ("Colamariani Poduti",), r"\bColamariani\b",
                                      "gruppocolamarianiepoduti.it", "commerciale per edilizia professionale"),
    "Sedefa Edilizia":             _a(_PA, ("Sedefa Edilizia",), r"\bSedefa\b", "sedefa.it"),
    "GF Carval":                   _a(_SA, ("GF Carval",), r"\bCarval\b", "gfcarval.it"),
    "GruppoE":                     _a(_SA, ("GruppoE materiali edili",), r"\bGruppoE\b|gruppoe\.com", "gruppoe.com",
                                      "commerciale per imprese e progettisti"),
    "BigMat Spiridigliozzi":       _a(_SA, ("BigMat Spiridigliozzi",), r"\bSpiridigliozzi\b",
                                      "spiridigliozzi.bigmat.it"),
    "Prefedil":                    _a(_SA, ("Prefedil Roma",), r"\bPrefedil\b", "prefedil.it"),
    "Hilti Italia – Roma":         _a(_SA, ("Hilti Roma",), r"\bHilti\b", "hilti.it", "account manager esterno"),
}

if __name__ == "__main__":
    import re
    assert len(AZIENDE) == 30 and all(a["fascia"] in FASCE for a in AZIENDE.values())
    for a in AZIENDE.values():
        re.compile(a["regex"])
    print("ok")
