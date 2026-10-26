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

# MS medical lane. Time-to-harm = hours WITHOUT the support before serious harm becomes likely. These are OPERATIONAL
# ESTIMATES (estimativa operacional) for ordering a queue, not clinical thresholds; they are never inputs to SEND/CALLBACK
# and a clinician/SAMU regulation overrides them. Lower bound first; sort key is the lower bound.
MEDICAL_BASIS='estimativa operacional (ordem de fila); validar com regulacao medica / SAMU'
MEDICAL_TIME_TO_HARM={
    'oxygen':{'label_pt':'Oxigenio / ventilacao domiciliar','hours':(1,6),'why_pt':'cilindro/concentrador sem energia ou carga esgota em poucas horas'},
    'pregnancy_labor':{'label_pt':'Gestante em trabalho de parto / sangramento','hours':(1,6),'why_pt':'parto pode ocorrer a qualquer momento; sem equipe'},
    'wound_trauma':{'label_pt':'Ferimento / trauma','hours':(1,8),'why_pt':'hemorragia, infeccao em agua contaminada'},
    'newborn':{'label_pt':'Recem-nascido','hours':(2,12),'why_pt':'termorregulacao e alimentacao frageis'},
    'insulin':{'label_pt':'Insulina / diabetes','hours':(12,24),'why_pt':'sem insulina a descompensacao surge em ate ~1 dia'},
    'bedridden':{'label_pt':'Pessoa acamada','hours':(12,48),'why_pt':'dependente de cuidador; risco por agua, frio e escaras'},
    'dialysis':{'label_pt':'Dialise / hemodialise','hours':(24,72),'why_pt':'sessao perdida acumula toxinas e liquido em 1-3 dias'},
    'medication_other':{'label_pt':'Medicacao de uso continuo','hours':(24,72),'why_pt':'depende do medicamento; confirmar qual'}}


def medical_needs(case,feedback=True):
    """One row per medical need, quote-backed, sorted by shortest time-to-harm. Never invents a need without a quote."""
    from app.agents.needs import scan_medical
    msgs=texts(case)+([f['text'] for f in case.get('feedback',[]) if not f.get('conflicts')] if feedback else [])
    seen={};rows=[]
    for r in list(case.get('operational_needs',{}).get('medical',[]))+scan_medical(msgs):
        need=r.get('medical_need')
        if need not in MEDICAL_TIME_TO_HARM or need in seen or not r.get('quote'): continue
        seen[need]=1;t=MEDICAL_TIME_TO_HARM[need]
        rows.append({'medical_need':need,'label_pt':t['label_pt'],'quote':r['quote'],'message_index':r.get('message_index'),
                     'hours_low':t['hours'][0],'hours_high':t['hours'][1],'basis':MEDICAL_BASIS,'why_pt':t['why_pt']})
    return sorted(rows,key=lambda r:(r['hours_low'],r['hours_high'],r['medical_need']))


def medical_view(case,now):
    """Card payload: needs + remaining hours against the shortest window, counted from when the message arrived."""
    rows=medical_needs(case)
    if not rows: return None
    waited=hours(now,case['received_at']) if timestamp(case['received_at'])<=timestamp(now) else 0
    first=rows[0]
    return {'needs':rows,'time_to_harm_hours':[first['hours_low'],first['hours_high']],'waited_hours':round(waited,2),
            'window_exceeded':waited>=first['hours_high'],'window_note_pt':'janela estimada ate dano, a partir da mensagem; '+MEDICAL_BASIS}


def medical_queue(cases,now=None):
    """'Fila medica': only cases with a quoted medical need, shortest remaining window first. Order only; no decision changes."""
    rows=[]
    for c in queue(cases,now):
        m=c.get('medical')
        if m: rows.append(c)
    return sorted(rows,key=lambda c:(c['medical']['time_to_harm_hours'][0]-c['medical']['waited_hours'],
                                     c['medical']['time_to_harm_hours'][1],-c['live_priority']['score'],c['case_id']))


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
    med=medical_needs(case)
    for m in med: reasons.append({'reason_pt':'Necessidade medica: '+m['label_pt']+' - dano provavel em ~'+str(m['hours_low'])+'-'+str(m['hours_high'])+' h sem apoio ('+MEDICAL_BASIS.split(';')[0]+'); "'+m['quote']+'"','points':0,'medical_need':m['medical_need']})
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
        c['stale_info']=stale_info(c,clock);c['live_priority']=score(c,clock,dated_depth(c,clock));c['medical']=medical_view(c,clock)
        c['result']['priority']=c['live_priority']['score'];out.append(c)
    return sorted(out,key=lambda c:(-c['live_priority']['score'],c['received_at'],c['case_id']))
