"""Citizen-reply simulator for demo and eval ONLY. Replies come from a hidden truth record, never from the questions' wording.

Every output is labelled: `simulated: true`, text prefixed `[SIMULADO]`. It refuses any case without a truth record
(real cases never have one) and when CALLBACK_SIMULATOR=0.
"""
import json
from pathlib import Path
from app.config import ROOT, setting
from app.callback.items import RANK

PREFIX = '[SIMULADO] '
DEFAULT_SET = ROOT/'eval'/'callback_set.jsonl'


def load_records(path=DEFAULT_SET):
    path = Path(path)
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec['message_id']] = rec
    return out


def enabled():
    return setting('CALLBACK_SIMULATOR', '1') != '0'


def available(case, records=None):
    records = load_records() if records is None else records
    return enabled() and bool(case.get('synthetic')) and record_id(case) in records


def record_id(case):
    # Re-triage has its own message id; truth belongs to the original synthetic delivery.
    return (case.get('messages') or [{}])[0].get('message_id') or case.get('message_id')


def reply_for(case, asked_ids, records=None):
    """Return {'text', 'simulated': True, 'truth_record'} answering only the asked, still-open item ids."""
    records = load_records() if records is None else records
    if not available(case, records):
        raise ValueError('Simulação indisponível: este caso não tem registro de verdade sintético.')
    rec = records[record_id(case)]
    phrases = rec.get('citizen_replies') or {}
    parts = [phrases[i] for i in sorted(set(asked_ids), key=lambda x: RANK.index(x) if x in RANK else 99) if phrases.get(i)]
    text = ' '.join(parts) or rec.get('unknown_reply') or 'Não sei dizer mais do que já informei.'
    return {'text': text, 'simulated': True, 'truth_record': rec['message_id']}
