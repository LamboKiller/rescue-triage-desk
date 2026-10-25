"""Operator-run live diagnostic; importing this module never contacts a service."""
import contextlib
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, load_env
from app.agents import hazard_critic
from app.llm.nightshift import Nightshift


def diagnose(client):
    passed = 0
    reasons = []
    for index, verdict in enumerate(('unsafe', 'caution', 'safe'), 1):
        case = {'proposed_asset':'synthetic_car', 'fields':{},
                'hazard_facts':[{'id':'fleet:synthetic_car',
                                 'text_pt':'Carro sintetico: '+verdict+'. Profundidade 0.5 m.'}]}
        client.start_message('diagnose-hazard-'+str(index))
        start = time.monotonic()
        meta = {}
        reason = 'ok'
        try:
            # Normal trace metadata stays in the file; console output is restricted.
            with contextlib.redirect_stdout(io.StringIO()):
                _, unsupported, meta = hazard_critic.run(client, '', case, start+45)
            if unsupported:
                reason = 'unsupported_citation_or_number'
        except Exception as exc:
            reason = type(exc).__name__
        seconds = round(time.monotonic()-start, 3)
        events = client.message_calls()
        meta = meta or (events[-1] if events else {})
        if reason == 'ok' and seconds <= 30:
            passed += 1
        else:
            reasons.append('call '+str(index)+': '+('over_30s' if seconds > 30 else reason))
        print(json.dumps({'status':meta.get('status','failed'), 'winner_model':meta.get('model'),
                          'seconds':seconds, 'output_chars':meta.get('output_chars',0),
                          'parse':'ok' if reason == 'ok' else 'fail:'+reason}))
    print('PASSED (3/3 ok, each <=30 s)' if passed == 3 else 'NOT YET '+ '; '.join(reasons))
    return 0 if passed == 3 else 1


def main():
    load_env()
    return diagnose(Nightshift(ROOT/'runtime/diagnose_hazard_trace.jsonl'))


if __name__ == '__main__':
    sys.exit(main())
