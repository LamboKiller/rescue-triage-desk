"""Deterministic watchers over the World Model. Code computes every number; each finding
carries the case/resource ids and one PT fact text that is the only source an agent may cite.

No hindsight: only cases received at or before the tick's replay time are considered, and depth
uses dated retrospective observations (<= replay day), labelled low confidence. Unknown != safe.
"""
import hashlib
from dataclasses import dataclass, asdict
from app.config import setting
from app.decide import timestamp
from app.priority import dated_depth, hours, stale_info, threshold, BANDS
from app.missions.planner import distance, point

CLOSED = ('RESCUED', 'NOT_FOUND', 'field_confirmed')
SEND = ('SEND', 'SEND_CANDIDATE')
ACTIONS = ('create_mission_proposal', 'trigger_callback', 'reprioritise', 'request_resources', 'acknowledge_unit')
ACTION_LABEL_PT = {'create_mission_proposal': 'Gerar proposta de missão', 'trigger_callback': 'Acionar retorno (callback)',
                   'reprioritise': 'Repriorizar fila', 'request_resources': 'Solicitar recursos', 'acknowledge_unit': 'Ciente; contatar equipe'}
ALLOWED = {'cluster_growth': ('create_mission_proposal', 'request_resources', 'reprioritise'),
           'stale_send': ('trigger_callback', 'reprioritise'),
           'idle_resources': ('create_mission_proposal',),
           'rising_depth': ('reprioritise', 'create_mission_proposal'),
           'callback_aging': ('reprioritise', 'trigger_callback'),
           'mission_feedback': ('trigger_callback', 'request_resources')}
BAND_PT = dict(zip(BANDS, ('<0,15 m', '0,15-0,3 m', '0,3-0,6 m', '0,6-1,2 m', '1,2-2,5 m', '>2,5 m')))


@dataclass(frozen=True)
class Config:
    interval_min: int = 30       # replay minutes between ticks
    cluster_k: int = 3           # >= K new cases ...
    cluster_radius_m: int = 500  # ... within R metres ...
    cluster_window_min: int = 60  # ... received in the last T minutes
    idle_wait_min: int = 60      # eligible SEND case waiting at least this long
    callback_age_h: int = 2
    mission_feedback_h: int = 2
    max_depth_cases: int = 200

    @classmethod
    def from_env(cls):
        def num(name, default):
            try:
                v = int(setting(name, str(default)))
            except ValueError:
                return default
            return v if v > 0 else default
        return cls(**{k: num('SUPERVISOR_'+k.upper(), v) for k, v in asdict(cls()).items()})


def is_open(c):
    s = c.get('status', '')
    return (s not in CLOSED and not s.startswith('MERGED_INTO:')
            and c.get('result', {}).get('decision') != 'REPORTED_RESCUED')


def visible(cases, now):
    """No hindsight: drop cases that had not arrived yet at the replay time."""
    t = timestamp(now)
    return [c for c in cases if timestamp(c['received_at']) <= t]


def place(c):
    f = c.get('fields', {})
    parts = [str((f.get(k) or {}).get('value')) for k in ('landmark', 'street') if (f.get(k) or {}).get('value')]
    muni = (f.get('municipality') or {}).get('value')
    return (parts[0] if parts else 'local não informado') + (' ('+str(muni)+')' if muni else '')


def people(c):
    v = c.get('remaining_n', (c.get('fields', {}).get('people') or {}).get('value'))
    return v if type(v) is int and v >= 0 else None


def fid(kind, key):
    return kind + ':' + hashlib.sha1(key.encode()).hexdigest()[:8]


def finding(kind, key, case_ids, text, numbers, severity, resource_ids=(), mission_ids=(), evidence=None):
    i = fid(kind, key)
    return {'id': i, 'kind': kind, 'case_ids': sorted(case_ids), 'resource_ids': sorted(resource_ids),
            'mission_ids': sorted(mission_ids), 'numbers': numbers, 'severity': severity,
            'allowed_actions': list(ALLOWED[kind]), 'default_action': ALLOWED[kind][0],
            'facts': [{'id': i, 'text_pt': text}], 'evidence': evidence or []}


def cluster_growth(cases, now, cfg):
    t = timestamp(now)
    new = [c for c in cases if is_open(c) and point(c) and 0 <= (t-timestamp(c['received_at'])).total_seconds() < cfg.cluster_window_min*60]
    new.sort(key=lambda c: (timestamp(c['received_at']), c['case_id']))
    out, rest = [], new
    while len(rest) >= cfg.cluster_k:
        groups = [(c, [o for o in rest if distance(point(c), point(o)) <= cfg.cluster_radius_m]) for c in rest]
        center, best = max(groups, key=lambda g: len(g[1]))
        if len(best) < cfg.cluster_k:
            break
        anchor = best[0]
        spread = round(max(distance(point(center), point(o)) for o in best))
        known = [people(c) for c in best]
        total = sum(p for p in known if p is not None)
        unknown = sum(p is None for p in known)
        streets = ', '.join(dict.fromkeys(place(c) for c in best))
        text = (f"Aglomeração: {len(best)} novos pedidos abertos nos últimos {cfg.cluster_window_min} min, a até "
                f"{cfg.cluster_radius_m} m de um ponto central (maior distância {spread} m); {total} pessoas declaradas"
                + (f", {unknown} pedidos sem contagem" if unknown else '') + f". Locais: {streets}.")
        out.append(finding('cluster_growth', anchor['case_id'], [c['case_id'] for c in best], text,
                           {'novos_pedidos': len(best), 'janela_min': cfg.cluster_window_min, 'raio_m': cfg.cluster_radius_m,
                            'maior_distancia_m': spread, 'pessoas': total, 'sem_contagem': unknown},
                           60+10*len(best)+total, evidence=[{'case_id': c['case_id'], 'received_at': c['received_at'], 'place': place(c)} for c in best]))
        gone = {c['case_id'] for c in best}
        rest = [c for c in rest if c['case_id'] not in gone]
    return out


def stale_send(cases, now, cfg):
    rows = []
    for c in cases:
        info = stale_info(c, now)
        if is_open(c) and info['stale'] and c.get('status') != 'callback_requested':
            rows.append((c, info['age_hours']))
    if not rows:
        return []
    top = max(a for _, a in rows)
    detail = '; '.join(f"{place(c)}: {round(a, 1)} h" for c, a in sorted(rows, key=lambda r: -r[1])[:6])
    text = (f"{len(rows)} pedidos SEND/ASSIGNED sem atualização há mais que o limite de {threshold():g} h "
            f"(maior espera {round(top, 1)} h). {detail}.")
    return [finding('stale_send', 'all', [c['case_id'] for c, _ in rows], text,
                    {'pedidos': len(rows), 'limite_h': threshold(), 'maior_espera_h': round(top, 1)},
                    80+5*len(rows)+int(top),
                    evidence=[{'case_id': c['case_id'], 'age_hours': a, 'status': c.get('status'), 'place': place(c)} for c, a in rows])]


def idle_resources(cases, now, inventory, cfg):
    day = now[:10]
    idle = [u for u in inventory if u.get('available') is True and u.get('observed_date', '9999') <= day]
    waiting = [(c, hours(now, c['received_at'])*60) for c in cases
               if is_open(c) and c.get('result', {}).get('decision') in SEND and c.get('status') in ('proposed', 'PARTIAL')
               and hours(now, c['received_at'])*60 >= cfg.idle_wait_min]
    if not idle or not waiting:
        return []
    longest = round(max(m for _, m in waiting))
    unknown_cap = sum(u.get('capacity') is None for u in idle)
    text = (f"{len(idle)} recursos disponíveis sem missão enquanto {len(waiting)} pedidos SEND aguardam há pelo menos "
            f"{cfg.idle_wait_min} min (maior espera {longest} min)."
            + (f" {unknown_cap} recursos com capacidade a confirmar." if unknown_cap else ''))
    return [finding('idle_resources', 'all', [c['case_id'] for c, _ in waiting], text,
                    {'recursos_ociosos': len(idle), 'pedidos_aguardando': len(waiting), 'espera_minima_min': cfg.idle_wait_min,
                     'maior_espera_min': longest, 'capacidade_a_confirmar': unknown_cap},
                    70+4*len(waiting)+5*len(idle), resource_ids=[u['id'] for u in idle],
                    evidence=[{'resource_id': u['id'], 'asset': u.get('asset'), 'capacity': u.get('capacity')} for u in idle])]


def rising_depth(cases, now, cfg):
    rows = []
    for c in [c for c in cases if is_open(c) and point(c)][:cfg.max_depth_cases]:
        try:
            obs = [r for r in dated_depth(c, now) if r.get('depth_band') in BANDS]
        except Exception:
            continue
        obs.sort(key=lambda r: r['observation_date'])
        if len(obs) >= 2:
            a, b = obs[-2], obs[-1]
            if BANDS.index(b['depth_band']) > BANDS.index(a['depth_band']):
                rows.append((c, a, b))
    if not rows:
        return []
    detail = '; '.join(f"{place(c)}: {BAND_PT[a['depth_band']]} em {a['observation_date']} -> {BAND_PT[b['depth_band']]} em {b['observation_date']}"
                       for c, a, b in rows[:5])
    text = (f"Faixa de profundidade subiu entre observações datadas perto de {len(rows)} pedidos abertos "
            f"(HAND retrospectivo, confiança baixa; ausência de dado não significa seco). {detail}.")
    return [finding('rising_depth', 'all', [c['case_id'] for c, _, _ in rows], text,
                    {'pedidos': len(rows)}, 50+6*len(rows),
                    evidence=[{'case_id': c['case_id'], 'from': {'band': a['depth_band'], 'date': a['observation_date']},
                               'to': {'band': b['depth_band'], 'date': b['observation_date']}, 'retrospective': True, 'place': place(c)}
                              for c, a, b in rows])]


def callback_aging(cases, now, cfg, callback_times=None):
    callback_times = callback_times or {}
    rows = []
    for c in cases:
        if not is_open(c) or not (c.get('result', {}).get('decision') == 'CALLBACK' or c.get('status') == 'callback_requested'):
            continue
        ref = c.get('last_update_at', c['received_at'])
        asked = callback_times.get(c['case_id'])
        if asked and timestamp(asked) > timestamp(ref):
            ref = asked
        age = hours(now, ref)
        if age >= cfg.callback_age_h:
            rows.append((c, age))
    if not rows:
        return []
    top = max(a for _, a in rows)
    text = (f"{len(rows)} retornos (callbacks) abertos sem resposta há pelo menos {cfg.callback_age_h} h "
            f"(maior espera {round(top, 1)} h). " + '; '.join(f"{place(c)}: {round(a, 1)} h" for c, a in sorted(rows, key=lambda r: -r[1])[:6]) + '.')
    return [finding('callback_aging', 'all', [c['case_id'] for c, _ in rows], text,
                    {'retornos': len(rows), 'limite_h': cfg.callback_age_h, 'maior_espera_h': round(top, 1)},
                    55+4*len(rows)+int(top), evidence=[{'case_id': c['case_id'], 'age_hours': round(a, 2)} for c, a in rows])]


def missions_state(cases):
    by = {}
    for c in cases:
        mid = c.get('mission_id')
        if mid and c.get('mission'):
            by.setdefault(mid, []).append(c)
    return by


def mission_feedback(cases, now, cfg, first_seen=None):
    first_seen = first_seen or {}
    out = []
    for mid, members in sorted(missions_state(cases).items()):
        if not any(c.get('status') == 'ASSIGNED:'+mid for c in members):
            continue
        stops = [s['case_id'] for s in members[0]['mission']['stops']]
        done = [c for c in members if c.get('mission_stop_done')]
        pending = [c for c in members if c['case_id'] in stops and not c.get('mission_stop_done')]
        if not pending:
            continue
        times = [f['received_at'] for c in done for f in c.get('feedback', []) if f.get('received_at')]
        ref = max(times, key=timestamp) if times else first_seen.get(mid)
        if not ref or hours(now, ref) < cfg.mission_feedback_h:
            continue
        age = round(hours(now, ref), 1)
        text = (f"Missão em andamento com {len(done)} de {len(stops)} paradas com retorno de campo; "
                f"sem retorno novo há {age} h (limite {cfg.mission_feedback_h} h). Pendentes: " + ', '.join(place(c) for c in pending) + '.')
        out.append(finding('mission_feedback', mid, [c['case_id'] for c in pending], text,
                           {'paradas_total': len(stops), 'paradas_com_retorno': len(done), 'espera_h': age, 'limite_h': cfg.mission_feedback_h},
                           65+5*len(pending)+int(age), mission_ids=[mid],
                           evidence=[{'case_id': c['case_id'], 'place': place(c)} for c in pending]))
    return out


def detect(cases, now, inventory, cfg=None, first_seen=None, callback_times=None):
    cfg = cfg or Config.from_env()
    cases = visible(cases, now)
    found = (cluster_growth(cases, now, cfg) + stale_send(cases, now, cfg) + idle_resources(cases, now, inventory, cfg)
             + rising_depth(cases, now, cfg) + callback_aging(cases, now, cfg, callback_times) + mission_feedback(cases, now, cfg, first_seen))
    return sorted(found, key=lambda f: (-f['severity'], f['id'])), cases
