"""Upload versioned CSVs to S3, register Zetaris tables and verify counts.

Never print SQL, credentials or raw provider errors. Reuse a version only for
identical bytes; choose a new version after changing a source file.
"""
import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env, setting
from app.data.s3 import S3
from app.data.zetaris import Zetaris, identifier


def sql_string(value):
    # Gate 0 syntax uses double-quoted option values. Reject metacharacters.
    if any(ch in value for ch in ('"', '\\', '\n', '\r')):
        raise ValueError('Unsupported SQL option character')
    return '"'+value+'"'


def load(version='v3', seed=7):
    identifier(version)
    client, s3 = Zetaris(), S3()
    s3.request('PUT', create_bucket=True)
    client.query('CREATE LIGHTNING DATABASE OAH_S3 DESCRIBE BY "Rescue_Triage_Desk_V1"', allow_exists=True)
    payloads = []
    if not (ROOT/'data/landmarks.csv').exists():
        raise FileNotFoundError('Landmark snapshot required before registering tables')
    for path in sorted((ROOT/'data').glob('*.csv')):
        payloads.append((path.stem+'_'+version, path.read_bytes()))
    sample = ROOT/f'data/sample/messages_seed{seed}.jsonl'
    messages = [json.loads(line) for line in sample.read_text(encoding='utf-8').splitlines()]
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=['message_id', 'synthetic', 'received_at', 'text'])
    writer.writeheader()
    writer.writerows({k: m[k] for k in writer.fieldnames} for m in messages)
    payloads.append((f'messages_seed{seed}_{version}', out.getvalue().encode()))
    table_counts = {}
    for table, payload in payloads:
        identifier(table)
        digest = hashlib.sha256(payload).hexdigest()[:12]
        key = f'{table}_{digest}.csv'
        s3.put(key, payload)
        if s3.get(key) != payload:
            raise RuntimeError('S3 byte verification failed')
        options = {'PATH': f's3a://{setting("S3_BUCKET", "oah-data")}/{key}',
                   's3Endpoint': setting('S3_ENDPOINT_INTERNAL', 'http://oah-s3:8333'),
                   'useS3PathStyleAccess': 'true', 'AWSACCESSKEYID': setting('S3_ACCESS_KEY'),
                   'AWSSECRETACCESSKEY': setting('S3_SECRET_KEY'), 'header': 'true',
                   # Keep values exactly as written (timestamps keep -03:00; Spark type inference dropped the offset).
                   'inferSchema': 'false'}
        sql = f'CREATE LIGHTNING FILESTORE TABLE {table} FROM OAH_S3 FORMAT CSV OPTIONS ('
        sql += ', '.join(k+' '+sql_string(v) for k, v in options.items())+')'
        client.query(sql, allow_exists=True)
        result = client.query(f'SELECT COUNT(*) AS n FROM OAH_S3.{table}')
        actual = int(result['data'][0][0])
        expected = len(list(csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))))
        if actual != expected:
            raise RuntimeError(f'Row count mismatch for {table}: {actual} vs {expected}')
        table_counts[table] = expected
        print(f'{table}: upload/read-back verified; Zetaris SELECT count={actual}')
    (ROOT/'data/zetaris_tables.json').write_text(json.dumps(table_counts, indent=2)+'\n', encoding='utf-8')
    return table_counts


if __name__ == '__main__':
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='v3')
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args()
    try:
        load(args.version, args.seed)
    except Exception as exc:
        sys.exit('Load failed ('+type(exc).__name__+'). Check local services and .env; no credentials printed.')
