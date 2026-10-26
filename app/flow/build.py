"""Graph + loops from the records the desk already writes. Read-only: nothing here appends, decides or calls a model.

Sources: World Model journal (ingest/analysis with per-case calls/agents, actions, supervisor ticks/decisions, mission
approvals, field feedback, stale callbacks, place memory), optional callback log, optional red-team files.
Every node/edge/loop is derived from a record; the builder invents nothing. Journal events carry no wall clock, so the
time axis is the replay clock (case.replay_time, supervisor replay_time) with the journal line as total order.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
RECENT_MIN = 15
PAYLOAD_MAX = 80

NODE_DEFS = {
    'citizen': ('Cidadão', 'human'), 'intake': ('Leitura inicial', 'agent'), 'critic': ('Crítico', 'agent'),
    'revision': ('Revisão', 'agent'), 'location': ('Agente de localização', 'agent'),
    'needs': ('Meios e necessidades', 'tool'), 'hazard_critic': ('Crítico de risco', 'agent'),
    'credibility': ('Credibilidade', 'agent'), 'duplicate_reviewer': ('Revisor de duplicatas', 'agent'),
    'hydro': ('Hidrografia retrospectiva', 'data'), 'decide': ('Decisão por regras', 'tool'),
    'callback_planner': ('Planejador de retorno', 'agent'), 'supervisor': ('Supervisor', 'agent'),
    'mission_planner': ('Planejador de missão', 'agent'), 'red_team': ('Red-team (atacante)', 'agent'),
    'judge': ('Juiz do red-team', 'tool'), 'place_memory': ('Memória de lugares', 'data'),
    'zetaris': ('Zetaris', 'data'), 'nightshift': ('Nightshift (modelo)', 'system'),
    'operator': ('Operador (porta humana)', 'human'), 'crew': ('Equipe de campo', 'human'),
    'regression': ('Regressão aprovada', 'data'),
}
ROLE_NODE = {'location_agent': 'location', 'credibility_reviewer': 'credibility', 'field_feedback': 'crew'}
ACTION_ROUTE = {  # operator action -> (src, dst, label)
    'confirm_location': ('operator', 'location', 'Operador confirmou o local'),
    'approve_dispatch': ('operator', 'decide', 'Operador aprovou o meio'),
    'dispatch': ('operator', 'crew', 'Operador despachou'),
    'field_confirm': ('crew', 'operator', 'Equipe confirmou em campo'),
    'request_callback': ('operator', 'callback_planner', 'Operador pediu retorno'),
    'report_rescued': ('operator', 'decide', 'Resgate relatado'),
}
_CACHE = {}


def _s(x, n=PAYLOAD_MAX):
    x = ' '.join(str(x).split())
    return x if len(x) <= n else x[:n-1]+'…'


def _epoch(ts):
    if not isinstance(ts, str) or not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone(datetime.now().astimezone().utcoffset()))
    return d.timestamp()


def _node_of(role):
    return ROLE_NODE.get(role, role)


def _jsonl(path):
    out = []
    p = Path(path) if path else None
    if p and p.is_file():
        for line in p.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                v = json.loads(line)
            except ValueError:
                continue
            if isinstance(v, dict):
                out.append(v)
    return out


def _stamp(path):
    p = Path(path) if path else None
    if p and p.is_file():
        s = p.stat()
        return (s.st_size, s.st_mtime_ns)
    return None


class Graph:
    def __init__(self):
        self.edges, self.loops, self.events = [], [], {}
        self.calls = []   # (node, ts, seconds, status)
        self.simulated_citizen = False
        self.n = 0

    def edge(self, seq, src_kind, ts, src, dst, kind, label, payload, **kw):
        self.n += 1
        e = {'id': f'e{src_kind}{seq}.{self.n}', 'src_kind': src_kind, 'seq': seq, 'ts': ts, 't': _epoch(ts), 'src': src, 'dst': dst,
             'kind': kind, 'label': label, 'payload': _s(payload), 'detail': kw.pop('detail', {}), 'latency_s': kw.pop('latency_s', None),
             'model': kw.pop('model', None), 'receipt': kw.pop('receipt', None), 'status': kw.pop('status', 'ok'),
             'case_ids': kw.pop('case_ids', []), 'version': kw.pop('version', None), 'human_gate': kw.pop('human_gate', False),
             'simulated': kw.pop('simulated', False), 'offset_s': kw.pop('offset_s', 0.0)}
        e.update(kw)
        self.edges.append(e)
        for n in (src, dst):
            self.events[n] = self.events.get(n, 0)+1
        if e['simulated'] and 'citizen' in (src, dst):
            self.simulated_citizen = True
        return e

    def loop(self, **kw):
        self.loops.append(kw)
        return kw


def _fields_changed(case):
    before, after = case.get('initial_fields') or {}, case.get('fields') or {}
    out = []
    for k in sorted(set(before)|set(after)):
        b = (before.get(k) or {}).get('value') if isinstance(before.get(k), dict) else None
        a = (after.get(k) or {}).get('value') if isinstance(after.get(k), dict) else None
        if b != a:
            out.append({'field': k, 'from': b, 'to': a})
    return out


def _case_event(g, seq, ev, ctx):
    """ingest / analysis: per-message pipeline path."""
    c = ev.get('case') or {}
    cid, ver = ev['case_id'], ev.get('version')
    ts = c.get('replay_time') or c.get('received_at')
    ctx['last_ts'][cid] = ts
    prev = ctx['last_case'].get(cid)
    res = c.get('result') or {}
    decision = res.get('decision')
    reply = ev['kind'] == 'analysis' and c.get('parent_version') is not None
    calls = [x for x in (c.get('calls') or []) if isinstance(x, dict)]
    agents = c.get('agents') or {}
    errors = [str(x) for x in (c.get('errors') or [])]
    off = [0.0]
    base = dict(case_ids=[cid], version=ver)

    def add(src, dst, kind, label, payload, call=None, **kw):
        lat = call.get('seconds') if call else kw.pop('latency_s', None)
        e = g.edge(seq, 'j', ts, src, dst, kind, label, payload, latency_s=lat, offset_s=round(off[0], 3),
                   model=(call or {}).get('model') or kw.pop('model', None), receipt=(call or {}).get('receipt') or kw.pop('receipt', None),
                   **base, **kw)
        off[0] += lat or 0
        return e

    # callers' calls (model calls recorded for this message)
    for call in calls:
        g.calls.append((_node_of(call.get('role')), ts, call.get('seconds'), call.get('status') or 'ok', call.get('receipt')))
    by_role = {}
    for call in calls:
        by_role.setdefault(_node_of(call.get('role')), []).append(call)

    text = c.get('text') or ''
    mid = c.get('message_id') or ''
    simulated = bool(c.get('synthetic')) or text.startswith('[SIMULADO]')
    last_msg = (c.get('messages') or [{}])[-1] if c.get('messages') else {}
    msg_text = last_msg.get('text') or text
    first_edge = len(g.edges)
    add('citizen', 'intake', 'reply' if reply else 'message', 'Resposta do cidadão' if reply else 'Mensagem recebida',
        f'{mid}: {len(msg_text)} caracteres', simulated=simulated, detail={'message_id': mid, 'received_at': c.get('received_at'), 'chars': len(msg_text)})

    chain = []  # (node, label, payload, call, status, detail)
    fields = c.get('fields') or {}
    init = c.get('initial_fields') or fields
    ic = by_role.get('intake', [None])[0]
    if ic:
        chain.append(('intake', 'Campos extraídos', 'campos: '+', '.join(sorted(init)) if init else 'sem campos', ic, ic.get('status') or 'ok', {'fields': sorted(init)}))
    elif isinstance(agents.get('intake'), str) and 'unavailable' in agents['intake']:
        chain.append(('intake', 'Extração por regras (sem modelo)', 'campos: '+', '.join(sorted(fields)) if fields else 'sem campos', None, 'fallback', {'fields': sorted(fields)}))
    elif agents.get('intake') == 'failed':
        chain.append(('intake', 'Leitura falhou', _s(next((e for e in errors if 'intake' in e or 'agent_step' in e), 'falha')), None, 'failed', {}))
    elif isinstance(agents.get('intake'), dict):
        chain.append(('intake', 'Campos extraídos', 'campos: '+', '.join(sorted(init)), None, 'ok', {'fields': sorted(init)}))
    cr = by_role.get('critic', [None])[0]
    crit = agents.get('critic')
    if cr or isinstance(crit, dict) or crit == 'failed':
        obj = crit.get('objections', []) if isinstance(crit, dict) else []
        failed = crit == 'failed' or (cr or {}).get('status') == 'failed'
        chain.append(('critic', 'Objeções do crítico', f'{len(obj)} objeções: '+', '.join(str(o.get('field')) for o in obj[:5]) if obj else ('crítico falhou' if failed else '0 objeções'),
                      cr, 'failed' if failed else 'ok', {'objections': obj[:8]}))
    rv = by_role.get('revision', [])
    if rv or isinstance(agents.get('revision'), dict):
        ch = _fields_changed(c)
        failed = bool(rv) and all(x.get('status') == 'failed' for x in rv)
        chain.append(('revision', 'Revisão com objeções', ('mudou: '+', '.join(x['field'] for x in ch[:6])) if ch else 'sem mudança nos campos',
                      rv[0] if rv else None, 'failed' if failed else 'ok', {'changed': ch}))
    loc = agents.get('location') if isinstance(agents.get('location'), dict) else None
    lc = by_role.get('location', [None])[0]
    if lc or (loc and not loc.get('offline')) or c.get('location_path'):
        steps = (loc or {}).get('steps') or []
        fb = bool((loc or {}).get('fallback'))
        chain.append(('location', 'Localização', f"{c.get('location_path') or (loc or {}).get('location_path') or 'n/d'}; precisão {c.get('location_precision') or (loc or {}).get('precision') or 'n/d'}; {len(steps)} passos",
                      lc, 'failed' if (lc or {}).get('status') == 'failed' else 'fallback' if fb or (loc or {}).get('offline') else 'ok', {'steps': len(steps)}))
    fleet = c.get('fleet') if isinstance(c.get('fleet'), list) else []
    if fleet:
        good = [a for a in fleet if a.get('verdict') in ('suitable', 'caution')]
        chain.append(('needs', 'Avaliação de meios', f'{len(fleet)} meios avaliados, {len(good)} utilizáveis', None, 'ok', {'verdicts': {a.get('asset'): a.get('verdict') for a in fleet[:10]}}))
    hr = c.get('hazard_review')
    hc = by_role.get('hazard_critic', [None])[0]
    if hc or isinstance(hr, dict) or 'hazard_critic_failed' in errors:
        failed = 'hazard_critic_failed' in errors or (hc or {}).get('status') == 'failed'
        o = hr.get('objections', []) if isinstance(hr, dict) else []
        chain.append(('hazard_critic', 'Parecer de risco', f'{len(o)} objeções de risco' if not failed else 'parecer de risco falhou', hc, 'failed' if failed else 'ok',
                      {'objections': [x.get('text_pt') for x in o[:5]]}))
    cred = c.get('credibility')
    if isinstance(cred, dict):
        chain.append(('credibility', 'Credibilidade', f"{cred.get('verdict')}; fonte {cred.get('source')}", by_role.get('credibility', [None])[0],
                      'fallback' if cred.get('fallback_reason') else 'ok', {'verdict': cred.get('verdict'), 'fallback_reason': cred.get('fallback_reason')}))
    dups = c.get('duplicates') if isinstance(c.get('duplicates'), list) else []
    if dups or by_role.get('duplicate_reviewer'):
        reviewed = [d for d in dups if isinstance(d.get('review'), dict)]
        chain.append(('duplicate_reviewer', 'Duplicatas', f'{len(dups)} candidatas, {len(reviewed)} revisadas por modelo', by_role.get('duplicate_reviewer', [None])[0],
                      'ok' if reviewed or not dups else 'fallback', {'candidates': len(dups)}))
    prev_node = 'intake'
    for node, label, payload, call, status, detail in chain:
        if node == 'intake':   # the citizen->intake handoff carries the intake call's receipt/latency/status
            e = g.edges[first_edge]
            e.update(status=status, model=(call or {}).get('model'), receipt=(call or {}).get('receipt'), latency_s=(call or {}).get('seconds'),
                     label=label, detail={**e['detail'], **detail}, payload=_s(e['payload']+' → '+payload))
            off[0] += (call or {}).get('seconds') or 0
            continue
        add(prev_node, node, 'handoff', label, payload, call, status=status, detail=detail)
        if node == 'location':
            for st in (loc or {}).get('steps') or []:
                tool = st.get('tool') or 'ferramenta'
                tn = 'tool:'+tool
                ids = st.get('result_ids') or []
                add('location', tn, 'tool_call', f'Passo {st.get("step")}: {tool}', f'{tool}({_s(json.dumps(st.get("args"), ensure_ascii=False), 40)}) → {len(ids)} resultados',
                    latency_s=st.get('seconds'), model=st.get('model'), receipt=st.get('receipt'), status='failed' if st.get('error') else 'ok',
                    detail={'step': st.get('step'), 'tool': tool, 'args': st.get('args'), 'result_ids': ids[:10], 'result_count': len(ids)})
                g.calls.append((tn, ts, st.get('seconds'), 'failed' if st.get('error') else 'ok', None))
        prev_node = node
    if 'data_source_failed' in ' '.join(errors):
        add('zetaris', 'intake', 'data', 'Fonte de dados', _s(next(e for e in errors if 'data_source_failed' in e)), status='failed')
    hyd = c.get('hydro_conflict') or (c.get('landmark_check') or {}).get('hydro_area') or (c.get('landmark_check') or {}).get('hydro_relative')
    if hyd:
        add('hydro', 'decide', 'data', 'Camada hidrográfica', _s('conflito hidrográfico' if c.get('hydro_conflict') else 'área hidrográfica (retrospectiva, confiança baixa)'),
            detail={'retrospective': True, 'confidence': 'low'})
    before = prev.get('result', {}).get('decision') if prev else None
    d = add(prev_node, 'decide', 'handoff', 'Decisão', f'{before} → {decision}' if reply and before else f'{decision}; prioridade {res.get("priority")}',
            detail={'decision': decision, 'decision_before': before, 'reason': res.get('decision_reason')})
    add('decide', 'operator', 'decision', 'Aguarda decisão humana', _s(f'{decision}: {res.get("decision_reason") or ""}'), human_gate=True, detail={'decision': decision})
    if decision == 'CALLBACK':
        qs = res.get('questions') or []
        add('decide', 'callback_planner', 'callback_ask', 'Retorno necessário', f'{len(qs) or len(c.get("open_items") or [])} pendências', detail={'questions': qs[:6]})
        add('callback_planner', 'citizen', 'callback_ask', 'Pergunta ao cidadão', _s((qs or ['pergunta de retorno'])[0]), simulated=simulated)
    ctx['last_case'][cid] = c

    # ---- loops tied to this analysis
    objs = (crit or {}).get('objections', []) if isinstance(crit, dict) else []
    if objs:
        ch = _fields_changed(c)
        done = bool(rv) or isinstance(agents.get('revision'), dict)
        g.loop(id=f'critic_revision:{cid}:v{ver}', kind='critic_revision', case_ids=[cid], seq=seq, ts=ts, status='closed' if done else 'open',
               iterations=len(rv) or (1 if done else 0), outcome=(f'{len(ch)} campos mudaram' if ch else 'revisão sem mudança') if done else 'objeção sem revisão registrada',
               detail={'objections': [o.get('field') for o in objs], 'changed': ch}, closed_ts=ts if done else None, basis='replay')
    steps = (loc or {}).get('steps') or []
    if steps:
        ids = sum(len(s.get('result_ids') or []) for s in steps)
        g.loop(id=f'location_tools:{cid}:v{ver}', kind='location_tools', case_ids=[cid], seq=seq, ts=ts, status='closed', iterations=len(steps),
               outcome=f'{ids} resultados; precisão {(loc or {}).get("precision")}', closed_ts=ts, basis='replay',
               detail={'tools': [s.get('tool') for s in steps], 'result_counts': [len(s.get('result_ids') or []) for s in steps], 'fallback': bool(loc.get('fallback'))})
    # callback loop state machine
    cb = ctx['callbacks'].get(cid)
    if decision == 'CALLBACK' and not reply and cb is None:
        ctx['callbacks'][cid] = cb = g.loop(id=f'callback:{cid}:v{ver}', kind='callback', case_ids=[cid], seq=seq, ts=ts, status='open', iterations=0,
                                            outcome='aguardando resposta do cidadão', basis='replay', detail={'trigger': 'decision', 'decisions': ['CALLBACK']}, closed_ts=None)
    elif reply:
        if cb is None:
            ctx['callbacks'][cid] = cb = g.loop(id=f'callback:{cid}:v{ver}', kind='callback', case_ids=[cid], seq=seq, ts=ts, status='open', iterations=0,
                                                outcome='', basis='replay', detail={'trigger': 'reply', 'decisions': [before]}, closed_ts=None)
        cb['iterations'] += 1
        cb['detail']['decisions'].append(decision)
        cb['detail']['reply_version'] = ver
        cb['detail']['simulated'] = simulated
        cb['detail']['changes'] = [x.get('field') for x in (c.get('changes') or [])][:8]
        if decision != 'CALLBACK':
            cb.update(status='closed', closed_ts=ts, outcome=f'{cb["detail"]["decisions"][0]} → {decision}')
            ctx['callbacks'][cid] = None
        else:
            cb['outcome'] = 'resposta recebida; ainda CALLBACK'


def _action_event(g, seq, ev, ctx):
    cid = ev['case_id']
    ts = ctx['last_ts'].get(cid)
    route = ACTION_ROUTE.get(ev.get('action'))
    base = dict(case_ids=[cid], version=ev.get('version'))
    if ev.get('action') in ('merge', 'unmerge'):
        route = ('operator', 'decide', 'Operador '+ev['action'])
    if not route:
        return
    src, dst, label = route[:3]
    payload = f'{ev.get("action")} por {ev.get("actor")}' + (f' · meio {ev["asset"]}' if ev.get('asset') else '')
    g.edge(seq, 'j', ts, src, dst, 'human_action', label, payload, human_gate=True, **base, detail={'action': ev.get('action'), 'actor': ev.get('actor'), 'asset': ev.get('asset')})
    if ev.get('action') == 'request_callback':
        cb = ctx['callbacks'].get(cid)
        if cb is None:
            ctx['callbacks'][cid] = g.loop(id=f'callback:{cid}:v{ev.get("version")}', kind='callback', case_ids=[cid], seq=seq, ts=ts, status='open', iterations=0,
                                           outcome='retorno pedido pelo operador', basis='replay', detail={'trigger': 'operator', 'decisions': [(ctx['last_case'].get(cid) or {}).get('result', {}).get('decision')]}, closed_ts=None)
        else:
            cb['detail']['operator_requested'] = True
        g.edge(seq, 'j', ts, 'callback_planner', 'citizen', 'callback_ask', 'Pergunta ao cidadão', 'roteiro de retorno pedido pelo operador', **base)


def _stale_event(g, seq, ev, ctx):
    for p in ev.get('projections') or []:
        cid = p.get('case_id')
        act = next((a for a in reversed(p.get('actions') or []) if a.get('action') == 'stale_callback'), {})
        ts = act.get('received_at') or ctx['last_ts'].get(cid)
        g.edge(seq, 'j', ts, 'decide', 'callback_planner', 'callback_ask', 'Sem atualização', 'pedido sem atualização; "Ainda estão no local?"', case_ids=[cid], version=p.get('version'),
               detail={'reason': 'stale'})
        if ctx['callbacks'].get(cid) is None:
            ctx['callbacks'][cid] = g.loop(id=f'callback:{cid}:v{p.get("version")}', kind='callback', case_ids=[cid], seq=seq, ts=ts, status='open', iterations=0,
                                           outcome='aguardando resposta (sem atualização)', basis='replay', detail={'trigger': 'stale', 'decisions': ['STALE']}, closed_ts=None)
        ctx['last_ts'][cid] = ctx['last_ts'].get(cid) or ts


def _mission_event(g, seq, ev, ctx):
    ps = ev.get('projections') or []
    cids = [p.get('case_id') for p in ps]
    mid = ev.get('mission_id')
    ts = ctx['last_ts'].get(cids[0]) if cids else None
    plan = next((p.get('mission') for p in ps if p.get('mission')), None) or {}
    mid = mid or plan.get('proposal_id')
    if ev['kind'] == 'approve_mission':
        stops = plan.get('stops') or []
        g.edge(seq, 'j', ts, 'mission_planner', 'operator', 'mission_proposal', 'Proposta de missão', f'{plan.get("asset")}; {len(stops)} paradas; {len(plan.get("units") or [])} unidades',
               case_ids=cids, detail={'mission_id': mid, 'asset': plan.get('asset'), 'stops': [s.get('case_id') for s in stops]})
        g.edge(seq, 'j', ts, 'operator', 'crew', 'human_action', 'Operador aprovou a missão', f'{mid} por {ev.get("actor")}', human_gate=True, case_ids=cids,
               detail={'mission_id': mid, 'actor': ev.get('actor')})
        ctx['missions'][mid] = g.loop(id=f'mission:{mid}', kind='mission', case_ids=cids, seq=seq, ts=ts, status='open', iterations=0, closed_ts=None, basis='replay',
                                      outcome='aprovada; aguardando relato da equipe', detail={'mission_id': mid, 'asset': plan.get('asset'), 'stops': len(stops), 'done': []})
    else:
        g.edge(seq, 'j', ts, 'operator', 'mission_planner', 'human_action', 'Operador cancelou a missão', f'{mid} por {ev.get("actor")}', human_gate=True, case_ids=cids,
               detail={'mission_id': mid, 'actor': ev.get('actor')})
        m = ctx['missions'].get(mid)
        if m:
            m.update(status='closed', outcome='cancelada pelo operador', closed_ts=ts)


def _feedback_event(g, seq, ev, ctx):
    for p in ev.get('projections') or []:
        cid = p.get('case_id')
        act = next((a for a in reversed(p.get('actions') or []) if a.get('action') == 'field_feedback'), {})
        ts = act.get('received_at') or ctx['last_ts'].get(cid)
        ctx['last_ts'][cid] = ts
        mid = act.get('mission_id')
        g.edge(seq, 'j', ts, 'crew', 'operator', 'field_report', 'Relato da equipe', f'estado {p.get("status")}; parada {"concluída" if act.get("stop_done") else "aberta"}',
               case_ids=[cid], version=p.get('version'), human_gate=True, detail={'status': p.get('status'), 'mission_id': mid, 'stop_done': act.get('stop_done'), 'outcome': act.get('outcome')})
        m = ctx['missions'].get(mid) if mid else None
        if m:
            m['iterations'] += 1
            if act.get('stop_done') and cid not in m['detail']['done']:
                m['detail']['done'].append(cid)
            if len(m['detail']['done']) >= m['detail']['stops'] > 0:
                m.update(status='closed', closed_ts=ts, outcome=f'concluída; {len(m["detail"]["done"])} paradas; caso {p.get("status")}')
            else:
                m['outcome'] = f'{len(m["detail"]["done"])}/{m["detail"]["stops"]} paradas concluídas'
        if p.get('status') in ('RESCUED', 'field_confirmed'):
            pass


def _supervisor_events(g, seq, ev, ctx):
    ts = ev.get('replay_time')
    if ev.get('type') == 'tick':
        fb = ev.get('fallback_reason')
        g.calls.append(('supervisor', ts, sum((c.get('seconds') or 0) for c in ev.get('calls') or []) or None, 'fallback' if fb else 'ok', None))
        ctx['ticks'].append((seq, ts, fb))
        for a in ev.get('alerts') or []:
            e = g.edge(seq, 'j', a.get('created_at') or ts, 'supervisor', 'operator', 'alert', 'Alerta do supervisor', f'{a.get("kind")}: {a.get("why_pt")}', human_gate=True,
                       case_ids=list(a.get('case_ids') or []), status='fallback' if fb else 'ok', detail={'alert_id': a['alert_id'], 'action': a.get('action'), 'severity': a.get('severity'), 'tick_id': a.get('tick_id'), 'fallback_reason': fb})
            ctx['alerts'][a['alert_id']] = g.loop(id=f'supervisor:{a["alert_id"]}', kind='supervisor', case_ids=list(a.get('case_ids') or []), seq=seq, ts=a.get('created_at') or ts,
                                                  status='open', iterations=0, closed_ts=None, basis='replay', outcome='alerta aberto; aguardando operador',
                                                  detail={'alert_id': a['alert_id'], 'kind': a.get('kind'), 'action': a.get('action'), 'decision': None, 'rechecks': []})
        for r in ev.get('rechecks') or []:
            loop = ctx['alerts'].get(r.get('alert_id'))
            if not loop:
                continue
            g.edge(seq, 'j', ts, 'supervisor', 'operator', 'recheck', 'Re-checagem', _s(r.get('delta_pt') or r.get('outcome')), case_ids=list(loop['case_ids']),
                   detail={'alert_id': r.get('alert_id'), 'outcome': r.get('outcome'), 'delta': r.get('delta')})
            loop['iterations'] += 1
            loop['detail']['rechecks'].append(r.get('outcome'))
            if r.get('outcome') == 'resolved':
                loop.update(status='closed', closed_ts=ts, outcome=f'resolvido: {r.get("delta_pt")}')
            else:
                loop['outcome'] = f'ainda aberto: {r.get("delta_pt")}'
    elif ev.get('type') == 'decision':
        loop = ctx['alerts'].get(ev.get('alert_id'))
        cids = list(loop['case_ids']) if loop else []
        g.edge(seq, 'j', ts, 'operator', 'supervisor', 'human_action', 'Operador ' + ('aceitou' if ev.get('decision') == 'accept' else 'dispensou') + ' o alerta',
               f'{ev.get("decision")} por {ev.get("actor")}', human_gate=True, case_ids=cids, detail={'alert_id': ev.get('alert_id'), 'decision': ev.get('decision'), 'actor': ev.get('actor')})
        if loop:
            loop['detail']['decision'] = ev.get('decision')
            if ev.get('decision') == 'dismiss':
                loop.update(status='closed', closed_ts=ts, outcome='dispensado pelo operador')
            else:
                loop['outcome'] = 'aceito; aguardando re-checagem'


def _memory_event(g, seq, ev, ctx):
    ts = ev.get('at')
    if ev.get('action') == 'propose':
        en = ev.get('entry') or {}
        cids = [en.get('evidence_case_id')] if en.get('evidence_case_id') else []
        g.edge(seq, 'j', ts, 'location', 'place_memory', 'memory_proposal', 'Memória proposta', f'"{en.get("phrase")}" → {en.get("place_name")}', case_ids=cids,
               detail={'entry_id': en.get('id'), 'city': en.get('city')})
        ctx['memory'][en.get('id')] = g.loop(id=f'memory:{en.get("id")}', kind='memory', case_ids=cids, seq=seq, ts=ts, status='open', iterations=0, closed_ts=None,
                                             basis='wall', outcome='proposta; aguardando aprovação humana', detail={'phrase': en.get('phrase'), 'place': en.get('place_name')})
    else:
        loop = ctx['memory'].get(ev.get('id'))
        cids = list(loop['case_ids']) if loop else []
        g.edge(seq, 'j', ts, 'operator', 'place_memory', 'human_action', f'Operador: {ev.get("action")}', f'{ev.get("action")} por {ev.get("actor")}', human_gate=True, case_ids=cids,
               detail={'entry_id': ev.get('id'), 'actor': ev.get('actor')})
        if loop:
            loop['iterations'] += 1
            closed = ev.get('action') in ('approve', 'reject', 'revoke')
            loop.update(status='closed' if closed else 'open', closed_ts=ts, outcome={'approve': 'aprovada', 'reject': 'rejeitada', 'revoke': 'revogada'}.get(ev.get('action'), ev.get('action')))


def _redteam(g, store_rows):
    decls, results, proposals, regs = store_rows
    by_decl = {}
    seq = 0
    timeline = []
    for d in decls:
        timeline.append((d.get('declared_at') or '', 0, d))
    for r in results:
        timeline.append((r.get('at') or '', 1, r))
    for p in proposals:
        timeline.append((p.get('created_at') or '', 2, p))
        if p.get('decided_at'):
            timeline.append((p['decided_at'], 3, p))
    for x in regs:
        timeline.append((x.get('approved_at') or '', 4, x))
    timeline.sort(key=lambda t: (t[0], t[1]))
    loops = {}
    for ts, kind, row in timeline:
        seq += 1
        if kind == 0:
            g.edge(seq, 'r', ts, 'red_team', 'judge', 'attack', 'Ataque declarado', f'{row.get("category")} ({row.get("source")}): {_s(row.get("message"), 40)}',
                   detail={'decl_id': row.get('decl_id'), 'category': row.get('category'), 'source': row.get('source')}, status='ok')
            loops[row.get('decl_id')] = g.loop(sk='r', id=f'redteam:{row.get("decl_id")}', kind='redteam', case_ids=[], seq=seq, ts=ts, status='open', iterations=0, closed_ts=None, basis='wall',
                                               outcome='ataque declarado; aguardando julgamento', detail={'category': row.get('category'), 'decl_hash': row.get('decl_hash'), 'source': row.get('source'), 'verdicts': []})
        elif kind == 1:
            ok = bool(row.get('passed'))
            g.edge(seq, 'r', ts, 'judge', 'operator', 'verdict', 'Veredito do juiz', f'{"defesa ok" if ok else "FALHOU"}: {row.get("decision")}; {_s((row.get("reasons") or ["—"])[0], 36)}',
                   status='ok', human_gate=not ok, detail={'decl_id': row.get('decl_id'), 'passed': ok, 'decision': row.get('decision'), 'reasons': (row.get('reasons') or [])[:3], 'run_id': row.get('run_id')})
            lp = loops.get(row.get('decl_id'))
            if lp is None:
                lp = loops[row.get('decl_id')] = g.loop(sk='r', id=f'redteam:{row.get("decl_id")}', kind='redteam', case_ids=[], seq=seq, ts=ts, status='open', iterations=0, closed_ts=None, basis='wall',
                                                       outcome='', detail={'category': row.get('category'), 'decl_hash': row.get('decl_hash'), 'source': row.get('source'), 'verdicts': []})
            lp['iterations'] += 1
            lp['detail']['verdicts'].append(ok)
            lp['detail']['failed_reasons'] = (row.get('reasons') or [])[:2]
            lp['detail']['decl_hash'] = row.get('decl_hash')
            if ok:
                lp.update(status='closed', closed_ts=ts, outcome='defesa passou')
            else:
                lp.update(status='open', closed_ts=None, outcome='defesa falhou; proposta de regressão pendente de humano')
        elif kind == 2:
            lp = next((l for l in loops.values() if l['detail'].get('decl_hash') == row.get('decl_hash')), None)
            g.edge(seq, 'r', ts, 'judge', 'operator', 'proposal', 'Proposta de regressão', f'{row.get("proposal_id")}: {_s(row.get("category"))}', human_gate=True,
                   detail={'proposal_id': row.get('proposal_id'), 'key': row.get('key'), 'status': row.get('status')})
            if lp:
                lp['detail']['proposal_id'] = row.get('proposal_id')
                if row.get('status') == 'pending':
                    lp['outcome'] = 'proposta de regressão aguardando aprovação humana'
        elif kind == 3:
            lp = next((l for l in loops.values() if l['detail'].get('proposal_id') == row.get('proposal_id')), None)
            g.edge(seq, 'r', ts, 'operator', 'regression' if row.get('status') == 'approved' else 'judge', 'human_action', f'Operador: {row.get("status")}',
                   f'{row.get("proposal_id")} {row.get("status")} por {row.get("decided_by")}', human_gate=True, detail={'proposal_id': row.get('proposal_id'), 'decided_by': row.get('decided_by')})
            if lp:
                lp.update(status='closed', closed_ts=ts, outcome='regressão criada' if row.get('status') == 'approved' else 'proposta rejeitada')
                lp['detail']['decided'] = row.get('status')


def _enrich_callbacks(g, rows):
    for r in rows:
        for lp in g.loops:
            if lp['kind'] == 'callback' and lp['case_ids'] == [r.get('case_id')] and lp['detail'].get('reply_version') == r.get('version_after'):
                lp['detail'].update(simulated=bool(r.get('simulated')), resolved=r.get('resolved'), remaining=r.get('remaining'))


def _stats(g, latest):
    cut = latest-RECENT_MIN*60 if latest else None
    out = {}
    for node, ts, sec, status, receipt in g.calls:
        s = out.setdefault(node, {'calls': 0, 'failures': 0, 'fallbacks': 0, 'recent_calls': 0, '_lat': [], 'last_ts': None, 'receipts': 0})
        s['calls'] += 1
        s['failures'] += status == 'failed'
        s['fallbacks'] += status == 'fallback'
        s['receipts'] += bool(receipt)
        if isinstance(sec, (int, float)) and sec > 0:
            s['_lat'].append(sec)
        t = _epoch(ts)
        if t is not None and cut is not None and t >= cut:
            s['recent_calls'] += 1
        if ts and (s['last_ts'] is None or (_epoch(ts) or 0) >= (_epoch(s['last_ts']) or 0)):
            s['last_ts'] = ts
    for s in out.values():
        lat = s.pop('_lat')
        s['mean_latency_s'] = round(sum(lat)/len(lat), 3) if lat else None
    return out


def _build_all(journal_path, callback_log, redteam_rows, now):
    g = Graph()
    ctx = {'last_ts': {}, 'last_case': {}, 'callbacks': {}, 'missions': {}, 'alerts': {}, 'memory': {}, 'ticks': []}
    seq = 0
    p = Path(journal_path)
    lines = p.read_text(encoding='utf-8', errors='replace').splitlines() if p.is_file() else []
    for line in lines:
        seq += 1
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        k = ev.get('kind')
        if k in ('ingest', 'analysis') and ev.get('case_id') and isinstance(ev.get('case'), dict):
            _case_event(g, seq, ev, ctx)
        elif k == 'action':
            _action_event(g, seq, ev, ctx)
        elif k in ('merge', 'unmerge') and ev.get('case_id'):
            ev = {**ev, 'action': k}
            _action_event(g, seq, ev, ctx)
        elif k == 'stale_callback':
            _stale_event(g, seq, ev, ctx)
        elif k in ('approve_mission', 'cancel_mission'):
            _mission_event(g, seq, ev, ctx)
        elif k == 'field_feedback':
            _feedback_event(g, seq, ev, ctx)
        elif k == 'supervisor':
            _supervisor_events(g, seq, ev, ctx)
        elif k == 'place_memory':
            _memory_event(g, seq, ev, ctx)
    journal_seq = seq
    _redteam(g, redteam_rows)
    _enrich_callbacks(g, callback_log)
    # a callback still open after its last reply/ask keeps counting until a human or a reply closes it
    times = [e['t'] for e in g.edges if e['t'] is not None and e['src_kind'] == 'j']
    latest = max(times) if times else None
    for lp in g.loops:
        t0 = _epoch(lp['ts'])
        ref = now if lp.get('basis') == 'wall' else latest
        t1 = _epoch(lp.get('closed_ts')) if lp['status'] == 'closed' else ref
        lp['duration_s'] = round(t1-t0, 1) if t0 is not None and t1 is not None else None
        lp['age_min'] = round(max(0, (ref-t0))/60, 1) if lp['status'] == 'open' and t0 is not None and ref is not None else None
    stats = _stats(g, latest)
    # nodes: only those with at least one recorded event
    counts = dict(g.events)
    for node in stats:
        counts[node] = counts.get(node, 0)+stats[node]['calls']
    if any(s['receipts'] for s in stats.values()):
        counts['nightshift'] = sum(s['receipts'] for s in stats.values())
        stats['nightshift'] = {'calls': counts['nightshift'], 'failures': 0, 'fallbacks': 0, 'recent_calls': 0, 'mean_latency_s': None, 'last_ts': None, 'receipts': counts['nightshift']}
    nodes = []
    for nid, n in counts.items():
        if n <= 0:
            continue
        if nid in NODE_DEFS:
            label, kind = NODE_DEFS[nid]
        elif nid.startswith('tool:'):
            label, kind = 'Ferramenta: '+nid[5:], 'tool'
        else:
            label, kind = nid, 'agent'
        if nid == 'citizen' and g.simulated_citizen:
            label = 'Cidadão [SIMULADO]'
        nodes.append({'id': nid, 'label': label, 'kind': kind, 'event_count': n, 'simulated': nid == 'citizen' and g.simulated_citizen})
    return {'edges': g.edges, 'loops': g.loops, 'nodes': nodes, 'stats': stats, 'journal_seq': journal_seq, 'latest_ts': max(
        (e['ts'] for e in g.edges if e['t'] == latest and e['src_kind'] == 'j'), default=None), 'latest_t': latest}


def _parse_since(since):
    cur = {'j': 0, 'r': 0}
    if since in (None, ''):
        return cur
    if isinstance(since, int):
        cur['j'] = since
        return cur
    for part in str(since).replace(';', ',').split(','):
        k, _, v = part.partition(':')
        if v == '' and k.strip().isdigit():
            cur['j'] = int(k)
        elif k.strip() in cur and v.strip().isdigit():
            cur[k.strip()] = int(v)
    return cur


def build_flow(journal_path, *, case_id=None, since=None, callback_log=None, redteam_dir=None, redteam_eval_dir=None, now=None, use_cache=True):
    """Return {nodes, edges, loops, open_loops, stats, cursor, clock}. `since` ("j:N,r:M" or int) keeps only newer edges/loops."""
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    rt = None
    if redteam_dir is not None or redteam_eval_dir is not None:
        rt = (Path(redteam_dir) if redteam_dir else None, Path(redteam_eval_dir) if redteam_eval_dir else None)
    key = (str(journal_path), _stamp(journal_path), _stamp(callback_log),
           tuple(_stamp(Path(d)/f) for d, f in ((rt[0], 'declarations.jsonl'), (rt[0], 'results.jsonl'), (rt[1], 'proposed.jsonl'), (rt[1], 'regression.jsonl')) if d) if rt else None)
    full = _CACHE.get(key) if use_cache else None
    if full is None:
        rows = ([_jsonl(rt[0]/'declarations.jsonl'), _jsonl(rt[0]/'results.jsonl')] if rt and rt[0] else [[], []]) + \
               ([_jsonl(rt[1]/'proposed.jsonl'), _jsonl(rt[1]/'regression.jsonl')] if rt and rt[1] else [[], []])
        full = _build_all(journal_path, _jsonl(callback_log) if callback_log else [], rows, now)
        if use_cache:
            _CACHE.clear()
            _CACHE[key] = full
    cur = _parse_since(since)
    jmax = full['journal_seq']
    rmax = max([e['seq'] for e in full['edges'] if e['src_kind'] == 'r'] or [0])
    edges = [e for e in full['edges'] if e['seq'] > cur[e['src_kind']]]
    loops = [l for l in full['loops'] if l['seq'] > cur[l.get('sk', 'j')]
             or l['status'] == 'open']
    if case_id:
        edges = [e for e in edges if case_id in e['case_ids']]
        loops = [l for l in loops if case_id in l['case_ids']]
    touched = {n for e in edges for n in (e['src'], e['dst'])}
    if any(e.get('receipt') for e in edges):
        touched.add('nightshift')
    nodes = [n for n in full['nodes'] if n['id'] in touched] if (case_id or cur['j'] or cur['r']) else list(full['nodes'])
    open_loops = sorted((l for l in full['loops'] if l['status'] == 'open'), key=lambda l: -(l.get('age_min') or 0))
    if case_id:
        open_loops = [l for l in open_loops if case_id in l['case_ids']]
    return {'schema': SCHEMA, 'case_id': case_id, 'incremental': bool(cur['j'] or cur['r']), 'cursor': f'j:{jmax},r:{rmax}',
            'clock': {'basis': 'replay', 'latest': full['latest_ts'], 'recent_window_min': RECENT_MIN,
                      'note': 'Eventos do diário não têm relógio de parede; tempo = relógio do replay (red-team e memória usam UTC real).'},
            'nodes': nodes, 'edges': edges, 'loops': loops, 'open_loops': open_loops, 'stats': full['stats']}
