"""Recompute example outputs through the actual pipeline, never saved answers."""
import argparse
import json
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env, setting, sample_mode
from app.engines.world_model.registry import Registry
from app.pipeline import Pipeline


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument('--sample', action='store_true')
    args = parser.parse_args()
    offline = args.sample or sample_mode() or not (setting('NIGHTSHIFT_API_KEY') and setting('ZETARIS_API_KEY'))
    for path in sorted((ROOT/'examples').glob('input_*.json')):
        pipeline = Pipeline(Registry(ROOT/'runtime'/('example_'+uuid.uuid4().hex+'.jsonl')), sample=offline)
        result = pipeline.run(json.loads(path.read_text(encoding='utf-8')))
        target = path.with_name(path.name.replace('input_', 'output_'))
        target.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        print(target.name+': '+result['mode'])


if __name__ == '__main__':
    main()
