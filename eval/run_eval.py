"""Synthetic held-out evaluation. Provider results are unavailable offline."""
import argparse
import json
import math
import contextlib
import io
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
          'municipality', 'landmark', 'cross_street', 'risk_words', 'already_rescued', 'conflicting_counts')


def score(cases, truth, seconds):
    truth_by_id = {t['message_id']: t for t in truth}
    counts = {k: {'tp': 0, 'fp': 0, 'fn': 0} for k in FIELDS}
    correct, unsupported, predicted, calls = 0, 0, 0, 0
    families = {}
    critic = dict(objections=0, messages_with_objections=0, revisions=0,
                  revisions_changed_field=0, fields_changed=0, changes_correct=0,
                  changes_wrong=0, changes_neutral=0, failed=0)
    landmark_correct = landmark_n = 0
    latencies = []
    failure_messages = failure_events = 0
    for case in cases:
        t = truth_by_id[case['message_id']]
        correct += case['result']['decision'] == t['expected_decision']
        unsupported += len(case['unsupported'])
        predicted += case.get('proposed_field_count', len(case['fields'])+len(case['unsupported']))
        calls += len(case['calls'])
        family = str(t.get('template_family', 'challenge'))
        latencies.append(case.get('seconds', 0))
        errors = case.get('errors', [])
        failure_messages += bool(errors or not case.get('complete', True))
        failure_events += len(errors)
        agents = case.get('agents', {})
        review = agents.get('critic')
        critic['failed'] += review == 'failed'
        objections = review.get('objections', []) if isinstance(review, dict) else []
        critic['objections'] += len(objections)
        critic['messages_with_objections'] += bool(objections)
        if isinstance(agents.get('revision'), dict):
            critic['revisions'] += 1
            before = case.get('initial_fields', {})
            changed = [k for k in set(before) | set(case['fields'])
                       if before.get(k, {}).get('value') != case['fields'].get(k, {}).get('value')]
            critic['revisions_changed_field'] += bool(changed)
            critic['fields_changed'] += len(changed)
            for key in changed:
                expected = t['expected_fields'].get(key)
                was = equal_value(before.get(key, {}).get('value'), expected)
                now = equal_value(case['fields'].get(key, {}).get('value'), expected)
                label = 'correct' if now and not was else 'wrong' if was and not now else 'neutral'
                critic['changes_'+label] += 1
        target = t.get('expected_landmark')
        if target is not None:
            landmark_n += 1
            lm = case.get('landmark_check') or {}
            hit = lm.get('status', 'unresolved') == target['status']
            # Yussef 24/10: "ambiguous" (candidates listed, callback) is as safe as "unresolved" when the decision matches.
            if (target['status'] == 'unresolved' and lm.get('status') == 'ambiguous'
                    and case['result']['decision'] == t['expected_decision']):
                hit = True
            if target['status'] == 'resolved':
                matched = lm.get('matched') or {}
                if target.get('osm_id'):
                    members = matched.get('osm_members', []) + [matched]
                    hit = hit and any(str(r.get('osm_id')) == str(target['osm_id']) and
                                      (not target.get('osm_type') or r.get('osm_type') == target['osm_type'])
                                      for r in members)
                elif target.get('name'):
                    names = [matched.get('name', '')] + matched.get('alt_names', '').split('|')
                    hit = hit and any(equal_value(name, target['name']) for name in names)
            landmark_correct += hit
        else:
            # Decision proxy is explicitly labelled and never treated as place identity.
            landmark_correct += case['result']['decision'] == t['expected_decision']
        f = families.setdefault(family, {'correct': 0, 'n': 0})
        f['n'] += 1
        f['correct'] += case['result']['decision'] == t['expected_decision']
        for key in FIELDS:
            actual = case['fields'].get(key, {}).get('value')
            expected = t['expected_fields'].get(key)
            equal = equal_value(actual, expected)
            counts[key]['tp'] += actual is not None and expected is not None and equal
            counts[key]['fp'] += actual is not None and (expected is None or not equal)
            counts[key]['fn'] += expected is not None and (actual is None or not equal)
    for c in counts.values():
        p = c['tp']/(c['tp']+c['fp']) if c['tp']+c['fp'] else 0
        r = c['tp']/(c['tp']+c['fn']) if c['tp']+c['fn'] else 0
        c.update(precision=round(p, 4), recall=round(r, 4), f1=round(2*p*r/(p+r), 4) if p+r else 0)
    n = len(cases)
    return {'n': n, 'fields': counts, 'decision_accuracy': round(correct/n, 4) if n else 0,
            'unsupported_claim_rate': round(unsupported/predicted, 4) if predicted else 0,
            'unsupported_definition': 'schema/span/value-rejected fields / all proposals across intake and revision; not semantic truth',
            'mean_seconds_per_message': round(statistics.mean(latencies), 4) if n else 0,
            'p90_seconds_per_message': round(sorted(latencies)[max(0, math.ceil(.9*n)-1)], 4) if n else 0,
            'amortized_wall_seconds_per_message': round(seconds/n, 4) if n else 0,
            'landmark_resolution_accuracy': round(landmark_correct/n, 4) if n else 0,
            'landmark_identity_messages': landmark_n,
            'landmark_decision_proxy_messages': n-landmark_n,
            'landmark_definition': 'Identity/status on labelled landmarks; expected-decision proxy otherwise',
            'critic': critic, 'failures': failure_messages, 'failure_events': failure_events,
            'mean_calls_per_message': round(calls/n, 4) if n and all(c.get('call_count_complete', True) for c in cases) else None,
            'families': families}



def equal_value(actual, expected):
    if isinstance(actual, str) and isinstance(expected, str):
        return normalize(actual) == normalize(expected)
    return actual == expected


def datasets(seeds, n, rows):
    messages, labels = [], []
    for seed in seeds:
        generated, truth = generate(seed, n, rows)
        messages.extend(generated)
        labels.extend(truth)
    challenge = [json.loads(line) for line in (ROOT/'eval/challenge_set.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    truth = json.loads((ROOT/'eval/challenge_truth.json').read_text(encoding='utf-8'))
    if {m['message_id'] for m in challenge} != {t['message_id'] for t in truth}:
        raise ValueError('Challenge messages and labels differ')
    return {'generated': (messages, labels), 'challenge': (challenge, truth)}


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
    if 7 in seeds or len(set(seeds)) != len(seeds):
        parser.error('Use distinct held-out seeds; seed 7 is tuning data')
    results = {'mode':'offline' if args.offline else 'live', 'tuning_seeds':[7], 'test_seeds':seeds,
               'limitations':'Author-written synthetic truth; challenge texts reviewed by one native Porto Alegre speaker '
                              'on 24/10/2026 and labels re-derived. Real-message accuracy unmeasured. '
                              'No evidence of critic benefit without live ablations. Landmark scores use a decision proxy '
                              'when identity/status labels are absent. Curated aliases and airport terminal dispatch use the local snapshot.',
               'sets':{}}
    for name, (messages, truth) in datasets(seeds, args.n, LocalSource().streets()).items():
        methods = results['sets'][name] = {}
        for method in ('baseline', 'intake', 'full'):
            if args.offline and method != 'baseline':
                methods[method] = {'status':'unavailable (offline)'}
                continue
            cases, elapsed = [], 0
            for offset in range(0, len(messages), 15):
                registry = Registry(ROOT/'runtime'/('eval_'+uuid.uuid4().hex+'.jsonl'))
                pipeline = Pipeline(registry, sample=(method == 'baseline'))
                start = time.monotonic()
                with contextlib.redirect_stdout(io.StringIO()):
                    output = pipeline.run({'replay_time':'2024-05-06T14:00:00-03:00',
                                           'messages':messages[offset:offset+15]}, ablation=method)
                elapsed += time.monotonic()-start
                cases.extend(output['cases'])
                print(name+' / '+method+': '+str(len(cases))+'/'+str(len(messages))+' done ('+str(round(elapsed))+' s so far)', flush=True)
            methods[method] = dict(score(cases, truth, elapsed), status='measured',
                                   partial_messages=sum(not c['complete'] for c in cases))
            print(name+' / '+method+': '+str(len(cases))+' messages measured')
    (ROOT/'eval/results.json').write_text(json.dumps(results, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    lines = ['# V1.3 synthetic evaluation', '', results['limitations'], '',
             'Generated held-out seeds: '+str(seeds)+'. Challenge texts are unchanged.', '',
             'Mean and nearest-rank p90 use per-message processing time; amortized batch wall time is separate.',
             'Unsupported rate is rejected schema/span/value proposals divided by all proposals, not semantic truth.',
             'Critic change outcomes count changed fields against truth, including removed fields.', '']
    for name, methods in results['sets'].items():
        lines.extend(['## '+name, '', '| Method | Decision | Landmark* | Unsupported | Calls/msg | Mean s | p90 s | Failures |',
                      '|---|---:|---:|---:|---:|---:|---:|---:|'])
        for method, result in methods.items():
            if result['status'] != 'measured':
                lines.append('| '+method+' | unavailable (offline) | - | - | - | - | - | - |')
                continue
            keys = ('decision_accuracy','landmark_resolution_accuracy','unsupported_claim_rate',
                    'mean_calls_per_message','mean_seconds_per_message','p90_seconds_per_message','failures')
            lines.append('| '+method+' | '+' | '.join(str(result[k]) for k in keys)+' |')
        for method, result in methods.items():
            if result['status'] != 'measured':
                continue
            lines.extend(['', '### '+method+' fields', '', '| Field | P | R | F1 |', '|---|---:|---:|---:|'])
            for key, values in result['fields'].items():
                lines.append('| '+key+' | '+' | '.join(str(values[k]) for k in ('precision','recall','f1'))+' |')
            lines.extend(['', 'Critic: '+json.dumps(result['critic'], sort_keys=True)+'.',
                          'Landmark identity/status labels: '+str(result['landmark_identity_messages'])+
                          '; expected-decision proxies: '+str(result['landmark_decision_proxy_messages'])+'.', ''])
    lines.extend(['*Landmark combines labelled identity/status accuracy with decision proxies, explicitly counted above.',
                  'Detailed family metrics, failures, wall time and critic counts are in results.json.', ''])
    (ROOT/'eval/results.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Evaluation written: eval/results.md and eval/results.json')


if __name__ == '__main__':
    main()
