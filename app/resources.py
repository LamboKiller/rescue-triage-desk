"""Documented shift inventory, stored as World Model events; unknown capacity stays null."""
import copy
from datetime import date
from app.fleet import document
from app.redact import redact


def validate(unit):
    if not isinstance(unit,dict): raise ValueError('Informe um recurso.')
    out=copy.deepcopy(unit)
    if 'type' in out:
        from app.fleet.assets import normalize
        out=normalize(out)
    for key in ('id','crew','base','source','observed_date'):
        if not isinstance(out.get(key),str) or not out[key].strip() or len(out[key])>500: raise ValueError('Informe '+key+'.')
    if out.get('asset') not in document()['assets']: raise ValueError('Tipo fora das regras da frota.')
    if out.get('status') not in ('available','assigned','maintenance','out_of_service'): raise ValueError('Estado de recurso invalido.')
    if date.fromisoformat(out['observed_date']).isoformat()!=out['observed_date']: raise ValueError('Data invalida.')
    cap=out.get('capacity')
    if cap is not None and (type(cap) is not int or cap<=0): raise ValueError('Capacidade deve ser positiva ou desconhecida.')
    if cap is not None and not out.get('capacity_source'): raise ValueError('Informe a fonte documental da capacidade.')
    flags=out.get('attestations',{})
    if not isinstance(flags,dict) or any(k not in document()['verification_fields'] or v is not None and type(v) is not bool for k,v in flags.items()): raise ValueError('Verificacoes de frota invalidas.')
    if type(out.get('synthetic',False)) is not bool: raise ValueError('synthetic deve ser booleano.')
    out['capacity_basis']='rescue_passengers_after_crew_and_equipment'
    out['capacity']=cap;out['available']=out['status']=='available' and out.get('type')!='helicoptero'
    return out


def read(registry):
    with registry.locked():
        units={}
        if registry.path.exists():
            import json
            for line in registry.path.read_text(encoding='utf-8-sig').splitlines():
                event=json.loads(line)
                if event['kind']=='resource': units[event['unit']['id']]=event['unit']
        from app.missions.actions import reserved_units
        reserved=reserved_units(registry._read()[0].values())
        for uid,unit in units.items():
            if uid in reserved: unit.update(status='assigned',available=False)
        return sorted(copy.deepcopy(list(units.values())),key=lambda u:u['id'])


def register(registry,request):
    from app.engines.world_model.registry import Conflict
    if not isinstance(request,dict): raise ValueError('Envie objeto JSON.')
    actor=request.get('actor');expected=request.get('expected_version',0)
    if not isinstance(actor,str) or not actor.strip() or len(actor)>120: raise ValueError('Identifique o operador.')
    if type(expected) is not int or expected<0: raise ValueError('Informe expected_version inteiro.')
    unit=validate(request.get('unit'))
    with registry.locked():
        current=next((u for u in read_unlocked(registry) if u['id']==unit['id']),None)
        if (current or {}).get('version',0)!=expected: raise Conflict('Recurso alterado; recarregue.')
        from app.missions.actions import reserved_units
        if unit['id'] in reserved_units(registry._read()[0].values()): raise Conflict('Recurso em missao ativa; concluir ou cancelar antes de editar.')
        unit['version']=expected+1
        registry._append({'schema_version':1,'kind':'resource','actor':redact(actor.strip()),'unit':unit})
    return copy.deepcopy(unit)


def read_unlocked(registry):
    import json
    units={}
    if registry.path.exists():
        for line in registry.path.read_text(encoding='utf-8-sig').splitlines():
            event=json.loads(line)
            if event['kind']=='resource': units[event['unit']['id']]=event['unit']
    return list(units.values())


def inventory(registry,legacy=None):
    stored=read(registry);ids={u['id'] for u in stored}
    from app.unit_status import overlay_inventory
    return overlay_inventory(registry,stored+[copy.deepcopy(u) for u in legacy or [] if u['id'] not in ids])
