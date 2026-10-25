"""Demo entrypoint.

python -m app.replay                  offline desk (deterministic sample pipeline) with a CLEAN registry, open /v2
python -m app.replay --live           same, but Nightshift agents answer (the human runs this; needs the local Nightshift)
python -m app.replay --headless       run the whole scenario without a browser at maximum speed and print the event log
"""
import argparse
import json
import threading
from app.config import ROOT, load_env, setting
from app.replay import scenario as scenarios


def summarize(events):
    for e in events:
        extra = {k: v for k, v in e.items() if k in ('message_id', 'decision', 'after', 'asset', 'alert_kind', 'outcome', 'status', 'remaining_n', 'reason', 'message', 'text')
                 and v not in (None, '')}
        who = ' [scenario_input]' if e['scenario_input'] else ''
        if e['kind'] == 'agent_stage':
            continue
        print(f"{e['replay_time'][11:16]} {e['lane']:<10} {e['kind']}{who} "+json.dumps(extra, ensure_ascii=False)[:230])


def main():
    load_env()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--live', action='store_true', help='use the Nightshift agents instead of the offline pipeline')
    p.add_argument('--port', type=int, default=int(setting('PORT', '8090')))
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--speed', type=int, default=10, choices=(1, 10, 60))
    p.add_argument('--keep', action='store_true', help='keep runtime/replay_events.jsonl instead of starting clean')
    p.add_argument('--headless', action='store_true')
    p.add_argument('--scenario', default=str(scenarios.DEFAULT))
    args = p.parse_args()
    registry_path = ROOT/'runtime'/('replay_events_live.jsonl' if args.live else 'replay_events.jsonl')
    registry_path.parent.mkdir(exist_ok=True)
    if registry_path.exists() and not args.keep:
        registry_path.unlink()
    from app.web.server import create_server
    server = create_server(args.host, 0 if args.headless else args.port, sample=not args.live, registry_path=registry_path)
    server.replay.path = args.scenario
    if args.headless:
        server.replay.sleep = lambda s: None
        server.replay.start(args.speed)
        server.replay.runner.speed = 10**9
        server.replay.runner.thread.join()
        state = server.replay.state()
        summarize(state['events'])
        print('status', state['status'], 'events', state['event_count'])
        return
    print(f"Replay desk ({'LIVE Nightshift' if args.live else 'offline sample'}): http://{args.host}:{server.server_port}/v2  -> open 'Linha do tempo' and press Iniciar", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
