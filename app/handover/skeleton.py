"""Deterministic handover skeleton. Every line is derived from a record and carries an id the summary must cite.
Code computes every number; nothing here calls a model. Replay clock only: records after `now` are invisible (no hindsight)."""
import json
from app.decide import timestamp
from app.priority import queue, hours
from app.supervisor.detectors import is_open, visible
from app.flow.build import build_flow

SEND = ('SEND', 'SEND_CANDIDATE')
NEAR_FULL = 0.2  # remaining/capacity at or below this = "perto da lotação"
TOP = 8


def _item(i, text, **kw):
    return {'id': i, 'text_pt': text, **kw}


def _section(key, title, items, total=None, unavailable=None):
    return {'key': key, 'title_pt': title, 'count': len(items) if total is None else total, 'items': items[:TOP],
            'truncated': len(items) > TOP, **({'unavailable_pt': unavailable} if unavailable else {})}


def _safe(key, title, fn):
    try:
        return fn()
    except Exception as exc:  # visible, never silent
        return _section(key, title, [], 0, 'Indisponível nesta passagem (%s).' % type(exc).__name__)


def default_now(cases, day):
    ok = []
    for c in cases:
        for k in ('replay_time', 'received_at'):
            s = c.get(k)
            if isinstance(s, str) and s[:10] <= day:
                try:
                    timestamp(s)
                    ok.append(s)
                except ValueError:
                    pass
    return max(ok, key=timestamp) if ok else day + 'T23:59:00-03:00'


def build(registry, now, *, shelters=None, supervisor=None, missions=None, volunteers=None, contradictions=None, unit_status_fn=None):
    timestamp(now)
    from app.handover.replay import snapshot
    history = snapshot(registry, now)
    cases = visible(history.read(), now)
    q = [c for c in queue(cases, now) if is_open(c)]

    def send_cases():
        rows = [c for c in q if c.get('result', {}).get('decision') in SEND and not c.get('status', '').startswith('ASSIGNED:')]
        rows.sort(key=lambda c: (-c['live_priority']['score'], c['received_at'], c['case_id']))
        items = [_item(c['case_id'], 'caso %s: prioridade %s, espera %s h, %s pessoa(s), status %s' % (
            c['case_id'], c['live_priority']['score'], round(hours(now, c['received_at']), 1),
            (c.get('fields', {}).get('people') or {}).get('value', 'desconhecido'), c.get('status')), case_ids=[c['case_id']]) for c in rows]
        return _section('send_cases', 'Casos SEND abertos (prioridade, depois espera)', items, len(rows))

    def loops():
        flow = build_flow(registry.path, now=timestamp(now).timestamp(), use_cache=False,
                          journal_lines=history.path.read_text().splitlines())
        rows = []
        for lp in flow['open_loops']:
            if lp.get('kind') == 'redteam' or not lp.get('case_ids') or not isinstance(lp.get('ts'), str):
                continue
            try:
                if timestamp(lp['ts']) > timestamp(now):
                    continue
                rows.append((hours(now, lp['ts']), lp))
            except ValueError:
                continue
        rows.sort(key=lambda r: (-r[0], r[1]['id']))
        items = [_item(lp['id'], 'ciclo aberto %s (%s) há %s h; casos %s' % (lp['id'], lp['kind'], round(a, 1), ', '.join(lp['case_ids'])),
                       case_ids=lp['case_ids']) for a, lp in rows]
        return _section('open_loops', 'Ciclos abertos, mais antigos primeiro', items, len(rows))

    def callbacks():
        rows = [c for c in q if c.get('result', {}).get('decision') == 'CALLBACK' or c.get('status') == 'callback_requested']
        items = [_item(c['case_id'], 'retorno pendente no caso %s: status %s, espera %s h' % (
            c['case_id'], c.get('status'), round(hours(now, c['received_at']), 1)), case_ids=[c['case_id']]) for c in rows]
        return _section('callbacks', 'Retornos pendentes', items, len(rows))

    def active_missions():
        by = {}
        for c in q:
            if c.get('status', '').startswith('ASSIGNED:'):
                by.setdefault(c.get('mission_id') or c['status'][9:], []).append(c['case_id'])
        items = [_item(m, 'missão %s em andamento com %s caso(s): %s' % (m, len(ids), ', '.join(sorted(ids))), case_ids=sorted(ids))
                 for m, ids in sorted(by.items())]
        return _section('missions', 'Missões em andamento', items)

    def shelter_rows():
        rows = [s for s in shelters.listing(now)['shelters'] if s.get('capacity_known') and s.get('capacity_total')
                and (s['full'] or s['remaining'] / s['capacity_total'] <= NEAR_FULL)]
        rows.sort(key=lambda s: (s['remaining'] / s['capacity_total'], s['shelter_id']))
        items = [_item(s['shelter_id'], 'abrigo %s: %s de %s vagas livres%s' % (s['shelter_id'], s['remaining'], s['capacity_total'],
                 ' (lotado)' if s['full'] else ''), case_ids=[]) for s in rows]
        return _section('shelters', 'Abrigos perto da lotação (só com capacidade conhecida)', items, len(rows))

    def alerts():
        from app.supervisor.service import SupervisorService
        rows = [a for a in SupervisorService(history).state()['alerts'].values() if timestamp(a['created_at']) <= timestamp(now)
                and (a['status'] == 'open' or (a['status'] == 'accepted' and a['outcome'] != 'resolved'))]
        rows.sort(key=lambda a: (a['created_at'], a['alert_id']))
        items = [_item(a['alert_id'], 'alerta %s (%s, %s) sem resolução: %s' % (a['alert_id'], a['kind'], a['status'], a['why_pt']),
                       case_ids=list(a.get('case_ids') or [])) for a in rows]
        return _section('alerts', 'Alertas do supervisor sem resolução', items, len(rows))

    def risks():
        items = []
        for c in q:
            m = c.get('medical')
            if m and m.get('window_exceeded'):
                items.append((0, c['case_id'], _item('risk:%s:medical' % c['case_id'], 'caso %s: janela médica estimada de %s a %s h excedida (espera %s h)' % (
                    c['case_id'], m['time_to_harm_hours'][0], m['time_to_harm_hours'][1], m['waited_hours']), case_ids=[c['case_id']])))
            elif c.get('stale_info', {}).get('stale'):
                items.append((1, c['case_id'], _item('risk:%s:stale' % c['case_id'], 'caso %s: sem atualização há %s h' % (
                    c['case_id'], c['stale_info']['age_hours']), case_ids=[c['case_id']])))
        items.sort(key=lambda r: r[:2])
        return _section('risks', 'Principais riscos (janela médica excedida, casos sem atualização)', [i[2] for i in items])

    def reroute_rows():
        from app.missions.reroutes import reroutes
        res = reroutes(missions, now[:10])
        items = [_item(p['id'], p['text_pt'], case_ids=[p['case_id']]) for p in res['alerts']]
        return _section('reroutes', 'Propostas de desvio (aguardam aprovação humana)', items)

    def volunteer_rows():
        n = volunteers.list()['counts'].get('pending', 0)
        items = [_item('volunteers:pending', '%s voluntário(s) aguardando verificação humana' % n, case_ids=[])] if n else []
        return _section('volunteers', 'Voluntários pendentes', items, n)

    def contradiction_rows():
        items = []
        for c in q:
            for it in contradictions.overlay(c['case_id'], c.get('cross_source') or []):
                if it.get('state') in (None, 'open', 'pending'):
                    items.append(_item(it['id'], 'contradição %s aberta no caso %s' % (it['id'], c['case_id']), case_ids=[c['case_id']]))
        return _section('contradictions', 'Contradições entre fontes em aberto', items)

    def units():
        items = [_item(x['id'], x['text_pt'], case_ids=[]) for x in unit_status_fn(now)]
        return _section('units', 'Status das unidades', items)

    plan = [('send_cases', 'Casos SEND abertos', send_cases, True), ('open_loops', 'Ciclos abertos', loops, True),
            ('callbacks', 'Retornos pendentes', callbacks, True), ('missions', 'Missões em andamento', active_missions, True),
            ('shelters', 'Abrigos perto da lotação', shelter_rows, shelters is not None),
            ('alerts', 'Alertas do supervisor', alerts, supervisor is not None), ('risks', 'Principais riscos', risks, True),
            ('units', 'Status das unidades', units, unit_status_fn is not None),
            ('reroutes', 'Propostas de desvio', reroute_rows, missions is not None),
            ('volunteers', 'Voluntários pendentes', volunteer_rows, volunteers is not None),
            ('contradictions', 'Contradições abertas', contradiction_rows, contradictions is not None)]
    sections = [_safe(k, t, fn) if on else _section(k, t, [], 0, 'Fonte não conectada neste servidor.') for k, t, fn, on in plan]
    return {'now': now, 'sections': sections, 'counts': {s['key']: s['count'] for s in sections},
            'clock_note_pt': 'Tempo = relógio do replay; registros posteriores a este instante não entram.'}


def facts(skeleton):
    """id -> text_pt for every citable line (displayed items; the model never sees or cites anything else)."""
    return {i['id']: i['text_pt'] for s in skeleton['sections'] for i in s['items']}


def allowed_text(skeleton):
    return json.dumps({'counts': skeleton['counts'], 'facts': facts(skeleton), 'now': skeleton['now']}, ensure_ascii=False)
