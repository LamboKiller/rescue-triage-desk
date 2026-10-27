"""Raw input never opts out of redaction; trusted structured OSM IDs use a typed path."""
import hashlib
import json
import re

PATTERNS = [
    (r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[EMAIL REDIGIDO]'),
    (r'(?<![\w.])\d{3}[. ]\d{3}[. ]\d{3}[- ]\d{2}(?!\w)|(?<![\w.])\d{11}(?![\w.])', '[CPF REDIGIDO]'),
    (r'(?<![\w.])(?:\+?55[ .-]*)?(?:\(\d{2}\)\s*|\d{2}[ .-]+)9?\d{4}[ .-]*\d{4}(?![\w.])', '[TELEFONE REDIGIDO]'),
    (r'(?<![\w.])\d{4,5}[- ]\d{4}(?![\w.])', '[TELEFONE REDIGIDO]'),
]

TRUSTED_ID_FIELDS = {'osm_id', 'candidate_id', 'candidate_ids', 'result_id', 'result_ids',
                     'source_id', 'source_ids', 'fact_id', 'fact_ids', 'rule_ids'}
OSM_TOKEN = re.compile(r'\b(?:osm:)?(?:node|way|relation):\d+\b')


def _source_display(text):
    # Only a code-built candidate display can contain typed embedded OSM refs.
    parts, start = [], 0
    for match in OSM_TOKEN.finditer(text):
        parts.extend((_personal(text[start:match.start()]), match.group()))
        start = match.end()
    parts.append(_personal(text[start:]))
    return ''.join(parts)


def _personal(text):
    text = re.sub(r'\b((?:telefone|fone|tel|celular|whatsapp|whats|contato)\s*[:=]?\s*)'
                  r'(?:\+?55\s*)?\d{10,11}\b', r'\1[TELEFONE REDIGIDO]', text, flags=re.I)
    for pattern, replacement in PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.I)
    text = re.sub(r'(?<![\w.])(?:\+?55)?\d{10,11}(?![\w.])', '[TELEFONE REDIGIDO]', text)
    return text


def external_id(value):
    """Stable opaque identity for contact-like caller IDs, without persisting PII."""
    if _personal(value) == value and not re.search(r'\d{10,}', value): return value
    # Letter-only digest remains opaque and idempotent through repeated redaction.
    digest = hashlib.sha256(value.encode()).hexdigest()[:24].translate(str.maketrans('0123456789', 'ghijklmnop'))
    return 'external-'+digest


def redact_data(value, field=None):
    """Typed internal serialization. Callers must never pass raw citizen JSON here."""
    if isinstance(value, dict):
        return {k: redact_data(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_data(v, field) for v in value]
    if not isinstance(value, str): return value
    if field in TRUSTED_ID_FIELDS: return value
    if field == 'message_id': return external_id(value)
    if field == 'candidates': return _source_display(value)
    return _personal(value)


def redact_json(text):
    """Serialize a code-built JSON payload with typed source identifiers intact."""
    try: return json.dumps(redact_data(json.loads(text)), ensure_ascii=False)
    except (ValueError, TypeError): return redact(text)


def _raw_data(value):
    if isinstance(value, dict): return {_personal(k): _raw_data(v) for k,v in value.items()}
    if isinstance(value, list): return [_raw_data(v) for v in value]
    if type(value) is int and 10 <= len(str(abs(value))) <= 13: return _personal(str(value))
    return _personal(value) if isinstance(value, str) else value


def redact(text):
    text = str(text)
    try:
        structured = json.loads(text) if text.lstrip().startswith(('{', '[')) else None
    except (ValueError, TypeError):
        structured = None
    if isinstance(structured, (dict, list)):
        return json.dumps(_raw_data(structured), ensure_ascii=False)
    return _personal(text)
