"""Derive a people total from the people a sender lists ("estou com meus dois bebês" = 3). Pure code, never the model.

Only used when no total was written. Skipped for relayed messages (the sender is not one of the people) and for
plural relations without a number ("meus filhos": count unknown -> keep asking).
"""
import re
import unicodedata
from app.agents.counts import WORDS

NUMBERS = dict(WORDS)
COUNT_NUMBER = r'(?:\d+|'+'|'.join(sorted((w for w, n in NUMBERS.items() if n >= 2 and w != 'duzia'), key=len, reverse=True))+r'|três)'
RELATIONS = (r'filh[oa]s?|beb[eê]s?|crian[cç]as?|guri[as]?s?|gurizad[ao]|m[aã]e|pais?|v[oóô]|av[oóô]|irm[aã]o?s?|irm[aã]s|'
             r'esposa|esposo|marido|mulher|namorad[oa]|sobrinh[oa]s?|ti[oa]s?|prim[oa]s?|sogr[oa]|net[oa]s?|cunhad[oa]|vizinh[oa]s?|'
             r'vozinha|vovo|vov[oó]|colegas?')
FIRST_PERSON = re.compile(r'\b(eu|estou|tou|t[oô]|estamos|tamo|tamos|n[oó]s|a gente|comigo|tenho)\b', re.I)
RELAYED = re.compile(r'\b(repass|encaminh|mandou|pediu pra avisar|me mandou|msg de|mensagem de)', re.I)
TOTAL_WRITTEN = re.compile(r'\b(\d+|dois|duas|dos|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|uma d[uú]zia)\s+(pessoas|personas|no total|ao todo)\b'
                           r'|\b(somos|tamo|tamos|estamos|ficamos|ficaram|restam)\s+(em\s+)?(\d+|dois|duas|tr[eê]s|quatro|cinco|seis)\b', re.I)
PHRASE = re.compile(r'\b(?:(?:o|a|os|as)\s+)?(?:meus?|minhas?|mais|o|a|os|as)?\s*(\d+|um|uma|dois|duas|tr[eê]s|quatro|cinco|seis)?\s*'
                    r'(?:meus?|minhas?)?\s*\b(' + RELATIONS + r')\b', re.I)


def _plain(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if unicodedata.category(c) != 'Mn')


# Popular municipality short names (the model copies "POA" exactly; lookups need the official name).
MUNICIPALITY_ALIASES = {'poa': 'Porto Alegre', 'sl': 'São Leopoldo', 'nh': 'Novo Hamburgo',
                        'portoalegre': 'Porto Alegre', 'canos': 'Canoas', 'canoaz': 'Canoas',
                        'sao leopodo': 'São Leopoldo', 'sao leopldo': 'São Leopoldo',
                        'eldorado': 'Eldorado do Sul', 'eldorado do su': 'Eldorado do Sul',
                        'guaiva': 'Guaíba', 'guayba': 'Guaíba', 'novo amburgo': 'Novo Hamburgo',
                        'novo hamburgo rs': 'Novo Hamburgo',
                        'porto alegre rs': 'Porto Alegre', 'porto alegre/rs': 'Porto Alegre'}


def canonical_municipality(value):
    if not isinstance(value, str):
        return value
    return MUNICIPALITY_ALIASES.get(_plain(value).strip(' .,'), value)


CORRECTION = re.compile(r'na verdade|na real|corrigindo|corrijo|arrumando|atualizando|t[aá] errad|escrevi errad|botei', re.I)
_N = '('+COUNT_NUMBER+')'
TOTAL_FORMS = re.compile(r'\b(?:somos?|tamo|tamos|estamos|ficamos|ficaram|restam|s[aã]o)\s+(?:em\s+|s[oó]\s+n[oó]s\s+)?'+_N+r'\b'
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


# ACC1: instructions aimed at the system, general forms (forget/role-play/secret requests/skip checks/directives/fake authority).
INJECTION = re.compile(INJECTION.pattern +
    r'|\besque[cç]a(?:m)?\b[^.;!\n]{0,40}\b(?:regras?|instru\w+|tudo|anteriores?|ordens|diretrizes)\b'
    r'|\b(?:ignore|ignora|ignorem|desconsidere|desconsiderem|pule|pulem|dispense|dispensem|ignore o|ignorar|desligue)\b[^.;!\n]{0,30}\b(?:checagem|verifica[cç][aã]o|revis[aã]o|filtro|valida[cç][aã]o|humano|fila|aprova[cç][aã]o)\b'
    r'|\b(?:sou|aqui [eé]|eu sou)\s+(?:o |a )?(?:administrador|admin|desenvolvedor|operador|programador)\b[^.;!\n]{0,25}\b(?:sistema|plataforma|desk)\b'
    r'|\b(?:apague|apaguem|delete|exclua|excluam|remova|limpe)\b[^.;!\n]{0,40}\b(?:pedidos?|fila|registros?|hist[oó]rico|duplicados?)\b'
    r'|\b(?:libere|liberem|libera)\b[^.;!\n]{0,20}\b(?:viaturas?|equipes?|barcos?|unidades?)\b[^.;!\n]{0,25}\b(?:para|pra)\s+(?:o |a )?endere[cç]o\b'
    r'|\b(?:forget|ignore)\s+(?:the |your |all |every )?(?:rules|instructions|guidelines)\b'
    r'|\bvoc[eê]\s+(?:agora\s+)?(?:[eé]|ser[aá])\s+(?:o |a |um |uma )?(?:despachante|administrador|admin|chefe|sistema|assistente|ia|rob[oô]|bot|comandante)\b'
    r'|\byou\s+are\s+(?:now\s+)?(?:the |a |an )?(?:dispatcher|admin|system|assistant)\b|\b(?:aja|atue|haja|act)\s+(?:como|as)\b'
    r'|\bprompt\b|\bapi.?key\b|\bchave\s+(?:da\s+)?api\b'
    r'|\b(?:mostr\w+|revel\w+|exib\w+|imprim\w+|repit\w+|vaz\w+|divulg\w+|reveal|show|leak|display)\b[^.;!\n]{0,60}\b(?:instru[cç][oõ]es (?:internas|do sistema)|credenciais|segredos?|senhas?)\b'
    r'|\bsem\s+(?:qualquer\s+)?(?:verifica[cç][aã]o|checagem|checar|confer[eê]ncia|conferir|valida[cç][aã]o|revis[aã]o|aprova[cç][aã]o|verificar)\b'
    r'|\bn[aã]o\s+(?:precisa|precisam|pode|podem)\s+(?:verificar|checar|conferir|revisar|validar)\b'
    r'|\b(?:pule|pulem|pular|dispense|dispensem)\b[^.;!\n]{0,20}\b(?:revis[aã]o|verifica[cç][aã]o|checagem|aprova[cç][aã]o|humano)\b'
    r'|<!--|\bskip_review\b|\b(?:decision|decis[aã]o|priority|prioridade|dispatch)\s*[:=]\s*\w+'
    r'|\b(?:autorizo|determino|ordeno)\b[^.;!\n]{0,40}\b(?:despacho|envio|dispatch|equipes?|barcos?)\b'
    r'|\b(?:coronel|comandante|general|major|tenente|capit[aã]o|prefeito|secret[aá]rio)\b[^.;!\n]{0,30}\b(?:da |do |de )?(?:defesa civil|bombeiros|prefeitura|governo|comando|ex[eé]rcito)\b'
    r'|\b(?:priorize|priorizem|priorizar)\b[^.;!\n]{0,40}\b(?:pedido|caso|mensagem|n[oó]s|nossa|nosso|meu|minha|esta|este)\b'
    r'|\b(?:coloque|ponha|passe|suba|mova)\b[^.;!\n]{0,30}\b(?:pedido|caso|mensagem)\b[^.;!\n]{0,30}\b(?:primeiro|topo|frente|prioridade)\b'
    r'|\b(?:mand[ea]m?|envie|enviem|despache|despachem)\b[^.;!\n]{0,20}\b(?:todos|todas|tudo)\b[^.;!\n]{0,30}\b(?:barcos?|equipes?|unidades?|helic\w+|viaturas?|recursos)\b', re.I)


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
    for m in total_mentions(text or ''):
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
    for m in total_mentions(text):
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


def total_mentions(text):
    """Head counts exclude clock readings even when introduced by 'são'."""
    for match in TOTAL_FORMS.finditer(text):
        if re.match(r'\s*(?:h\b|horas?\b|anos?\b|meses\b|da (?:manha|tarde|noite)\b|:\d)', _plain(text[match.end():])):
            continue
        yield match


def disjoint_people(text):
    """Sum explicitly coordinated populations, never overlapping vulnerability tags."""
    n = GROUP_N
    patterns = (
        r'\b('+n+r')\s+adult[oa]s?\s+e\s+('+n+r')\s+criancas?\b',
        r'\b('+n+r')\s+idos[oa]s?\s+e\s+('+n+r')\s+cuidador[ae]s?\b',
        r'\b(gestante)(?:\s+de\s+\d+\s+meses)?\s+e\s+(?:mais\s+)?('+n+r')\s+criancas?\b',
        r'\b(um|uma)\s+(?:cadeirante|idoso|idosa)\s+e\s+(um|uma)\s+(?:senhora?|homem|mulher)\b',
    )
    for pattern in patterns:
        m = re.search(pattern, _plain(text))
        if m:
            values = [int(x) if x.isdigit() else 1 if x == 'gestante' else NUMBERS[x] for x in m.groups()]
            return dict(value=sum(values), quote=text[m.start():m.end()], derived=True,
                        count_basis='derived', source='rule:disjoint_people', listed=[text[m.start():m.end()]])
    return None


def derive_people(text):
    """Compute household totals or sender plus an explicitly enumerated list."""
    if not text or INJECTION.search(text) or RELAYED.search(text):
        return None
    couple = re.search(r'\b(?:um\s+)?casal\s+de\s+(?:idosos|moradores|adultos|pessoas)\b', _plain(text))
    if couple:
        return dict(value=2, quote=text[couple.start():couple.end()], derived=True,
                    count_basis='derived', source='rule:couple', listed=[text[couple.start():couple.end()]])
    # Explicit lists with named people are distinct individuals, unlike category tags.
    name = r'(?:[oa]\s+[A-ZÀ-Ý][a-zà-ÿ]+|(?:[oa]|meu|minha|nosso|nossa)\s+(?:bebe|bebê|marido|esposa|filho|filha))'
    named = re.search(r'\b[Ee]u\s*,\s*('+name+r'(?:\s*,\s*'+name+r')*\s+e\s+'+name+r')\s+(?:estamos|ficamos|aguardamos)\b', text)
    if named:
        members = re.split(r'\s*,\s*|\s+e\s+', named[1])
        return dict(value=1+len(members), quote=named[0], derived=True, count_basis='derived',
                    source='rule:enumerated_people', listed=members)
    household = re.search(r'\b(?:(?:minha|nossa)\s+fam[ií]lia\s+de|n[oó]s)\s+('
                          + GROUP_N + r')\b', text, re.I)
    if household and not TOTAL_WRITTEN.search(text):
        raw = _plain(household[1])
        n = int(raw) if raw.isdigit() else NUMBERS.get(raw)
        if n and n > 0:
            return dict(value=n, quote=household[0], derived=True, count_basis='derived',
                        source='rule:household_total', listed=[household[0]])
    grouped = derive_grouped(text)
    if grouped:
        return grouped
    if not text or INJECTION.search(text) or RELAYED.search(text) or TOTAL_WRITTEN.search(text) or not FIRST_PERSON.search(text):
        return None
    from app.geo.incident import incident_text
    scoped = people_text(text)
    if not FIRST_PERSON.search(scoped):
        return None  # A remote reporter is not an additional victim.
    # Prefer an explicit current enumeration over relatives mentioned in the backstory.
    enumerations = list(re.finditer(r'\beu\s*(?:,\s*|\s+e\s+|\s+com\s+)(?=(?:[oa]|meus?|minhas?|noss[oa]s?|mais|\d+)\b)', scoped))
    if enumerations:
        start = enumerations[-1].start()
        scoped = ' '*start + scoped[start:]
    listed, total, first, last = [], 1, None, None  # 1 = the sender
    for m in PHRASE.finditer(scoped):
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
            n = 2 if word == 'pais' else 1
        total += n
        listed.append(text[m.start():m.end()].strip())
        first = first or m
        last = m
    if not listed or first is None:
        alone = re.search(r'\b(?:estou|to|tou)\s+sozinh[oa]\b', scoped)
        if alone:
            return dict(value=1, quote=text[alone.start():alone.end()], derived=True,
                        count_basis='derived', source='rule:alone', listed=[text[alone.start():alone.end()]])
        return None
    sender = [m for m in FIRST_PERSON.finditer(text) if m.start() < first.start()]
    start = sender[-1].start() if sender else first.start()
    return {'value': total, 'quote': text[start:last.end()].strip(), 'derived': True,
            'count_basis': 'derived', 'source': 'rule:sender_plus_listed_people', 'listed': listed}


def people_text(text):
    """Keep offsets while excluding caller provenance and numbered street names."""
    from app.geo.incident import incident_text
    return re.sub(r'\b(?:rua|avenida|av\.?|travessa|estrada)\s+[^\d,.;!?\n]{1,80}(?=\s+\d)',
                  lambda m: ' '*len(m[0]), incident_text(text))


def reconcile_people(fields, text):
    """Apply count evidence after extraction, equally for offline and model intake."""
    if not text or INJECTION.search(text):
        return
    # Live intake can copy an age as a category's phrase. Recompute without
    # ages before comparing vulnerable groups with the incident total.
    from app.agents.counts import count
    age_pattern = r'\b(?:(?:de|com)\s+)?(\d+|'+'|'.join(NUMBERS)+r')\s+(anos?|meses?)\b'
    for key in ('children', 'elderly', 'disabled'):
        field = fields.get(key, {})
        quote = _plain(field.get('quote', ''))
        ages = list(re.finditer(age_pattern, quote))
        if not ages:
            continue
        without_ages = re.sub(age_pattern, '', quote).strip()
        value = count(without_ages, key)
        if value is None and key == 'children' and re.fullmatch(
                r'(?:(?:meu|minha|o|a)\s+)?(?:filh[oa]|crianca|bebe|guri|guria)', without_ages):
            age = int(ages[0][1]) if ages[0][1].isdigit() else NUMBERS[ages[0][1]]
            if len(ages) == 1 and (ages[0][2].startswith('mes') or age < 18):
                value = 1
        if value is None:
            fields.pop(key, None)  # Age alone does not establish a group count.
        else:
            fields[key] = {**field, 'value': value, 'derived': True, 'source': 'rule:age_not_count'}
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
    for m in total_mentions(text):
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
        disjoint = None if grouped else disjoint_people(text)
        if disjoint:
            fields['people'] = disjoint
            fields.pop('count_unknown', None)
            return
        household = derive_people(text)
        known_household = household and household.get('source') == 'rule:household_total'
        unknown = bool(re.search(r'\b(?:familias?|um monte de gente|muita gente|varias pessoas)\b', _plain(text)))
        if (grouped and grouped.get('minimum')) or (unknown and not grouped and not known_household):
            fields.pop('people', None)
            fields['count_unknown'] = dict(value=True, quote=text, source='rule:unknown_group')
        elif not grouped:
            from app.geo.incident import incident_text
            scoped = people_text(text)
            remote = bool(FIRST_PERSON.search(text) and not FIRST_PERSON.search(scoped))
            derived = None if remote else derive_people(text)
            if derived:
                fields['people'] = derived
                fields.pop('count_unknown', None)
            # An explicitly remote reporter contributes zero people. Count only
            # quantified relatives in the incident clause, retaining each quote.
            elif remote or re.search(r'\b(?:ligo|ligando|telefonando|repassando|estou em)\b', _plain(text)):
                members = list(PHRASE.finditer(scoped))
                if members and not unknown:
                    total, listed = 0, []
                    for member in members:
                        raw, noun = member.groups()
                        n = int(raw) if raw and raw.isdigit() else NUMBERS.get(_plain(raw)) if raw else None
                        if n is None and noun.endswith('s') and _plain(noun) != 'pais':
                            break
                        total += n if n is not None else 2 if _plain(noun) == 'pais' else 1
                        listed.append(text[member.start():member.end()].strip())
                    else:
                        fields['people'] = dict(value=total, quote=text[members[0].start():members[-1].end()],
                            derived=True, count_basis='derived', source='rule:remote_reporter_relations', listed=listed)


RESCUE_COMPLETE = re.compile(
    r'\b(?:ja sai(?:mos)?\b|(?:um |uma |o |a )?vizinh[oa][^.;!\n]{0,35}me levou de (?:caiaque|barco|lancha)|ja (?:foram|estao|estamos|fomos) (?:tod[oa]s? )?(?:resgatad[oa]s?|retirad[oa]s?|tirad[oa]s?|no abrigo)|'
    r'(?:consegui|conseguimos|conseguiram) sair|(?:um |uma |o |a )?vizinh[oa][^.;!\n]{0,45}me tirou)\b')
RESCUE_COMPLETE = re.compile(RESCUE_COMPLETE.pattern +
    r'|\bja\s+resgatad[oa]s?\b'
    r'|\b(?:estamos|estou|estao)\s+(?:ja\s+)?(?:em seguranca|a salvo|salv[oa]s?|segur[oa]s?)\b'
    r'|\bnao\s+(?:precisamos|preciso|precisa|precisam)\s+mais\s+(?:de\s+)?(?:resgate|ajuda|socorro|barco)\b'
    r'|\b(?:todos|todas|todo mundo)\s+(?:ja\s+)?(?:resgatad[oa]s?|retirad[oa]s?)\b'
    r'|\b(?:fui|foi|fomos|foram|estou|estamos|estao)\s+(?:ja\s+)?(?:tod[oa]s?\s+)?(?:resgatad[oa]s?|retirad[oa]s?)\b'
    r'|\b(?:estamos|estao)\s+(?:ja\s+)?(?:no abrigo|na casa de parentes)\b'
    r'|\bja\s+estavam\s+(?:no abrigo|na casa de parentes)\b'
    r'|\b(?:minha|meu|nossa|nosso)\s+(?:mae|pai|filh[oa]|irma|irmao|prim[oa]|ti[oa]|familia)\s+ja\s+saiu\b'
    r'|\blev(?:ou|aram)\s+(?:todo mundo|o pessoal|a familia)\s+(?:para o|pro|ao)\s+abrigo\b'
    r'|\bja\s+(?:(?:tinham|haviamos|haviam|estavam)\s+saido|sairam)\b'
    r'|\b(?:bombeiros|barco|equipe|voluntarios)\s+(?:ja\s+)?(?:nos\s+)?(?:buscou|buscaram|levou|levaram|retirou|retiraram)\b'
    r'|\bja\s+(?:nos\s+)?tiraram\b'
    r'|\b(?:pode[m]?\s+(?:tirar\s+da\s+lista|apagar(?:\s+(?:o\s+)?(?:pedido|post|publicacao))?)|'
    r'desconsider(?:ar|e|em)\s+(?:o|meu|nosso)\s+(?:pedido|post|publicacao))\b')
REMAINING = re.compile(
    r'\b(?:ainda|continua[m]?|segue[m]?)\s+(?:(?:esta[o]?|tem|ha|ficou|ficaram)\s+)?'
    r'[^.;!\n]{0,45}\b(?:pres[oa]s?|ilhad[oa]s?|no telhado|para tras|pra tras|precisa[m]? de (?:resgate|ajuda))\b'
    r'|\b(?:mas|porem)\b[^.;!\n]{0,55}\b(?:ficou|ficaram|resta|restam)\b[^.;!\n]{0,25}(?:la|no local|na casa|no telhado)\b')


def completed_rescue_quote(text):
    """Positive completed-rescue evidence, never a negation or a partial rescue."""
    from app.rescue_state import PARTIAL
    plain = _plain(text)
    if PARTIAL.search(plain) or REMAINING.search(plain):
        return None
    for match in RESCUE_COMPLETE.finditer(plain):
        if not re.search(r'\b(?:nao|nunca|not|se|quando|caso|sem|talvez)\s+(?:\w+\s+){0,5}$',
                         plain[max(0, match.start()-65):match.start()]):
            return text[match.start():match.end()]
    return None
