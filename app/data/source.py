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


class LocalSource:
    def landmarks(self, timeout=120):
        path = ROOT/'data/landmarks.csv'
        if not path.exists():
            return []
        with path.open(encoding='utf-8', newline='') as file:
            return with_aliases(list(csv.DictReader(file)))

    def streets(self, timeout=120):
        with (ROOT/'data/streets_flood.csv').open(encoding='utf-8', newline='') as file:
            return list(csv.DictReader(file))


class ZetarisSource:
    def landmarks(self, timeout=120):
        return with_aliases(Zetaris().rows(setting('ZETARIS_LANDMARKS_TABLE', 'landmarks_v3'), timeout=timeout))

    def streets(self, timeout=120):
        return Zetaris().rows(setting('ZETARIS_STREETS_TABLE', 'streets_flood_v3'), timeout=timeout)

    def messages(self, timeout=120):
        return Zetaris().rows(setting('ZETARIS_MESSAGES_TABLE', 'messages_seed7_v3'), timeout=timeout)
