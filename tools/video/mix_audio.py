"""Rebuild voice timeline from per-scene WAVs, duck one CC0 bed, normalize in two passes."""
import json,subprocess,wave,re
from pathlib import Path
R=Path(__file__).resolve().parents[2];O=R/'out/video/final';T=json.loads((O/'timeline.json').read_text(encoding='utf-8'))
rate=48000;data=bytearray(round(T['duration']*rate)*2)
for s in T['scenes']:
    with wave.open(str(O/s['wav'])) as w:
        assert w.getframerate()==rate and w.getnchannels()==1 and w.getsampwidth()==2
        pcm=w.readframes(w.getnframes())
    a=round(s['narrationStart']*rate)*2
    if a+len(pcm)>round(s['end']*rate)*2:raise ValueError('Voice does not fit scene '+str(s['scene']))
    data[a:a+len(pcm)]=pcm
with wave.open(str(O/'voice-timeline.wav'),'wb') as w:w.setparams((1,2,rate,0,'NONE','not compressed'));w.writeframes(data)
def run(args):
    p=subprocess.run(['ffmpeg','-hide_banner','-nostdin','-y',*args],capture_output=True,text=True,timeout=300)
    if p.returncode:raise RuntimeError(p.stderr[-3000:])
    return p
# −20 LUFS music bed, approximately 10 dB additional ducking during narration.
f='[0:a]loudnorm=I=-16:TP=-2:LRA=9,aresample=48000,asplit=2[voice][key];[1:a]atempo=0.98,loudnorm=I=-20:TP=-3:LRA=11,aresample=48000,apad,atrim=0:'+str(T['duration'])+",volume='if(lt(t,8),0.7+0.3*t/8,if(gt(t,222),1+0.4*(t-222)/15,1))':eval=frame,afade=t=out:st="+str(T['duration']-2)+':d=2[music];[music][key]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400:makeup=1:link=average:detector=rms[ducked];[voice][ducked]amix=inputs=2:normalize=0[mix]'
f=f.replace('detector=rms','detection=rms')
run(['-i',str(O/'voice-timeline.wav'),'-i',str(R/'tools/video/assets/soul-release.mp3'),'-filter_complex',f,'-map','[mix]','-ar','48000','-ac','2','-c:a','pcm_s24le',str(O/'mix-premaster.wav')])
first=run(['-i',str(O/'mix-premaster.wav'),'-af','loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json','-f','null','-'])
m=re.findall(r'\{\s*"input_i".*?\}',first.stderr,re.S)[-1];stats=json.loads(m);(O/'loudness-pass1.json').write_text(json.dumps(stats,indent=2))
af='loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}:measured_thresh={input_thresh}:offset={target_offset}:linear=true:print_format=json'.format(**stats)
last=run(['-i',str(O/'mix-premaster.wav'),'-af',af,'-ar','48000','-ac','2','-c:a','aac','-b:a','256k',str(O/'soundtrack.m4a')]);(O/'loudness-pass2.log').write_text(last.stderr)
check=run(['-i',str(O/'soundtrack.m4a'),'-af','loudnorm=I=-14:TP=-1:print_format=json','-f','null','-']);m=re.findall(r'\{\s*"input_i".*?\}',check.stderr,re.S)[-1];(O/'loudness-verified.json').write_text(m+'\n')
print(m)
