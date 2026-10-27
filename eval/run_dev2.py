"""dev2: ~180 own-words PT-BR labelled messages aimed at known failure classes.

  python eval/run_dev2.py --offline                 # fake client, no network
  python eval/run_dev2.py --live --jobs 2           # Orbit only (needs .env providers)
  python eval/run_dev2.py --offline --only derived_count,reg_ --sample 40 --seed 1
Writes out/dev2/dev2_<mode>.json and .md (+ timestamped copies).
"""
import argparse
import contextlib
import io
import json
import random
import statistics
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.failures import failure_kind  # noqa: E402

SEND_FAMILY = ('SEND', 'SEND_APPROX')
DECISIONS = {'SEND_CANDIDATE': 'SEND', 'CALLBACK': 'CALLBACK', 'REPORTED_RESCUED': 'RESCUED', 'REVIEW_REQUIRED': 'REVIEW'}
BATCH = 10


def _scratch():
    # Ordinary directories avoid Windows tempfile.mkdtemp's restrictive ACL
    # in the build sandbox (the test suite uses the same workspace strategy).
    path = ROOT / '.tmp' / ('dev2-' + uuid.uuid4().hex)
    path.mkdir(parents=True)
    return path


def load_items(only=None, sample=None, seed=0):
    path = ROOT / 'eval/dev2/messages.jsonl'
    rows = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
    if only:
        keys = [k.strip() for k in only.split(',') if k.strip()]
        rows = [r for r in rows if any(r['id'] == k or r['class'].startswith(k) or r['bucket'] == k for k in keys)]
    if sample and sample < len(rows):
        rows = sorted(random.Random(seed).sample(rows, sample), key=lambda r: r['id'])
    return rows


def extract(case):
    """Pipeline case -> comparable observation (no message text)."""
    result = case.get('result') or {}
    decision = DECISIONS.get(result.get('decision'))
    if decision == 'SEND' and (result.get('location_approximate') or result.get('location_precision') in ('approximate', 'area')):
        decision = 'SEND_APPROX'
    people = (case.get('fields') or {}).get('people', {}).get('value')
    people = people if isinstance(people, int) and not isinstance(people, bool) and people >= 0 else None
    return {'got_decision': decision or 'ERROR', 'got_people': result.get('people') or people,
            'got_route': (case.get('route') or {}).get('id'), 'got_precision': result.get('location_precision'),
            'seconds': case.get('seconds', 0), 'failure': failure_kind(case)}


def judge(item, obs):
    exp, got = item['expected_decision'], obs['got_decision']
    fam = got in SEND_FAMILY if exp in SEND_FAMILY else got == exp
    row = {'id': item['id'], 'class': item['class'], 'bucket': item['bucket'], 'ambiguous': item['ambiguous'],
           'expected_decision': exp, 'expected_people': item['expected_people'], 'expected_route': item['expected_route'],
           **obs, 'decision_ok': fam, 'strict_ok': got == exp,
           'people_ok': None if item['expected_people'] is None else obs['got_people'] == item['expected_people'],
           'route_ok': None if item['expected_route'] is None else obs['got_route'] == item['expected_route'],
           'unsafe': got in SEND_FAMILY and exp not in SEND_FAMILY,
           'missed_send': exp in SEND_FAMILY and got not in SEND_FAMILY,
           'invented_count': item['expected_people'] is None and exp in SEND_FAMILY and obs['got_people'] is not None}
    return row


def _acc(rows, key):
    use = [r for r in rows if r[key] is not None]
    return (sum(1 for r in use if r[key]), len(use))


def summarize(rows):
    """rows: judged rows. Main table excludes ambiguous items; they are reported separately."""
    def block(group):
        secs = sorted(r['seconds'] for r in group)
        return {'n': len(group), 'decision': _acc(group, 'decision_ok'), 'strict': _acc(group, 'strict_ok'),
                'people': _acc(group, 'people_ok'), 'route': _acc(group, 'route_ok'),
                'unsafe': sum(r['unsafe'] for r in group), 'missed_send': sum(r['missed_send'] for r in group),
                'invented_count': sum(r['invented_count'] for r in group),
                'mean_s': round(statistics.mean(secs), 3) if secs else 0,
                'p95_s': secs[max(0, -(-95 * len(secs) // 100) - 1)] if secs else 0}
    firm = [r for r in rows if not r['ambiguous']]
    classes = defaultdict(list)
    for r in firm: classes[r['class']].append(r)
    fails = defaultdict(int)
    for r in rows:
        if r['failure']: fails[r['failure']] += 1
    buckets = defaultdict(list)
    for r in firm: buckets[r['bucket']].append(r)
    return {'overall': block(firm), 'ambiguous': block([r for r in rows if r['ambiguous']]),
            'by_class': {k: block(v) for k, v in sorted(classes.items())},
            'by_bucket': {k: block(v) for k, v in sorted(buckets.items())},
            'failure_kinds': dict(fails), 'unsafe_ids': [r['id'] for r in rows if r['unsafe']]}


def pack(items):
    """Batches with unique street+city per batch and one replay date (fresh registry per batch)."""
    pending = sorted(items, key=lambda r: r['id'])
    batches = []
    while pending:
        date, used, batch, rest = pending[0]['replay_date'], set(), [], []
        for it in pending:
            kf = it['key_fields']; key = (kf.get('municipality'), kf.get('street')) if kf.get('street') else None
            if it['replay_date'] == date and len(batch) < BATCH and (key is None or key not in used):
                batch.append(it); key and used.add(key)
            else:
                rest.append(it)
        batches.append(batch); pending = rest
    return batches


class _NullTrace:
    def __truediv__(self, name): return self
    @property
    def parent(self): return self
    def mkdir(self, **kw): pass
    def open(self, *a, **kw): return open('NUL' if sys.platform == 'win32' else '/dev/null', 'w', encoding='utf-8')


def make_runner(offline):
    from app.engines.world_model.registry import Registry
    import app.pipeline as pm
    local = threading.local()
    if not offline:
        from app.config import load_env
        load_env()
        from app.llm.nightshift import Nightshift
        pm.ROOT = _NullTrace()

    def run_batch(batch):
        if not hasattr(local, 'pipeline'):
            client = None if offline else Nightshift(_NullTrace())
            local.pipeline = pm.Pipeline(Registry(_scratch() / 'events.jsonl'),
                                         sample=offline, client=client, max_workers=2)
        local.pipeline.registry = Registry(_scratch() / 'events.jsonl')
        date = batch[0]['replay_date']
        request = {'replay_time': date + 'T14:00:00-03:00',
                   'messages': [{'message_id': it['id'], 'text': it['text']} for it in batch]}
        with contextlib.redirect_stdout(io.StringIO()):  # the pipeline prints run summaries
            out = local.pipeline.run(request, ablation='baseline' if offline else 'full')
        by_id = {c['message_id']: c for c in out['cases']}
        return [judge(it, extract(by_id[it['id']])) if it['id'] in by_id else
                judge(it, {'got_decision': 'ERROR', 'got_people': None, 'got_route': None, 'got_precision': None,
                           'seconds': 0, 'failure': 'agent_failure'}) for it in batch]
    return run_batch


def run(items, offline=True, jobs=1):
    runner = make_runner(offline)
    start, rows = time.monotonic(), []
    def safe(batch):
        try:
            return runner(batch)
        except Exception as exc:  # a crashed batch is counted as errors, never hidden
            return [judge(it, {'got_decision': 'ERROR:' + type(exc).__name__, 'got_people': None, 'got_route': None,
                               'got_precision': None, 'seconds': 0, 'failure': 'agent_failure'}) for it in batch]
    with ThreadPoolExecutor(max(1, jobs)) as pool:
        for part in pool.map(safe, pack(items)): rows.extend(part)
    rows.sort(key=lambda r: r['id'])
    return rows, round(time.monotonic() - start, 2)


def fmt(pair):
    return '%d/%d (%.0f%%)' % (pair[0], pair[1], 100 * pair[0] / pair[1]) if pair[1] else '-'


def markdown(summary, mode, seconds):
    lines = ['# dev2 results (%s, %ss)' % (mode, seconds), '',
             '| class | n | decision | strict | people | route | unsafe | missed SEND | mean s |', '|---|---|---|---|---|---|---|---|---|']
    def line(name, b):
        return '| %s | %d | %s | %s | %s | %s | %d | %d | %s |' % (name, b['n'], fmt(b['decision']), fmt(b['strict']),
                                                                   fmt(b['people']), fmt(b['route']), b['unsafe'], b['missed_send'], b['mean_s'])
    for name, b in summary['by_class'].items(): lines.append(line(name, b))
    lines.append(line('**TOTAL (non-ambiguous)**', summary['overall']))
    lines.append(line('ambiguous (separate)', summary['ambiguous']))
    lines += ['', '## by bucket'] + [line(k, b) for k, b in summary['by_bucket'].items()]
    lines += ['', 'failure kinds: %s' % (summary['failure_kinds'] or 'none'), 'unsafe ids: %s' % (summary['unsafe_ids'] or 'none'),
              'decision = SEND/SEND_APPROX treated as one family; strict = exact label incl. approximate.']
    return '\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--offline', action='store_true'); mode.add_argument('--live', action='store_true')
    ap.add_argument('--only'); ap.add_argument('--sample', type=int); ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--jobs', type=int, default=3, help='parallel batches (live: provider slots are global, keep 2-3)'); ap.add_argument('--out', default=str(ROOT / 'out/dev2'))
    args = ap.parse_args(argv)
    items = load_items(args.only, args.sample, args.seed)
    rows, seconds = run(items, offline=args.offline, jobs=args.jobs)
    name = 'offline' if args.offline else 'live'
    summary = summarize(rows)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    payload = {'mode': name, 'seconds': seconds, 'n': len(rows), 'summary': summary, 'rows': rows}
    stamp = time.strftime('%Y%m%d-%H%M%S')
    md = markdown(summary, name, seconds)
    for suffix in ('', '_' + stamp):
        (out / ('dev2_%s%s.json' % (name, suffix))).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
        (out / ('dev2_%s%s.md' % (name, suffix))).write_text(md, encoding='utf-8')
    print(md)
    return 1 if summary['overall']['unsafe'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
