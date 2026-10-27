"""Measure decoded duplicates in explicitly marked motion windows; retain capture counters."""
import json,re,subprocess,sys
from pathlib import Path
import numpy as np
R=Path(__file__).resolve().parents[2];rows=[]
for name in sys.argv[1:] or ['live1','offline-rest','surge','map']:
    p=R/f'out/video/raw/{name}.mp4';marks=json.loads(p.with_suffix('.marks.json').read_text(encoding='utf-8'))
    fps=marks['fps'];windows=[]
    if name=='map':windows=[(11,23)]
    elif name=='surge':windows=[(8,17)]
    else:
        windows=[(m['t'],m['t']+.9) for m in marks['marks'] if m.get('box')]
    stats=[]
    for a,b in windows:
        cmd=['ffmpeg','-hide_banner','-loglevel','error','-threads','1','-ss',str(a),'-t',str(b-a),'-i',str(p),'-vf','scale=480:270','-threads','1','-f','rawvideo','-pix_fmt','gray','pipe:1']
        data=subprocess.check_output(cmd,timeout=90);n=len(data)//(480*270)
        if n<2:continue
        x=np.frombuffer(data[:n*480*270],dtype=np.uint8).reshape(n,270,480).astype(np.int16)
        diff=np.mean(np.abs(np.diff(x,axis=0)),axis=(1,2));dups=int(np.sum(diff<.06))
        stats.append({'start':round(a,3),'end':round(b,3),'frames':n,'nearDuplicates':dups,'duplicatePct':round(dups/(n-1)*100,2),'meanAbsDifference':round(float(diff.mean()),5),'threshold':.06})
    log=p.with_suffix('.ffmpeg.log').read_text(encoding='utf-8',errors='replace');final=re.findall(r'frame=\s*(\d+).*?dup=(\d+) drop=(\d+)',log)
    total=sum(s['frames']-1 for s in stats);dup=sum(s['nearDuplicates'] for s in stats)
    rows.append({'clip':name,'captureFps':fps,'motionWindows':stats,'motionDuplicatePct':round(100*dup/total,2) if total else None,'ffmpegFinal':{'frames':int(final[-1][0]),'dup':int(final[-1][1]),'drop':int(final[-1][2])} if final else None,'targetMet':bool(total and dup/total<.02)})
    print(name,rows[-1]['motionDuplicatePct'],flush=True)
out=R/'out/video/final/smoothness.json';out.write_text(json.dumps(rows,indent=2),encoding='utf-8')
