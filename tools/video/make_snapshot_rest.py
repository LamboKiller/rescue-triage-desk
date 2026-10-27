import json
from pathlib import Path
p=Path(__file__).parent
s=json.loads((p/'scenes/brief_snapshot.json').read_text(encoding='utf-8'))
s['name']='brief-snapshot-rest';s['actions']=s['actions'][7:]
s['actions'][0]['expr']="(async()=>{await DeskApp.refresh();select(S.cases[0].case_id);return 'selected original case'})()"
(p/'scenes/brief_snapshot_rest.json').write_text(json.dumps(s,indent=2,ensure_ascii=False),encoding='utf-8')
