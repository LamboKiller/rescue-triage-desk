"""Redact real-looking identifiers before extraction, persistence or tracing."""
import re

PATTERNS = [
    (r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '[EMAIL REDIGIDO]'),
    (r'(?<!\d)\d{3}[. ]?\d{3}[. ]?\d{3}[- ]?\d{2}(?!\d)', '[CPF REDIGIDO]'),
    (r'(?<!\d)(?:\+?55[ .-]*)?\(?\d{2}\)?[ .-]*9?\d{4}[ .-]*\d{4}(?!\d)', '[TELEFONE REDIGIDO]'),
    (r'(?<!\d)\d{4,5}[- ]\d{4}(?!\d)', '[TELEFONE REDIGIDO]'),
]


def redact(text):
    for pattern, replacement in PATTERNS:
        text = re.sub(pattern, replacement, str(text), flags=re.I)
    return text
