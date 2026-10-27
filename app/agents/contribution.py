"""Per-role agent contribution counters (what each agent actually did), persisted in runtime/agent_contribution.json.

Counted per processed message, from the finished case only (receipts, stage records, validated fields):
  fired            a real model call was made for the role
  changed_outcome  the role changed a validated field value or the credibility verdict (never a dispatch: humans approve)
  warned           the role produced a warning / objection that reached the case
  skipped          {reason: n} why the role did not run ('no_signal', 'certain_intake', 'no_candidate', budget reasons ...)
Counters are evidence for the ablation, not a quality score: a role that never fires is reported as such.
"""
import json
import os
import threading
import time
from pathlib import Path

from app.config import ROOT

ROLES = ('intake', 'critic', 'revision', 'verifier', 'location_agent', 'credibility_reviewer', 'hazard_critic',
         'duplicate_reviewer', 'arbiter')
LOCK = threading.RLock()


def path():
    return Path(os.environ.get('RTD_CONTRIBUTION_PATH') or ROOT/'runtime'/'agent_contribution.json')


def _values(fields):
    return {k: v.get('value') for k, v in (fields or {}).items() if isinstance(v, dict)}


def events_for(case):
    """{role: dict(fired, changed_outcome, warned, skipped)} for one finished case (skipped is a reason or None)."""
    receipts = [r for r in case.get('calls', []) if isinstance(r, dict) and r.get('source') != 'stage_boundary'
                and r.get('status') != 'skipped']
    called = {r.get('role') for r in receipts}
    stages = (case.get('latency_budget') or {}).get('stages', [])
    reasons = {}
    for row in stages:
        if row.get('status') == 'skipped' and row.get('reason'):
            reasons.setdefault(row.get('role') or row.get('stage'), row['reason'])
    out = {role: dict(fired=role in called, changed_outcome=False, warned=False, skipped=None) for role in ROLES}
    for role in ROLES:
        if not out[role]['fired']:
            out[role]['skipped'] = reasons.get(role)
    agents = case.get('agents') or {}
    critic = agents.get('critic')
    objections = critic.get('objections') if isinstance(critic, dict) else []
    out['critic']['warned'] = bool(objections)
    changed = _values(case.get('initial_fields')) != _values(case.get('fields'))
    out['revision']['changed_outcome'] = out['revision']['fired'] and changed
    verifier = (case.get('agents') or {}).get('verifier')
    diffs = verifier.get('diffs') or [] if isinstance(verifier, dict) else []
    out['verifier']['warned'] = bool(diffs)
    out['verifier']['changed_outcome'] = out['verifier']['fired'] and bool(diffs) and changed
    if not out['critic']['fired'] and not out['critic']['skipped'] and not out['verifier']['fired']:
        out['critic']['skipped'] = 'certain_intake'
    cred = case.get('credibility') or {}
    if cred:
        out['credibility_reviewer']['warned'] = cred.get('verdict') in ('doubtful', 'likely_fake')
        if not cred.get('signals') and not out['credibility_reviewer']['fired']:
            out['credibility_reviewer']['skipped'] = 'no_signal'
        elif cred.get('source') == 'agent' and cred.get('agent_verdict') is not None:
            from app.credibility.reviewer import rule_verdict
            out['credibility_reviewer']['changed_outcome'] = cred.get('verdict') != rule_verdict(cred.get('signals') or [])
    review = case.get('hazard_review')
    if isinstance(review, dict):
        out['hazard_critic']['warned'] = any(isinstance(v, list) and v for v in review.values())
    elif not out['hazard_critic']['skipped']:
        out['hazard_critic']['skipped'] = 'no_hydro_conflict'
    if 'duplicates' in case:
        reviews = [d.get('review') for d in case['duplicates'] if isinstance(d, dict)]
        out['duplicate_reviewer']['warned'] = any(isinstance(r, dict) and r.get('verdict') == 'same' for r in reviews)
        if not case['duplicates'] and not out['duplicate_reviewer']['fired']:
            out['duplicate_reviewer']['skipped'] = 'no_candidate'
    arbitration = [e for e in case.get('arbitration', []) if isinstance(e, dict)]
    out['arbiter']['warned'] = any(e.get('verdict') == 'ESCALATE' for e in arbitration)
    out['arbiter']['changed_outcome'] = any(e.get('method') == 'model' and e.get('verdict') == 'ESCALATE' for e in arbitration)
    if not arbitration and not out['arbiter']['fired']:
        out['arbiter']['skipped'] = 'no_conflict'
    return out


def _read(target):
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) and isinstance(data.get('roles'), dict) else None
    except (OSError, ValueError):
        return None


def empty():
    return dict(messages=0, updated_at=None, roles={r: dict(fired=0, changed_outcome=0, warned=0, skipped={}) for r in ROLES})


def apply(data, events):
    data['messages'] += 1
    for role, ev in events.items():
        row = data['roles'].setdefault(role, dict(fired=0, changed_outcome=0, warned=0, skipped={}))
        for key in ('fired', 'changed_outcome', 'warned'):
            row[key] += 1 if ev[key] else 0
        if ev['skipped'] and not ev['fired']:
            row['skipped'][ev['skipped']] = row['skipped'].get(ev['skipped'], 0)+1
    data['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    return data


def observe(case, target=None):
    """Add one finished case to the persisted counters. Telemetry only: never raises into a rescue decision."""
    try:
        target = Path(target) if target else path()
        events = events_for(case)
        with LOCK:
            data = _read(target) or empty()
            apply(data, events)
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = target.with_suffix('.tmp')
            pending.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            os.replace(pending, target)
        return events
    except Exception:
        return None


def snapshot(target=None):
    data = _read(Path(target) if target else path()) or empty()
    data['n_messages'] = data['messages']
    return data


def handle(handler, path_):
    """GET /api/agents/contribution -> counters (JSON)."""
    if path_ != '/api/agents/contribution':
        return False
    handler.send_json(200, snapshot())
    return True
