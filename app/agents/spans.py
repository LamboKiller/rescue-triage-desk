"""Validate model structure and evidence. Matching text alone never authorizes actions."""
import unicodedata
import re
from app.geo.streets import normalize

COUNTS = {'people', 'children', 'elderly', 'disabled', 'pets'}
TEXT = {'street', 'number', 'municipality', 'landmark', 'cross_street', 'risk_words'}
FIELDS = COUNTS | TEXT | {'already_rescued', 'conflicting_counts'}
NUMBER_WORDS = {0: ['zero'], 1: ['um', 'uma'], 2: ['dois', 'duas'], 3: ['tres'],
                4: ['quatro'], 5: ['cinco'], 6: ['seis'], 7: ['sete'], 8: ['oito'],
                9: ['nove'], 10: ['dez'], 11: ['onze'], 12: ['doze'], 13: ['treze'],
                14: ['quatorze', 'catorze'], 15: ['quinze'], 16: ['dezesseis'],
                17: ['dezessete'], 18: ['dezoito'], 19: ['dezenove'], 20: ['vinte']}


def folded(text):
    return ''.join(c for c in unicodedata.normalize('NFD', str(text).casefold())
                   if unicodedata.category(c) != 'Mn')


def validate(output, text):
    accepted, unsupported = {}, []
    fields = output.get('fields', {}) if isinstance(output, dict) else {}
    if not isinstance(fields, dict):
        return {}, [{'field': '*', 'reason': 'invalid_schema'}]
    for key, field in fields.items():
        reason = None
        if key not in FIELDS or not isinstance(field, dict):
            reason = 'invalid_schema'
        else:
            quote, value = field.get('quote'), field.get('value')
            if not isinstance(quote, str) or not quote.strip() or folded(quote) not in folded(text):
                reason = 'unsupported_quote'
            elif key in COUNTS and (type(value) is not int or not 0 <= value <= 10000):
                reason = 'invalid_count'
            elif key in TEXT and (not isinstance(value, str) or not value.strip() or len(value) > 500):
                reason = 'invalid_text'
            elif key in ('already_rescued', 'conflicting_counts') and type(value) is not bool:
                reason = 'invalid_boolean'
            elif key in COUNTS and not (str(value) in re.findall(r'\b\d+\b', quote)
                    or any(re.search(r'\b'+word+r'\b', folded(quote)) for word in NUMBER_WORDS.get(value, []))):
                reason = 'unsupported_count_value'
            elif key in ('street', 'cross_street', 'municipality') and normalize(value) not in normalize(quote):
                reason = 'unsupported_location_value'
            elif key == 'number' and not re.search(r'\b'+re.escape(value)+r'\b', quote, re.I):
                reason = 'unsupported_number_value'
            elif key in ('landmark', 'risk_words') and folded(value) not in folded(quote):
                reason = 'unsupported_text_value'
        if reason:
            unsupported.append({'field': key, 'reason': reason})
        else:
            accepted[key] = {'value': value, 'quote': quote}
    return accepted, unsupported
