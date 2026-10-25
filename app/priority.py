"""Replay-clock priority and idempotent stale callback detection. All arithmetic is code."""
import copy
import math
from app.decide import timestamp
from app.config import setting
from app.agents.needs import fallback, texts, pick_vertical

BANDS=('d_lt_0_15','d_0_15_to_0_3','d_0_3_to_0_6','d_0_6_to_1_2','d_1_2_to_2_5','d_gt_2_5')
# P1S: where the people are matters, and more when the water is rising. Reposts never add points (not here, not anywhere).
VERTICAL_POINTS={'roof':(20,'No telhado / laje'),'attic_forro':(20,'No forro / sotao'),'upper_floor':(8,'Andar superior'),'first_floor':(3,'Primeiro andar')}
VERTICAL_WATER_BONUS={'roof':10,'attic_forro':10,'upper_floor':5}
WEIGHTS={'medical_urgent':35,'structural_risk':35,'water_rising':25,'infant':20,'stretcher_or_bedridden':20,'wheelchair':15,'pregnant':15}


def threshold():
    n=float(setting('STALE_HOURS','6'))
    if not math.isfinite(n) or n<=0: raise ValueError('STALE_HOURS deve ser positivo.')
    return n


def hours(now,then): return max(0,(timestamp(now)-timestamp(then)).total_seconds()/3600)


def dated_depth(case,now):
    """Use the same retrospective grids as the map, never a later observation."""
    from app.geo.depth import DATES, lookup
    from app.missions.planner import point
    p=point(case)
    if not p: return []
    rows=[]
    for day in DATES:
        if day>now[:10]: continue
        row=lookup(p['lon'],p['lat'],day)
        if row:
            rows.append({**row,'observation_date':row['depth_observed_date'],
                         'retrospective':True})
    return rows


def stale_info(case,now,n=None):
    age=hours(now,case.get('last_update_at',case['received_at']))
    active=(case.get('status','').startswith('ASSIGNED:') or case.get('result',{}).get('decision') in ('SEND','SEND_CANDIDATE'))
    active=active and case.get('status') not in ('RESCUED','NOT_FOUND','field_confirmed')
    return {'stale':bool(active and age>=(threshold() if n is None else n)),'age_hours':round(age,2)}


def score(case,now,depth_history=None):
    reasons=[]
    def add(label,points):
        if points: reasons.append({'reason_pt':label,'points':points})
    if timestamp(case['received_at'])>timestamp(now): return {'score':0,'reasons':[]}
    context=fallback(texts(case)+[f['text'] for f in case.get('feedback',[]) if not f.get('conflicts')])
    needs={r['tag'] for r in context['needs']}
    needs.update(r['tag'] for r in case.get('operational_needs',{}).get('needs',[]))
    level=pick_vertical({'vertical':context['vertical']+list(case.get('operational_needs',{}).get('vertical',[]))})['level']
    for tag,weight in WEIGHTS.items():
        if tag in needs: add({'medical_urgent':'Urgencia medica','structural_risk':'Risco de desabamento','water_rising':'Agua subindo','infant':'Bebe','stretcher_or_bedridden':'Pessoa acamada / maca','wheelchair':'Cadeira de rodas','pregnant':'Gestante'}[tag],weight)
    if level in VERTICAL_POINTS: add(VERTICAL_POINTS[level][1],VERTICAL_POINTS[level][0])
    if 'water_rising' in needs and level in VERTICAL_WATER_BONUS: add('Agua subindo com pessoas em nivel alto',VERTICAL_WATER_BONUS[level])
    v=lambda k:case.get('fields',{}).get(k,{}).get('value',0)
    people=case.get('remaining_n',v('people'))
    add('Pessoas aguardando (limite 20)',min(20,max(0,people)) if type(people) is int else 0)
    vulnerable=max([v(k) if type(v(k)) is int else 0 for k in ('children','elderly','disabled')])
    add('Pessoas vulneraveis (categorias podem se sobrepor)',5*min(10,max(0,vulnerable)))
    add('Tempo de espera em horas (limite 24)',min(24,int(hours(now,case['received_at']))))
    stale=stale_info(case,now)['stale'];add('Sem atualizacao; retorno necessario',8 if stale else 0)
    add('Local aproximado; confirmar ponto exato',-3 if case.get('result',{}).get('location_approximate') else 0)
    # Only dated observations available on the replay day may influence score.
    rows=list(depth_history if depth_history is not None else case.get('depth_history',[]))
    hazard=case.get('hazards') or {}
    observed=hazard.get('depth_observed_date',hazard.get('observation_date'))
    if observed: rows.append({**hazard,'observation_date':observed,'retrospective':hazard.get('depth_retrospective',hazard.get('retrospective',False))})
    day=now[:10]
    rows=sorted([r for r in rows if isinstance(r,dict) and r.get('observation_date','9999')<=day and r.get('depth_band') in BANDS],key=lambda r:r['observation_date'])
    if rows:
        latest=rows[-1];band=BANDS.index(latest['depth_band'])
        add('Faixa de profundidade observada'+(' (retrospectiva, confianca baixa)' if latest.get('retrospective') else ''),band*3)
        previous=next((r for r in reversed(rows[:-1]) if r['observation_date']<latest['observation_date']),None)
        if previous and band>BANDS.index(previous['depth_band']): add('Faixa de profundidade aumentou entre observacoes datadas',12)
    else: reasons.append({'reason_pt':'Profundidade sem observacao datada; desconhecido nao significa seco','points':0})
    return {'score':sum(r['points'] for r in reasons),'reasons':reasons}


def queue(cases,now=None):
    out=[]
    for case in cases:
        c=copy.deepcopy(case);clock=now or c['replay_time']
        c['stale_info']=stale_info(c,clock);c['live_priority']=score(c,clock,dated_depth(c,clock))
        c['result']['priority']=c['live_priority']['score'];out.append(c)
    return sorted(out,key=lambda c:(-c['live_priority']['score'],c['received_at'],c['case_id']))
