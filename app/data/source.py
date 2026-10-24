import csv
from typing import Protocol
from app.config import ROOT, setting
from app.data.zetaris import Zetaris


class DataSource(Protocol):
    def streets(self, timeout=120): ...
    def landmarks(self, timeout=120): ...


class LocalSource:
    def landmarks(self, timeout=120):
        path = ROOT/'data/landmarks.csv'
        if not path.exists():
            return []
        with path.open(encoding='utf-8', newline='') as file:
            return list(csv.DictReader(file))

    def streets(self, timeout=120):
        with (ROOT/'data/streets_flood.csv').open(encoding='utf-8', newline='') as file:
            return list(csv.DictReader(file))


class ZetarisSource:
    def landmarks(self, timeout=120):
        return Zetaris().rows(setting('ZETARIS_LANDMARKS_TABLE', 'landmarks_v3'), timeout=timeout)

    def streets(self, timeout=120):
        return Zetaris().rows(setting('ZETARIS_STREETS_TABLE', 'streets_flood_v2'), timeout=timeout)

    def messages(self, timeout=120):
        return Zetaris().rows(setting('ZETARIS_MESSAGES_TABLE', 'messages_seed7_v2'), timeout=timeout)
