import json,os
from pathlib import Path
p=Path(__file__).parent
s=json.loads((p/'scenes/brief_snapshot.json').read_text(encoding='utf-8'));s['name']='live-verified'
for a in s['actions']:
    if a['do']=='navigate':a['url']=a['url'].replace('8096','8097')
    if a['do']=='run':
        a['args']=[x.replace('tools/video/run_snapshot.py','tools/video/run_live_take.py').replace('--offline','--live').replace('8096','8097').replace('viddesk03','vidlive02') for x in a['args']]
        a['followRun']=os.environ.get('RTD_VIDEO_FEED','out/video/vid_current_run.json')
    if a['do']=='eval' and a['expr'].startswith('select('):a['expr']="(async()=>{await DeskApp.refresh();select(S.cases[0].case_id);return 'selected real case'})()"
# Refresh on the actual recorded state after every step, so a 60-second UI polling interval cannot hide the action.
actions=[]
for a in s['actions']:
    actions.append(a)
    if a['do']=='run':actions.append({'do':'eval','expr':"(async()=>{await DeskApp.refresh();return 'refreshed recorded state'})()"})
s['actions']=actions
(p/'scenes/live_verified.json').write_text(json.dumps(s,indent=2,ensure_ascii=False),encoding='utf-8')
