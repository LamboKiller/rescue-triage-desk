"""Offline evaluation of the cross-source contradiction detectors (no model calls, no network).

Metrics: item precision / recall against the hand-written expectations in eval/contradiction_set.jsonl (15 cases: 9 contradictions,
6 clean controls), decision changes (must be 0), quotes that are exact substrings of their source text, mean detection time.
Run: python eval/run_contradictions.py [--write]
"""
import copy
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contradictions import service as svc  # noqa: E402
from app.shelters.state import Catalogue, Shelters, Store  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def shelters_from(spec):
    if not spec:
        return None
    sh = Shelters(catalogue=Catalogue.from_places(spec['places']), store=Store())
    for e in spec['events']:
        sh.record(e)
    return sh


def evaluate():
    rows = [json.loads(l) for l in (ROOT / 'eval/contradiction_set.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    tp = fp = fn = changed = bad_quotes = no_ids = 0
    seconds = []
    detail = []
    for row in rows:
        case = copy.deepcopy(row['case'])
        before = {k: copy.deepcopy(case.get(k)) for k in ('status', 'priority')}
        before['decision'] = case['result']['decision']
        before['priority'] = case['result']['priority']
        started = time.perf_counter()
        items = svc.attach(case, key='k-' + row['id'], peers=row['peers'], shelters=shelters_from(row['shelter']), now=case['replay_time'])
        seconds.append(time.perf_counter() - started)
        got = sorted((i['kind'], i['strength']) for i in items)
        want = sorted((e['kind'], e['strength']) for e in row['expect'])
        tp += sum(1 for g in got if g in want)
        fp += sum(1 for g in got if g not in want)
        fn += sum(1 for w in want if w not in got)
        changed += (case['result']['decision'], case['result']['priority'], case['status']) != (before['decision'], before['priority'], row['case']['status'])
        for it in items:
            for s in it['sources']:
                if s['source'] == 'message' and s['quote'] not in case['text']:
                    bad_quotes += 1
            no_ids += not all(s.get('ref') and s.get('quote') for s in it['sources'])
        detail.append({'id': row['id'], 'ok': got == want, 'got': got, 'want': want})
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {'cases': len(rows), 'expected_items': sum(len(r['expect']) for r in rows), 'tp': tp, 'fp': fp, 'fn': fn,
            'precision': round(precision, 3), 'recall': round(recall, 3), 'decision_changes_without_human': int(changed),
            'quote_not_in_message': bad_quotes, 'sources_without_id_or_quote': int(no_ids),
            'mean_detect_ms': round(1000 * sum(seconds) / len(seconds), 3), 'max_detect_ms': round(1000 * max(seconds), 3),
            'model_calls': 0, 'failed_cases': [d for d in detail if not d['ok']]}


if __name__ == '__main__':
    result = evaluate()
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if '--write' in sys.argv:
        (ROOT / 'eval/contradiction_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
