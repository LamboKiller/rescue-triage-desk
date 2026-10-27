"""Schema + data-existence checks for dev2 (shared by tests and the CLI)."""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.geo.streets import normalize  # noqa: E402
from eval.dev2.spec import DECISIONS, BASES, ROUTES  # noqa: E402

MESSAGES = Path(__file__).with_name('messages.jsonl')
REQUIRED = ('id', 'text', 'replay_date', 'expected_decision', 'expected_people', 'count_basis', 'expected_route',
            'expected_precision', 'key_fields', 'class', 'rationale', 'ambiguous', 'bucket', 'in_area')


def load():
    return [json.loads(l) for l in MESSAGES.read_text(encoding='utf-8').splitlines() if l.strip()]


def schema_errors(rows):
    errors, seen = [], set()
    for r in rows:
        miss = [k for k in REQUIRED if k not in r]
        if miss:
            errors.append((r.get('id'), 'missing ' + ','.join(miss))); continue
        if r['id'] in seen: errors.append((r['id'], 'duplicate id'))
        seen.add(r['id'])
        if r['expected_decision'] not in DECISIONS: errors.append((r['id'], 'decision'))
        if r['count_basis'] not in BASES: errors.append((r['id'], 'basis'))
        if r['expected_route'] not in ROUTES: errors.append((r['id'], 'route'))
        if r['expected_people'] is not None and not (isinstance(r['expected_people'], int) and r['expected_people'] >= 0):
            errors.append((r['id'], 'people'))
        if r['count_basis'] in ('unknown', 'none') and r['expected_people'] is not None and r['expected_decision'] != 'REVIEW':
            errors.append((r['id'], 'people with unknown basis'))
        if not str(r['text']).strip() or not r['rationale']: errors.append((r['id'], 'empty text/rationale'))
        if r['bucket'] not in ('targeted', 'regression', 'adversarial'): errors.append((r['id'], 'bucket'))
        if r['expected_decision'] == 'SEND_APPROX' and r['expected_precision'] != 'approximate': errors.append((r['id'], 'precision'))
    return errors


def data_errors(rows):
    with open(ROOT / 'data/streets_flood.csv', encoding='utf-8') as fh:
        streets = {(normalize(r['display_name']), r['municipality']) for r in csv.DictReader(fh)}
    places, names = set(), set()
    with open(ROOT / 'data/landmarks.csv', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            names.add((r['name'], r['municipality']))
            if r['category'].startswith('place:'): places.add((r['name'], r['municipality']))
    errors = []
    for r in rows:
        k, mun = r['key_fields'], r['key_fields'].get('municipality')
        if not r.get('in_area', True): continue
        if k.get('street') and mun and (normalize(k['street']), mun) not in streets:
            errors.append((r['id'], 'street not in data: %s / %s' % (k['street'], mun)))
        if k.get('bairro') and mun and (k['bairro'], mun) not in places:
            errors.append((r['id'], 'bairro not in data: %s / %s' % (k['bairro'], mun)))
        if k.get('landmark') and mun and (k['landmark'], mun) not in names:
            errors.append((r['id'], 'landmark not in data: %s / %s' % (k['landmark'], mun)))
    return errors


if __name__ == '__main__':
    rows = load()
    for e in schema_errors(rows) + data_errors(rows): print(e)
