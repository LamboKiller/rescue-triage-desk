"""Offline shelter-routing eval (12 author-written synthetic cases; no model, no network).

Checks recommendation correctness plus the two hard rules: a shelter reported/recorded FULL, or with FLOODED access while a
non-flooded alternative exists, is never recommended; unknown capacity is always labelled.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.shelters import router
from app.shelters.state import Catalogue, Shelters, Store


def run_case(item):
    cat = Catalogue.from_places([{k: v for k, v in s.items() if k != 'access'} for s in item['shelters']])
    S = Shelters(cat, Store())
    for e in item['events']: S.record(e)
    access = {(round(s['lat'], 5), round(s['lon'], 5)): s['access'] for s in item['shelters']}
    fn = lambda lat, lon, day: {'state': access[(round(lat, 5), round(lon, 5))], 'source': 'synthetic', 'reason_pt': 'camada sintética'}
    g = item['group']
    group = {'point': g['point'], 'people': g['people'], 'animals': g['animals'], 'case_ids': [item['id']],
             'medical': [{'medical_need': m, 'quote': m, 'hours_low': 1, 'hours_high': 6} for m in g['medical']]}
    return router.recommend(group, S.state(item['now']), item['now'][:10], fn), S.state(item['now']), access


def evaluate():
    items = [json.loads(l) for l in (ROOT / 'eval/shelter_set.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    correct = never_violations = unlabeled_unknown = flooded_when_alt = full_rec = 0;results = []
    for item in items:
        rec, states, access = run_case(item)
        ids = [r['shelter_id'] for r in rec['recommendations']];t = item['truth'];fails = []
        if (ids[:1] or [None])[0] not in t['top1']: fails.append('top1:' + str(ids[:1]))
        else: correct += 1
        bad = [i for i in ids if i in t['never']]
        if bad: fails.append('never:' + ','.join(bad));never_violations += len(bad)
        full = {s['shelter_id'] for s in states if s['full']}
        full_rec += len(full & set(ids))
        alt = any(a != 'flooded' for a in access.values())
        flooded_rec = [r['shelter_id'] for r in rec['recommendations'] if r['access']['state'] == 'flooded']
        if alt and flooded_rec: flooded_when_alt += len(flooded_rec);fails.append('flooded_with_alternative')
        if 'only_flooded' in t and rec['only_flooded_access'] != t['only_flooded']: fails.append('only_flooded_flag')
        for sid in t.get('must_label_unknown', []):
            row = next((r for r in rec['recommendations'] if r['shelter_id'] == sid), None)
            if not row or not any('Capacidade desconhecida' in c for c in row['confirm_pt']) or row['capacity']['known']:
                unlabeled_unknown += 1;fails.append('unknown_not_labelled')
        results.append({'id': item['id'], 'recommended': ids, 'failures': fails})
    n = len(items)
    return {'cases': n, 'synthetic': True, 'top1_correct': correct, 'top1_accuracy': correct / n, 'never_list_violations': never_violations,
            'full_recommended': full_rec, 'flooded_recommended_with_dry_alternative': flooded_when_alt, 'unknown_capacity_unlabelled': unlabeled_unknown,
            'results': results,
            'limits': 'Author-written synthetic shelters/events; measures the deterministic ranking and its hard rules, not real-world coverage of shelter data.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__);p.add_argument('--output', type=Path);a = p.parse_args()
    r = evaluate();text = json.dumps(r, ensure_ascii=False, indent=2)
    if a.output: a.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    raise SystemExit(bool(r['never_list_violations'] or r['full_recommended'] or r['flooded_recommended_with_dry_alternative'] or r['unknown_capacity_unlabelled'] or r['top1_correct'] != r['cases']))
