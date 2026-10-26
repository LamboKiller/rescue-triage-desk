"""Volunteer intake eval (offline, author-written set). Run: python eval/run_volunteers.py [--out file.json]

Metrics: classification (offer / rescue / not_offer) correct, offers dispatchable while unverified (must be 0),
rescue requests swallowed as offers (must be 0), extracted quotes that are not literally in the text (must be 0).
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.engines.world_model.registry import Registry
from app.volunteers import detect
from app.volunteers.service import VolunteerService
from tools.scratch import scratch

SET = ROOT/'eval'/'volunteer_set.jsonl'
LABEL = {'offer': 'offer', 'rescue': 'rescue'}


def evaluate():
    rows = [json.loads(l) for l in SET.read_text(encoding='utf-8').splitlines() if l.strip()]
    results, swallowed, unverified_dispatchable, bad_quotes = [], 0, 0, 0
    with scratch() as tmp:
        registry = Registry(tmp/'events.jsonl')
        service = VolunteerService(tmp/'volunteers.jsonl', registry, None, lambda: '2024-05-08T12:00:00Z')
        for r in rows:
            got = LABEL.get(detect.classify(r['text'])['kind'], 'not_offer')
            ok = got == r['label']
            swallowed += r['label'] == 'rescue' and got == 'offer'
            if got == 'offer':
                v = service.submit(r['text'], source_ref=r['id'], synthetic=True)
                bad_quotes += sum(1 for f in v['fields'].values() if f['quote'] not in r['text'])
                unverified_dispatchable += bool(v['dispatchable'])
            results.append({'id': r['id'], 'label': r['label'], 'got': got, 'ok': ok})
        listing = service.list()['volunteers']
        inventory = [u for u in __import__('app.resources', fromlist=['read']).read(registry)]
        dup = sum(1 for v in listing if any(w['code'] == 'DUPLICATE_OFFER' for w in v['warnings']))
        implausible = sum(1 for v in listing if any(w['code'] == 'CAPACITY_IMPLAUSIBLE' for w in v['warnings']))
    passed = sum(x['ok'] for x in results)
    return {'cases': len(rows), 'passed': passed, 'failures': [x for x in results if not x['ok']],
            'offers_dispatchable_unverified': unverified_dispatchable, 'inventory_units_before_verification': len(inventory),
            'rescue_swallowed_as_offer': swallowed, 'quotes_not_in_text': bad_quotes,
            'duplicate_warnings': dup, 'implausible_capacity_warnings': implausible, 'results': results}


if __name__ == '__main__':
    ap = argparse.ArgumentParser();ap.add_argument('--out')
    report = evaluate()
    summary = {k: v for k, v in report.items() if k != 'results'}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args := ap.parse_args().out:
        Path(args).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.exit(0 if report['passed'] >= 14 and not (report['offers_dispatchable_unverified'] or report['rescue_swallowed_as_offer'] or report['quotes_not_in_text']) else 1)
