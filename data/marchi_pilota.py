"""Pilota B1 della ricerca agenti (preventivo PREV-2026-06, 5/11): 30 aziende
della filiera del serramento, tutte NON concorrenti, scelte dall'elenco del
committente (che resta fuori dal repo: qui solo nomi e domini).

Stesso formato di data/marchi_agenti.MARCHI, piu':
- `grande`: azienda grande e specializzata -> solo la ricerca nazionale,
  niente agenzie, al massimo PROFILI_GRANDE profili raccolti;
- `contesto`: per i nomi generici (cognomi, parole comuni) il nome vale
  solo vicino a una parola della filiera (porte, serrature, zanzariere...).
"""

from data.marchi_agenti import CONTESTO

PROFILI_GRANDE = 5

CONTESTO_FILIERA = (CONTESTO + r"|serratur|manigli|ferrament|zanzarier|avvolgibil|tapparell"
                    r"|controtela|portoncin|blindat|tende|automazion|cerniere|scorrevol")


def _m(regex: str, dominio: str, generico: bool = False, grande: bool = False) -> dict:
    return {"regex": regex, "dominio": dominio, "generico": generico, "grande": grande,
            "contesto": CONTESTO_FILIERA}


PILOTA = {
    # grandi specializzate: tetto di PROFILI_GRANDE profili
    "Schüco":           _m(r"\bsch(?:u|ue)co\b", "schueco.com", grande=True),
    "REHAU":            _m(r"\brehau\b", "rehau.it", grande=True),
    "Roto Frank":       _m(r"\broto\b", "roto-frank.com", generico=True, grande=True),
    "CISA":             _m(r"\bcisa\b", "cisa.com", generico=True, grande=True),
    "Somfy":            _m(r"\bsomfy\b", "somfy.it", grande=True),
    # finestre
    "Oknoplast":        _m(r"\boknoplast\b", "oknoplast.it"),
    "Alpilegno":        _m(r"\balpi\s*legno\b", "alpilegno.com"),
    "Deceuninck":       _m(r"\bdeceuninck\b", "deceuninck.it"),
    "Drutex":           _m(r"\bdrutex\b", "drutex.it"),
    "Navello":          _m(r"\bnavello\b", "navello.it", generico=True),
    "Focchi":           _m(r"\bfocchi\b", "focchi.it", generico=True),
    # porte
    "FerreroLegno":     _m(r"\bferrero\s*legno\b", "ferrerolegno.com"),
    "Flessya":          _m(r"\bflessya\b", "flessya.com"),
    "Garofoli":         _m(r"\bgarofoli\b", "garofoli.com", generico=True),
    "Barausse":         _m(r"\bbarausse\b", "barausse.com"),
    "Hörmann":          _m(r"\bh(?:o|oe)rmann\b", "hormann.it", generico=True),
    # ferramenta e serrature
    "Colfert":          _m(r"\bcolfert\b", "colfert.com"),
    "Olivari":          _m(r"\bolivari\b", "olivari.it", generico=True),
    "Meroni Serrature": _m(r"\bmeroni\b", "serraturemeroni.it", generico=True),
    "Securemme":        _m(r"\bsecuremme\b", "securemme.it"),
    "Giesse":           _m(r"\bgiesse\b", "giessegroup.it", generico=True),
    # zanzariere
    "Grifoflex":        _m(r"\bgrifoflex\b", "grifoflex.com"),
    "Palagina":         _m(r"\bpalagina\b", "palagina.eu"),
    "Bettio":           _m(r"\bbettio\b", "bettio.it", generico=True),
    # avvolgibili
    "Griesser":         _m(r"\bgriesser\b", "griesser.it"),
    "Donelli":          _m(r"\bdonelli\b", "donelliavvolgibili.it", generico=True),
    "Acediplast":       _m(r"\bacediplast\b", "acediplast.com"),
    # controtelai
    "Eclisse":          _m(r"\beclisse\b", "eclisse.it", generico=True),
    "Scrigno":          _m(r"\bscrigno\b", "scrigno.net", generico=True),
    "Roverplastik":     _m(r"\broverplastik\b", "roverplastik.it"),
}
