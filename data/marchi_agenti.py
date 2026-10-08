"""Marchi dei serramenti da cui il committente vuole agenti (8/10): una
PRIORITA', non un filtro. `dominio`: il sito del marchio (mandato dal
committente l'8/10). `generico`: il nome da solo puo' essere un'altra
azienda (SPI, Uniform...): vale solo col contesto serramenti o col dominio.
Mandati attuali e passati hanno la stessa priorita' (l'app mostra lo stato).
"""

MARCHI = {
    # domini mandati dal committente l'8/10
    "Finstral":       {"regex": r"\bfinstral\b",          "dominio": "finstral.com",          "generico": False},
    "Piva Group":     {"regex": r"\bpiva\s*group\b",      "dominio": "pivagroupspa.com",      "generico": False},
    "Sciuker Frames": {"regex": r"\bsciuker\b",           "dominio": "sciuker.it",            "generico": False},
    "Tecnoplast":     {"regex": r"\btecnoplast\b",        "dominio": "tecnoplastinfissi.com", "generico": True},
    "Biemme":         {"regex": r"\bbiemme\b",            "dominio": "biemmefinestre.it",     "generico": True},
    "Fossati":        {"regex": r"\bfossati\b",           "dominio": "fossatiserramenti.it",  "generico": True},
    "Nurith":         {"regex": r"\bnurith\b",            "dominio": "nurith.it",             "generico": False},
    "Uniform":        {"regex": r"\buniform\b",           "dominio": "uniform.it",            "generico": True},
    "Nobento":        {"regex": r"\bnobento\b",           "dominio": "nobento.it",            "generico": False},
    "Agostini Group": {"regex": r"\bagostini\s*group\b|\bagostini\b", "dominio": "agostinigroup.com", "generico": False},
    "I Nobili":       {"regex": r"\bi\s*-?\s*nobili\b",     "dominio": "i-nobili.com",          "generico": False},
    "SPI":            {"regex": r"\bspi\b",               "dominio": "spifinestre.it",        "generico": True},
    "Isolcasa":       {"regex": r"\bisolcasa\b",          "dominio": "isolcasa.it",           "generico": False},
    "Internorm":      {"regex": r"\binternorm\b",         "dominio": "internorm.com",         "generico": False},
}

# Per i GENERICI il nome vale solo vicino a una di queste parole (entro
# CONTESTO_CARATTERI) o se il profilo cita il dominio del marchio
CONTESTO = r"serrament|finestr|infiss|porte|portoni|pvc|persian|scorrevol|alluminio|frangisole|oscurant"
CONTESTO_CARATTERI = 120

NON_GENERICI = tuple(m for m, d in MARCHI.items() if not d["generico"])
