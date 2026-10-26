"""Invalidated, process-local allocation read snapshot; approval still reads atomically."""
import copy
from app.resources import read_unlocked
from app.missions.actions import reserved_units
from .assets import normalize, replay_inventory, RULE_TYPES


def read(service,case_id,day):
    registry=service.registry
    with registry.locked():
        stat=registry.path.stat() if registry.path.exists() else None
        stamp=(stat.st_mtime_ns,stat.st_size,stat.st_ctime_ns) if stat else None
        cache=getattr(service,'_fleet_snapshot',None)
        if cache is None or cache[0]!=stamp:
            cases=registry._read()[0]
            stored=read_unlocked(registry);ids={u['id'] for u in stored}
            service._fleet_snapshot=(stamp,cases,stored,ids,reserved_units(cases.values()))
        _,cases,stored,ids,reserved=service._fleet_snapshot
        case=cases.get(case_id)
        if case is None: raise KeyError(case_id)
        units=stored+[u for u in service.allocation_inventory if u['id'] not in ids]
        units=[normalize(u) for u in replay_inventory(units,day)
               if u.get('type') in RULE_TYPES or u.get('asset') in RULE_TYPES.values()]
        for u in units:
            if u['id'] in reserved: u.update(status='assigned',available=False)
        return copy.deepcopy(case),units
