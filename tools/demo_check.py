"""Per-step PASS/FAIL of the scripted demo against a running desk (reads runtime/demo_state.json written by tools/demo_run.py).

  python tools/demo_check.py --url http://127.0.0.1:8080
Exit code 0 only when every step passes. Read-only: it never posts anything to the desk.
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_lib as lib  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--url', default='http://127.0.0.1:8080')
    p.add_argument('--state', type=Path, default=lib.STATE)
    p.add_argument('--verbose', action='store_true')
    args = p.parse_args()
    scenario = lib.load()
    state = lib.load_state(args.state)
    desk = lib.Desk(args.url)
    rows = lib.Check(desk, scenario, state).all()
    passed = 0
    for n, title, ok, fails, notes in rows:
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  passo {n}: {title}")
        for x in fails:
            print('       - '+x)
        if args.verbose:
            for x in notes:
                print('       · '+x)
    print(f'{passed}/{len(rows)} PASS')
    sys.exit(0 if passed == len(rows) else 1)


if __name__ == '__main__':
    main()
