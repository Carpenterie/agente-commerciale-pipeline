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
