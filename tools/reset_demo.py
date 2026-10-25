"""Back up the demo journal, then rebuild sample inputs offline with the current pipeline."""
import argparse
import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import ROOT
from app.engines.world_model.registry import Registry
from app.pipeline import Pipeline


def reset(target=None,inputs=None):
    target=Path(target or ROOT/'runtime/events.jsonl').resolve()
    if not target.is_relative_to(ROOT.resolve()): raise ValueError('Demo journal must stay inside this repository.')
    inputs=list(inputs or sorted((ROOT/'examples').glob('input_*.json')))
    if not inputs: raise ValueError('No sample inputs found.')
    target.parent.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=target.with_name(target.name+'.backup-'+stamp)
    # OS/process lock protects snapshot and replacement. Replay uses a separate journal.
    registry=Registry(target)
    with registry.locked():
        if target.exists(): shutil.copy2(target,backup)
        build=target.with_name(target.name+'.rebuild-'+stamp)
        built=Registry(build);pipeline=Pipeline(built,sample=True)
        try:
            for path in inputs:
                request=json.loads(Path(path).read_text(encoding='utf-8-sig'))
                if any(m.get('synthetic') is not True for m in request['messages']): raise ValueError('Demo reset only accepts explicitly synthetic samples.')
                with contextlib.redirect_stdout(io.StringIO()): result=pipeline.run(request)
                if result['partial'] or any(c.get('errors') for c in result['cases']): raise RuntimeError('Offline rebuild failed; original journal retained.')
            cases=built.read()
            build.replace(target)
        finally:
            if build.exists(): build.unlink()
            build.with_suffix('.lock').unlink(missing_ok=True)
    return {'cases':len(cases),'errors':sum(bool(c.get('errors')) for c in cases),'mode':'sample_offline','backup':str(backup) if backup.exists() else None,'journal':str(target)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--target',type=Path);p.add_argument('--input',type=Path,action='append');args=p.parse_args()
    print(json.dumps(reset(args.target,args.input),indent=2))
