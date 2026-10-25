"""Derive a people total from the people a sender lists ("estou com meus dois bebês" = 3). Pure code, never the model.

Only used when no total was written. Skipped for relayed messages (the sender is not one of the people) and for
plural relations without a number ("meus filhos": count unknown -> keep asking).
"""
import re
import unicodedata
from app.agents.counts import WORDS

NUMBERS = dict(WORDS)
COUNT_NUMBER = r'(?:\d+|'+'|'.join(sorted((w for w, n in NUMBERS.items() if n >= 2 and w != 'duzia'), key=len, reverse=True))+r'|três)'
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


CORRECTION = re.compile(r'na verdade|na real|corrigindo|corrijo|arrumando|atualizando|t[aá] errad|escrevi errad|botei', re.I)
_N = '('+COUNT_NUMBER+')'
TOTAL_FORMS = re.compile(r'\b(?:somos|tamo|tamos|estamos|ficamos|ficaram|restam|s[aã]o)\s+(?:em\s+)?'+_N+r'\b'
                         r'|\b'+_N+r'\s+(?:pessoas|personas|no total|ao todo)\b'
                         # other count mentions: only used to detect a SECOND, different count
                         r'|\b(?:tem|t[aá]|falaram em|dizem|diz|conto|teima que tem)\s+'+_N+r'\b', re.I)
# Instructions or "not a request" inside the text: code must never read a count out of these (the model ignores them too).
INJECTION = re.compile(r'retorne|json|finja|ignore (?:as )?regras|\[sistema\]|approve_dispatch|\bsystem\s*:|\[/?(?:system|assistant)\]|```|role.?play|interprete (?:o papel|um)|base64|ignore (?:all|previous|todas|instru)|n[aã]o h[aá] pedido', re.I)
# Role impersonation and commands remain untrusted even inside a real plea.
INJECTION = re.compile(INJECTION.pattern +
    r'|\b(?:sistema|system|assistant|assistente|admin|developer)\s*:'
    r'|(?:\[|<|<\|)/?(?:sistema|system|assistant|admin|developer)(?:\]|>|\|>)'
    r'|\b(?:ordem do comando|operador autorizado|orden del comando|authorized operator|command orders)\b'
    r'|\b(?:ignore|ignora|ignorem|desconsidere|desconsidera|desconsiderem|disregard|bypass|override|skip)\b'
    r'[^.;!\n]{0,80}\b(?:regras?|reglas?|rules?|instru[cç][oõ]es|instructions?|instrucciones|policy|policies|safety|checks?|tudo|previous|anteriores)\b'
    r'|\b(?:aprove|aprovar|autorize|autorizar|approve|authorize|apruebe|autoriza|despache|dispatch|clasifique|classifique|classify)\b'
    r'[^.;!\n]{0,80}\b(?:despacho|dispatch|resgate|rescue|send|barco|boat|pedido|request|urgente|urgencia|emergencia)\b', re.I)


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


def reconcile_people(fields, text):
    """Apply count evidence after extraction, equally for offline and model intake."""
    if not text or INJECTION.search(text):
        return
    left = re.search(r'\b(?:mas|porem)\s+(?:ficou|ficaram|restou|restaram)\s+([^.;!\n]+)', _plain(text))
    if left:
        clause = text[left.start(1):left.end(1)]
        members = list(PHRASE.finditer(clause))
        named = list(re.finditer(r'\b(?:o|a)\s+(?:seu|dona|senhor|senhora)\s+\w+', _plain(clause)))
        total, listed = 0, []
        for member in members:
            raw, noun = member.groups()
            if not raw and _plain(noun).endswith('s'):
                fields.pop('people', None)
                fields['count_unknown'] = dict(value=True, quote=clause, source='rule:remaining_people')
                return
            total += int(raw) if raw and raw.isdigit() else NUMBERS.get(_plain(raw), 1) if raw else 1
            listed.append(member[0])
        for member in named:
            if not any(a.start() <= member.start() < a.end() for a in members):
                total += 1
                listed.append(clause[member.start():member.end()])
        if total:
            fields['people'] = dict(value=total, quote=clause, derived=True,
                                    source='rule:remaining_people', listed=listed)
            fields.pop('conflicting_counts', None)
            return
    mentions = []
    for m in TOTAL_FORMS.finditer(text):
        if re.match(r'\s+(?:familias?|adultos?|idos[oa]s?|criancas?|bebes?|cachorros?|gatos?|pets?)\b', _plain(text[m.end():])):
            continue
        raw = next(g for g in m.groups() if g)
        n = int(raw) if raw.isdigit() else NUMBERS.get(_plain(raw))
        if n:
            mentions.append((m, n))
    cues = list(CORRECTION.finditer(text))
    corrected = [(m, n) for m, n in mentions if cues and m.start() >= cues[-1].end()]
    distinct = {n for _, n in mentions}
    if len(distinct) > 1 and corrected and len({n for _, n in corrected}) == 1:
        m, n = corrected[-1]
        fields['people'] = dict(value=n, quote=m[0], source='rule:corrected_people', derived=True,
            previous=[dict(value=v, quote=old[0]) for old, v in mentions if old.start() < cues[-1].start()],
            listed=[m[0]])
        # Only a self-correction inside one message needs confirming; a correction sent as a
        # later message (history is joined by newlines) is the reporter's deliberate answer.
        boundary = text.rfind(chr(10), 0, cues[-1].start())
        if not (boundary >= 0 and all(old.end() <= boundary for old, _ in mentions if old.start() < cues[-1].start())):
            fields['people']['confirm'] = True
        fields.pop('conflicting_counts', None)
    elif len(distinct) > 1 and not derive_grouped(text):
        fields['conflicting_counts'] = dict(value=True, quote=text, source='rule:count_conflict',
                                          alternatives=[dict(value=n, quote=m[0]) for m, n in mentions])
    elif len(distinct) == 1 and not derive_grouped(text):
        m, n = mentions[-1]
        fields['people'] = {**fields.get('people', {}), 'value': n, 'quote': m[0], 'source': 'text_total'}
    else:
        grouped = derive_grouped(text)
        unknown = bool(re.search(r'\b(?:familias?|um monte de gente|muita gente|varias pessoas)\b', _plain(text)))
        if (grouped and grouped.get('minimum')) or (unknown and not grouped):
            fields.pop('people', None)
            fields['count_unknown'] = dict(value=True, quote=text, source='rule:unknown_group')
        elif not grouped:
            from app.geo.incident import incident_text
            scoped = incident_text(text)
            remote = bool(FIRST_PERSON.search(text) and not FIRST_PERSON.search(scoped))
            derived = None if remote else derive_people(text)
            if derived:
                fields['people'] = derived
            # An explicitly remote reporter contributes zero people. Count only
            # quantified relatives in the incident clause, retaining each quote.
            elif re.search(r'\b(?:ligo|ligando|telefonando|repassando|estou em)\b', _plain(text)):
                members = list(PHRASE.finditer(scoped))
                if members and not unknown:
                    total, listed = 0, []
                    for member in members:
                        raw, noun = member.groups()
                        n = int(raw) if raw and raw.isdigit() else NUMBERS.get(_plain(raw)) if raw else None
                        if n is None and noun.endswith('s'):
                            break
                        total += n if n is not None else 1
                        listed.append(text[member.start():member.end()].strip())
                    else:
                        fields['people'] = dict(value=total, quote=text[members[0].start():members[-1].end()],
                            derived=True, source='rule:remote_reporter_relations', listed=listed)


RESCUE_COMPLETE = re.compile(
    r'\b(?:ja sai(?:mos)?\b|(?:um |uma |o |a )?vizinh[oa][^.;!\n]{0,35}me levou de (?:caiaque|barco|lancha)|ja (?:foram|estao|estamos|fomos) (?:tod[oa]s? )?(?:resgatad[oa]s?|retirad[oa]s?|tirad[oa]s?|no abrigo)|'
    r'(?:consegui|conseguimos|conseguiram) sair|(?:um |uma |o |a )?vizinh[oa][^.;!\n]{0,45}me tirou)\b')
REMAINING = re.compile(
    r'\b(?:ainda|continua[m]?|segue[m]?)\s+(?:(?:esta[o]?|tem|ha|ficou|ficaram)\s+)?'
    r'[^.;!\n]{0,45}\b(?:pres[oa]s?|ilhad[oa]s?|para tras|pra tras|precisa[m]? de (?:resgate|ajuda))\b'
    r'|\b(?:mas|porem)\b[^.;!\n]{0,55}\b(?:ficou|ficaram|resta|restam)\b[^.;!\n]{0,25}(?:la|no local|na casa|no telhado)\b')


def completed_rescue_quote(text):
    """Positive completed-rescue evidence, never a negation or a partial rescue."""
    from app.rescue_state import state
    plain = _plain(text)
    if state(text)['partial'] or REMAINING.search(plain):
        return None
    for match in RESCUE_COMPLETE.finditer(plain):
        if not re.search(r'\b(?:nao|nunca|not|no)\s+(?:\w+\s+){0,2}$', plain[max(0, match.start()-35):match.start()]):
            return text[match.start():match.end()]
    return None
