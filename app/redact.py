"""Redact message prose without rewriting source IDs or structured data."""
import json
import re

PATTERNS = [
    (r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[EMAIL REDIGIDO]'),
    (r'(?<![\w.])\d{3}[. ]\d{3}[. ]\d{3}[- ]\d{2}(?!\w)|(?<![\w.])\d{11}(?![\w.])', '[CPF REDIGIDO]'),
    (r'(?<![\w.])(?:\+?55[ .-]*)?(?:\(\d{2}\)\s*|\d{2}[ .-]+)9?\d{4}[ .-]*\d{4}(?![\w.])', '[TELEFONE REDIGIDO]'),
    (r'(?<![\w.])\d{4,5}[- ]\d{4}(?![\w.])', '[TELEFONE REDIGIDO]'),
]

# These are prose/evidence fields, including model-written quotations. All other
# fields (IDs, names, coordinates, counts, timestamps) retain their source value.
TEXT_FIELDS = {'text', 'message', 'quote', 'why_quote', 'content', 'evidence',
               'reason', 'reason_pt', 'text_pt', 'brief_pt', 'question', 'questions',
               'decision_reason', 'warnings', 'warning', 'warning_pt', 'note', 'note_pt'}
ID_TOKEN = re.compile(r'\b(?:osm:)?(?:node|way|relation):\d+\b|'
                      r'\b(?:[\w.-]+_ids?|id|ids)\s*[:=]\s*[\"\']?[\w:./+\-]+', re.I)


def _prose(text):
    # Preserve explicit ID syntax even when embedded in a prose prompt/trace.
    parts, start = [], 0
    for match in ID_TOKEN.finditer(text):
        parts.extend((_personal(text[start:match.start()]), match.group()))
        start = match.end()
    parts.append(_personal(text[start:]))
    return ''.join(parts)


def _personal(text):
    text = re.sub(r'\b((?:telefone|fone|tel|celular|whatsapp|whats|contato)\s*[:=]?\s*)'
                  r'(?:\+?55\s*)?\d{10,11}\b', r'\1[TELEFONE REDIGIDO]', text, flags=re.I)
    for pattern, replacement in PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


def redact_data(value, field=None):
    """Traverse structured payloads; redact only their free-text leaves."""
    if isinstance(value, dict):
        return {k: redact_data(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_data(v, field) for v in value]
    return _prose(value) if isinstance(value, str) and field in TEXT_FIELDS else value


def redact(text):
    text = str(text)
    try:
        structured = json.loads(text) if text.lstrip().startswith(('{', '[')) else None
    except (ValueError, TypeError):
        structured = None
    if isinstance(structured, (dict, list)):
        return json.dumps(redact_data(structured), ensure_ascii=False)
    return _prose(text)
