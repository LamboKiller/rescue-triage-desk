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
    values = re.findall(r'\b\d{1,5}\b|\b(?:'+'|'.join(WORDS)+r')\b', text)
    if values:
        return int(values[0]) if values[0].isdigit() else WORDS[values[0]]
    if key == 'children' and re.search(r'\b(?:bebe de colo|meu bebe|minha bebe)\b', text):
        return 1
    if key == 'elderly' and re.search(r'\b(?:minha vo|meu vo|minha avo|meu avo)\b', text):
        return 1
    if key == 'disabled' and re.search(r'\b(?:nao anda|nao consegue andar|cadeirante|acamad[oa])\b', text):
        return 1
    return None
