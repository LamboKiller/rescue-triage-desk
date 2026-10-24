"""Synthetic held-out evaluation. Provider results are unavailable offline."""
import argparse
import json
import statistics
import sys
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env
from app.data.source import LocalSource
from app.engines.world_model.registry import Registry
from app.geo.streets import normalize
from app.pipeline import Pipeline
from tools.generate_messages import generate

FIELDS = ('people', 'children', 'elderly', 'disabled', 'pets', 'street', 'number',
          'municipality', 'landmark', 'risk_words', 'already_rescued', 'conflicting_counts')


def score(cases, truth, seconds):
    truth_by_id = {t['message_id']: t for t in truth}
    counts = {k: {'tp': 0, 'fp': 0, 'fn': 0} for k in FIELDS}
    correct, unsupported, predicted, calls = 0, 0, 0, 0
    families = {}
    for case in cases:
        t = truth_by_id[case['message_id']]
        correct += case['result']['decision'] == t['expected_decision']
        unsupported += len(case['unsupported'])
        predicted += case.get('proposed_field_count', len(case['fields'])+len(case['unsupported']))
        calls += len(case['calls'])
        family = str(t['template_family'])
        f = families.setdefault(family, {'correct': 0, 'n': 0})
        f['n'] += 1
        f['correct'] += case['result']['decision'] == t['expected_decision']
        for key in FIELDS:
            actual = case['fields'].get(key, {}).get('value')
            expected = t['expected_fields'].get(key)
            equal = actual == expected
            if isinstance(actual, str) and isinstance(expected, str):
                equal = normalize(actual) == normalize(expected)
            counts[key]['tp'] += actual is not None and expected is not None and equal
            counts[key]['fp'] += actual is not None and (expected is None or not equal)
            counts[key]['fn'] += expected is not None and (actual is None or not equal)
    for c in counts.values():
        p = c['tp']/(c['tp']+c['fp']) if c['tp']+c['fp'] else 0
        r = c['tp']/(c['tp']+c['fn']) if c['tp']+c['fn'] else 0
        c.update(precision=round(p, 4), recall=round(r, 4), f1=round(2*p*r/(p+r), 4) if p+r else 0)
    n = len(cases)
    return {'n': n, 'fields': counts, 'decision_accuracy': round(correct/n, 4),
            'unsupported_claim_rate': round(unsupported/predicted, 4) if predicted else 0,
            'unsupported_definition': 'schema/span/value-rejected fields / all proposals across intake and revision; not semantic truth',
            'mean_seconds_per_message': round(seconds/n, 4),
            'mean_calls_per_message': round(calls/n, 4) if all(c.get('call_count_complete', True) for c in cases) else None,
            'families': families}


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--seeds', default='101,202')
    parser.add_argument('--n', type=int, default=15)
    args = parser.parse_args()
    if not 1 <= args.n <= 15:
        parser.error('--n must be 1..15')
    seeds = [int(s) for s in args.seeds.split(',')]
    if 7 in seeds:
        parser.error('Seed 7 is tuning data; use held-out seeds')
    rows = LocalSource().streets()
    results = {'mode': 'offline' if args.offline else 'live', 'tuning_seeds': [7], 'test_seeds': seeds,
               'held_out_template_families': [8, 9, 10, 11, 12, 13, 14],
               'limitations': 'Synthetic text-supported truth only; real-message accuracy UNMEASURED. '
                              'No claim that the critic improves accuracy without live ablations. '
                              'Seeds vary counts, streets and vulnerabilities; request-rate assumptions are not validated.',
               'ablations': {}}
    for ablation in ('baseline', 'intake', 'full'):
        if args.offline and ablation != 'baseline':
            results['ablations'][ablation] = {'status': 'unavailable (offline)'}
            continue
        all_cases, all_truth, elapsed = [], [], 0
        for seed in seeds:
            messages, truth = generate(seed, args.n, rows)
            reg = Registry(ROOT/'runtime'/('eval_'+uuid.uuid4().hex+'.jsonl'))
            pipeline = Pipeline(reg, sample=(ablation == 'baseline'))
            start = time.monotonic()
            output = pipeline.run({'replay_time': '2024-05-06T14:00:00-03:00', 'messages': messages}, ablation=ablation)
            elapsed += time.monotonic()-start
            all_cases.extend(output['cases'])
            all_truth.extend(truth)
        result = score(all_cases, all_truth, elapsed)
        result['status'] = 'measured'
        result['partial_messages'] = sum(not c['complete'] for c in all_cases)
        results['ablations'][ablation] = result
    output = ROOT/'eval'
    (output/'results.json').write_text(json.dumps(results, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    lines = ['# V1 synthetic evaluation', '', results['limitations'], '',
             f'Tuning seed: 7 (families 0–7). Held-out seeds: {seeds}; all 15 families, including held-out families 8–14.', '',
             '| Method | Decision accuracy | Unsupported rate | Mean s/message | Calls/message |',
             '|---|---:|---:|---:|---:|']
    for method, result in results['ablations'].items():
        if result['status'] != 'measured':
            lines.append(f'| {method} | unavailable (offline) | — | — | — |')
        else:
            lines.append(f'| {method} | {result["decision_accuracy"]} | {result["unsupported_claim_rate"]} | {result["mean_seconds_per_message"]} | {result["mean_calls_per_message"]} |')
    base = results['ablations']['baseline']
    lines.extend(['', '## Regex baseline fields', '', '| Field | Precision | Recall | F1 |', '|---|---:|---:|---:|'])
    for key, values in base['fields'].items():
        lines.append(f'| {key} | {values["precision"]} | {values["recall"]} | {values["f1"]} |')
    lines.extend(['', 'Unsupported rate counts span/schema/value rejections; semantic errors are reflected in field metrics.',
                  'The offline baseline emits only literal spans, so a zero rejection rate is expected and does not imply correctness.',
                  'Wall time/message is amortized run time, including deterministic tools and registry; provider retries are in traces.',
                  'Detailed counts and per-template decision accuracy are in results.json.', ''])
    (output/'results.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Evaluation written: eval/results.md and eval/results.json')
    print('baseline decision accuracy:', base['decision_accuracy'])


if __name__ == '__main__':
    main()
