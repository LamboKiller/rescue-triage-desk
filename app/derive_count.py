"""Derive a people total from the people a sender lists ("estou com meus dois bebês" = 3). Pure code, never the model.

Only used when no total was written. Skipped for relayed messages (the sender is not one of the people) and for
plural relations without a number ("meus filhos": count unknown -> keep asking).
"""
import re
import unicodedata

NUMBERS = {'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'tres': 3, 'quatro': 4, 'cinco': 5, 'seis': 6}
RELATIONS = (r'filh[oa]s?|beb[eê]s?|crian[cç]as?|guri[as]?s?|gurizad[ao]|m[aã]e|pai|v[oóô]|av[oóô]|irm[aã]o?s?|irm[aã]s|'
             r'esposa|esposo|marido|mulher|namorad[oa]|sobrinh[oa]s?|ti[oa]s?|prim[oa]s?|sogr[oa]|net[oa]s?|cunhad[oa]|vizinh[oa]s?|'
             r'vozinha|vovo|vov[oó]')
FIRST_PERSON = re.compile(r'\b(eu|estou|tou|t[oô]|estamos|tamo|tamos|n[oó]s|a gente|comigo)\b', re.I)
RELAYED = re.compile(r'\b(repass|encaminh|mandou|pediu pra avisar|me mandou|msg de|mensagem de)', re.I)
TOTAL_WRITTEN = re.compile(r'\b(\d+|dois|duas|dos|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|uma d[uú]zia)\s+(pessoas|personas|no total|ao todo)\b'
                           r'|\b(somos|tamo|tamos|estamos|ficamos|ficaram|restam)\s+(em\s+)?(\d+|dois|duas|tr[eê]s|quatro|cinco|seis)\b', re.I)
PHRASE = re.compile(r'\b(?:(?:o|a|os|as)\s+)?(?:meus?|minhas?|mais|o|a|os|as)?\s*(\d+|um|uma|dois|duas|tr[eê]s|quatro|cinco|seis)?\s*'
                    r'(?:meus?|minhas?)?\s*\b(' + RELATIONS + r')\b', re.I)


def _plain(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if unicodedata.category(c) != 'Mn')


def derive_people(text):
    """Return {'value': total, 'quote': first listed phrase, 'derived': True, 'listed': [...]} or None."""
    if not text or RELAYED.search(text) or TOTAL_WRITTEN.search(text) or not FIRST_PERSON.search(text):
        return None
    listed, total, first = [], 1, None  # 1 = the sender
    for m in PHRASE.finditer(text):
        word = _plain(m.group(2))
        number = m.group(1)
        plural = word.endswith('s') and word not in ('pais',)
        if number:
            n = int(number) if number.isdigit() else NUMBERS.get(_plain(number))
            if n is None:
                return None
        elif plural:
            return None  # "meus filhos" without a number: count unknown
        else:
            n = 1
        total += n
        listed.append(m.group(0).strip())
        first = first or m
    if not listed or first is None:
        return None
    return {'value': total, 'quote': first.group(0).strip(), 'derived': True, 'listed': listed}
