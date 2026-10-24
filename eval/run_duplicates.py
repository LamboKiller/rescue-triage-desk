"""Original synthetic pairs; truth is read only by the evaluator."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env
from app.duplicates import candidate
from app.agents.duplicate_reviewer import run
from app.llm.nightshift import Nightshift


def evaluate(offline=False):
    pairs=[json.loads(l) for l in (ROOT/'eval/duplicate_set.jsonl').read_text(encoding='utf-8').splitlines()]
    truth=json.loads((ROOT/'eval/duplicate_truth.json').read_text(encoding='utf-8'))
    found=same=correct=reviewed=wrong=crashes=0
    rows=[]
    client=None if offline else Nightshift(ROOT/'logs/duplicates_eval.jsonl')
    for p in pairs:
        expected=truth[p['pair_id']]['same'];same+=expected
        try:
            match=candidate(p['a'],p['b']);found+=bool(match) and expected
            row={'pair_id':p['pair_id'],'candidate':match,'review':'unavailable (offline)' if offline else None}
            if not offline:
                client.start_message(p['pair_id'])
                review,meta=run(client,p['a'],p['b'],time.monotonic()+90)
                row['review']=review;row['call']=meta;reviewed+=1
                correct+=review['verdict']==('same' if expected else 'different')
                wrong+=review['verdict']=='same' and not expected
            rows.append(row)
        except Exception as exc:
            crashes+=1;rows.append({'pair_id':p['pair_id'],'error':type(exc).__name__})
    return {'mode':'offline' if offline else 'live','pairs':len(pairs),'candidate_recall':found/same,
            'reviewer_accuracy':correct/reviewed if reviewed else None,'reviewed':reviewed,
            'wrong_merge_suggestions':wrong if reviewed else None,'automatic_merges':0,'crashes':crashes,'results':rows}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    if not args.offline:load_env()
    result=evaluate(args.offline)
    (ROOT/'eval/duplicate_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='results'},ensure_ascii=False))
