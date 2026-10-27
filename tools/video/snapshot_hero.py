import json
from pathlib import Path
R=Path(__file__).resolve().parents[2]
rows=[json.loads(x) for x in (R/'data/demo/hero.jsonl').read_text(encoding='utf-8').splitlines()]
for s in rows:
    if s.get('step')==1:
        s['message']['text']='socorro!! segundo andar, minha mãe acamada e meu filho de 8 anos, a água não para de subir, estamos perto da rodoviária'
        s['expect']['decision_in']=['CALLBACK','SEND_CANDIDATE']
        s['title']='Original brief: 3 people, bedridden mother, near the bus station'
(R/'tools/video/assets/hero-brief-snapshot.jsonl').write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in rows)+'\n',encoding='utf-8')
print('Snapshot saved; shared fixture unchanged')
