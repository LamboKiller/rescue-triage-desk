"""[SIMULADO] Explicitly started loopback-only demo; no automatic device binding.

Operator binds sim:<unit-id> in Recursos first. Uses the SAME OsmAnd ingest.
Virtual route motion is accelerated; timestamps remain wall time, never future.
"""
import argparse
import json
import math
import random
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.telemetry import metres


def position(segments,elapsed):
    for leg in segments:
        speed=(8 if leg['mode']=='water' else 25)/3.6
        for a,b in zip(leg['polyline'],leg['polyline'][1:]):
            duration=metres(a,b)/speed
            if elapsed<=duration:
                t=elapsed/duration if duration else 1
                return [a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t],speed,math.degrees(math.atan2((b[0]-a[0])*math.cos(a[1]*math.pi/180),b[1]-a[1]))%360
            elapsed-=duration
    return (segments[-1]['polyline'][-1],0,0) if segments else (None,0,0)


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--url',default='http://127.0.0.1:8080'); p.add_argument('--speed',default='4x')
    args=p.parse_args(); target=urlsplit(args.url)
    if target.scheme!='http' or target.hostname not in ('127.0.0.1','localhost','::1') or target.username or target.password: p.error('Demo loopback HTTP only.')
    try: multiplier=float(args.speed.rstrip('x'))
    except ValueError: p.error('Use --speed 4x')
    if not 0<multiplier<=100: p.error('Speed must be >0 and <=100x')
    started={}; base=args.url.rstrip('/')
    print('[SIMULADO] off by default; Ctrl+C stops. Bind sim:<unit-id> in Recursos. First unit loses signal for 11 wall minutes after virtual minute 5; second detours at virtual 3–5 min.',flush=True)
    while True:
        with urlopen(base+'/api/telemetry/missions',timeout=60) as r: payload=json.load(r)
        for i,m in enumerate(payload['missions']):
            uid=m['unit_id']; device='sim:'+uid
            if payload['bindings'].get(device)!=uid or not m['segments']: continue
            key=m['mission_id']+':'+uid; started.setdefault(key,time.monotonic()); elapsed=(time.monotonic()-started[key])*multiplier
            if i==0 and 300<elapsed<300+660*multiplier: continue
            point,speed,bearing=position(m['segments'],elapsed)
            if point is None: continue
            lon,lat=point
            if (i==1 or len(payload['missions'])==1) and 180<elapsed<300: lat+=0.004
            lat+=random.uniform(-0.00004,0.00004); lon+=random.uniform(-0.00004,0.00004)
            query=urlencode(dict(id=device,lat=lat,lon=lon,timestamp=time.time(),speed=speed/0.514444,bearing=bearing,accuracy=10,source='simulated'))
            with urlopen(base+'/api/telemetry/osmand?'+query,timeout=15) as r: result=json.load(r)
            print('[SIMULADO]',uid,result['status'],round(elapsed),flush=True)
        time.sleep(2)


if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: print('[SIMULADO] stopped')
