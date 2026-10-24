import csv
from typing import Protocol
from app.config import ROOT, setting
from app.data.zetaris import Zetaris


class DataSource(Protocol):
    def streets(self, timeout=120): ...


class LocalSource:
    def streets(self, timeout=120):
        with (ROOT/'data/streets_flood.csv').open(encoding='utf-8', newline='') as file:
            return list(csv.DictReader(file))


class ZetarisSource:
    def streets(self, timeout=120):
        return Zetaris().rows(setting('ZETARIS_STREETS_TABLE', 'streets_flood_v1'), timeout=timeout)

    def messages(self, timeout=120):
        return Zetaris().rows(setting('ZETARIS_MESSAGES_TABLE', 'messages_seed7_v1'), timeout=timeout)
