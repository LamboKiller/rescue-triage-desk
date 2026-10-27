"""Run the scripted 8-message demo (data/demo/scenario.jsonl) against a desk, step by step.

  python tools/demo_run.py --offline              # embedded sample desk on :8098 (fake client, deterministic); prints PASS/FAIL at the end
  python tools/demo_run.py --offline --speed 4    # same, with pauses between steps (4 = four times faster than real pacing)
  python tools/demo_run.py --live --url http://127.0.0.1:8080 --speed 1
                                                  # Orbit only: posts to a desk that YOU started against Nightshift; this tool never calls a model

Every operator/crew action goes through the same HTTP routes the screens use; the scenario holds inputs and expectations only.
Reset first for a live run:  python tools/reset_demo.py --demo   (moves runtime state to runtime/demo_backup, deletes nothing).
"""
import argparse
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_lib as lib  # noqa: E402


def serve_embedded(workdir, port=8098):
    """Offline sample desk whose every store lives under `workdir` (never the shared runtime/ files)."""
    import app.web.server as web
    runtime = Path(workdir)/'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    web.ROOT = _Root(Path(workdir))
    server = web.create_server('127.0.0.1', port, sample=True, registry_path=runtime/'events.jsonl')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class _Root:
    """Path-like stand-in so create_server's ROOT/'runtime/...' stores land inside the demo workdir."""
    def __init__(self, base):
        self.base = base

    def __truediv__(self, other):
        return self.base/other


def run_offline(workdir, port=8098, speed=0, only=None, say=lambda *a: None):
    """Used by the CLI and the tests: start the embedded desk, run all steps, return (state, check rows). Always closes the server."""
    import app.web.server as web
    original = web.ROOT
    server = serve_embedded(workdir, port)
    try:
        scenario = lib.load()
        desk = lib.Desk(f'http://127.0.0.1:{server.server_port}')
        runner = lib.Runner(desk, scenario, sleep=(lambda s: None) if not speed else time.sleep, say=say)
        state = runner.run(only=only, speed=speed)
        rows = lib.Check(desk, scenario, state).all()
        return state, rows
    finally:
        server.shutdown()
        server.server_close()
        web.ROOT = original


def report(rows, out=print):
    passed = 0
    for n, title, ok, fails, notes in rows:
        passed += ok
        out(f"  {'PASS' if ok else 'FAIL'}  passo {n}: {title}")
        for x in fails:
            out('        - '+x)
    out(f'{passed}/{len(rows)} PASS')
    return passed == len(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--offline', action='store_true', help='fake client (default): embedded sample desk, or --url to a sample desk')
    mode.add_argument('--live', action='store_true', help='desk started by you against Nightshift (requires --url); Orbit runs this')
    p.add_argument('--url', help='desk base URL; omit with --offline to start the embedded one')
    p.add_argument('--port', type=int, default=8098)
    p.add_argument('--speed', type=float, default=0, help='pause scaling between steps; 0 = no pauses (default), 1 = real pacing, 4 = 4x faster')
    p.add_argument('--only', type=int, nargs='*', help='run only these step numbers (earlier steps must already have run)')
    p.add_argument('--keep', action='store_true', help='embedded desk: keep serving after the run (Ctrl+C to stop) so you can open /v2')
    args = p.parse_args()
    if args.live and not args.url:
        p.error('--live needs --url of the desk you started (python -m app.web.server --port 8080)')
    scenario = lib.load()
    print(f"Cenário: {scenario['meta']['name']} · {len(scenario['steps'])} passos")
    if args.url:
        desk = lib.Desk(args.url)
        mode_now = desk.health().get('mode')
        want = 'live' if args.live else 'sample_offline'
        if mode_now != want:
            p.error(f'o desk em {args.url} está em modo {mode_now!r}; esperado {want!r}')
        prior = lib.load_state() if args.only else None
        runner = lib.Runner(desk, scenario, sleep=time.sleep)
        if prior:
            runner.state = prior
        state = runner.run(only=set(args.only) if args.only else None, speed=args.speed or 0)
        rows = lib.Check(desk, scenario, state).all()
        ok = report(rows)
        sys.exit(0 if ok else 1)
    workdir = lib.ROOT/'runtime'/'demo'
    if workdir.exists():
        import shutil
        shutil.rmtree(workdir)  # only the embedded demo's own directory
    import app.web.server as web
    original = web.ROOT
    server = serve_embedded(workdir, args.port)
    try:
        desk = lib.Desk(f'http://127.0.0.1:{server.server_port}')
        runner = lib.Runner(desk, scenario, sleep=time.sleep if args.speed else (lambda s: None))
        state = runner.run(speed=args.speed)
        rows = lib.Check(desk, scenario, state).all()
        ok = report(rows)
        if args.keep:
            print(f'Desk offline em http://127.0.0.1:{server.server_port}/v2 — Ctrl+C para encerrar')
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        sys.exit(0 if ok else 1)
    finally:
        server.shutdown()
        server.server_close()
        web.ROOT = original


if __name__ == '__main__':
    main()
