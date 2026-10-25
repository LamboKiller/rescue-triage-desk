"""Credibility filter evaluation (20 hand-written synthetic cases).

Default is OFFLINE: (a) code rule only, (b) a scripted agent that returns the verdict stored in each case, which proves the
validator/combiner wiring, NOT model quality. `--live` calls Nemotron via Nightshift (run by the operator).
Key metric: likely_fake on genuine messages (target 0).
"""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.credibility import assess
from app.geo.hydro import hydro_conflict

SET = ROOT / 'eval/credibility_set.jsonl'


class ScriptedClient:
    """Offline stand-in: returns the case's scripted verdict, citing the first strong (else first) signal."""
    def __init__(self, verdict):
        self.verdict = verdict

    def call(self, role, system, payload, deadline):
        signals = json.loads(payload)['signals']
        pick = next((s for s in signals if s['strength'] == 'strong'), signals[0])
        return {'verdict': self.verdict, 'reasons': [{'signal_id': pick['id'], 'quote': pick['quote']}]}, {'role': role, 'offline': True}


def conflict_for(case):
    p = case.get('point')
    if not p:
        return None
    return hydro_conflict(case['text'], p['lat'], p['lon'], p['day'], street=p.get('street'), municipality=p.get('municipality'),
                          precision=p.get('precision', 'street'))


def evaluate(cases, mode='offline'):
    rows, genuine_fl, genuine_doubt, fake_flagged, fakes, exact = [], 0, 0, 0, 0, 0
    live = None
    if mode == 'live':
        from app.llm.nightshift import Nightshift
        live = Nightshift(ROOT / 'runtime/credibility_eval_trace.jsonl')
    for case in cases:
        conflict = conflict_for(case)
        base = dict(time=case['time'], history=case.get('history', ()), hydro_conflict=conflict)
        rule = assess(case['text'], **base)
        client = live if mode == 'live' else ScriptedClient(case['scripted_agent']['verdict'])
        full = assess(case['text'], client=client, deadline=time.monotonic() + 120, **base)
        truth = case['truth']
        ok = full['verdict'] in truth['acceptable']
        exact += full['verdict'] == truth['verdict']
        if truth['genuine']:
            genuine_fl += full['verdict'] == 'likely_fake' or rule['verdict'] == 'likely_fake'
            genuine_doubt += full['verdict'] == 'doubtful'
        else:
            fakes += 1
            fake_flagged += full['verdict'] != 'credible'
        rows.append({'id': case['id'], 'truth': truth['verdict'], 'rule': rule['verdict'], 'final': full['verdict'], 'source': full['source'],
                     'signals': [s['id'] for s in full['signals']], 'acceptable': ok, 'fallback_reason': full.get('fallback_reason')})
    n_gen = sum(1 for c in cases if c['truth']['genuine'])
    return {'mode': 'live' if mode == 'live' else 'offline_wiring_only', 'cases': len(cases), 'genuine': n_gen, 'fake': fakes,
            'likely_fake_on_genuine': genuine_fl, 'doubtful_on_genuine': genuine_doubt,
            'doubtful_on_genuine_rate': round(genuine_doubt / n_gen, 3) if n_gen else None,
            'fake_flagged_rate': round(fake_flagged / fakes, 3) if fakes else None, 'acceptable': sum(r['acceptable'] for r in rows),
            'exact_match': exact, 'rule_only_exact': sum(r['rule'] == r['truth'] for r in rows), 'results': rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--live', action='store_true', help='call Nemotron through Nightshift (operator only)')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    cases = [json.loads(line) for line in SET.read_text(encoding='utf-8').splitlines() if line.strip()]
    result = evaluate(cases, 'live' if args.live else 'offline')
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for r in result['results']:
            print('%-4s truth=%-11s rule=%-11s final=%-11s %-13s %s%s' % (r['id'], r['truth'], r['rule'], r['final'], r['source'],
                  ','.join(r['signals']) or '-', '' if r['acceptable'] else '   <-- NOT ACCEPTABLE'))
        print({k: v for k, v in result.items() if k != 'results'})
    return 0 if result['likely_fake_on_genuine'] == 0 and result['acceptable'] == result['cases'] else 1


if __name__ == '__main__':
    sys.exit(main())
