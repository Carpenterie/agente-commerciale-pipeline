"""Comuni per provincia, primi ~20 per popolazione (PRD §3).

Elenchi compilati a mano dai dati ISTAT: l'ordine è indicativo, conta solo
chi c'è. Ogni comune costa 3 query Maps (una per categoria): aggiungerne
uno è una riga, ma ha un costo.
"""

COMUNI = {
    "RM": (
        "Roma", "Guidonia Montecelio", "Fiumicino", "Pomezia", "Tivoli",
        "Anzio", "Velletri", "Civitavecchia", "Ardea", "Nettuno",
        "Marino", "Monterotondo", "Albano Laziale", "Ladispoli", "Cerveteri",
        "Ciampino", "Frascati", "Mentana", "Fonte Nuova", "Colleferro",
        # fuori classifica ma nel test di sourcing validato (zona artigiana,
        # ci lavora un TARGET del campione)
        "Palombara Sabina",
    ),
    "LT": (
        "Latina", "Aprilia", "Terracina", "Fondi", "Formia",
        "Cisterna di Latina", "Sezze", "Gaeta", "Sabaudia", "Minturno",
        "Priverno", "Pontinia", "Sermoneta", "Cori", "Itri",
        "San Felice Circeo", "Castelforte", "Monte San Biagio",
    ),
    "FR": (
        "Frosinone", "Cassino", "Alatri", "Sora", "Ceccano",
        "Anagni", "Ferentino", "Veroli", "Isola del Liri",
        "Monte San Giovanni Campano", "Pontecorvo", "Ceprano",
        "Boville Ernica", "Paliano", "Piedimonte San Germano",
        "Roccasecca", "Arpino", "Fiuggi",
    ),
    "RI": (
        "Rieti", "Fara in Sabina", "Cittaducale", "Poggio Mirteto",
        "Contigliano", "Antrodoco", "Borgorose", "Poggio Moiano",
        "Montopoli di Sabina", "Magliano Sabina", "Forano", "Cantalice",
        "Scandriglia", "Leonessa", "Amatrice",
    ),
    "VT": (
        "Viterbo", "Civita Castellana", "Tarquinia", "Vetralla",
        "Montefiascone", "Ronciglione", "Tuscania", "Nepi", "Orte",
        "Soriano nel Cimino", "Sutri", "Acquapendente", "Capranica",
        "Fabrica di Roma", "Vitorchiano", "Caprarola", "Bolsena",
        "Bagnoregio",
    ),
}


# Indice inverso comune -> sigla, per ricavare la provincia quando il
# modello non l'ha letta dal sito (succede su due terzi delle righe: chi non
# ha sito non ha una pagina contatti da leggere).
# ATTENZIONE: questa tabella e' la lista dei comuni da INTERROGARE su Maps,
# non un registro dei comuni del Lazio: ne contiene 90 sui 378 della
# regione. Copre quindi solo una parte delle righe, ed e' giusto cosi' —
# aggiungere un comune qui costa 3 query Maps a ogni ciclo. Se un giorno
# servisse piu' copertura, la strada e' una tabella separata di sola
# consultazione, non allargare questa.
PROVINCIA_DI_COMUNE = {c.strip().lower(): sigla
                       for sigla, lista in COMUNI.items() for c in lista}


def provincia_di(comune: str | None, log=None) -> str | None:
    """-> sigla della provincia del comune, o None se non e' in tabella."""
    sigla = PROVINCIA_DI_COMUNE.get((comune or "").strip().lower())
    if not sigla and (comune or "").strip() and log:
        log(f"comune '{comune.strip()}' non in tabella: provincia lasciata vuota")
    return sigla


if __name__ == "__main__":
    assert provincia_di("Roma") == "RM"
    assert provincia_di("  guidonia montecelio ") == "RM"
    assert provincia_di("Viterbo") == "VT" and provincia_di("Rieti") == "RI"
    # un comune vero del Lazio ma fuori dalla lista di sourcing: non si indovina
    assert provincia_di("Ariccia") is None
    assert provincia_di("Milano") is None
    assert provincia_di("") is None and provincia_di(None) is None
    assert len(PROVINCIA_DI_COMUNE) == sum(len(v) for v in COMUNI.values())
    print("ok")
