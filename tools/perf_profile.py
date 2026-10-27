"""PERF reproducible stdlib profiles; offline, disposable journals, no credentials."""
import argparse
import cProfile
import contextlib
import io
import json
from pathlib import Path
import pstats
import sys
import threading
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    from tests.support import Scratch
    from app.data.source import LocalSource
    from app.engines.world_model.registry import Registry
    from app.pipeline import Pipeline
    from app.web.server import create_server
    from tests.test_missions import make_case, inventory
    scratch = Scratch()
    results = {}

    def measure(name, fn):
        prof = cProfile.Profile()
        start = time.perf_counter()
        value = prof.runcall(fn)
        results[name] = {'seconds': time.perf_counter() - start}
        if isinstance(value, bytes): results[name]['bytes'] = len(value)
        stream = io.StringIO()
        pstats.Stats(prof, stream=stream).sort_stats('cumulative').print_stats(35)
        (args.out / (name + '.txt')).write_text(stream.getvalue(), encoding='utf-8')
        prof.dump_stats(str(args.out / (name + '.prof')))
        return value

    try:
        reg = Registry(Path(scratch.name) / 'events.jsonl')
        pipeline = Pipeline(reg, sample=True, source=LocalSource())
        def run(mid):
            with contextlib.redirect_stdout(io.StringIO()):
                return pipeline.run({'replay_time': '2024-05-06T14:00:00-03:00', 'messages': [
                    {'message_id': mid, 'text': 'Socorro, 3 pessoas no telhado na Rua da Praia, em Canoas.'}]})
        measure('pipeline_cold', lambda: run('perf-cold'))
        measure('pipeline_warm', lambda: run('perf-warm'))
        case = reg.ingest(make_case('perf-landing', text='Meu pai usa oxigênio.'))
        if hasattr(reg, 'queue_view'):
            from app.web.server import _summary
            legacy_drop = ('facts','fleet','hazard_facts','hazards','fleet_summary','incident_state')
            full_cases = reg.read()
            legacy = [dict({k:v for k,v in c.items() if k not in legacy_drop}, summary=True,
                           fleet=[{k:a.get(k) for k in ('asset','label_pt','verdict')} for a in c.get('fleet') or []],
                           version_count=len(c.get('facts') or [])) for c in full_cases]
            results['finalized_projection_bytes'] = {'before': len(json.dumps(legacy)),
                                                      'after': len(json.dumps([_summary(c) for c in full_cases]))}
        server = create_server('127.0.0.1', 0, sample=True, pipeline=pipeline, inventory=inventory())
        server.intake.close()
        server.intake.workers = 0
        # Profiles execute the actual handler in the profiled thread, including server CPU.
        server.timeout = 120
        def fetch(path):
            box = []
            def client():
                with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}' + path, timeout=180) as r:
                    box.append(r.read())
            t = threading.Thread(target=client)
            t.start()
            server.handle_request()
            t.join()
            return box[0]
        # ThreadingHTTPServer normally handles on a worker; inline it for cProfile.
        server.process_request = lambda request, address: server.process_request_thread(request, address)
        for i in range(600):
            mid = f'queued-{i}'
            server.intake._register({'message_id': mid, 'text': f'Pedido {i}: pessoas aguardando resgate.',
                                    'received_at': '2024-05-06T12:00:00-03:00'},
                                   '2024-05-06T14:00:00-03:00', time.time(), None, None, journal=False)
        measure('cases_600_cold', lambda: fetch('/api/cases'))
        measure('cases_600_warm', lambda: fetch('/api/cases'))
        measure('case_detail', lambda: fetch('/api/cases/' + case['case_id']))
        measure('landing_first', lambda: fetch('/api/cases/' + case['case_id'] + '/landing?date=2024-05-08'))
        warm = getattr(server, 'warmup', None)
        if warm:
            warm.thread.join(180)
            results['warmup'] = warm.snapshot()
        measure('landing_warm', lambda: fetch('/api/cases/' + case['case_id'] + '/landing?date=2024-05-08'))
        server.server_close()
    finally:
        scratch.cleanup()
        (args.out / 'metrics.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps(results, indent=2))


if __name__ == '__main__': main()
