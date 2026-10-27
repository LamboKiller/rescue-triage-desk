"""Unified Semantic Layer reads: pure joins over whichever DataSource is active.

Each function mirrors one view in sql/usl/*.sql exactly, so SAMPLE_MODE (LocalSource,
offline CSVs) and connected mode (ZetarisSource, live Zetaris) compute the identical
shape from the identical underlying rows. Not yet called from the pipeline, agents or
web layer -- see docs/submission/SPONSOR_GAPS.md for why and where it would plug in.
"""
from app.config import sample_mode
from app.data.source import LocalSource, ZetarisSource


def _source():
    return LocalSource() if sample_mode() else ZetarisSource()


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def incident_context(timeout=120):
    """sql/usl/incident_context.sql: landmarks x per-municipality flooded-segment totals."""
    source = _source()
    totals = {}
    for row in source.streets(timeout=timeout):
        muni = row.get('municipality')
        agg = totals.setdefault(muni, {'total_segments': 0.0, 'flooded_segments_0506': 0.0})
        agg['total_segments'] += _num(row.get('segments')) or 0.0
        agg['flooded_segments_0506'] += _num(row.get('segments_in_water_2024-05-06')) or 0.0
    out = []
    for row in source.landmarks(timeout=timeout):
        agg = totals.get(row.get('municipality'), {})
        out.append({
            **{k: row.get(k) for k in ('osm_type', 'osm_id', 'name', 'category', 'municipality',
                                        'street', 'housenumber', 'lat', 'lon')},
            'landmark_in_water_0506': row.get('in_water_2024-05-06'),
            'landmark_in_water_0508': row.get('in_water_2024-05-08'),
            'municipality_flooded_segments_0506': agg.get('flooded_segments_0506'),
            'municipality_total_segments': agg.get('total_segments'),
        })
    return out


def asset_availability(timeout=120):
    """sql/usl/asset_availability.sql: pump assets x their daily status feed."""
    source = _source()
    by_pump = {row['source_fid']: row for row in source.pumps(timeout=timeout)}
    out = []
    for row in source.pump_status_daily(timeout=timeout):
        pump = by_pump.get(row.get('source_fid'))
        if pump is None:
            continue
        out.append({
            'source_fid': row['source_fid'], 'asset_name': pump.get('name'),
            'municipality': pump.get('municipality'), 'lat': pump.get('lat'), 'lon': pump.get('lon'),
            'status_date': row.get('date'), 'status': row.get('status'),
            'is_down': row.get('status') == 'Inoperante',
        })
    return out


def shelter_capacity(timeout=120):
    """sql/usl/shelter_capacity.sql: shelter snapshots with derived occupancy fields."""
    out = []
    for row in _source().shelters(timeout=timeout):
        cap, sheltered = _num(row.get('capacity')), _num(row.get('sheltered_people'))
        out.append({
            **{k: row.get(k) for k in ('id', 'municipality', 'facility_type', 'lat', 'lon',
                                        'capacity', 'sheltered_people', 'vacancies', 'snapshot_local')},
            'occupancy_rate': (sheltered / cap) if cap and sheltered is not None else None,
            'over_capacity_flag': bool(cap is not None and sheltered is not None and sheltered > cap),
        })
    return out


def shelter_over_capacity_rule(timeout=120):
    """sql/usl/dq_rules.sql rule 1: sheltered_people must not exceed capacity."""
    checked = [row for row in shelter_capacity(timeout=timeout) if row['capacity'] not in (None, '')]
    violations = [row for row in checked if row['over_capacity_flag']]
    return {'checked': len(checked), 'violations': len(violations), 'examples': violations[:5]}
