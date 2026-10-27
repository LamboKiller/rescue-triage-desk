import json
from pathlib import Path
p=Path(__file__).parent
s=json.loads((p/'scenes/offline_fresh.json').read_text(encoding='utf-8'))
s['name']='brief-snapshot'
for a in s['actions']:
    if a['do']=='navigate':a['url']='http://127.0.0.1:8096/v2/?lang=pt&t=2024-05-06T12:01'
    if a['do']=='run':
        a['args']=[x.replace('tools/demo_hero.py','tools/video/run_snapshot.py').replace('viddesk02','viddesk03') for x in a['args']]
(p/'scenes/brief_snapshot.json').write_text(json.dumps(s,indent=2,ensure_ascii=False),encoding='utf-8')
