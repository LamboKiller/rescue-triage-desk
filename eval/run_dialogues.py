"""Ten original synthetic callback dialogues; truth never enters the pipeline."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env
from app.pipeline import Pipeline
from app.engines.world_model.registry import Registry
from tools.scratch import scratch


def evaluate(offline=False):
    dialogues=[json.loads(l) for l in (ROOT/'eval/dialogue_set.jsonl').read_text(encoding='utf-8').splitlines()]
    truth={t['dialogue_id']:t for t in json.loads((ROOT/'eval/dialogue_truth.json').read_text(encoding='utf-8'))}
    decisions=contradictions=versions=crashes=flagged=0
    fields={}; failures=[]
    with scratch() as folder:
        pipeline=Pipeline(Registry(Path(folder)/'events.jsonl'),sample=offline)
        for d in dialogues:
            key=d['dialogue_id']; expected=truth[key]
            # Dialogues are independent incidents: a fresh registry keeps one dialogue's
            # rescued/duplicate state from leaking into the next one at the same address.
            pipeline=Pipeline(Registry(Path(folder)/(key+'.jsonl')),sample=offline)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    first=pipeline.run({'replay_time':d['messages'][0]['received_at'],'messages':[dict(d['messages'][0],message_id=key)]})['cases'][0]
                    final=pipeline.reply(first['case_id'],d['messages'][1])
                decisions+=final['result']['decision']==expected['decision']
                flagged+=bool(final.get('contradictions'))
                contradictions+=bool(final.get('contradictions'))==expected['contradiction']
                versions+=len(final['facts'])==expected['version_count'] and final['version']==expected['version_count']
                bad={}
                for field,value in expected['fields'].items():
                    actual=final['fields'].get(field,{}).get('value'); entry=fields.setdefault(field,{'correct':0,'total':0})
                    entry['total']+=1;entry['correct']+=actual==value
                    if actual!=value:bad[field]={'actual':actual,'expected':value}
                if final['result']['decision']!=expected['decision'] or bad:
                    failures.append({'dialogue_id':key,'decision':final['result']['decision'],'fields':bad})
            except Exception as exc:
                crashes+=1;failures.append({'dialogue_id':key,'error':type(exc).__name__})
    for entry in fields.values():entry['accuracy']=entry['correct']/entry['total']
    return {'mode':'offline' if offline else 'live','dialogues':len(dialogues),'final_decision_accuracy':decisions/len(dialogues),
            'merge_accuracy_per_field':fields,'contradictions_flagged_accuracy':contradictions/len(dialogues),
            'contradictions_flagged':flagged,'expected_contradictions':sum(t['contradiction'] for t in truth.values()),
            'correct_version_counts':versions,'version_count_accuracy':versions/len(dialogues),'crashes':crashes,'failures':failures}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    if not getattr(args,'offline',False): load_env()
    result=evaluate(args.offline);print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(bool(result['crashes'] or result['failures'] or result['contradictions_flagged_accuracy']!=1 or result['version_count_accuracy']!=1))
