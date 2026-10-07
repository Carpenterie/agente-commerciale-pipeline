"""Comuni per provincia, i principali per popolazione (PRD §3).

Elenchi compilati a mano dai dati ISTAT: l'ordine è indicativo, conta solo
chi c'è. Ogni comune costa 3 query Maps (una per categoria): aggiungerne
uno è una riga, ma ha un costo — la stima Apify di un ciclo si ricava dal
numero di comuni (config.stima_apify_usd).
Lazio dal 2026-08; Toscana, Campania, Puglia, Abruzzo e Marche dal
2026-10-07 (costi approvati dal committente), stesso criterio: ~15-20
comuni per provincia, qualcuno in piu' nelle tre grandi (FI, NA, BA).
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
    # --- Toscana ---
    "FI": (
        "Firenze", "Scandicci", "Sesto Fiorentino", "Empoli", "Campi Bisenzio",
        "Bagno a Ripoli", "Fucecchio", "Figline e Incisa Valdarno", "Pontassieve",
        "Signa", "Lastra a Signa", "Borgo San Lorenzo", "Calenzano",
        "Castelfiorentino", "Certaldo", "Impruneta", "Vinci", "Montelupo Fiorentino",
        "Reggello", "San Casciano in Val di Pesa",
    ),
    "PO": (
        "Prato", "Montemurlo", "Carmignano", "Poggio a Caiano", "Vaiano",
        "Vernio", "Cantagallo",
    ),
    "PT": (
        "Pistoia", "Quarrata", "Monsummano Terme", "Pescia", "Montecatini-Terme",
        "Agliana", "Serravalle Pistoiese", "Pieve a Nievole", "Larciano",
        "Massa e Cozzile", "Lamporecchio", "Buggiano", "Montale",
        "Chiesina Uzzanese", "Ponte Buggianese",
    ),
    "LU": (
        "Lucca", "Viareggio", "Capannori", "Camaiore", "Massarosa", "Pietrasanta",
        "Altopascio", "Porcari", "Seravezza", "Forte dei Marmi",
        "Castelnuovo di Garfagnana", "Barga", "Montecarlo", "Borgo a Mozzano",
        "Pescaglia",
    ),
    "MS": (
        "Massa", "Carrara", "Aulla", "Montignoso", "Pontremoli", "Fivizzano",
        "Licciana Nardi", "Villafranca in Lunigiana", "Fosdinovo",
    ),
    "PI": (
        "Pisa", "Cascina", "San Giuliano Terme", "Pontedera", "San Miniato",
        "Ponsacco", "Vecchiano", "Santa Croce sull'Arno", "Calcinaia",
        "Castelfranco di Sotto", "Vicopisano", "Volterra", "Bientina",
        "Santa Maria a Monte", "Capannoli", "Casciana Terme Lari",
    ),
    "LI": (
        "Livorno", "Piombino", "Rosignano Marittimo", "Cecina", "Collesalvetti",
        "San Vincenzo", "Portoferraio", "Castagneto Carducci",
        "Campiglia Marittima", "Bibbona", "Suvereto", "Capoliveri",
    ),
    "AR": (
        "Arezzo", "Montevarchi", "Cortona", "San Giovanni Valdarno", "Sansepolcro",
        "Bibbiena", "Terranuova Bracciolini", "Castiglion Fiorentino",
        "Foiano della Chiana", "Bucine", "Monte San Savino", "Cavriglia",
        "Civitella in Val di Chiana", "Castelfranco Piandiscò", "Lucignano",
        "Subbiano", "Anghiari",
    ),
    "SI": (
        "Siena", "Poggibonsi", "Colle di Val d'Elsa", "Montepulciano", "Sinalunga",
        "Monteriggioni", "Chiusi", "Castelnuovo Berardenga", "Torrita di Siena",
        "Montalcino", "Asciano", "Sovicille", "Monteroni d'Arbia",
        "Abbadia San Salvatore", "Chianciano Terme", "Rapolano Terme",
    ),
    "GR": (
        "Grosseto", "Follonica", "Orbetello", "Massa Marittima", "Monte Argentario",
        "Castiglione della Pescaia", "Gavorrano", "Pitigliano", "Manciano",
        "Scarlino", "Roccastrada", "Capalbio", "Arcidosso", "Castel del Piano",
    ),
    # --- Campania ---
    "NA": (
        "Napoli", "Giugliano in Campania", "Torre del Greco", "Pozzuoli", "Casoria",
        "Castellammare di Stabia", "Afragola", "Marano di Napoli", "Acerra",
        "Portici", "Ercolano", "Casalnuovo di Napoli", "San Giorgio a Cremano",
        "Quarto", "Torre Annunziata", "Pomigliano d'Arco", "Nola",
        "Melito di Napoli", "Arzano", "Volla", "Somma Vesuviana", "Gragnano",
    ),
    "CE": (
        "Caserta", "Aversa", "Marcianise", "Maddaloni", "Santa Maria Capua Vetere",
        "Castel Volturno", "Mondragone", "Sessa Aurunca", "Capua",
        "Orta di Atella", "San Nicola la Strada", "Trentola Ducenta",
        "Casal di Principe", "San Felice a Cancello", "Teano",
        "Piedimonte Matese", "Sant'Arpino", "Lusciano", "Santa Maria a Vico",
        "Gricignano di Aversa",
    ),
    "SA": (
        "Salerno", "Cava de' Tirreni", "Battipaglia", "Scafati", "Nocera Inferiore",
        "Eboli", "Angri", "Pagani", "Sarno", "Nocera Superiore",
        "Mercato San Severino", "Pontecagnano Faiano", "Capaccio Paestum",
        "Agropoli", "Baronissi", "Fisciano", "Bellizzi", "Sala Consilina",
        "Montecorvino Rovella", "Vallo della Lucania",
    ),
    "AV": (
        "Avellino", "Ariano Irpino", "Monteforte Irpino", "Solofra", "Mercogliano",
        "Atripalda", "Montoro", "Cervinara", "Mirabella Eclano", "Grottaminarda",
        "Avella", "Lioni", "Sant'Angelo dei Lombardi", "Montella", "Serino",
    ),
    "BN": (
        "Benevento", "Montesarchio", "Sant'Agata de' Goti", "San Giorgio del Sannio",
        "Telese Terme", "Airola", "San Bartolomeo in Galdo", "Cerreto Sannita",
        "Guardia Sanframondi", "San Salvatore Telesino", "Morcone", "Apice",
        "Solopaca",
    ),
    # --- Puglia ---
    "BA": (
        "Bari", "Altamura", "Molfetta", "Bitonto", "Monopoli", "Corato",
        "Gravina in Puglia", "Modugno", "Triggiano", "Gioia del Colle",
        "Putignano", "Casamassima", "Conversano", "Acquaviva delle Fonti",
        "Mola di Bari", "Noci", "Valenzano", "Capurso", "Palo del Colle",
        "Noicattaro", "Santeramo in Colle", "Rutigliano",
    ),
    "BT": (
        "Andria", "Barletta", "Trani", "Bisceglie", "Canosa di Puglia",
        "San Ferdinando di Puglia", "Trinitapoli", "Margherita di Savoia",
        "Minervino Murge", "Spinazzola",
    ),
    "FG": (
        "Foggia", "Cerignola", "Manfredonia", "San Severo", "San Giovanni Rotondo",
        "Lucera", "Vieste", "Torremaggiore", "Monte Sant'Angelo", "Orta Nova",
        "San Marco in Lamis", "Apricena", "Mattinata", "San Nicandro Garganico",
        "Troia",
    ),
    "BR": (
        "Brindisi", "Fasano", "Francavilla Fontana", "Ostuni", "Mesagne",
        "San Vito dei Normanni", "Ceglie Messapica", "Oria", "Carovigno",
        "Latiano", "San Pietro Vernotico", "Cisternino", "Torre Santa Susanna",
        "San Pancrazio Salentino",
    ),
    "LE": (
        "Lecce", "Nardò", "Galatina", "Copertino", "Casarano", "Gallipoli",
        "Tricase", "Surbo", "Maglie", "Galatone", "Squinzano", "Leverano",
        "Monteroni di Lecce", "Taviano", "Trepuzzi", "Veglie",
    ),
    "TA": (
        "Taranto", "Martina Franca", "Massafra", "Grottaglie", "Manduria", "Ginosa",
        "Castellaneta", "Palagiano", "Mottola", "Sava", "Pulsano", "Statte",
        "Crispiano", "Laterza", "San Giorgio Ionico", "Lizzano",
    ),
    # --- Abruzzo ---
    "AQ": (
        "L'Aquila", "Avezzano", "Sulmona", "Celano", "Pratola Peligna",
        "Tagliacozzo", "Pescina", "Castel di Sangro", "Trasacco", "Luco dei Marsi",
        "Capistrello", "San Benedetto dei Marsi", "Raiano", "Carsoli",
        "Scurcola Marsicana",
    ),
    "CH": (
        "Chieti", "Vasto", "Lanciano", "Francavilla al Mare", "Ortona", "San Salvo",
        "San Giovanni Teatino", "Guardiagrele", "Atessa", "Casalbordino",
        "Ripa Teatina", "Fossacesia", "Paglieta", "Cupello", "Miglianico",
        "Bucchianico", "Casoli",
    ),
    "PE": (
        "Pescara", "Montesilvano", "Spoltore", "Città Sant'Angelo", "Penne",
        "Cepagatti", "Pianella", "Manoppello", "Loreto Aprutino", "Scafa", "Popoli Terme",
        "Moscufo", "Rosciano", "Collecorvino", "Alanno",
    ),
    "TE": (
        "Teramo", "Giulianova", "Roseto degli Abruzzi", "Martinsicuro", "Silvi",
        "Alba Adriatica", "Pineto", "Atri", "Mosciano Sant'Angelo",
        "Sant'Egidio alla Vibrata", "Nereto", "Tortoreto", "Notaresco",
        "Corropoli", "Montorio al Vomano", "Colonnella",
    ),
    # --- Marche ---
    "AN": (
        "Ancona", "Senigallia", "Jesi", "Fabriano", "Osimo", "Falconara Marittima",
        "Castelfidardo", "Chiaravalle", "Loreto", "Filottrano", "Camerano",
        "Montemarciano", "Corinaldo", "Ostra", "Polverigi", "Sassoferrato",
    ),
    "PU": (
        "Pesaro", "Fano", "Urbino", "Vallefoglia", "Fossombrone", "Cagli",
        "Mondolfo", "Gabicce Mare", "Tavullia", "Pergola", "Sant'Angelo in Vado",
        "Urbania", "Colli al Metauro", "Terre Roveresche", "Montelabbate",
    ),
    "MC": (
        "Macerata", "Civitanova Marche", "Recanati", "Tolentino", "Potenza Picena",
        "Porto Recanati", "Corridonia", "Morrovalle", "Montecosaro",
        "San Severino Marche", "Camerino", "Matelica", "Treia", "Montecassiano",
        "Cingoli", "Appignano",
    ),
    "AP": (
        "Ascoli Piceno", "San Benedetto del Tronto", "Grottammare", "Monteprandone",
        "Folignano", "Castel di Lama", "Spinetoli", "Offida", "Acquaviva Picena",
        "Colli del Tronto", "Cupra Marittima", "Monsampolo del Tronto",
        "Castorano", "Ripatransone", "Maltignano",
    ),
    "FM": (
        "Fermo", "Porto San Giorgio", "Porto Sant'Elpidio", "Sant'Elpidio a Mare",
        "Montegranaro", "Monte Urano", "Montegiorgio", "Grottazzolina",
        "Amandola", "Pedaso", "Altidona", "Rapagnano", "Petritoli", "Falerone",
    ),
}


# Indice inverso comune -> sigla, per ricavare la provincia quando il
# modello non l'ha letta dal sito (succede su due terzi delle righe: chi non
# ha sito non ha una pagina contatti da leggere).
# ATTENZIONE: questa tabella e' la lista dei comuni da INTERROGARE su Maps,
# non un registro dei comuni: nel Lazio ne contiene 90 sui 378 della
# regione, e cosi' nelle altre. Copre quindi solo una parte delle righe, ed e' giusto cosi' —
# aggiungere un comune qui costa 3 query Maps a ogni ciclo. Se un giorno
# servisse piu' copertura, la strada e' una tabella separata di sola
# consultazione, non allargare questa.
# Grafie che Maps e i siti usano ancora, diverse da quella ISTAT usata per
# le ricerche: nomi vecchi e forme comuni (7/10). Valgono come il nome
# ufficiale per la provincia e per il segnale territoriale, mai per
# interrogare Maps (si interroga una volta sola, col nome ISTAT).
ALTRI_NOMI = {
    "Montecatini Terme": "Montecatini-Terme",
    "Sannicandro Garganico": "San Nicandro Garganico",
    "Popoli": "Popoli Terme",
}


def chiave(comune: str | None) -> str:
    """Trattino o spazio, apostrofo dritto o curvo, maiuscole: la stessa cosa."""
    return " ".join((comune or "").replace("’", "'").replace("-", " ").lower().split())


PROVINCIA_DI_COMUNE = {chiave(c): sigla
                       for sigla, lista in COMUNI.items() for c in lista}
PROVINCIA_DI_COMUNE.update({chiave(vecchio): PROVINCIA_DI_COMUNE[chiave(ufficiale)]
                            for vecchio, ufficiale in ALTRI_NOMI.items()})


def provincia_di(comune: str | None, log=None) -> str | None:
    """-> sigla della provincia del comune, o None se non e' in tabella."""
    sigla = PROVINCIA_DI_COMUNE.get(chiave(comune))
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
    # ogni comune ha la sua chiave; gli altri nomi ne aggiungono solo se non
    # coincidono gia' a meno del trattino (Montecatini Terme no, Popoli si')
    assert len({chiave(c) for v in COMUNI.values() for c in v}) == sum(len(v) for v in COMUNI.values())
    assert len(PROVINCIA_DI_COMUNE) == sum(len(v) for v in COMUNI.values()) + 2
    for forma in ("Montecatini Terme", "montecatini-terme", "MONTECATINI  TERME"):
        assert provincia_di(forma) == "PT", forma
    assert provincia_di("Sannicandro Garganico") == provincia_di("San Nicandro Garganico") == "FG"
    assert provincia_di("Popoli") == provincia_di("Popoli Terme") == "PE"
    assert provincia_di("Sant’Angelo dei Lombardi") == "AV"     # apostrofo curvo
    assert provincia_di("Firenze") == "FI" and provincia_di("Città Sant'Angelo") == "PE"
    assert provincia_di("Cava de' Tirreni") == "SA" and provincia_di("Fermo") == "FM"
    assert len(COMUNI) == 35, len(COMUNI)
    print("ok")
