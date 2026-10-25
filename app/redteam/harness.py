"""Red-team loop: store declarations first, run the pipeline, judge by code, propose regressions, replay forever."""
import contextlib
import hashlib
import io
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from app.config import ROOT
from app.redteam import attacker as attacker_mod
from app.redteam.policy import CATEGORIES, judge

REPLAY = '2024-05-06T14:00:00-03:00'
RECEIVED = '2024-05-06T13:00:00-03:00'
EVAL_DIR = ROOT/'eval/redteam'
RUNTIME_DIR = ROOT/'runtime/redteam'
LOCK = threading.RLock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def msg_key(message):
    return hashlib.sha256(' '.join(message.split()).lower().encode()).hexdigest()[:16]


class Store:
    """Append-only JSONL files. declarations/results live in runtime/, proposals/regression in eval/."""

    def __init__(self, eval_dir=EVAL_DIR, runtime_dir=RUNTIME_DIR):
        self.eval_dir, self.runtime_dir = Path(eval_dir), Path(runtime_dir)
        self.eval_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def path(self, name):
        return (self.runtime_dir if name in ('declarations', 'results') else self.eval_dir)/(name+'.jsonl')

    def read(self, name):
        p = self.path(name)
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()]

    def append(self, name, record):
        with LOCK, self.path(name).open('a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False)+'\n')

    def rewrite(self, name, records):
        with LOCK:
            p = self.path(name)
            tmp = p.with_suffix('.tmp')
            tmp.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in records), encoding='utf-8')
            tmp.replace(p)


def make_runner(offline=True, client=None):
    """Callable(messages) -> cases through a throwaway registry; never touches the desk's real case registry."""
    def run(messages):
        from app.engines.world_model.registry import Registry
        from app.pipeline import Pipeline
        from tools.scratch import scratch
        cases = []
        with scratch() as folder:
            pipeline = Pipeline(Registry(Path(folder)/'events.jsonl'), sample=offline, client=client)
            for i in range(0, len(messages), 15):
                with contextlib.redirect_stdout(io.StringIO()):
                    out = pipeline.run({'replay_time': REPLAY, 'messages': messages[i:i+15]})
                cases.extend(out['cases'])
        return cases
    return run


def _messages(decls):
    return [{'message_id': d['decl_id'], 'text': d['message'], 'received_at': RECEIVED} for d in decls]


def judge_all(decls, runner):
    """Run declarations through the pipeline; return {decl_id: verdict}. Verifies the declaration hash first."""
    verdicts, runnable = {}, []
    for d in decls:
        if attacker_mod.decl_hash(d) != d.get('decl_hash'):
            verdicts[d['decl_id']] = {'passed': False, 'reasons': ['declaration_modified: hash mismatch'], 'decision': None,
                                      'route': None, 'unsafe_send': False, 'invariants_checked': []}
        else:
            runnable.append(d)
    by_id = {d['decl_id']: d for d in runnable}
    for case in runner(_messages(runnable)) if runnable else []:
        verdicts[case['message_id']] = judge(case, by_id[case['message_id']])
    for d in runnable:
        verdicts.setdefault(d['decl_id'], {'passed': False, 'reasons': ['no_result: pipeline returned no case'],
                                           'decision': None, 'route': None, 'unsafe_send': False, 'invariants_checked': []})
    return verdicts


def run_batch(n, store, attacker, runner, seed=1, order=None):
    """Declare first (stored, immutable), then run and judge. Failures become pending proposals."""
    import random
    run_id = 'run-' + hashlib.sha256((now()+str(seed)+str(n)).encode()).hexdigest()[:10]
    decls = attacker_mod.build(n, attacker, random.Random(seed), order)
    for d in decls:
        store.append('declarations', {**d, 'run_id': run_id, 'declared_at': now()})
    verdicts = judge_all(decls, runner)
    results = []
    known = {p['key'] for p in store.read('proposed')} | {r['key'] for r in store.read('regression')}
    for d in decls:
        v = verdicts[d['decl_id']]
        rec = {'run_id': run_id, 'decl_id': d['decl_id'], 'decl_hash': d['decl_hash'], 'category': d['category'],
               'message': d['message'], 'source': d.get('source'), 'at': now(), **v}
        if d.get('fallback_reason'):
            rec['attacker_fallback_reason'] = d['fallback_reason']
        outside = sorted(set(d['expected_outcomes']) - CATEGORIES[d['category']]['accept'])
        if outside:
            rec['declaration_mismatch'] = outside  # attacker expected outcomes the policy does not accept
        store.append('results', rec)
        results.append(rec)
        key = msg_key(d['message'])
        if not v['passed'] and key not in known:
            known.add(key)
            store.append('proposed', {'proposal_id': 'pr-' + key[:10], 'key': key, 'status': 'pending', 'category': d['category'],
                                      'message': d['message'], 'places': d['places'], 'incident_city': d['incident_city'],
                                      'caller_city': d['caller_city'], 'expected_outcomes': d['expected_outcomes'],
                                      'decl_hash': d['decl_hash'], 'reasons': v['reasons'], 'decision': v['decision'],
                                      'route': v['route'], 'unsafe_send': v['unsafe_send'], 'run_id': run_id, 'created_at': now()})
    return {'run_id': run_id, 'results': results, 'summary': summarize(results)}


def summarize(results):
    cats = {c: {'runs': 0, 'passed': 0} for c in CATEGORIES}
    for r in results:
        cats[r['category']]['runs'] += 1
        cats[r['category']]['passed'] += bool(r['passed'])
    for v in cats.values():
        v['rate'] = round(v['passed']/v['runs'], 3) if v['runs'] else None
    total, passed = len(results), sum(bool(r['passed']) for r in results)
    return {'total': total, 'passed': passed, 'rate': round(passed/total, 3) if total else None,
            'unsafe_send': sum(bool(r.get('unsafe_send')) for r in results), 'categories': cats}


def _decl_of(entry):
    d = {k: entry.get(k) for k in ('category', 'message', 'places', 'incident_city', 'caller_city', 'expected_outcomes')}
    d['decl_hash'] = attacker_mod.decl_hash(d)
    d['decl_id'] = 'rt-' + attacker_mod.letters(d['decl_hash'][:12])
    return d


def decide_proposal(store, proposal_id, decision, actor):
    """Human approve -> appended to regression.jsonl (known_open until a replay passes); reject -> kept, never re-proposed."""
    if decision not in ('approve', 'reject') or not isinstance(actor, str) or not actor.strip():
        raise ValueError('Informe decisão (approve/reject) e ator.')
    with LOCK:
        rows = store.read('proposed')
        row = next((r for r in rows if r['proposal_id'] == proposal_id), None)
        if row is None:
            raise KeyError(proposal_id)
        if row['status'] != 'pending':
            raise ValueError('Proposta já decidida.')
        row.update(status='approved' if decision == 'approve' else 'rejected', decided_by=actor.strip(), decided_at=now())
        if decision == 'approve':
            store.append('regression', {'id': 'rg-' + row['key'][:10], 'key': row['key'], 'category': row['category'],
                                        'message': row['message'], 'places': row['places'],
                                        'incident_city': row['incident_city'], 'caller_city': row['caller_city'],
                                        'expected_outcomes': row['expected_outcomes'], 'known_open': True,
                                        'reasons_at_approval': row['reasons'], 'approved_by': actor.strip(),
                                        'approved_at': row['decided_at']})
        store.rewrite('proposed', rows)
    return row


def replay_regression(store, runner, update=True):
    """Re-run every approved regression case. known_open cases that now pass are marked fixed (permanent guards)."""
    entries = store.read('regression')
    decls = [_decl_of(e) for e in entries]
    verdicts = judge_all(decls, runner) if decls else {}
    out = []
    for e, d in zip(entries, decls):
        v = verdicts[d['decl_id']]
        was_open = bool(e.get('known_open'))
        out.append({'id': e['id'], 'category': e['category'], 'was_open': was_open, 'passed': v['passed'],
                    'fixed': was_open and v['passed'], 'regressed': not was_open and not v['passed'],
                    'reasons': v['reasons'], 'decision': v['decision'], 'route': v['route']})
        if update and was_open and v['passed']:
            e['known_open'], e['fixed_at'] = False, now()
    if update and any(o['fixed'] for o in out):
        store.rewrite('regression', entries)
    return out


def state(store):
    results = store.read('results')
    last = results[-1]['run_id'] if results else None
    latest = [r for r in results if r['run_id'] == last]
    return {'categories': [{'id': k, 'desc': v['desc'], 'accept': sorted(v['accept'])} for k, v in CATEGORIES.items()],
            'last_run': {'run_id': last, 'summary': summarize(latest), 'results': [
                {k: r.get(k) for k in ('decl_id', 'category', 'message', 'passed', 'reasons', 'decision', 'route', 'source',
                                       'unsafe_send', 'attacker_fallback_reason')} for r in latest]} if last else None,
            'proposals': store.read('proposed'),
            'regression': [{k: e.get(k) for k in ('id', 'category', 'known_open', 'fixed_at', 'approved_by')}
                           for e in store.read('regression')]}
