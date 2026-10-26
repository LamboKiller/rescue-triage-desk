"""Offline eval for the Reencontro matcher: precision of the top candidate, abstention on non-matches, 0 auto-confirms."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.reunite import matcher, records  # noqa: E402


def build(row):
    s = row['search']
    case = {'case_id': s['case_id'], 'text': s['text'], 'received_at': s['received_at'], 'location_confirmed': bool(s.get('location_confirmed')), 'lat': s.get('lat'), 'lon': s.get('lon')}
    missing = records.missing_from_case(case)
    found = []
    for f in row['found']:
        if f['kind'] == 'shelter':
            rec = records.found_from_shelter({'kind': 'delivered', 'value': 1, 'shelter_id': 'S' + f['id'], 'seq': 0, 'at': f['at'], 'quote': f['text']},
                                             {'lat': f.get('lat'), 'lon': f.get('lon'), 'municipality': f.get('municipality')})
        else:
            recs = records.found_from_feedback({'case_id': f.get('case_id', 'cx'), 'text': '', 'received_at': f['at'], 'location_confirmed': True, 'lat': f.get('lat'), 'lon': f.get('lon'),
                                                'feedback': [{'text': f['text'], 'received_at': f['at'], 'outcomes': []}]})
            rec = recs[0] if recs else None
        if rec:
            rec['label'] = f['id']
            found.append(rec)
    return missing, found


def run(path=ROOT / 'eval/reunite_set.jsonl'):
    rows = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    top_ok = top_n = abstain_ok = abstain_n = auto = 0
    detail = []
    for row in rows:
        missing, found = build(row)
        cands = matcher.match([missing] if missing else [], found)
        auto += sum(1 for c in cands if c['status'] != 'candidate' or not c['requires_human'])
        top = cands[0]['found']['label'] if cands else None
        if row['expect']:
            top_n += 1; top_ok += top == row['expect']
        else:
            abstain_n += 1; abstain_ok += top is None
        detail.append((row['id'], row['expect'], top))
    return {'cases': len(rows), 'top1_precision': f'{top_ok}/{top_n}', 'abstain_correct': f'{abstain_ok}/{abstain_n}', 'auto_confirms': auto, 'detail': detail}


if __name__ == '__main__':
    out = run()
    print(json.dumps({k: v for k, v in out.items() if k != 'detail'}, ensure_ascii=False))
    for d in out['detail']:
        if d[1] != d[2]:
            print('MISS', d)
    sys.exit(0 if out['auto_confirms'] == 0 and all(expected == got for _, expected, got in out['detail']) else 1)
