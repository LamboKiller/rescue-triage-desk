"""User-run live smoke. No service call is made on import; never prints secrets."""
import json
import sys
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env, setting
from app.data.s3 import S3
from app.data.zetaris import Zetaris, identifier
from app.data.source import ZetarisSource
from app.engines.world_model.registry import Registry
from app.llm.nightshift import Nightshift
from app.pipeline import Pipeline


def main():
    load_env()
    for key in ('NIGHTSHIFT_API_KEY', 'ZETARIS_API_KEY', 'S3_ACCESS_KEY', 'S3_SECRET_KEY'):
        if not setting(key):
            print('Missing environment setting: '+key)
            return 1
    try:
        print('[1] Nightshift: one small JSON call (thinking ON)')
        client = Nightshift(ROOT/'logs'/('run_smoke_'+uuid.uuid4().hex+'.jsonl'))
        result, meta = client.call('smoke', 'Return JSON only with ok=true. Do not include personal information.',
                                   {'task': 'connection smoke test'}, time.monotonic()+180)
        if not isinstance(result, dict) or result.get('ok') is not True or not meta.get('receipt'):
            raise ValueError('Nightshift JSON/receipt missing')
        # Nightshift races its lanes; the winner may differ from the requested id. Require a real Nemotron winner.
        routed = str(meta.get('model') or '')
        if not (routed.startswith('nvidia/') and 'nemotron' in routed):
            raise ValueError('Routed model is not an NVIDIA Nemotron model: ' + routed)
        print('Nightshift JSON + Nemotron winner (' + routed + ') + receipt checked')
        print('[2] Zetaris: SELECT each registered table')
        table_file = ROOT/'data/zetaris_tables.json'
        if not table_file.exists():
            raise RuntimeError('Run tools/load_zetaris.py first')
        tables = json.loads(table_file.read_text())
        required = [setting('ZETARIS_LANDMARKS_TABLE', 'landmarks_v3'),
                    setting('ZETARIS_STREETS_TABLE', 'streets_flood_v3'),
                    setting('ZETARIS_MESSAGES_TABLE', 'messages_seed7_v3')]
        if any(table not in tables or tables[table] <= 0 for table in required):
            raise ValueError('Register all v3 tables, including landmarks, before smoke testing')
        for table, expected in tables.items():
            actual = int(Zetaris().query('SELECT COUNT(*) AS n FROM OAH_S3.'+identifier(table))['data'][0][0])
            if actual != expected:
                raise ValueError('Zetaris table count mismatch')
            print(f'{table}: {actual} rows verified')
        print('[3] S3: signed upload/read-back of tiny synthetic probe')
        s3 = S3()
        key, payload = 'smoke/probe-'+uuid.uuid4().hex+'.txt', b'synthetic live smoke only\n'
        s3.put(key, payload)
        if s3.get(key) != payload:
            raise ValueError('S3 read-back mismatch')
        print('S3 bytes verified (small probe retained)')
        print('[4] End-to-end: three synthetic messages, normal Zetaris source + Nightshift')
        messages = ZetarisSource().messages()[:3]
        if len(messages) != 3:
            raise ValueError('Synthetic message table must have at least three rows')
        request = {'replay_time': '2024-05-06T14:00:00-03:00', 'messages': messages}
        registry = Registry(ROOT/'runtime'/('smoke_'+uuid.uuid4().hex+'.jsonl'))
        result = Pipeline(registry, source=ZetarisSource()).run(request)
        if result['partial'] or len(result['cases']) != 3 or any(not c['calls'] for c in result['cases']):
            raise RuntimeError('End-to-end returned partial results')
        print('3 cases persisted; all agent stages completed; receipts stored in logs.')
        print('LIVE SMOKE PASSED. Next: python tools/make_examples.py and python eval/run_eval.py')
        return 0
    except Exception as exc:
        detail = str(exc)[:200]
        for name in ('NIGHTSHIFT_API_KEY', 'ZETARIS_API_KEY', 'S3_ACCESS_KEY', 'S3_SECRET_KEY'):
            if setting(name):
                detail = detail.replace(setting(name), '***')
        print('LIVE SMOKE FAILED: '+type(exc).__name__+': '+detail+' (secrets omitted).')
        return 1


if __name__ == '__main__':
    sys.exit(main())
