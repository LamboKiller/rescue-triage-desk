import subprocess,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
for name in sys.argv[1:] or ['live1','offline-rest']:
    src=ROOT/f'out/video/raw/{name}.mp4';dest=ROOT/f'out/video/frames/{name}';dest.mkdir(parents=True,exist_ok=True)
    if (dest/'complete.json').exists():continue
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-threads','2','-i',str(src),'-vf','fps=30','-q:v','2','-threads','2',str(dest/'%06d.jpg')],check=True,timeout=600)
    (dest/'complete.json').write_text(json.dumps({'source':str(src),'frames':len(list(dest.glob('*.jpg'))),'fps':30}))
    print(name,'ready',flush=True)
