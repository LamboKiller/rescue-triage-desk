"""Conservative counts derived from quoted Portuguese phrases, never model totals."""
import re
import unicodedata

NUMBER_WORDS = {0: ['zero'], 1: ['um', 'uma'], 2: ['dois', 'duas'], 3: ['tres'],
                4: ['quatro'], 5: ['cinco'], 6: ['seis'], 7: ['sete'], 8: ['oito'],
                9: ['nove'], 10: ['dez'], 11: ['onze'], 12: ['doze', 'duzia'],
                13: ['treze'], 14: ['quatorze', 'catorze'], 15: ['quinze'],
                16: ['dezesseis'], 17: ['dezessete'], 18: ['dezoito'],
                19: ['dezenove'], 20: ['vinte']}
WORDS = {w: n for n, words in NUMBER_WORDS.items() for w in words}
TENS = {'trinta': 30, 'quarenta': 40, 'cinquenta': 50, 'sessenta': 60, 'setenta': 70,
        'oitenta': 80, 'noventa': 90, 'cem': 100}
UNIT_WORDS = {w: n for n, ws in NUMBER_WORDS.items() if 1 <= n <= 9 for w in ws}
_ALL = '|'.join(sorted(list(WORDS) + list(TENS), key=len, reverse=True))
_NUM = r'(?:\d{1,5}(?:[.,]\d+)?|(?:' + _ALL + r')\b)'
_PEOPLE = r'(?:pessoas?|criancas?|filh[oa]s?|idos[oa]s?|adultos?|moradores|netos?|bebes?|vizinhos?|familiares|feridos?|pets?|animais|caes|gatos)'
# Numbers that describe something other than a head-count. They are blanked BEFORE counts are read, so a
# remaining number is one the writer attached to people. Ambiguous quotes stay unknown, never guessed.
_NOT_COUNT = [
    r'\b(?:telefone|tel|fone|celular|whats(?:app)?|zap|contato)\b[^a-z]{0,4}[\d\s().+-]{6,}',
    r'\+?\d{2}[\s.-]?\(?\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}\b', r'\b(?:\d{2}\s+)?\d{4,5}[\s.-]\d{4}\b', r'\b\d{2}\s\d{4,5}\b', r'\b\d{6,}\b',
    r'\b\d{1,2}\s*(?:h|hs|hrs|horas?)\b(?:\s*\d{1,2}\b)?', r'\b\d{1,2}:\d{2}\b', r'\b(?:as|ate as|desde as|por volta das)\s+\d{1,2}\b',
    r'\b' + _NUM + r'(?:\s*(?:,|e)\s*' + _NUM + r')*\s*(?:anos?|aninhos?|meses|mes|semanas?|dias?|min|minutos?|segundos?|a)\b',
    r'\b' + _NUM + r'\s*(?:cm|centimetros?|mm|m|metros?|mts?|km|kg|quilos?|graus?|°|%|reais)(?![a-z])',
    r'\br\$\s*\d+', r'\b(?:' + _NUM + r')\s*(?:o|º|°)?\s*andar\b', r'\bandar\s*(?:' + _NUM + r')\b',
    r'\b(?:numero|num|n|no|nº|n°|apto?|apartamento|casa|lote|bloco|sala|km|quadra|unidade|ap)\.?\s*[:#]?\s*\d+\b',
    r'\b(?:rua|avenida|av|travessa|estrada|rodovia|br|rs)\b[^,;]{0,40}?[,\s]\s*\d+\b',
    r'\bidade\s+(?:de\s+)?' + _NUM + r'\b',
    # "<relative> de N" with no people noun after it is an age ("vo de 75", "filho de 8")
    r'\b(?:mae|pai|avo|vo|vovo|filh[oa]|bebe|neto|neta|crianca|menino|menina|idos[oa]|senhora?|irma[o]?|tio|tia|esposa|marido)\s+de\s+' + _NUM + r'\b(?!\s+' + _PEOPLE + r')',
    r'\b(?:tem|tinha|completou|fez)\s+' + _NUM + r'\b(?!\s+' + _PEOPLE + r')(?=\s*(?:$|[,.;]|e\s|mas|e\s))' ,
]
_NOUNS = {'people': r'(?:pessoas?|moradores|familiares)', 'children': r'(?:criancas?|filh[oa]s?|bebes?|netos?|netas?|menin[oa]s?)',
          'elderly': r'(?:idos[oa]s?|avos?|vovos?)', 'disabled': r'(?:cadeirantes?|acamad[oa]s?|deficientes)',
          'pets': r'(?:pets?|animais|caes|gatos|cachorros?)'}
_PERSON = {'children': r'filh[oa]|menin[oa]|crianca|bebe|neto|neta|entead[oa]',
           'elderly': r'avo|vo|vovo|idos[oa]|mae|pai|senhora?|dona|tio|tia'}
_NOT_COUNT_RE = [re.compile(x) for x in _NOT_COUNT]


def _value(token):
    return int(token) if token.isdigit() else WORDS.get(token, TENS.get(token))


def _numbers(text):
    """Integers in reading order; tens + unit ("vinte e cinco") form one number. Decimals are not counts."""
    out = []
    last_end = -1
    for m in re.finditer(r'\b\d{1,5}(?:[.,]\d+)?\b|\b(?:' + _ALL + r')\b', text):
        t = m[0]
        if re.fullmatch(r'\d+[.,]\d+', t):
            continue
        v = _value(t)
        if v is None:
            continue
        if out and t in UNIT_WORDS and 20 <= out[-1] < 100 and out[-1] % 10 == 0 \
                and re.fullmatch(r'\s+e\s+', text[last_end:m.start()]):
            out[-1] += v
        else:
            out.append(v)
        last_end = m.end()
    return out


def neutralize(text):
    """Blank non-count numbers (ages, times, addresses, phones, depth, floors, money)."""
    for rx in _NOT_COUNT_RE:
        text = rx.sub(' ', text)
    return text


def folded(text):
    return ''.join(c for c in unicodedata.normalize('NFD', str(text).casefold())
                   if unicodedata.category(c) != 'Mn')


def count(quote, key='people'):
    text = folded(quote).strip().rstrip('.!;')
    # Corrections supersede the earlier number only when explicitly marked.
    text = re.split(r'\b(?:na verdade|corrigindo|corrigindo aqui|corrijo)\b', text)[-1]
    if re.match(r'^(?:nao (?:tem|ha|temos)|sem|nenhum[ae]?)\b', text):
        return 0
    if re.search(r'\bmeia duzia\b', text):
        return 6
    if re.search(r'\b(?:uma\s+)?duzia\b', text):
        return 12
    # A complete relation list can be summed; categories elsewhere may overlap.
    if key == 'people' and re.match(r'^eu\b', text):
        parts = re.split(r'\s*,\s*|\s+e\s+', text)
        total = 0
        for part in parts:
            if part == 'eu':
                total += 1
            elif re.fullmatch(r'(?:minha|meu) (?:mae|pai|avo|irma|irmao|esposa|marido|tia|tio)', part):
                total += 1
            else:
                m = re.fullmatch(r'(?:meus|minhas) (\d+|dois|duas|tres|quatro) (?:filhos|filhas|netos|netas)', part)
                if not m:
                    return None
                total += int(m[1]) if m[1].isdigit() else WORDS[m[1]]
        return total
    original, text = text, neutralize(text)
    # Prefer the number written next to a head-count noun; otherwise the first remaining one.
    near = re.search(r'(' + _NUM + r'(?:\s+e\s+(?:' + '|'.join(UNIT_WORDS) + r'))?)\s+(?:\w+\s+)?' + _NOUNS.get(key, r'(?!)') + r'\b', text)
    if near:
        nums = _numbers(near[1])
        if nums:
            return nums[0]
    values = _numbers(text)
    if values:
        return values[0]
    if key == 'children' and re.search(r'\b(?:bebe de colo|meu bebe|minha bebe)\b', original):
        return 1
    if key == 'elderly' and re.search(r'\b(?:minha vo|meu vo|minha avo|meu avo)\b', original):
        return 1
    # One singular person noun carrying an age ("filha de 8 anos", "bebe de 8 meses", "mae de 75 anos") is one person
    # of that group; the age itself is never the count. Plurals and bare ages stay unknown.
    aged = re.search(r'\b(?:' + '|'.join([_PERSON[key]]) + r')\s+(?:de|com|tem)\s+' + _NUM + r'\b', original) if key in _PERSON else None
    if aged:
        return 1
    if key == 'disabled' and re.search(r'\b(?:nao anda|nao consegue andar|cadeirante|acamad[oa])\b', original):
        return 1
    return None
