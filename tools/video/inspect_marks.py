from pathlib import Path
import json,sys
for name in sys.argv[1:]:
    j=json.loads(Path(f'out/video/raw/{name}.marks.json').read_text())
    print(name)
    for m in j['marks']:
        if m['name'] in ['run','run_end','end'] or m.get('box'):print(round(m['t'],2),m['name'],m.get('code',''),m.get('box',{}).get('text',''))
