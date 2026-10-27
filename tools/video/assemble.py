"""Assemble the submission video from scene clips + generated cards (ffmpeg only, no new deps).

  python tools/video/assemble.py --spec tools/video/assemble_example.json --out out/video/final.mp4 [--work out/video/_work]

Spec (JSON): {"fps":30, "size":[1920,1080], "segments":[ ... ]}
Segment types
  {"type":"clip", "file":"out/video/scene4.mp4", "srt":"captions/scene4.srt",            # burned-in captions (optional)
   "badge":"4× · real time 47 s", "trim":[0,35], "speed":1.0}                             # badge top-right (optional); speed>1 = timelapse
  {"type":"card", "title":"May 2024 · Rio Grande do Sul", "lines":["185 deaths","478/497 municipalities","2.4 M affected"],
   "footnote":"Sources: ...", "duration":8, "bg":"#0d1b24"}                               # stats fade in one by one, footnote bottom
  {"type":"list", "title":"Also built", "items":["shift handover", ...], "duration":12}   # animated: items appear one after another
Every segment is normalised to the same size/fps/pixel format + silent stereo track so the final concat is lossless (-c copy).
Narration/music are not mixed here: Orbit adds them in a last pass (see out of this script: <out> has a silent track).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

FONT = 'C\\:/Windows/Fonts/arial.ttf'
FONT_B = 'C\\:/Windows/Fonts/arialbd.ttf'


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        sys.exit('ffmpeg falhou:\n'+' '.join(cmd)+'\n'+r.stderr[-1500:])


def textfile(work, name, text):
    p = work/name
    p.write_text(text, encoding='utf-8')
    return name


def common(fps, w, h):
    return ['-r', str(fps), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-shortest']


def fade_draw(work, key, text, y, size, start, color='white', font=FONT, x='(w-text_w)/2', fade=0.6):
    f = textfile(work, f'{key}.txt', text)
    alpha = f"if(lt(t,{start}),0,if(lt(t,{start+fade}),(t-{start})/{fade},1))"
    return f"drawtext=fontfile='{font}':textfile={f}:fontsize={size}:fontcolor={color}:x={x}:y={y}:alpha='{alpha}'"


def clip(seg, i, work, fps, w, h, root):
    out = f'seg{i:02d}.mp4'
    src = Path(seg['file']).resolve()
    vf = []
    if seg.get('speed', 1) != 1:
        vf.append(f"setpts=PTS/{seg['speed']}")
    vf.append(f'scale={w}:{h}:flags=lanczos,fps={fps}')
    if seg.get('srt'):
        srt = Path(seg['srt']).resolve()
        (work/f'cap{i:02d}.srt').write_text(srt.read_text(encoding='utf-8'), encoding='utf-8')
        vf.append(f"subtitles=cap{i:02d}.srt:force_style='FontName=Arial,FontSize=26,Outline=2,Shadow=1,MarginV=46,PrimaryColour=&HFFFFFF&'")
    if seg.get('badge'):
        f = textfile(work, f'badge{i:02d}.txt', seg['badge'])
        vf.append(f"drawtext=fontfile='{FONT_B}':textfile={f}:fontsize=30:fontcolor=white:box=1:boxcolor=0xb3261eE0:boxborderw=12:x=w-text_w-40:y=36")
    cmd = ['ffmpeg', '-y', '-v', 'error']
    if seg.get('trim'):
        cmd += ['-ss', str(seg['trim'][0]), '-to', str(seg['trim'][1])]
    cmd += ['-i', str(src), '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-vf', ','.join(vf)] + common(fps, w, h) + [out]
    run(cmd, work)
    return out


def card(seg, i, work, fps, w, h, root):
    out = f'seg{i:02d}.mp4'
    d = float(seg.get('duration', 8))
    bg = seg.get('bg', '#0d1b24').replace('#', '0x')
    vf = [fade_draw(work, f'c{i}t', seg['title'], 150, 72, 0.3, '0xf4d67d', FONT_B)]
    y = 340
    for k, line in enumerate(seg.get('lines', [])):
        vf.append(fade_draw(work, f'c{i}l{k}', line, y, 54, 1.4+k*1.1))
        y += 95
    if seg.get('footnote'):
        vf.append(fade_draw(work, f'c{i}f', seg['footnote'], h-70, 22, 2.0, '0xa9b9c5'))
    cmd = ['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'color=c={bg}:s={w}x{h}:r={fps}:d={d}', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
           '-t', str(d), '-vf', ','.join(vf)] + common(fps, w, h) + [out]
    run(cmd, work)
    return out


def listcard(seg, i, work, fps, w, h, root):
    seg = {**seg, 'lines': []}
    out = f'seg{i:02d}.mp4'
    d = float(seg.get('duration', 12))
    items = json.loads(json.dumps(seg.get('items', [])))
    bg = seg.get('bg', '#0d1b24').replace('#', '0x')
    vf = [fade_draw(work, f'l{i}t', seg.get('title', 'Also built'), 90, 66, 0.2, '0xf4d67d', FONT_B)]
    step = max(0.5, (d-2.5)/max(1, len(items)))
    for k, item in enumerate(items):
        col, row = divmod(k, 5)
        vf.append(fade_draw(work, f'l{i}i{k}', '• '+item, 240+row*150, 44, 1.0+k*step, x=f'{110+col*930}', fade=0.5))
    cmd = ['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'color=c={bg}:s={w}x{h}:r={fps}:d={d}', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
           '-t', str(d), '-vf', ','.join(vf)] + common(fps, w, h) + [out]
    run(cmd, work)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--spec', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--work', default='out/video/_work')
    a = p.parse_args()
    spec = json.loads(Path(a.spec).read_text(encoding='utf-8'))
    fps = spec.get('fps', 30)
    w, h = spec.get('size', [1920, 1080])
    work = Path(a.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    root = Path.cwd()
    parts = []
    for i, seg in enumerate(spec['segments']):
        kind = seg['type']
        parts.append({'clip': clip, 'card': card, 'list': listcard}[kind](seg, i, work, fps, w, h, root))
        print(f'  {i:02d} {kind} ok')
    (work/'concat.txt').write_text('\n'.join(f"file '{x}'" for x in parts), encoding='utf-8')
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', 'concat.txt', '-c', 'copy', str(out)], work)
    print('ok', out)


if __name__ == '__main__':
    main()
