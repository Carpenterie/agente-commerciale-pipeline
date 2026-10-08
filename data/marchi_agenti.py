"""Marchi dei serramenti da cui il committente vuole agenti (8/10): una
PRIORITA', non un filtro. `dominio` e' la parte del dominio del sito del
marchio (per le pagine "rete vendita" e per riconoscerlo nei profili).
`generico`: il nome da solo puo' essere un'altra azienda (SPI, Uniform...):
vale solo col contesto serramenti o col dominio, e finche' il committente
non manda i siti questi marchi restano fuori dai giri.
"""

MARCHI = {
    "Finstral":       {"regex": r"\bfinstral\b",          "dominio": "finstral",  "generico": False},
    "Piva Group":     {"regex": r"\bpiva\s*group\b",      "dominio": "pivagroup", "generico": False},
    "Sciuker Frames": {"regex": r"\bsciuker\b",           "dominio": "sciuker",   "generico": False},
    "Tecnoplast":     {"regex": r"\btecnoplast\b",        "dominio": "",          "generico": True},
    "Biemme":         {"regex": r"\bbiemme\b",            "dominio": "",          "generico": True},
    "Fossati":        {"regex": r"\bfossati\b",           "dominio": "",          "generico": True},
    "Nurith":         {"regex": r"\bnurith\b",            "dominio": "nurith",    "generico": False},
    "Uniform":        {"regex": r"\buniform\b",           "dominio": "",          "generico": True},
    "Nobento":        {"regex": r"\bnobento\b",           "dominio": "nobento",   "generico": False},
    "Agostini Group": {"regex": r"\bagostini\s*group\b|\bagostini\b", "dominio": "agostinigroup", "generico": False},
    "I Nobili":       {"regex": r"\bi\s*nobili\b",        "dominio": "inobili",   "generico": False},
    "SPI":            {"regex": r"\bspi\b",               "dominio": "",          "generico": True},
    "Isolcasa":       {"regex": r"\bisolcasa\b",          "dominio": "isolcasa",  "generico": False},
    "Internorm":      {"regex": r"\binternorm\b",         "dominio": "internorm", "generico": False},
}

NON_GENERICI = tuple(m for m, d in MARCHI.items() if not d["generico"])
