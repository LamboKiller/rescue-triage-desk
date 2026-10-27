"""Synthetic surge against the real HTTP desk; stdlib only, no provider calls offline.

Default live workload is burst 20 followed by Poisson 6/min for five minutes.
Offline starts an isolated real desk process with a latency-shaped fake provider.
"""
import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.failures import failure_counts as classify

DATA = ROOT/'data/load'
REPLAY = '2024-05-08T12:00:00-03:00'


def generate(count, seed=7, tag='synthetic'):
    """Fresh authored templates × repository streets; metadata never enters model prompts."""
    rng = random.Random(seed)
    templates = json.loads((DATA/'templates.json').read_text(encoding='utf-8'))
    with (ROOT/'data/streets_flood.csv').open(encoding='utf-8-sig', newline='') as stream:
        streets = sorted({(r['display_name'], r['municipality']) for r in csv.DictReader(stream)
                          if r['municipality'] in ('Porto Alegre', 'Canoas') and
                          len(r['display_name']) > 9})
    kinds = ['repost'] * (count//10)
    for kind in ('injection', 'volunteer', 'not_rescue'):
        kinds += [kind] * (count//20)
    kinds += ['rescue'] * (count-len(kinds))
    rng.shuffle(kinds)
    if kinds and kinds[0] == 'repost':
        at = next(i for i, k in enumerate(kinds) if k == 'rescue')
        kinds[0], kinds[at] = kinds[at], kinds[0]
    rows, originals = [], []
    for i, kind in enumerate(kinds):
        street, city = rng.choice(streets)
        args = dict(street=street, city=city, number=100+i*3, people=rng.randint(2, 12),
                    children=rng.randint(0, 2), water=rng.choice(templates['water']),
                    medical=rng.choice(templates['medical']))
        row = dict(message_id=f'load-{tag}-{seed}-{i:05d}', synthetic=True, kind=kind)
        if kind == 'repost':
            parent = rng.choice(originals)
            row.update(text=parent['text'], repost_of=parent['message_id'])
        else:
            template = templates[kind] if kind in ('volunteer', 'not_rescue') else rng.choice(templates['rescue'])
            row['text'] = template.format(**args)
            if kind == 'injection':
                row['text'] = templates['injection'] + row['text']
            if kind == 'rescue':
                originals.append(row)
        rows.append(row)
    return rows


def arrivals(burst=0, rate=0, minutes=0, seed=7):
    if burst < 0 or rate < 0 or minutes < 0 or not all(math.isfinite(x) for x in (rate, minutes)):
        raise ValueError('arrival inputs must be finite and nonnegative')
    out, elapsed, rng = [0.] * burst, 0., random.Random(seed)
    if rate:
        while True:
            elapsed += rng.expovariate(rate/60)
            if elapsed >= minutes*60:
                break
            out.append(elapsed)
    return out


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    index = (len(values)-1)*q/100
    lo, hi = math.floor(index), math.ceil(index)
    return round(values[lo] + (values[hi]-values[lo])*(index-lo), 6)


def unsafe(case):
    decision = (case.get('result') or {}).get('decision', '')
    landmark = case.get('landmark_check') or {}
    location = case.get('location_resolution') or {}
    valid = ((case.get('checks') or {}).get('found') is True or
             (landmark.get('status') == 'resolved' and not landmark.get('context_only')) or
             location.get('validated') is True)
    return decision.startswith('SEND') and not valid


def request(url, path, payload=None, timeout=5):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url.rstrip('/')+path, data=body,
                                 headers={'Content-Type': 'application/json'} if body else {})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    value = json.loads(raw) if raw[:1] in (b'{', b'[') else None
    return status, value, time.monotonic()-start


def rss_bytes(pid):
    """Actual target process RSS; None means unavailable, never zero-filled."""
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes as w
            class Counters(ctypes.Structure):
                _fields_ = [('cb', w.DWORD), ('faults', w.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ('peak', 'working', 'quota_peak_paged',
                    'quota_paged', 'quota_peak_nonpaged', 'quota_nonpaged', 'pagefile', 'peak_pagefile')]
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
            kernel.OpenProcess.restype = w.HANDLE
            kernel.CloseHandle.argtypes = [w.HANDLE]
            proc = kernel.OpenProcess(0x410, False, pid)
            if not proc:
                return None
            try:
                info = Counters()
                info.cb = ctypes.sizeof(info)
                api = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
                api.argtypes = [w.HANDLE, ctypes.POINTER(Counters), w.DWORD]
                return int(info.working) if api(proc, ctypes.byref(info), info.cb) else None
            finally:
                kernel.CloseHandle(proc)
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                return int(line.split()[1])*1024
    except (OSError, ValueError):
        return None


def identities(case):
    ids = {case.get('message_id')}
    ids.update(f.get('message_id') for f in case.get('facts', []))
    ids.update(r.get('message_id') for r in case.get('linked_reports', []) if not r.get('unlinked'))
    return ids - {None}


def stream(url, run_id, events, stop, timeout):
    try:
        req = urllib.request.Request(url+'/api/runs/'+run_id+'/events')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if 'text/event-stream' not in response.headers.get('Content-Type', ''):
                raise ValueError('wrong SSE content type')
            for raw in response:
                if stop.is_set():
                    break
                line = raw.decode('utf-8').strip()
                if line.startswith('data: '):
                    events.put((time.monotonic(), json.loads(line[6:])))
                elif line.startswith(':'):
                    events.put((time.monotonic(), {'stage': 'heartbeat'}))
    except (OSError, ValueError) as exc:
        events.put((time.monotonic(), {'stage': 'stream_error', 'error': type(exc).__name__}))
    finally:
        events.put((time.monotonic(), {'stage': 'stream_closed', 'run_id': run_id}))


def measure(url, messages, schedule, *, max_minutes=15, sample_seconds=5, pid=None,
            arrival_scale=1, latency_source=None, latency_scale=1, batch_size=15, mode='live'):
    """Keep all inputs, including refused/unfinished ones, in the written manifest.

    Busy rejections are retained in the harness queue and retried explicitly. That
    queue is NOT desk visibility and never counts as server graceful degradation.
    """
    started = time.monotonic()
    end = started+max_minutes*60
    records = {m['message_id']: dict(m, arrival_seconds=t*arrival_scale, attempts=0)
               for m, t in zip(messages, schedule)}
    by_case = {hashlib.sha256(mid.encode()).hexdigest()[:24]: mid for mid in records}
    waiting, active, index = collections.deque(), {}, 0
    first, analyses, all_cases, ui, backlog, memory = {}, {}, {}, [], [], []
    events, probes, stop = queue.Queue(), queue.Queue(), threading.Event()
    sse = dict(streams=0, events=0, heartbeats=0, errors=0, done=0, closed=0,
               decisions=0, max_event_gap_seconds=0.)
    failures_http, transport, retry_count = collections.Counter(), [], 0
    last_event, next_sample, next_poll, next_submit = started, started, started, started
    visibility = dict(hidden_pending_peak=0, pending_without_label_or_age=0,
                      priority_order_violations=0, priority_samples=0)
    threads = []
    seen = set()
    def http(path, payload=None):
        status, value, seconds = request(url, path, payload, timeout=max(.05, min(5, end-time.monotonic())))
        if status >= 500:
            failures_http[str(status)] += 1
        return status, value, seconds
    def note_case(case, now):
        for mid in identities(case) & records.keys():
            first.setdefault(mid, now-started-records[mid]['arrival_seconds'])
            records[mid]['case_id'] = case.get('case_id')
            # Linked reports retain their own analysis/latency, not the primary's.
            analysis = next((r.get('payload') for r in case.get('linked_reports', [])
                             if r.get('message_id') == mid and not r.get('unlinked')), None)
            analyses[mid] = analysis or case
        if case.get('case_id'):
            all_cases[case['case_id']] = case
    def probe(path):
        due = started
        while not stop.is_set() and time.monotonic() < end:
            if stop.wait(max(0, due-time.monotonic())):
                break
            at = time.monotonic()
            try:
                status, value, seconds = request(url, path, timeout=max(.05, min(5, end-at)))
                error = None
            except (OSError, ValueError) as exc:
                status, value, seconds, error = None, None, time.monotonic()-at, type(exc).__name__
            probes.put((path, at, time.monotonic(), status, value, seconds, error))
            due = max(due+sample_seconds, time.monotonic())
    def consume_probes():
        nonlocal seen
        while True:
            try:
                path, at, finished, status, value, seconds, error = probes.get_nowait()
            except queue.Empty:
                break
            ui.append(dict(path=path, at_seconds=at-started, seconds=seconds,
                           status=status, incomplete=bool(error)))
            if status is not None and status >= 500:
                failures_http[str(status)] += 1
            if error:
                transport.append(dict(path=path, error=error))
            if path != '/api/cases' or status != 200:
                continue
            cases = (value or {}).get('cases', [])
            priorities = [(c.get('live_priority') or {}).get('score') for c in cases]
            if priorities and all(isinstance(p, (int, float)) for p in priorities):
                visibility['priority_samples'] += 1
                visibility['priority_order_violations'] += int(priorities != sorted(priorities, reverse=True))
            seen = set()
            for case in cases:
                seen.update(identities(case))
                if (case.get('result') or {}).get('decision') not in (None, 'PENDING', 'QUEUED'):
                    note_case(case, finished)
                else:
                    marked = 'em fila' in json.dumps(case, ensure_ascii=False).casefold()
                    aged = any(k in case for k in ('age_seconds', 'queue_age_seconds', 'age_hours'))
                    visibility['pending_without_label_or_age'] += int(not marked or not aged)
            # Compare only attempts made before the probe started, avoiding
            # a false visibility failure for arrivals concurrent with its GET.
            attempted_pending = {mid for mid, r in records.items() if
                r.get('first_attempt_seconds', math.inf) <= at-started and mid not in first}
            visibility['hidden_pending_peak'] = max(visibility['hidden_pending_peak'], len(attempted_pending-seen))
    probe_threads = [threading.Thread(target=probe, args=(path,), daemon=True)
                     for path in ('/api/cases', '/v2')]
    for thread in probe_threads:
        thread.start()
    while time.monotonic() < end:
        now = time.monotonic()
        while index < len(messages) and schedule[index]*arrival_scale <= now-started:
            waiting.append(messages[index]['message_id'])
            index += 1
        while True:
            try:
                at, event = events.get_nowait()
            except queue.Empty:
                break
            stage = event.get('stage')
            sse['max_event_gap_seconds'] = max(sse['max_event_gap_seconds'], at-last_event)
            last_event = at
            if stage == 'stream_error':
                sse['errors'] += 1
            elif stage == 'stream_closed':
                sse['closed'] += 1
            elif stage == 'heartbeat':
                sse['heartbeats'] += 1
            else:
                sse['events'] += 1
                if stage == 'done':
                    sse['done'] += 1
                if stage == 'decision':
                    sse['decisions'] += 1
                    mid = by_case.get(event.get('case_id'))
                    if mid:
                        first.setdefault(mid, at-started-records[mid]['arrival_seconds'])
                        records[mid]['first_decision_source'] = 'SSE'
        consume_probes()
        if now >= next_sample:
            pending = {m['message_id'] for m in messages[:index]} - first.keys()
            backlog.append(dict(at_seconds=now-started, arrived=index, decided=len(first),
                                queued=len(pending), client_waiting=len(waiting),
                                server_visible_pending=len(pending & seen)))
            if pid:
                memory.append(dict(at_seconds=now-started, rss_bytes=rss_bytes(pid)))
            next_sample = time.monotonic()+sample_seconds
        if active and now >= next_poll:
            for run_id, ids in list(active.items()):
                if time.monotonic() >= end:
                    break
                try:
                    status, value, _ = http('/api/runs/'+run_id)
                    if status == 200 and value.get('status') not in ('running', 'queued', 'pending'):
                        for case in (value.get('result') or {}).get('cases', []):
                            note_case(case, time.monotonic())
                        if value.get('status') == 'failed':
                            for mid in ids:
                                records[mid]['run_failed'] = True
                        del active[run_id]
                    elif status != 200:
                        transport.append(dict(path='run_poll', status=status))
                except (OSError, ValueError) as exc:
                    transport.append(dict(path='run_poll', error=type(exc).__name__))
            next_poll = time.monotonic()+.15
        # Probe intake even while active so surge rejection is measured, not hidden.
        if waiting and now >= next_submit:
            fresh = [mid for mid in waiting if records[mid]['attempts'] == 0]
            ids = (fresh or list(waiting))[:batch_size]
            payload = dict(replay_time=REPLAY, async_=True, messages=[
                dict(message_id=mid, text=records[mid]['text'], received_at=REPLAY, synthetic=True) for mid in ids])
            payload['async'] = payload.pop('async_')
            for mid in ids:
                records[mid].setdefault('first_attempt_seconds', time.monotonic()-started)
                records[mid]['attempts'] += 1
            try:
                status, value, _ = http('/run', payload)
                if status == 202 and value.get('run_id'):
                    for mid in ids:
                        waiting.remove(mid)
                        records[mid]['submitted_seconds'] = time.monotonic()-started
                        records[mid]['run_id'] = value['run_id']
                    active[value['run_id']] = ids
                    sse['streams'] += 1
                    thread = threading.Thread(target=stream, args=(url, value['run_id'], events, stop,
                        max(.1, end-time.monotonic())), daemon=True)
                    thread.start()
                    threads.append(thread)
                elif status == 400 and 'ativa' in str((value or {}).get('error', '')).casefold():
                    retry_count += 1
                else:
                    for mid in ids:
                        waiting.remove(mid)
                        records[mid]['rejected_status'] = status
            except (OSError, ValueError) as exc:
                # Ambiguous POSTs are not retried: the response could have been lost after acceptance.
                for mid in ids:
                    if mid in waiting:
                        waiting.remove(mid)
                    records[mid]['submission_unknown'] = type(exc).__name__
                transport.append(dict(path='/run', error=type(exc).__name__))
            fresh_waiting = any(records[mid]['attempts'] == 0 for mid in waiting)
            next_submit = time.monotonic()+(0 if fresh_waiting else .5)
        if index == len(messages) and not waiting and not active:
            # Drain the SSE journal before the next loop decides to exit.
            if all(not t.is_alive() for t in threads) and events.empty() and len(ui) >= 2:
                break
        time.sleep(.01)
    elapsed = time.monotonic()-started
    stop.set()
    cleanup_deadline = time.monotonic()+.5
    for thread in threads+probe_threads:
        thread.join(timeout=max(0, cleanup_deadline-time.monotonic()))
    consume_probes()
    arrived_ids = {m['message_id'] for m in messages[:index]}
    persisted = set().union(*(identities(c) for c in all_cases.values())) if all_cases else set()
    successful = arrived_ids & persisted
    pending_ids = arrived_ids-successful
    missing = {mid for mid in pending_ids if records[mid].get('rejected_status') or
               records[mid].get('submission_unknown') or records[mid].get('run_failed')}
    waits, stage_failures, degraded = [], collections.Counter(), 0
    for mid, case in analyses.items():
        stages = (case.get('latency_budget') or {}).get('stages') or []
        # provider_queue and ran repeat the same wait; count each terminal call
        # once (a role may make several distinct location/duplicate calls).
        queue_total = 0.
        for row in stages:
            if row.get('status') in ('ran', 'code_fallback'):
                queue_total += row.get('queue_seconds', 0) or 0
            if row.get('status') == 'code_fallback' or row.get('availability') == 'stage_unavailable':
                kind = classify([dict(latency_budget={'stages': [row]}, complete=False)])
                stage_failures.update({k: v for k, v in kind.items() if v})
        waits.append(queue_total)
        records[mid]['queue_wait_seconds'] = queue_total
        records[mid]['decision'] = (case.get('result') or {}).get('decision')
        records[mid]['failure_kind'] = next((k for k, n in classify([case]).items() if n), None)
        degraded += bool(case.get('minimal_path') or case.get('review_degraded') or
                         (case.get('latency_budget') or {}).get('provider_pressure'))
    owners = {mid: cid for cid, c in all_cases.items() for mid in identities(c)}
    duplicates = [m for m in messages if m.get('repost_of') and m['message_id'] in successful]
    dedup = dict(expected=sum(bool(m.get('repost_of')) for m in messages), evaluated=len(duplicates),
                 correct=sum(owners.get(m['message_id']) == owners.get(m['repost_of']) for m in duplicates))
    false_links = 0
    for c in all_cases.values():
        mids = identities(c) & records.keys()
        originals = {records[mid].get('repost_of', mid) for mid in mids}
        false_links += int(len(originals) > 1)
    dedup['incorrect_merges'] = false_links
    latencies = [r['seconds'] for r in ui if r['seconds'] is not None]
    peak = max((b['queued'] for b in backlog), default=0)
    wall_ui95 = percentile(latencies, 95)
    report = dict(synthetic=True, mode=mode, url=url,
        generated=len(messages), arrived=index, decided=len(first), persisted=len(successful),
        attempted=sum(r['attempts'] > 0 for r in records.values()),
        dropped=len(missing), pending=len(pending_ids-missing), not_arrived=len(messages)-index,
        guard_hit=time.monotonic() >= end, elapsed_seconds=elapsed,
        decision_seconds=dict(p50=percentile(list(first.values()), 50), p95=percentile(list(first.values()), 95)),
        queue_wait_seconds=dict(p50=percentile(waits, 50), p95=percentile(waits, 95)),
        intake_wait_seconds={f'p{q}': percentile([
            max(0, r['submitted_seconds']-r['arrival_seconds']) for r in records.values()
            if 'submitted_seconds' in r], q) for q in (50, 95)},
        arrival_lag_seconds={f'p{q}': percentile([
            max(0, r['first_attempt_seconds']-r['arrival_seconds']) for r in records.values()
            if 'first_attempt_seconds' in r], q) for q in (50, 95)},
        throughput_msgs_min=len(successful)/elapsed*60 if elapsed else 0,
        unsafe_proxy=sum(unsafe(c) for c in analyses.values()),
        decision_mix=dict(collections.Counter((c.get('result') or {}).get('decision', 'UNKNOWN') for c in analyses.values())),
        failures=classify(list(analyses.values())), stage_failures=dict(stage_failures),
        degraded_mode_activations=degraded, busy_rejections=retry_count,
        http_5xx=dict(failures_http), transport_errors=transport, sse=sse,
        backlog_peak=peak, backlog=backlog, ui_samples=ui,
        ui_latency_seconds=dict(p50=percentile(latencies, 50), p95=wall_ui95,
                               over_1s=sum(t > 1 for t in latencies)),
        memory=dict(pid=pid, samples=memory, peak_rss_bytes=max(
            (s['rss_bytes'] for s in memory if s['rss_bytes'] is not None), default=None)),
        graceful_degradation=visibility, dedup=dedup, latency_source=latency_source,
        latency_scale=latency_scale, arrival_scale=arrival_scale,
        messages=[dict(r, first_decision_seconds=first.get(mid), persisted=mid in successful)
                  for mid, r in records.items()])
    report['acceptance'] = dict(no_dropped=not missing, all_decided=len(successful) == len(messages),
        all_attempted=report['attempted'] == len(messages),
        no_unsafe=report['unsafe_proxy'] == 0, ui_p95_under_1s=wall_ui95 is not None and wall_ui95 < 1,
        no_5xx=not failures_http, sse_healthy=sse['errors'] == 0 and sse['done'] == sse['streams'],
        ui_healthy=bool(ui) and all(row['status'] == 200 for row in ui),
        transport_healthy=not transport,
        every_pending_visible=visibility['hidden_pending_peak'] == 0,
        pending_marked_with_age=visibility['pending_without_label_or_age'] == 0 and visibility['hidden_pending_peak'] == 0,
        priority_order=visibility['priority_samples'] > 0 and visibility['priority_order_violations'] == 0,
        dedup_correct=dedup['correct'] == dedup['expected'] and false_links == 0)
    return report


def write_report(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6]
    target = directory/(stamp+'.json')
    markdown = target.with_suffix('.md')
    report.update(report_json=str(target.resolve()), report_markdown=str(markdown.resolve()))
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines = [f"# Synthetic load: {report['mode']}", '',
        f"Generated {report['generated']}; decided {report['decided']}; persisted {report['persisted']}; "
        f"dropped {report['dropped']}; pending {report['pending']}; guard hit {report['guard_hit']}.",
        f"Decision p50/p95 (wall seconds): {report['decision_seconds']}; backlog peak {report['backlog_peak']}.",
        f"Throughput: {report['throughput_msgs_min']:.2f} persisted messages/min (wall time).",
        f"Failures: {report['failures']}; stage failures: {report['stage_failures']}.",
        f"UI latency: {report['ui_latency_seconds']}; HTTP 5xx: {report['http_5xx']}.",
        f"Unsafe proxy {report['unsafe_proxy']}; degraded activations {report['degraded_mode_activations']}.",
        f"SSE: {report['sse']}; RSS peak bytes: {report['memory']['peak_rss_bytes']}.",
        f"Dedup: {report['dedup']}; overload visibility: {report['graceful_degradation']}.",
        f"Arrival scale {report['arrival_scale']}; provider sleep scale {report['latency_scale']}.",
        'Scaled runs are functional stress exercises; their wall latency is not a live forecast.', '',
        '## Acceptance', '']
    lines += [f"- {'PASS' if ok else 'FAIL'}: {name}" for name, ok in report['acceptance'].items()]
    markdown.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return report


class FakeClient:
    """Explicit synthetic proposal client; no answer dumps or evaluation labels.

    Piecewise uniform min/median/max matches the retained role summaries only;
    no measured distribution or token throughput was available in that artifact.
    """
    def __init__(self, rows, latency_scale, seed):
        self.rows, self.scale, self.seed = rows, latency_scale, seed
        self.local = threading.local()
        self.profile = json.loads((DATA/'LIVEFIX6_LATENCY.json').read_text(encoding='utf-8'))['role_seconds']
        from app.llm.nightshift import FairSlots
        self.slots = FairSlots(limit=2)

    def call(self, role, system, payload, deadline):
        start = time.monotonic()
        admitted = self.slots.acquire(timeout=max(0, deadline-start))
        waited = time.monotonic()-start
        observer = getattr(self.local, 'queue_observer', None)
        if observer:
            observer(waited, admitted)
        if not admitted:
            raise TimeoutError('synthetic provider admission deadline')
        try:
            key = hashlib.sha256((str(self.seed)+role+str(payload)).encode()).digest()
            rng = random.Random(int.from_bytes(key[:8], 'big'))
            p = self.profile.get(role, self.profile['critic'])
            u = rng.random()
            seconds = (p['min']+(p['median']-p['min'])*u*2 if u < .5 else
                       p['median']+(p['max']-p['median'])*(u-.5)*2)*self.scale
            remaining = deadline-time.monotonic()
            time.sleep(max(0, min(seconds, remaining)))
            if seconds >= remaining:
                raise TimeoutError('synthetic provider latency deadline')
            if role in ('intake', 'revision'):
                from app.agents.baseline import extract
                text = re.search(r'<<<(.*?)>>>', payload, re.S).group(1)
                fields = extract(text, self.rows)['fields']
                rename = dict(risk_words='risk', already_rescued='rescued')
                out = {rename.get(k, k): v['quote'] for k, v in fields.items() if k != 'conflicting_counts'}
            elif role == 'critic':
                out = {'objections': []}
            elif role == 'hazard_critic':
                out = {'block': [], 'warn': []}
                for fact in json.loads(payload).get('facts', []):
                    if fact['id'].startswith('fleet:'):
                        text = fact['text_pt'].casefold()
                        if 'unsafe' in text:
                            out['block'].append(fact['id'])
                        elif 'caution' in text:
                            out['warn'].append(fact['id'])
            elif role == 'location_agent':
                out = {'answer': {'candidate_id': None, 'precision': 'area', 'evidence': []}}
            elif role == 'credibility_reviewer':
                signals = json.loads(payload)['signals']
                out = dict(verdict='doubtful' if signals else 'credible', reasons=[
                    dict(signal_id=s['id'], quote=s['quote']) for s in signals[:2]])
            elif role == 'duplicate_reviewer':
                data = json.loads(payload)
                same = data['A']['message'] == data['B']['message']
                out = dict(verdict='same' if same else 'unsure', reason_pt='Comparação sintética.',
                    evidence=[dict(case=k, quote=data[k]['message']) for k in ('A', 'B')] if same else [])
            elif role == 'arbiter':
                out = {'choice': 'ESCALATE'}
            else:
                raise ValueError('unsupported fake role: '+role)
            return out, dict(role=role, model='SYNTHETIC-load-fake', receipt='synthetic',
                             seconds=time.monotonic()-start, queue_seconds=waited, route_kind='offline_fake')
        finally:
            self.slots.release()


def serve_offline(workdir, port, latency_scale, seed):
    # Everything this child writes lives in its unique run directory. Never load .env.
    from app.data.source import LocalSource
    from app.engines.world_model.registry import Registry
    import app.pipeline as pipeline_module
    import app.web.server as web
    workdir = Path(workdir)
    (workdir/'runtime').mkdir(parents=True, exist_ok=True)
    (workdir/'logs').mkdir(exist_ok=True)
    class CachedSource(LocalSource):
        def __init__(self):
            self._streets, self._landmarks = super().streets(), super().landmarks()
        def streets(self, timeout=120):
            return self._streets
        def landmarks(self, timeout=120):
            return self._landmarks
    source = CachedSource()
    pipeline_module.ROOT = workdir
    web.ROOT = workdir
    pipeline = pipeline_module.Pipeline(Registry(workdir/'runtime/events.jsonl'),
        source=source, client=FakeClient(source.streets(), latency_scale, seed))
    server = web.create_server('127.0.0.1', port, sample=True, pipeline=pipeline)
    (workdir/'ready.json').write_text(json.dumps(dict(port=server.server_port, pid=os.getpid())), encoding='utf-8')
    try:
        server.serve_forever()
    finally:
        server.server_close()


def run_offline(workdir, count=None, seed=7, latency_scale=1, max_minutes=15,
                sample_seconds=5, schedule=None, arrival_scale=1, outdir=None):
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    schedule = [0.] * (count or 0) if schedule is None else schedule
    messages = generate(len(schedule), seed, tag=workdir.name)
    with (workdir/'server.log').open('w', encoding='utf-8') as log:
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve-offline',
            '--workdir', str(workdir), '--port', '0', '--latency-scale', str(latency_scale), '--seed', str(seed)],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            env=dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'))
        try:
            deadline = time.monotonic()+90
            while not (workdir/'ready.json').exists():
                if proc.poll() is not None:
                    raise RuntimeError(f'offline desk exited; inspect {workdir / "server.log"}')
                if time.monotonic() >= deadline:
                    raise TimeoutError('offline desk startup')
                time.sleep(.1)
            ready = json.loads((workdir/'ready.json').read_text(encoding='utf-8'))
            report = measure(f"http://127.0.0.1:{ready['port']}", messages, schedule, max_minutes=max_minutes,
                sample_seconds=sample_seconds, pid=ready['pid'], latency_source='data/load/LIVEFIX6_LATENCY.json',
                arrival_scale=arrival_scale, latency_scale=latency_scale, mode='offline_fake')
            return write_report(report, outdir or workdir/'reports')
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--offline', action='store_true')
    modes.add_argument('--live', action='store_true')
    parser.add_argument('--url')
    parser.add_argument('--burst', type=int)
    parser.add_argument('--rate', type=float)
    parser.add_argument('--minutes', type=float)
    parser.add_argument('--max-minutes', type=float, default=15)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--pid', type=int, help='local server PID for RSS sampling')
    parser.add_argument('--latency-scale', type=float, default=1)
    parser.add_argument('--arrival-scale', type=float, default=1)
    parser.add_argument('--out', type=Path, default=ROOT/'out/load')
    parser.add_argument('--serve-offline', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--workdir', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--port', type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not all(math.isfinite(x) and x > 0 for x in (args.latency_scale, args.arrival_scale, args.max_minutes)):
        parser.error('scales and max-minutes must be finite and positive')
    if args.serve_offline:
        serve_offline(args.workdir, args.port, args.latency_scale, args.seed)
        return 0
    if args.live and not args.url:
        parser.error('--live requires --url of the running desk')
    if args.live and (args.latency_scale != 1 or args.arrival_scale != 1):
        parser.error('live mode requires real-time scales of 1')
    explicit = args.burst is not None or args.rate is not None
    burst = args.burst if args.burst is not None else (0 if explicit else 20 if args.live else 300)
    rate = args.rate if args.rate is not None else (0 if explicit else 6 if args.live else 30)
    minutes = args.minutes if args.minutes is not None else (5 if args.live else 10)
    try:
        schedule = arrivals(burst, rate, minutes, args.seed)
    except ValueError as exc:
        parser.error(str(exc))
    if not schedule:
        parser.error('workload has no messages')
    args.out.mkdir(parents=True, exist_ok=True)
    if args.live or args.url:
        status, health, _ = request(args.url, '/api/health')
        want = 'live' if args.live else 'sample_offline'
        if status != 200 or health.get('mode') != want:
            parser.error('server mode does not match requested mode')
        report = measure(args.url, generate(len(schedule), args.seed, uuid.uuid4().hex[:8]), schedule,
            max_minutes=args.max_minutes, pid=args.pid, arrival_scale=args.arrival_scale,
            mode='live' if args.live else 'offline_external')
        write_report(report, args.out)
    else:
        workdir = args.out/('desk-'+uuid.uuid4().hex[:10])
        report = run_offline(workdir, seed=args.seed, schedule=schedule, latency_scale=args.latency_scale,
            arrival_scale=args.arrival_scale, max_minutes=args.max_minutes, outdir=args.out)
    print(json.dumps({k: report[k] for k in ('generated', 'decided', 'dropped', 'pending',
        'decision_seconds', 'backlog_peak', 'ui_latency_seconds', 'unsafe_proxy', 'acceptance', 'report_json')}, indent=2))
    return 0 if all(report['acceptance'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
