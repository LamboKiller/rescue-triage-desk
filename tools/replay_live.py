"""Inspect live dumps for exact replay prerequisites; never fabricate model replies."""
import argparse
import json
from pathlib import Path


def missing_fields(dump):
    missing = []
    if not isinstance(dump, dict):
        return ['dump object']
    if not isinstance(dump.get('request'), dict):
        missing.append('request (replay_time and original messages)')
    calls = dump.get('calls')
    if not isinstance(calls, list) or not calls:
        missing.append('calls (ordered model attempts)')
    else:
        for index, call in enumerate(calls):
            if not isinstance(call, dict) or 'raw_output' not in call:
                missing.append(f'calls[{index}].raw_output')
    return missing


def inspect_dump(path):
    try:
        dump = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {'case': path.stem, 'then': None, 'now': None, 'missing': ['valid JSON dump']}
    return {'case': path.stem, 'then': dump.get('decision') if isinstance(dump, dict) else None,
            'now': None, 'missing': missing_fields(dump)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump', type=Path, required=True)
    args = parser.parse_args(argv)
    paths = sorted(args.dump.glob('*.json'))
    if not paths:
        print('Replay unavailable: no JSON dumps found.')
        return 2
    for path in paths:
        row = inspect_dump(path)
        print(f"{row['case']}: then={row['then']} now=UNAVAILABLE")
        print('  Missing: ' + ', '.join(row['missing']) if row['missing'] else
              '  Replay schema changed: inspect and implement the documented client contract first.')
    print('Exact replay unavailable; see docs/GATE.md for the minimal dump change. No pipeline was run.')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
