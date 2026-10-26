"""Offline coverage scenarios; no providers or external data."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.coverage import build


def evaluate():
    rows=[json.loads(s) for s in (Path(__file__).with_name('coverage_set.jsonl')).read_text(encoding='utf-8').splitlines()]
    correct=uncited=0;results=[]
    for row in rows:
        out=build([row['case']],row['units'],'2024-05-08',row['threshold_minutes'],
            lambda a,b:dict(distance_m=100,eta_seconds=row['eta_seconds'],basis_pt='[SIMULADO] estimativa de viagem'))
        gap=any(c['gap'] for c in out['cells'])
        uncited+=sum(not s['case_ids'] or not s['fact_ids'] or not set(s['case_ids'])<={row['case']['case_id']} for s in out['suggestions'])
        passed=gap==row['truth']['gap'];correct+=passed
        results.append(dict(name=row['name'],passed=passed))
    return dict(correct=correct,total=len(rows),suggestions_without_cited_cases=uncited,results=results)

if __name__=='__main__':
    result=evaluate();print(json.dumps(result,ensure_ascii=False,indent=2))
    sys.exit(0 if result['correct']==result['total'] and not result['suggestions_without_cited_cases'] else 1)
