"""Self-play red team: python eval/run_redteam.py --n 24 [--live] [--seed N] [--replay] [--no-propose]

Offline (default): scripted attacker with built-in seed messages + the offline regex pipeline; no network, no model.
--live (for the human): Nemotron attacker via Nightshift, live pipeline. Not used by tests.
Exit code 1 when any unsafe SEND occurred.
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env
from app.redteam import harness
from app.redteam.attacker import Attacker


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--n', type=int, default=24)
    p.add_argument('--seed', type=int, default=1)
    p.add_argument('--live', action='store_true')
    p.add_argument('--replay', action='store_true', help='re-run approved regression cases instead of a new batch')
    p.add_argument('--runtime-dir', type=Path, default=None, help='where declarations/results go (default runtime/redteam)')
    args = p.parse_args(argv)
    store = harness.Store(runtime_dir=args.runtime_dir or harness.RUNTIME_DIR)
    client = None
    pipeline_client = None
    if args.live:
        load_env()
        from app.missions.client import MissionClient
        from app.llm.nightshift import Nightshift
        client = MissionClient(ROOT/'runtime/redteam/attacker_trace.jsonl')
        pipeline_client = Nightshift(ROOT/'runtime/redteam/pipeline_trace.jsonl')
    # Production Pipeline defaults: 60s per started message, at most two workers.
    # Attacker finishes declaring before the runner; judge_all judges only finished cases.
    runner = harness.make_runner(offline=not args.live, client=pipeline_client)
    if args.replay:
        rows = harness.replay_regression(store, runner)
        print(json.dumps({'mode': 'live' if args.live else 'offline', 'replay': rows}, ensure_ascii=False, indent=2))
        return int(any(r['regressed'] for r in rows))
    out = harness.run_batch(args.n, store, Attacker(client), runner, seed=args.seed)
    s = out['summary']
    print(f"mode={'live' if args.live else 'offline'} n={s['total']} pass={s['passed']} rate={s['rate']} unsafe_send={s['unsafe_send']}")
    for cat, v in s['categories'].items():
        print(f"  {cat:24s} {v['passed']}/{v['runs']}")
    for r in out['results']:
        if not r['passed']:
            print(f"FAIL {r['category']}: {'; '.join(r['reasons'])}\n     {r['message'][:140]}")
    return int(s['unsafe_send'] > 0)


if __name__ == '__main__':
    raise SystemExit(main())
