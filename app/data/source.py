import csv
from typing import Protocol
from app.config import ROOT, setting
from app.data.zetaris import Zetaris


def with_aliases(rows):
    """Both sources use the small, reviewed local alias CSV."""
    with (ROOT/'data/landmark_aliases.csv').open(encoding='utf-8', newline='') as file:
        aliases = list(csv.DictReader(file))
    by_id = {}
    for alias in aliases:
        by_id.setdefault((alias['osm_type'], alias['osm_id']), []).append(alias)
    return [{**row, 'curated_aliases': by_id.get((row['osm_type'], row['osm_id']), [])} for row in rows]


class DataSource(Protocol):
    def streets(self, timeout=120): ...
    def landmarks(self, timeout=120): ...
    def closures(self, timeout=120): ...
    def pump_status_daily(self, timeout=120): ...
    def pumps(self, timeout=120): ...
    def events(self, timeout=120): ...
    def shelters(self, timeout=120): ...
    def street_points(self, timeout=120): ...



class LocalSource:
    def closures(self, timeout=120):
        with (ROOT/'data/hazards/closures.csv').open(encoding='utf-8-sig', newline='') as file:
            return list(csv.DictReader(file))

    def pump_status_daily(self, timeout=120):
        with (ROOT/'data/hazards/pump_status_daily.csv').open(encoding='utf-8-sig', newline='') as file:
            return list(csv.DictReader(file))

    def pumps(self, timeout=120):
        with (ROOT/'data/hazards/pumps.csv').open(encoding='utf-8-sig', newline='') as file:
            return list(csv.DictReader(file))

    def events(self, timeout=120):
        with (ROOT/'data/hazards/events.csv').open(encoding='utf-8-sig', newline='') as file:
            return list(csv.DictReader(file))

    def shelters(self, timeout=120):
        with (ROOT/'data/hazards/shelters.csv').open(encoding='utf-8-sig', newline='') as file:
            return list(csv.DictReader(file))

    def street_points(self, timeout=120):
        with (ROOT/'data/hazards/street_points.csv').open(encoding='utf-8-sig', newline='') as file:
            return list(csv.DictReader(file))

    def landmarks(self, timeout=120):
        path = ROOT/'data/landmarks.csv'
        if not path.exists():
            return []
        with path.open(encoding='utf-8', newline='') as file:
            return with_aliases(list(csv.DictReader(file)))

    def streets(self, timeout=120):
        with (ROOT/'data/streets_flood.csv').open(encoding='utf-8', newline='') as file:
            return list(csv.DictReader(file))


def as_csv_strings(rows):
    """Zetaris REST returns empty CSV cells as null; the app expects the same '' strings as the local CSV."""
    return [{k: ('' if v is None else str(v)) for k, v in row.items()} for row in rows]


class ZetarisSource:
    def closures(self, timeout=120):
        return as_csv_strings(Zetaris().rows(setting('ZETARIS_CLOSURES_TABLE', 'closures_v4'), timeout=timeout))

    def pump_status_daily(self, timeout=120):
        return as_csv_strings(Zetaris().rows(setting('ZETARIS_PUMP_STATUS_DAILY_TABLE', 'pump_status_daily_v4'), timeout=timeout))

    def pumps(self, timeout=120):
        return as_csv_strings(Zetaris().rows(setting('ZETARIS_PUMPS_TABLE', 'pumps_v4'), timeout=timeout))

    def events(self, timeout=120):
        return as_csv_strings(Zetaris().rows(setting('ZETARIS_EVENTS_TABLE', 'events_v4'), timeout=timeout))

    def shelters(self, timeout=120):
        return as_csv_strings(Zetaris().rows(setting('ZETARIS_SHELTERS_TABLE', 'shelters_v4'), timeout=timeout))

    def street_points(self, timeout=120):
        return as_csv_strings(Zetaris().rows(setting('ZETARIS_STREET_POINTS_TABLE', 'street_points_v4'), timeout=timeout))

    def landmarks(self, timeout=120):
        return with_aliases(as_csv_strings(Zetaris().rows(setting('ZETARIS_LANDMARKS_TABLE', 'landmarks_v3'), timeout=timeout)))

    def streets(self, timeout=120):
        return as_csv_strings(Zetaris().rows(setting('ZETARIS_STREETS_TABLE', 'streets_flood_v3'), timeout=timeout))

    def messages(self, timeout=120):
        return as_csv_strings(Zetaris().rows(setting('ZETARIS_MESSAGES_TABLE', 'messages_seed7_v3'), timeout=timeout))
