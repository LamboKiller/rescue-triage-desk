"""Detached queue projection; full evidence stays on the case-detail endpoint."""
import copy

# Fields omitted here are hydrated from detail by v2 before opening a case.
DETAIL_KEYS = ('facts', 'fleet', 'hazard_facts', 'hazards', 'fleet_summary', 'incident_state',
               'actions', 'agents', 'calls', 'latency_budget', 'initial_fields', 'duplicates',
               'cross_source', 'arbitration', 'message_results')


def project(case, *, scoring=False):
    drop = set(DETAIL_KEYS)
    if scoring:
        drop.discard('hazards')  # Priority uses dated hazard observations before serialization.
    out = {k: v for k, v in case.items() if k not in drop}
    out['summary'] = True
    out['fleet'] = [{k: a.get(k) for k in ('asset', 'label_pt', 'verdict')}
                    for a in case.get('fleet') or [] if isinstance(a, dict)]
    out['version_count'] = case.get('version_count', len(case.get('facts') or []))
    return copy.deepcopy(out)
