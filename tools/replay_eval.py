"""Offline replay: feed the model outputs saved by the last LIVE eval through the CURRENT code (no model calls).
Usage: python tools/replay_eval.py   -> per-method decision accuracy on the challenge set, old (as run) vs replayed."""
import glob, io, json, os, contextlib, sys, uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pipeline import Pipeline
from app.engines.world_model.registry import Registry
from app.data.source import LocalSource


class Replay:
    def __init__(self, stages):
        self.stages = stages

    def call(self, role, system, payload, deadline):
        out = self.stages.get(role)
        if role in ('intake', 'revision') and isinstance(out, dict) and 'model_quotes' in out:
            out = out['model_quotes']  # the saved stage keeps the raw model reply here
        if not isinstance(out, dict):
            raise RuntimeError('no saved '+role+' output')
        return out, {'role': role, 'model': 'replay', 'receipt': None, 'status': 'ok', 'seconds': 0}


def main():
    truth = {t['message_id']: t for t in json.loads((ROOT/'eval/challenge_truth.json').read_text(encoding='utf-8'))}
    texts = {json.loads(l)['message_id']: json.loads(l) for l in (ROOT/'eval/challenge_set.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()}
    saved = {}
    for f in sorted(glob.glob(str(ROOT/'runtime/eval_*.jsonl')), key=os.path.getmtime)[-40:]:
        for line in open(f, encoding='utf-8'):
            c = json.loads(line).get('case') or {}
            if c.get('message_id', '').startswith('challenge') and c.get('mode') in ('intake', 'full'):
                saved[(c['mode'], c['message_id'])] = c
    source = LocalSource()
    for mode in ('intake', 'full'):
        old = new = n = 0
        changed = []
        for (m, mid), c in sorted(saved.items()):
            if m != mode:
                continue
            stages = {'intake': c['agents'].get('intake'), 'critic': c['agents'].get('critic'),
                      'revision': c['agents'].get('revision'), 'location': c['agents'].get('location')}
            p = Pipeline(Registry(ROOT/'runtime'/('replay_'+uuid.uuid4().hex+'.jsonl')), source=source, client=Replay(stages))
            with contextlib.redirect_stdout(io.StringIO()):
                out = p.run({'replay_time': '2024-05-06T14:00:00-03:00', 'messages': [texts[mid]]}, ablation=mode)
            r = out['cases'][0]
            exp = truth[mid]['expected_decision']
            n += 1
            old += c['result']['decision'] == exp
            new += r['result']['decision'] == exp
            if r['result']['decision'] != exp:
                changed.append(mid+' exp '+exp+' got '+r['result']['decision']+' Q='+'; '.join(q[:40] for q in r['result']['questions']))
        print(mode+': live '+str(old)+'/'+str(n)+' -> replayed with current code '+str(new)+'/'+str(n))
        for line in changed:
            print('   still wrong: '+line)


if __name__ == '__main__':
    main()
