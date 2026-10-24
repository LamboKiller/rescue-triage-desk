"""Synthetic robustness evaluation; no truth enters the pipeline."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pipeline import Pipeline
from app.engines.world_model.registry import Registry
from app.config import ROOT
from tools.scratch import scratch


def evaluate(offline=False):
    messages = [json.loads(l) for l in (ROOT/'eval/adversarial_set.jsonl').read_text(encoding='utf-8').splitlines()]
    truth = {t['message_id']: t for t in json.loads((ROOT/'eval/adversarial_truth.json').read_text(encoding='utf-8'))}
    start = time.monotonic(); cases = []; crashes = 0; failures = []
    with scratch() as folder:
        pipeline = Pipeline(Registry(Path(folder)/'events.jsonl'), sample=offline)
        for offset in range(0, len(messages), 15):
            batch = messages[offset:offset+15]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    cases.extend(pipeline.run({'replay_time':'2024-05-06T14:00:00-03:00', 'messages':batch})['cases'])
            except Exception as exc:
                crashes += len(batch)
                failures.append({'error':type(exc).__name__, 'messages':[m['message_id'] for m in batch]})
    decision = route = unsafe = field_checks = field_correct = 0
    for case in cases:
        expected = truth[case['message_id']]
        d = case['result']['decision']; r = case['route']['id']
        decision += d == expected['expected_decision']; route += r == expected['expected_route']
        unsafe += d == 'SEND_CANDIDATE' and (r in ('out_of_area','not_a_request_or_injection') or
                  expected['expected_route'] in ('out_of_area','not_a_request_or_injection'))
        for key,value in expected['expected_fields'].items():
            field_checks += 1
            field_correct += case['fields'].get(key,{}).get('value') == value
        if d != expected['expected_decision'] or r != expected['expected_route']:
            failures.append({'message_id':case['message_id'], 'decision':d, 'route':r})
    return {'mode':'offline' if offline else 'live', 'messages':len(messages),
            'decision_accuracy':decision/len(messages), 'route_accuracy':route/len(messages),
            'key_field_accuracy':field_correct/field_checks if field_checks else None,
            'crashes':crashes, 'unsafe_send':unsafe, 'seconds':round(time.monotonic()-start,3), 'failures':failures}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--offline',action='store_true'); args=parser.parse_args()
    result=evaluate(args.offline)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(bool(result['crashes'] or result['unsafe_send']))
