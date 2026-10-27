"""Builds messages.jsonl from items_a/items_b (hand-written labels). Run: python -m eval.dev2.build"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name('messages.jsonl')


def bucket(cls):
    return 'regression' if cls.startswith('reg_') else 'adversarial' if cls.startswith('adv_') else 'targeted'


def build():
    from eval.dev2 import items_a, items_b
    rows = []
    for i, item in enumerate(items_a.ITEMS + items_b.ITEMS, 1):
        item = dict(item, bucket=bucket(item['class']))
        rows.append({'id': 'd2-%03d' % i, **item})
    return rows


if __name__ == '__main__':
    rows = build()
    OUT.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8', newline='\n')
    from collections import Counter
    print(len(rows), Counter(r['bucket'] for r in rows))
