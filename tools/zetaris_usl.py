"""Build and verify the Unified Semantic Layer (sql/usl/*.sql) against live Zetaris.

--build  submits each view's CREATE VIEW statement to Zetaris, proving the DDL parses
         and executes against the live engine (status, not a guess).
--check  runs 2-3 proving queries per view plus the data-quality rules in
         sql/usl/dq_rules.sql, inlining each view's body as a CTE in the same call
         (see the persistence note in sql/usl/incident_context.sql: the SQL-editor
         REST endpoint is stateless across calls, so a plain CREATE VIEW does not
         survive to a second request). Writes real captured results to
         data/zetaris_usl_last_check.json. Never prints SQL error bodies or credentials.

Both flags require a reachable Zetaris (ZETARIS_API_KEY etc. in .env); this tool makes
no sense under SAMPLE_MODE and does not try to run offline -- use app.data.usl plus
tests/test_zetaris_usl.py for the offline-safe equivalent.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env
from app.data.zetaris import Zetaris

VIEWS = ('incident_context', 'asset_availability', 'shelter_capacity')

PROOFS = {
    'incident_context': [
        ("rodoviaria landmarks with their municipality's flood exposure",
         "SELECT * FROM ({body}) v WHERE LOWER(landmark_name) LIKE '%rodoviaria%' "
         "OR LOWER(landmark_name) LIKE '%rodoviária%' LIMIT 5"),
        ('flooded landmarks in Canoas on 2024-05-06',
         "SELECT * FROM ({body}) v WHERE municipality='Canoas' AND landmark_in_water_0506='1' LIMIT 5"),
        ('landmark count and flooded-segment total per municipality',
         "SELECT municipality, COUNT(*) AS landmarks, MAX(municipality_flooded_segments_0506) AS flooded_segments "
         "FROM ({body}) v GROUP BY municipality ORDER BY flooded_segments DESC LIMIT 6"),
    ],
    'asset_availability': [
        ('pumps down on 2024-05-06',
         "SELECT * FROM ({body}) v WHERE status_date='2024-05-06' AND is_down=1 LIMIT 8"),
        ('down-days per municipality',
         "SELECT municipality, SUM(is_down) AS down_days, COUNT(*) AS total_rows "
         "FROM ({body}) v GROUP BY municipality ORDER BY down_days DESC"),
    ],
    'shelter_capacity': [
        ('shelters currently over capacity, worst first',
         "SELECT * FROM ({body}) v WHERE over_capacity_flag=1 ORDER BY occupancy_rate DESC LIMIT 8"),
    ],
}


def load_view(name):
    text = (ROOT / 'sql/usl' / (name + '.sql')).read_text(encoding='utf-8')
    match = re.search(r'CREATE VIEW\s+\w+\s+AS\s*(.*);\s*\Z', text, re.S | re.I)
    if not match:
        raise ValueError('sql/usl/' + name + '.sql does not look like a single CREATE VIEW statement')
    return match.group(1).strip()


def load_statements(path):
    """Strip '--' line comments before splitting on ';' -- a semicolon inside a
    comment (e.g. a parenthetical aside) must never be mistaken for a statement end."""
    text = (ROOT / path).read_text(encoding='utf-8')
    without_comments = '\n'.join(re.sub(r'--.*$', '', line) for line in text.splitlines())
    return [s.strip() for s in without_comments.split(';') if s.strip()]


def build():
    results = {}
    for name in VIEWS:
        body = load_view(name)
        ddl = 'CREATE VIEW ' + name + ' AS ' + body
        try:
            Zetaris().query(ddl, allow_exists=True)
            results[name] = {'ddl_executes': True}
            print(name + ': DDL parses and executes against live Zetaris')
        except Exception as exc:
            results[name] = {'ddl_executes': False, 'error': type(exc).__name__}
            print(name + ': DDL FAILED (' + type(exc).__name__ + ')')
    return results


def check():
    client = Zetaris()
    report = {'views': {}, 'data_quality': []}
    ok = True
    for name in VIEWS:
        body = load_view(name)
        report['views'][name] = []
        for label, template in PROOFS[name]:
            sql = template.format(body=body)
            try:
                result = client.query(sql)
                row_count = len(result['data'])
                report['views'][name].append({'label': label, 'sql': sql, 'headers': result['headers'],
                                               'row_count': row_count, 'sample': result['data'][:5]})
                print(name + ' / ' + label + ': ' + str(row_count) + ' rows')
            except Exception as exc:
                ok = False
                report['views'][name].append({'label': label, 'sql': sql, 'error': type(exc).__name__})
                print(name + ' / ' + label + ': FAILED (' + type(exc).__name__ + ')')
    for sql in load_statements('sql/usl/dq_rules.sql'):
        # The rule bodies reference the view names directly; expand shelter_capacity inline
        # the same way the proving queries do, since it is the only view a rule depends on.
        expanded = re.sub(r'\(SELECT \* FROM shelter_capacity\)', '(' + load_view('shelter_capacity') + ')', sql)
        try:
            result = client.query(expanded)
            row = dict(zip(result['headers'], result['data'][0])) if result['data'] else {}
            report['data_quality'].append({'sql': sql, 'result': row})
            print('data quality rule: checked=' + str(row.get('checked')) + ' violations=' + str(row.get('violations')))
        except Exception as exc:
            ok = False
            report['data_quality'].append({'sql': sql, 'error': type(exc).__name__})
            print('data quality rule FAILED (' + type(exc).__name__ + ')')
    dest = ROOT / 'data/zetaris_usl_last_check.json'
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('wrote ' + str(dest))
    return ok


if __name__ == '__main__':
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--build', action='store_true')
    group.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        if args.build:
            build()
        else:
            sys.exit(0 if check() else 1)
    except Exception as exc:
        sys.exit('zetaris_usl failed (' + type(exc).__name__ + '). Check local services and .env; no credentials printed.')
