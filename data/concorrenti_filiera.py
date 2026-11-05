"""Concorrenti fra le aziende della filiera del serramento (elenco del
committente, fuori dal repo) — regola DEFINITIVA per B2, decisa il 5/11/2026.

CONCORRENTI: chi fa grate o inferriate; chi fa persiane blindate o di
sicurezza; chi dichiara persiane o chiusure in acciaio o ferro.
Per i loro agenti valgono le regole dei concorrenti (conflitto per i mandati
attuali, recuperabili i passati): da implementare in B2.

NON CONCORRENTI:
- chi fa solo persiane senza indicare l'acciaio (materiale non indicato, o
  alluminio, legno, PVC), come gia' Finstral e Fossati;
- chi fa solo porte blindate o portoncini in acciaio: Carpenterie non fa
  porte, i loro agenti sono complementari;
- chi fa accessori o materiali, anche in acciaio o "di sicurezza"
  (serrature, maniglie, tasselli, profili, ferramenta).

Nel repo solo nomi di aziende: le ragioni sociali che contengono un nome di
persona sono indicate col codice della riga nel file del committente.
"""

# 27, con il motivo in una riga
CONCORRENTI = {
    "Agnelli Metalli": "grate, persiane e blindati in metallo",
    "AGRITAL": "cancelli e cancelletti di sicurezza; carpenteria",
    "AM Porte": "porte blindate e corazzate, grate e persiane",
    "Blindato Effepi": "porte blindate e grate di sicurezza",
    "IT-0069": "inferriate, cancelli e lavorazioni metalliche (ragione sociale con nome di persona)",
    "CONEGLIANO SERRAMENTI": "grate",
    "DI LUCA INFISSI": "grate",
    "DI.BI. Porte Blindate": "porte blindate, cancelletti e persiane",
    "Erreci Sicurezza": "grate e persiane di sicurezza",
    "FBS": "grate",
    "FERRARO": "grate e persiane",
    "FERWALL": "grate",
    "FIS": "grate",
    "GARDESA": "porte blindate, avvolgibili di sicurezza in acciaio",
    "Gruben Italia Security": "grate e persiane; il sito parla di ferro",
    "INFERRIATE.IT": "inferriate",
    "INVICTA": "grate",
    "ISOLA PVC": "grate e persiane",
    "LUXURY WINDOWS": "porte blindate e grate di sicurezza",
    "MITO": "grate",
    "NUOVA SIME": "porte blindate, inferriate e persiane di sicurezza",
    "OSMA": "grate",
    "PASTORE": "grate e persiane",
    "SANDRINI": "grate e persiane",
    "Sicurezza Italia": "grate",
    "TERMIKA": "grate",
    "Xecur": "inferriate apribili e fisse",
}

_SOLO_PERSIANE = "solo persiane, acciaio non indicato"

# 41: solo persiane senza acciaio
NON_CONCORRENTI_PERSIANE = {
    "Aldena": _SOLO_PERSIANE,
    "ALPI FENSTER": "solo persiane e oscuranti, acciaio non indicato",
    "BONO": _SOLO_PERSIANE,
    "BORA SYSTEM": "solo persiane; il sito parla di alluminio",
    "CALLIGARO": _SOLO_PERSIANE,
    "CDR": _SOLO_PERSIANE,
    "COBOLA": _SOLO_PERSIANE,
    "DIERRE": _SOLO_PERSIANE,
    "DIQUIGIOVANNI": _SOLO_PERSIANE,
    "DOTTI": _SOLO_PERSIANE,
    "Drago Italia": "solo persiane e scuri, acciaio non indicato",
    "ERCO": _SOLO_PERSIANE,
    "EUROFINESTRA": _SOLO_PERSIANE,
    "EUROMIX": _SOLO_PERSIANE,
    "FINBLOK": "solo persiane; il sito parla di legno",
    "GF INFISSI": _SOLO_PERSIANE,
    "GINKO": _SOLO_PERSIANE,
    "INFINITO": _SOLO_PERSIANE,
    "ISOMAX": _SOLO_PERSIANE,
    "ITAL JOLLY": "solo persiane; il sito parla di alluminio e legno",
    "ITALPLASTICK": _SOLO_PERSIANE,
    "Kikau": "solo persiane; il sito parla di alluminio",
    "LENNOK": _SOLO_PERSIANE,
    "MOLARO SERRAMENTI": _SOLO_PERSIANE,
    "MV Line": _SOLO_PERSIANE,
    "PANTO FINESTRE": _SOLO_PERSIANE,
    "PAVANELLO SERRAMENTI": _SOLO_PERSIANE,
    "Persit": "solo persiane; il sito parla di alluminio",
    "PIZZOLON": _SOLO_PERSIANE,
    "POLVANESI": _SOLO_PERSIANE,
    "Proline Italia": _SOLO_PERSIANE,
    "RSA ROSSO": "solo persiane; il sito parla di alluminio e PVC",
    "IT-0413": _SOLO_PERSIANE + " (ragione sociale con nome di persona)",
    "SICURA S.R.L.": "solo persiane; il sito parla di alluminio",
    "SIDEL": _SOLO_PERSIANE,
    "SL": _SOLO_PERSIANE,
    "STABIL ITALIA": _SOLO_PERSIANE,
    "TAIETTI": _SOLO_PERSIANE,
    "TESTUDO": _SOLO_PERSIANE,
    "Zanzar": _SOLO_PERSIANE,
    "ÈKASA GROUP": _SOLO_PERSIANE,
}

# casi decisi il 5/11 fuori dai due elenchi: complementari, non concorrenti
NON_CONCORRENTI_ALTRI = {
    "3M Tecnofer": "solo porte blindate: complementare",
    "Nusco": "porte interne e blindate: complementare",
    "Piesseti": "serramenti e blindati, niente persiane o grate: complementare",
    "AUROPORT": "porte e portoncini in acciaio: complementare",
    "MOTTURA SERRATURE": "accessori: serrature",
    "Fimet maniglie": "accessori: maniglie",
    "Allfix Italia": "materiali: tasselli",
    "EDILFERRO": "materiali: profili per intonaco",
    "TECNOSICUREZZA": "accessori: ferramenta e serrature",
}

if __name__ == "__main__":
    assert len(CONCORRENTI) == 27 and len(NON_CONCORRENTI_PERSIANE) == 41
    assert not set(CONCORRENTI) & (set(NON_CONCORRENTI_PERSIANE) | set(NON_CONCORRENTI_ALTRI))
    from data.marchi_pilota import PILOTA
    assert not {m.casefold() for m in PILOTA} & {c.casefold() for c in CONCORRENTI}
    print("ok")
