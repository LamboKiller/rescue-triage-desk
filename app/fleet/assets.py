"""Typed, documented units adapted to the existing mission inventory schema.

Unknown capabilities remain null. Demo limits describe synthetic units, not SOP.
"""
import copy
import json
import math
from datetime import date, datetime
from app.config import ROOT

RULE_TYPES = {'barco_aluminio':'aluminium_outboard', 'bote_inflavel':'irb',
    'jet_ski':'pwc_sled', 'caminhao_alto':'high_clearance_truck',
    'anfibio':'amphibious_vehicle', 'helicoptero':'helicopter_hoist',
    'ambulancia':'road_ambulance'}
TYPE_LABELS = {'barco_aluminio':'Barco de alumínio', 'bote_inflavel':'Bote inflável',
    'jet_ski':'Jet ski com prancha', 'caminhao_alto':'Caminhão alto',
    'anfibio':'Anfíbio', 'helicoptero':'Helicóptero (somente solicitação)',
    'ambulancia':'Ambulância (acesso seco)'}


def normalize(raw):
    if not isinstance(raw,dict): raise ValueError('Recurso deve ser objeto.')
    u=copy.deepcopy(raw)
    kind=u.get('type') or next((k for k,v in RULE_TYPES.items() if v==u.get('asset')),None)
    if kind not in RULE_TYPES: raise ValueError('Tipo fora do alocador.')
    if u.get('asset') not in (None,RULE_TYPES[kind]): raise ValueError('Tipo e regra divergem.')
    for key in ('id','source'):
        if not isinstance(u.get(key),str) or not u[key].strip() or len(u[key])>500:
            raise ValueError('Informe '+key+'.')
    if any(ch in u['id'] for ch in '\r\n\t'): raise ValueError('Identificador inválido.')
    u.update(type=kind,asset=RULE_TYPES[kind],label_pt=TYPE_LABELS[kind])
    u['status']=u.get('status', 'available' if u.get('available') is True else 'out_of_service')
    if u['status']=='maintenance': u['status']='out_of_service'
    if u['status'] not in ('available','assigned','out_of_service'): raise ValueError('Estado inválido.')
    cap=u.get('capacity_people',u.get('capacity'))
    if cap is not None and (type(cap) is not int or cap<1): raise ValueError('Capacidade inválida.')
    for key in ('draft_m','max_wading_depth_m'):
        v=u.get(key)
        if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or v<0):
            raise ValueError('Limite inválido: '+key)
        u[key]=v
    flags=u.get('attestations',{})
    if not isinstance(flags,dict) or any(v is not None and type(v) is not bool for v in flags.values()):
        raise ValueError('Verificações inválidas.')
    for key,legacy in [('stretcher','stretcher_capable'),('night_ok','night_capable'),
                       ('pets_ok',None),('medical_crew',None)]:
        v=u.get(key,flags.get(legacy) if legacy else None)
        if v is not None and type(v) is not bool: raise ValueError('Atributo inválido: '+key)
        u[key]=v
    p=u.get('base_location')
    if p is not None:
        if not isinstance(p,dict) or any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) for k in ('lat','lon')) or not -90<=p['lat']<=90 or not -180<=p['lon']<=180:
            raise ValueError('Coordenadas da base inválidas.')
    reported=u.get('last_report_at')
    if reported is not None:
        if not isinstance(reported,str): raise ValueError('Horário inválido.')
        stamp=datetime.fromisoformat(reported.replace('Z','+00:00'))
        if stamp.tzinfo is None: raise ValueError('Horário exige fuso.')
    observed=u.get('observed_date') or (reported[:10] if reported else None)
    if observed is not None and date.fromisoformat(observed).isoformat()!=observed: raise ValueError('Data inválida.')
    load=u.get('current_load',0)
    if type(load) is not int or load<0: raise ValueError('Carga atual inválida.')
    synthetic=u.get('synthetic',False)
    if type(synthetic) is not bool: raise ValueError('synthetic deve ser booleano.')
    if synthetic and '[SIMULADO]' not in u['source']: u['document_source']=u['source'];u['source']='[SIMULADO]'
    u.update(capacity_people=cap,capacity=cap,observed_date=observed,
        last_report_at=reported,source_kind='[SIMULADO]' if synthetic else u.get('source_kind','operator'),
        synthetic=synthetic,current_load=load,available=u['status']=='available' and kind!='helicoptero',
        request_only=kind=='helicoptero',
        capacity_basis='rescue_passengers_after_crew_and_equipment',attestations=flags)
    if u['source_kind'] not in ('configured','operator','[SIMULADO]'): raise ValueError('Origem inválida.')
    return u


def demo_inventory(day=None):
    units=[normalize(u) for u in json.loads((ROOT/'data/fleet/assets_demo.json').read_text(encoding='utf-8'))]
    for u in units:
        u['simulation_replay_template']=True
    return replay_inventory(units,day) if day else units


def replay_inventory(units,day):
    """Instantiate explicitly synthetic shift templates; real observations are never backdated."""
    date.fromisoformat(day)
    out=copy.deepcopy(units)
    for u in out:
        if u.get('synthetic') is True and u.get('simulation_replay_template') is True:
            u['template_observed_date']=u.get('template_observed_date',u.get('observed_date'))
            u['observed_date']=day;u['last_report_at']=day+'T00:00:00-03:00'
            u['simulation_replay_date']=day
    return out
