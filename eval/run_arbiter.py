"""15 synthetic conflicts: code policy + scripted validator checks, or --live.

Offline accuracy measures rules and the validation boundary, not Nemotron quality.
--realdev-skips measures eligibility on unmodified realdev messages, no truth read.
"""
import argparse
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agents import arbiter


class Scripted:
    def __init__(self, output):
        self.output = output

    def call(self, role, system, payload, deadline):
        return self.output, dict(role=role, receipt='SYNTHETIC-OFFLINE', model='scripted-validator-check')


def evaluate(live=False):
    rows = [json.loads(line) for line in (ROOT/'eval/arbiter_set.jsonl').read_text(encoding='utf-8').splitlines() if line]
    client = None
    if live:
        from app.config import load_env
        from app.llm.nightshift import Nightshift
        load_env()
        client = Nightshift(ROOT/'logs/arbiter_eval.jsonl')
    results = []
    for row in rows:
        case = dict(result=dict(decision=row['initial_decision']))
        conflict = copy.deepcopy(row['conflict'])
        event = arbiter.apply_verdict(case, arbiter.resolve(conflict,
            client if live else Scripted(row.get('response', {'choice':'ESCALATE'})), time.monotonic()+6))
        results.append(dict(id=row['id'], correct=event['verdict']==row['expected'],
                            verdict=event['verdict'], method=event['method'],
                            unsafe_send=case['result']['decision']=='SEND_CANDIDATE' and row['blocked']))
    total = len(results)
    return dict(mode='live' if live else 'offline_rules_and_scripted_validation', synthetic=True, cases=total,
                correct=sum(r['correct'] for r in results), accuracy=sum(r['correct'] for r in results)/total,
                escalations=sum(r['verdict']=='ESCALATE' for r in results),
                escalation_rate=sum(r['verdict']=='ESCALATE' for r in results)/total,
                unsafe_sends=sum(r['unsafe_send'] for r in results), results=results)


def measure_skips(directory):
    """Offline eligibility proxy: full pipeline, message data only, no labels."""
    import importlib.util
    runner = ROOT.parent/'open-agent-hackathon-2026/tools/run_holdout.py'
    spec = importlib.util.spec_from_file_location('a1l_holdout', runner)
    holdout = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(holdout)
    from app import pipeline as module
    from app.data.source import LocalSource
    messages = holdout.read_lines(Path(directory)/'holdout_20.txt')
    original_root = module.ROOT
    module.ROOT = holdout.NullTrace()
    totals = dict(messages=len(messages), critic_eligible=0, critic_skipped=0, location_eligible=0,
                  location_skipped=0, location_newly_skipped=0)
    try:
        pipeline = module.Pipeline(holdout.memory_registry(), sample=True, source=LocalSource())
        with contextlib.redirect_stdout(io.StringIO()):
            for start in range(0, len(messages), 15):
                # Eligibility is per message, before cross-case credibility or
                # duplicate review. Keep independent batches from accumulating
                # registry projections (and no approvals/learned aliases exist).
                pipeline.registry = holdout.memory_registry()
                cases = pipeline.run(dict(replay_time=holdout.REPLAY, messages=[
                    dict(message_id='a1l-skip-'+str(i), text=text, received_at=holdout.REPLAY)
                    for i,text in enumerate(messages[start:start+15], start)]))['cases']
                for case in cases:
                    flags = case.get('latency_budget', {}).get('eligibility', {})
                    totals['location_newly_skipped'] += bool(flags.get('location_newly_skipped'))
                    for role in ('critic', 'location'):
                        totals[role+('_eligible' if flags.get(role, True) else '_skipped')] += 1
    finally:
        module.ROOT = original_root
    totals.update(mode='offline_eligibility_proxy', actual_provider_calls=0,
                  critic_skip_rate=totals['critic_skipped']/len(messages),
                  location_skip_rate=totals['location_skipped']/len(messages),
                  expected_live_saving='incremental: critic_skipped * measured_critic_mean + location_newly_skipped * measured_location_loop_mean; most location skips predate A1L; no live latency measured')
    return totals


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--realdev-skips', type=Path)
    args = parser.parse_args()
    result = measure_skips(args.realdev_skips) if args.realdev_skips else evaluate(args.live)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(bool(result.get('unsafe_sends') or not args.realdev_skips and result['correct'] != result['cases']))
