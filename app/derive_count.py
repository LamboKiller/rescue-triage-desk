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


# Popular municipality short names (the model copies "POA" exactly; lookups need the official name).
MUNICIPALITY_ALIASES = {'poa': 'Porto Alegre', 'sl': 'São Leopoldo', 'nh': 'Novo Hamburgo',
                        'porto alegre rs': 'Porto Alegre', 'porto alegre/rs': 'Porto Alegre'}


def canonical_municipality(value):
    if not isinstance(value, str):
        return value
    return MUNICIPALITY_ALIASES.get(_plain(value).strip(' .,'), value)


CORRECTION = re.compile(r'na verdade|na real|corrigind|corrijo|arrumando|atualizando|t[aá] errad|escrevi errad|botei', re.I)
_N = r'(\d+|dois|duas|tr[eê]s|quatro|cinco|seis)'
TOTAL_FORMS = re.compile(r'\b(?:somos|tamo|tamos|estamos|ficamos|ficaram|restam|s[aã]o)\s+(?:em\s+)?'+_N+r'\b'
                         r'|\b'+_N+r'\s+(?:pessoas|personas|no total|ao todo)\b'
                         # other count mentions: only used to detect a SECOND, different count
                         r'|\b(?:tem|t[aá]|falaram em|dizem|diz|conto|teima que tem)\s+'+_N+r'\b', re.I)
# Instructions or "not a request" inside the text: code must never read a count out of these (the model ignores them too).
INJECTION = re.compile(r'retorne|json|finja|ignore (?:as )?regras|\[sistema\]|approve_dispatch|\bsystem\s*:|\[/?(?:system|assistant)\]|```|role.?play|interprete (?:o papel|um)|base64|ignore (?:all|previous|todas|instru)|n[aã]o h[aá] pedido', re.I)


GROUP_N = r'(?:\d+|um|uma|un|una|dois|duas|dos|tres|quatro|cinco|seis|sete|oito|nove|dez)'
GROUP_GLOBAL = re.compile(r'\b(?:somos|estamos em|ao todo|no total|total de)\s+'+GROUP_N+r'\b(?!\s+familias?\b)|\b'+GROUP_N+r'\s+(?:no total|ao todo)\b')
GROUP_PLACE = re.compile(r'\b(?:casa|fundos|frente|andar|cima|baixo|anexo|puxadinho|parte|sobrado)\b')
GROUP_MEMBER = re.compile(r'\b(?:(?P<n>'+GROUP_N+r')\s+)?(?P<kind>pessoas?|personas?|adult[oa]s?|idos[oa]s?|criancas?|bebes?|abuel[oa]s?|avos?|casais|casal|gemeos?|familias?)\b')


def derive_grouped(text):
    """Explicit members in separate spatial groups; unknown families give a minimum.

    A local total owns its immediately following parenthetical breakdown. No
    sender is added to third-party groups. Ambiguous prose is left for callback.
    """
    if not text or INJECTION.search(text):
        return None
    plain = _plain(text)
    if GROUP_GLOBAL.search(plain) or CORRECTION.search(text):
        return None
    # Mask only breakdowns attached to a stated people total.
    scoped = re.sub(r'\b'+GROUP_N+r'\s+(?:pessoas?|personas?)\s*\([^)]*\)',
                    lambda m: m[0][:m[0].index('(')]+' '*(len(m[0])-m[0].index('(')), plain)
    matches = list(GROUP_MEMBER.finditer(scoped))
    first_place = GROUP_PLACE.search(scoped)
    if first_place and len(GROUP_PLACE.findall(scoped)) >= 2:
        # A family heading followed by spatial member lists describes the
        # same people; it is neither an extra group nor an explicit total.
        matches = [m for m in matches if not (m['kind'].startswith('familia') and
                                             m.end() < first_place.start())]
    family = any(m['kind'].startswith('familia') for m in matches)
    if family and len(matches) > 1 and len(GROUP_PLACE.findall(scoped)) < 2:
        return None  # "2 families, 8 people" supplies a total, not 10 people.
    if not matches or not (any(m['kind'].startswith('familia') for m in matches) or
                           len(GROUP_PLACE.findall(scoped)) >= 2 and len(matches) >= 2):
        return None
    # A total followed by a prose breakdown is not safely additive.
    if re.search(r'\b(?:sendo|incluindo|entre el[ae]s|dest[ae]s|dos quais|dizem|disseram|falaram)\b', scoped):
        return None
    numbers = {**NUMBERS, 'un': 1, 'una': 1, 'dos': 2, 'sete': 7, 'oito': 8, 'nove': 9, 'dez': 10}
    total, minimum, listed = 0, False, []
    for m in matches:
        raw, kind = m['n'], m['kind']
        if raw:
            n = int(raw) if raw.isdigit() else numbers[raw]
        elif kind in ('casal', 'gemeos'):
            n = 1
        else:
            return None  # Unquantified groups must not silently disappear.
        total += n * (2 if kind in ('casal', 'casais', 'gemeos') else 1)
        minimum |= kind.startswith('familia')
        listed.append(text[m.start():m.end()])
    if total < 1:
        return None
    return dict(value=total, quote=text[matches[0].start():matches[-1].end()], derived=True,
                source='rule:grouped_people', listed=listed, minimum=minimum)


def count_values(text):
    """Distinct people counts mentioned in the text (for disagreement detection)."""
    if derive_grouped(text):
        return set()  # Local group totals are not conflicting incident totals.
    values = set()
    for m in TOTAL_FORMS.finditer(text or ''):
        # A category/group count is not another total ("tem 2 famílias,
        # 7 pessoas" or "tem 2 idosos entre 5 pessoas").
        if re.match(r'\s+(?:familias?|adultos?|idos[oa]s?|criancas?|bebes?|cachorros?|gatos?|pets?)\b',
                    _plain((text or '')[m.end():])):
            continue
        raw = next(g for g in m.groups() if g)
        n = int(raw) if raw.isdigit() else NUMBERS.get(_plain(raw))
        if n:
            values.add(n)
    return values


def written_total(text):
    """The one total written in the text ("somos em 6", "4 no total"), or None when absent, several differ, or injected."""
    if not text or INJECTION.search(text) or derive_grouped(text):
        return None
    values, first = set(), None
    for m in TOTAL_FORMS.finditer(text):
        if re.match(r'\s+(?:familias?|adultos?|idos[oa]s?|criancas?|bebes?|cachorros?|gatos?|pets?)\b',
                    _plain(text[m.end():])):
            continue
        raw = next(g for g in m.groups() if g)
        n = int(raw) if raw.isdigit() else NUMBERS.get(_plain(raw))
        if n:
            values.add(n)
            first = first or m
    if len(values) != 1 or first is None:
        return None
    return {'value': values.pop(), 'quote': first.group(0), 'source': 'text_total'}


def derive_people(text):
    """Return {'value': total, 'quote': first listed phrase, 'derived': True, 'listed': [...]} or None."""
    grouped = derive_grouped(text)
    if grouped:
        return grouped
    if not text or INJECTION.search(text) or RELAYED.search(text) or TOTAL_WRITTEN.search(text) or not FIRST_PERSON.search(text):
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
    return {'value': total, 'quote': first.group(0).strip(), 'derived': True, 'source': 'rule:sender_plus_listed_people', 'listed': listed}
