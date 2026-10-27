"""Agent ablation: run the same messages with each agent role switched off in turn and compare to all-on.

  python tools/ablation.py --sets dev2,realdev                       # offline, fake client (mechanics + deterministic layers)
  python tools/ablation.py --sets dev2 --sample 40 --configs all_on,no_critic --fake-noise
  python tools/ablation.py --live --sample 30 --roles critic,revision,hazard_critic --sets dev2   # Orbit only

HONEST LIMIT: offline the "model" is a fake that mirrors the regex baseline (and, with --fake-noise, a scripted intake
slip that the fake reviewers fix by construction). Offline numbers therefore prove the harness and the deterministic
layers, NOT model-agent value. Model value is only measurable with --live (real Nightshift, nondeterministic: always
include `all_on_repeat` so run-to-run noise is visible next to every difference).

"Role off" = that stage is removed with no replacement text: critic/hazard/duplicate/arbiter/contradiction/credibility fall
back to their deterministic path (what the app does when the stage is unavailable); revision cannot run; location_model
skips the location model step and keeps the code lookup; `verifier_on` switches critic+revision to the merged Verifier.
Output: out/ablation/ablation_<mode>.json + .md
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import random
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLANNING = Path(os.environ['RTD_PLANNING_DIR']) if os.environ.get('RTD_PLANNING_DIR') else None  # --planning-dir overrides
# Per-call seconds measured live (min/median/max); unmeasured roles borrow critic's (declared proxy).
LATENCY_DEFAULT = {'intake': dict(n=23, median=12.838, min=4.597, max=27.995),
                   'hazard_critic': dict(n=4, median=11.5275, min=3.017, max=13.012),
                   'critic': dict(n=10, median=9.199, min=2.584, max=23.525),
                   'revision': dict(n=4, median=6.5235, min=5.519, max=22.91),
                   'location_agent': dict(n=3, median=15.25, min=4.521, max=25.522)}
LATENCY = None  # optional --latency JSON file ({"role_seconds": {...}}) replaces the defaults
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'eval'))

ROLE_CONFIGS = {  # config -> role switched off
    'no_critic': 'critic', 'no_revision': 'revision', 'no_hazard_critic': 'hazard_critic',
    'no_credibility_reviewer': 'credibility_reviewer', 'no_duplicate_reviewer': 'duplicate_reviewer',
    'no_arbiter': 'arbiter', 'no_contradictions': 'contradictions', 'no_location_model': 'location_agent'}
ALL_CONFIGS = ['all_on'] + list(ROLE_CONFIGS) + ['verifier_on']
SEND = ('SEND', 'SEND_APPROX')
DECISIONS = {'SEND_CANDIDATE': 'SEND', 'CALLBACK': 'CALLBACK', 'REPORTED_RESCUED': 'RESCUED', 'REVIEW_REQUIRED': 'REVIEW'}
REPLAY = '2024-05-06T14:00:00-03:00'


# ---------------------------------------------------------------- fake client
class FakeModel:
    """Offline stand-in for Nightshift. Mirrors the regex baseline; optional scripted intake slip (noise)."""

    def __init__(self, noise=False, latency=None):
        from app.data.source import LocalSource
        self.rows = LocalSource().streets()
        self.noise = noise
        self.latency = latency or load_latency()
        self.lock = threading.Lock()

    def seconds(self, role, text):
        d = self.latency.get(role) or self.latency['critic']  # unmeasured roles borrow critic (declared proxy)
        rnd = random.Random(hashlib.sha256((role+text).encode()).hexdigest())
        return round(rnd.triangular(d['min'], d['max'], d['median']), 3)

    def slip(self, text):
        return self.noise and int(hashlib.sha256(text.encode()).hexdigest(), 16) % 5 == 0

    def _baseline(self, text):
        from app.agents import baseline, intake
        names = {v: k for k, v in intake.KEYS.items()}
        found = baseline.extract(text, self.rows).get('fields', {})
        return {names[k]: v['quote'] for k, v in found.items() if k in names and v.get('quote')}

    def call(self, role, system, payload, deadline):
        meta = {'role': role, 'model': 'fake-offline', 'receipt': 'fake-'+uuid.uuid4().hex[:8]}
        text = payload.split('<<<', 1)[1].rsplit('>>>', 1)[0] if '<<<' in payload else payload
        if role in ('intake', 'revision'):
            quotes = self._baseline(text)
            if role == 'intake' and self.slip(text):
                quotes.pop('people', None)
                quotes['confidence'] = 'low'  # a slip the real intake would also flag as uncertain
            return quotes, meta
        if role in ('critic', 'verifier'):
            truth = self._baseline(text) if self.slip(text) else {}
            if role == 'critic':
                return {'objections': [{'field': 'people', 'reason': 'missed', 'quote': truth['people']}]
                        if 'people' in truth else []}, meta
            return {'changes': [{'field': 'people', 'action': 'set', 'quote': truth['people']}]
                    if 'people' in truth else []}, meta
        if role == 'hazard_critic':
            return {'block': [], 'warn': []}, meta
        if role == 'credibility_reviewer':
            signals = json.loads(payload)['signals']
            return {'verdict': 'doubtful' if signals else 'credible',
                    'reasons': [{'signal_id': s['id'], 'quote': s['quote']} for s in signals]}, meta
        if role == 'duplicate_reviewer':
            return {'verdict': 'unsure', 'evidence': [], 'reason_pt': 'fake offline'}, meta
        if role == 'arbiter':
            return {'choice': 'ESCALATE'}, meta
        if role == 'location_agent':
            return {'answer': {'candidate_id': None, 'precision': 'area', 'evidence': []}}, meta
        raise ValueError('fake model has no behaviour for '+role)


def load_latency():
    data = json.loads(LATENCY.read_text(encoding='utf-8'))['role_seconds'] if LATENCY and Path(LATENCY).is_file() else dict(LATENCY_DEFAULT)
    data['revision'] = data.get('revision') or data.get('intake') or dict(min=3, median=7, max=23)
    default = dict(min=3., median=9., max=23.)
    for role in ('intake', 'critic', 'revision', 'location_agent', 'hazard_critic'):
        data.setdefault(role, default)
    return data


# ---------------------------------------------------------------- role switches
@contextlib.contextmanager
def role_off(role, env=None):
    """Remove one role's stage (module-level patches restored on exit)."""
    import app.pipeline as pm
    from app.agents import arbiter, critic, duplicate_reviewer, hazard_critic, intake
    import app.credibility as cred
    from app.credibility.reviewer import action_for, rule_verdict
    with contextlib.ExitStack() as stack:
        if env:
            stack.enter_context(patch.dict(os.environ, env))
        if role == 'critic':
            stack.enter_context(patch.object(critic, 'run', lambda *a, **k: ({'objections': []}, None)))
        elif role == 'revision':
            original = intake.run
            def run(client, text, deadline, objections=None):
                if objections is not None:
                    raise ValueError('revision disabled by ablation')
                return original(client, text, deadline, objections)
            stack.enter_context(patch.object(intake, 'run', run))
        elif role == 'hazard_critic':
            stack.enter_context(patch.object(hazard_critic, 'attach', lambda *a, **k: None))
        elif role == 'credibility_reviewer':
            def review(client, signals, deadline=None):
                verdict = rule_verdict(signals)
                return {'verdict': verdict, 'source': 'rule', 'reasons': [{'signal_id': s['id'], 'quote': s['quote']} for s in signals],
                        'agent_verdict': None, 'fallback_reason': None, 'note': None}
            stack.enter_context(patch.object(cred, 'review', review))
        elif role == 'duplicate_reviewer':
            def run(client, a, b, deadline):
                return {'verdict': 'unsure', 'evidence': [], 'reason_pt': 'desativado (ablação)'}, {}
            stack.enter_context(patch.object(duplicate_reviewer, 'run', run))
        elif role == 'arbiter':
            original = arbiter.resolve
            stack.enter_context(patch.object(arbiter, 'resolve', lambda conflict, client, deadline: original(conflict, None, deadline)))
        elif role == 'contradictions':
            import app.contradictions.hook as hook
            original = hook.after_decision
            stack.enter_context(patch.object(hook, 'after_decision', lambda pipe, results, previous, client: original(pipe, results, previous, None)))
        elif role == 'location_agent':
            stack.enter_context(patch.object(pm.StageBudget, 'location_available', lambda self, deadline: False))
        yield


def config_context(name):
    if name == 'verifier_on':
        return role_off(None, env={'RTD_VERIFIER': '1'})
    return role_off(ROLE_CONFIGS.get(name))


# ---------------------------------------------------------------- data
def load_sets(names, sample=None, seed=1):
    import run_dev2
    items = []
    if 'dev2' in names:
        for r in run_dev2.load_items(sample=sample, seed=seed):
            items.append(dict(set='dev2', id='dev2:'+r['id'], raw=r))
    if 'realdev' in names:
        if PLANNING is None:
            raise SystemExit('realdev needs --planning-dir (or RTD_PLANNING_DIR) pointing at the planning repo')
        directory = PLANNING/'review'/'realdev'
        sys.path.insert(0, str(PLANNING/'tools'))
        import run_holdout as rh
        messages = rh.read_lines(directory/'holdout_20.txt')
        truth = [rh.parse_truth(line) for line in rh.read_lines(directory/'holdout_20_truth.txt')]
        rows = [dict(set='realdev', id='realdev:%d' % (i+1), text=m, truth=t) for i, (m, t) in enumerate(zip(messages, truth))]
        if sample and sample < len(rows):
            rows = sorted(random.Random(seed).sample(rows, sample), key=lambda r: int(r['id'].split(':')[1]))
        items.extend(rows)
    return items


def batches(items):
    """dev2 uses its own packing (unique street per batch); realdev batches of 15 in file order."""
    import run_dev2
    out = []
    dev = [i for i in items if i['set'] == 'dev2']
    for batch in run_dev2.pack([i['raw'] for i in dev]):
        by_id = {i['raw']['id']: i for i in dev}
        out.append([by_id[r['id']] for r in batch])
    real = [i for i in items if i['set'] == 'realdev']
    for k in range(0, len(real), 15):
        out.append(real[k:k+15])
    return out


def mid(item):
    return item['id'].replace(':', '-')


def judge(item, case):
    result = case.get('result') or {}
    got = DECISIONS.get(result.get('decision')) or 'ERROR'
    if got == 'SEND' and (result.get('location_approximate') or result.get('location_precision') in ('approximate', 'area')):
        got_family = 'SEND_APPROX'
    else:
        got_family = got
    fields = case.get('fields') or {}
    people = result.get('people') or fields.get('people', {}).get('value')
    people = people if isinstance(people, int) and not isinstance(people, bool) else None
    route = (case.get('route') or {}).get('id')
    if item['set'] == 'dev2':
        raw = item['raw']
        exp = raw['expected_decision']
        decision_ok = got_family in SEND if exp in SEND else got_family == exp
        unsafe = got_family in SEND and exp not in SEND
        ok = decision_ok and (raw['expected_people'] is None or people == raw['expected_people']) and \
            (raw['expected_route'] is None or route == raw['expected_route'])
    else:
        t = item['truth']
        decision_ok = t['decision'] is None or got == t['decision']
        unsafe = got == 'SEND' and t['decision'] not in (None, 'SEND')
        ok = decision_ok and (t['people'] is None or people == t['people']) and (t['route_kind'] == 'asset' or t['route'] is None or route == t['route'])
    return dict(id=item['id'], set=item['set'], decision=got_family, decision_ok=bool(decision_ok), ok=bool(ok), unsafe=bool(unsafe),
                people=people, route=route)


# ---------------------------------------------------------------- running
class NullTrace:
    def __truediv__(self, name): return self
    @property
    def parent(self): return self
    def mkdir(self, **kw): pass
    def open(self, *a, **kw): return open(os.devnull, 'w', encoding='utf-8')


def scratch():
    path = ROOT/'.tmp'/('abl-'+uuid.uuid4().hex)
    path.mkdir(parents=True)
    return path


def case_cost(case, model, item):
    """(calls, seconds). Offline: simulated from the role latency distributions; live: measured receipts + wall time."""
    receipts = [r for r in case.get('calls', []) if isinstance(r, dict) and r.get('source') != 'stage_boundary'
                and r.get('status') not in ('skipped', 'timeout', 'failed')]
    if model is None:
        return len(receipts), float(case.get('seconds') or 0)
    text = item.get('raw', {}).get('text') or item.get('text') or ''
    return len(receipts), round(sum(model.seconds(r.get('role', 'critic'), text) for r in receipts), 3)


def run_config(name, items, live=False, noise=False, jobs=1, progress=None):
    import app.pipeline as pm
    from app.data.source import LocalSource
    from app.engines.world_model.registry import Registry
    model = None if live else FakeModel(noise=noise)
    pm.ROOT = NullTrace()
    os.environ['RTD_CONTRIBUTION_PATH'] = str(scratch()/'contribution.json')
    if live:
        from app.config import load_env
        load_env()
        from app.llm.nightshift import Nightshift
        client_factory = lambda: Nightshift(NullTrace())
    else:
        client_factory = lambda: model
    local = threading.local()
    rows, started = [], time.monotonic()

    def run_batch(batch):
        pipe = getattr(local, 'pipeline', None)
        if pipe is None:
            pipe = local.pipeline = pm.Pipeline(Registry(scratch()/'events.jsonl'), sample=False, source=LocalSource(),
                                                client=client_factory(), max_workers=2, budget_seconds=90)
        pipe.registry = Registry(scratch()/'events.jsonl')
        by_id = {}
        try:
            first = batch[0]
            date = (first['raw']['replay_date']+'T14:00:00-03:00') if first['set'] == 'dev2' else REPLAY
            request = dict(replay_time=date, messages=[dict(message_id=mid(i), text=(i['raw']['text'] if i['set'] == 'dev2' else i['text'])) for i in batch])
            with contextlib.redirect_stdout(io.StringIO()):
                out = pipe.run(request, ablation='full')
            by_id = {c['message_id']: c for c in out['cases']}
        except Exception as exc:  # a crashed batch is counted as errors, never hidden
            by_id = {'__error__': type(exc).__name__}
        result = []
        for item in batch:
            case = by_id.get(mid(item))
            if case is None:
                result.append(dict(id=item['id'], set=item['set'], decision='ERROR', decision_ok=False, ok=False, unsafe=False,
                                   people=None, route=None, calls=0, seconds=0., error=by_id.get('__error__', 'missing')))
                continue
            row = judge(item, case)
            row['calls'], row['seconds'] = case_cost(case, model, item)
            row['roles'] = sorted({r.get('role') for r in case.get('calls', []) if isinstance(r, dict)} - {None})
            result.append(row)
        return result

    with config_context(name):
        with ThreadPoolExecutor(max(1, jobs)) as pool:
            for part in pool.map(run_batch, batches(items)):
                rows.extend(part)
                if progress:
                    progress(name, len(rows))
        try:
            from app.contradictions.service import wait_all
            wait_all()
        except Exception:
            pass
    rows.sort(key=lambda r: r['id'])
    return rows, round(time.monotonic()-started, 2)


# ---------------------------------------------------------------- comparison
def summarize(rows, base):
    base_by = {r['id']: r for r in base}
    n = len(rows) or 1
    improved = sum(1 for r in rows if r['ok'] and not base_by.get(r['id'], {}).get('ok', False))
    worsened = sum(1 for r in rows if not r['ok'] and base_by.get(r['id'], {}).get('ok', False))
    changed = sum(1 for r in rows if r['decision'] != base_by.get(r['id'], {}).get('decision', r['decision']))
    return dict(n=len(rows), correct=sum(r['ok'] for r in rows), decision_correct=sum(r['decision_ok'] for r in rows),
                improved_vs_all_on=improved, worsened_vs_all_on=worsened, decision_changed=changed,
                unsafe=sum(r['unsafe'] for r in rows), errors=sum(1 for r in rows if r['decision'] == 'ERROR'),
                calls_per_message=round(sum(r['calls'] for r in rows)/n, 3),
                seconds_per_message=round(sum(r['seconds'] for r in rows)/n, 3))


def verdict(role_row, noise_row):
    """Merge/cut hint. Offline never cuts a model role: it has no model evidence."""
    if role_row['unsafe'] > noise_row['unsafe']:
        return 'KEEP (unsafe appears without it)'
    if role_row['worsened_vs_all_on'] > role_row['improved_vs_all_on']:
        return 'KEEP (removal worsens decisions)'
    return 'no measured value in this run'


def markdown(report):
    lines = ['# Agent ablation — %s (%s)' % (report['mode'], report['when']), '',
             report['limit'], '',
             '| config | n | correct | improved | worsened | decision changed | unsafe | calls/msg | s/msg |',
             '|---|---|---|---|---|---|---|---|---|']
    for name, row in report['configs'].items():
        lines.append('| %s | %d | %d | %d | %d | %d | %d | %.2f | %.1f |' % (
            name, row['n'], row['correct'], row['improved_vs_all_on'], row['worsened_vs_all_on'], row['decision_changed'],
            row['unsafe'], row['calls_per_message'], row['seconds_per_message']))
    lines += ['', 'improved = correct without the role but not with it; worsened = correct with it, wrong without. '
              'seconds: %s.' % report['seconds_basis']]
    return '\n'.join(lines)+'\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sets', default='dev2,realdev')
    ap.add_argument('--sample', type=int, default=None, help='seeded sample per set')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--configs', default=None, help='comma list; default all (offline) / all_on,all_on_repeat + --roles (live)')
    ap.add_argument('--roles', default=None, help='live: comma list of roles to switch off (critic,revision,...,verifier)')
    ap.add_argument('--live', action='store_true', help='real Nightshift calls (Orbit only; needs provider settings)')
    ap.add_argument('--fake-noise', action='store_true', help='offline: scripted intake slip fixed by the fake reviewers (mechanics check)')
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--planning-dir', type=Path, default=None, help='planning repo holding review/realdev (or env RTD_PLANNING_DIR)')
    ap.add_argument('--latency', type=Path, default=None, help='JSON with role_seconds distributions (default: built-in measured values)')
    ap.add_argument('--out', type=Path, default=ROOT/'out'/'ablation')
    args = ap.parse_args(argv)
    global PLANNING, LATENCY
    PLANNING = args.planning_dir or PLANNING
    LATENCY = args.latency
    sets = [s.strip() for s in args.sets.split(',') if s.strip()]
    if args.live:
        roles = [r.strip() for r in (args.roles or ','.join(ROLE_CONFIGS.values())).split(',') if r.strip()]
        configs = ['all_on', 'all_on_repeat']
        for r in roles:
            configs.append('verifier_on' if r == 'verifier' else 'no_'+r)
        unknown = [c for c in configs if c not in ALL_CONFIGS + ['all_on_repeat']]
        if unknown:
            raise SystemExit('unknown role(s): '+', '.join(unknown))
    else:
        configs = [c.strip() for c in args.configs.split(',')] if args.configs else ALL_CONFIGS
        if 'all_on' not in configs:
            configs.insert(0, 'all_on')
    mode = 'live' if args.live else 'offline'
    items = load_sets(sets, args.sample, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out/('ablation_%s.json' % mode)
    done = {}
    if args.live and target.is_file():  # resumable: Orbit can stop and rerun without losing finished configs
        done = json.loads(target.read_text(encoding='utf-8')).get('rows', {})
    all_rows = dict(done)
    for name in configs:
        if name in all_rows:
            continue
        rows, seconds = run_config('all_on' if name == 'all_on_repeat' else name, items, live=args.live, noise=args.fake_noise,
                                   jobs=args.jobs, progress=lambda n, k: print('  %s %d/%d' % (n, k, len(items)), file=sys.stderr, flush=True))
        all_rows[name] = rows
        print('%s: %d rows in %.1fs' % (name, len(rows), seconds), file=sys.stderr, flush=True)
        target.write_text(json.dumps({'rows': all_rows}), encoding='utf-8')
    base = all_rows['all_on']
    report = dict(mode=mode, when=time.strftime('%Y-%m-%d %H:%M'), sets=sets, sample=args.sample, seed=args.seed,
                  fake_noise=args.fake_noise, n=len(items),
                  limit=('OFFLINE: the model is a fake mirroring the regex baseline%s; this table validates the harness and deterministic '
                         'layers, not model-agent value.' % (' plus a scripted slip fixed by the fake reviewers' if args.fake_noise else '')) if not args.live else
                        'LIVE: real Nightshift, nondeterministic; compare each row to the all_on vs all_on_repeat noise before concluding.',
                  seconds_basis='measured wall time per message' if args.live else
                  'simulated: sum of sampled per-call latencies from measured live latencies (sequential upper bound; unmeasured roles borrow critic)',
                  configs={name: summarize(rows, base) for name, rows in all_rows.items()})
    for name, row in report['configs'].items():
        if name in ROLE_CONFIGS:
            row['hint'] = verdict(row, report['configs']['all_on']) if not args.live else None
    target.write_text(json.dumps(dict(report, rows=all_rows), ensure_ascii=False), encoding='utf-8')
    (args.out/('ablation_%s.md' % mode)).write_text(markdown(report), encoding='utf-8')
    print(markdown(report))
    return 1 if any(r['unsafe'] for r in report['configs'].values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
