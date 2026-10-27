import urllib.request,zipfile,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
A=ROOT/'tools/video/assets';F=ROOT/'tools/video/fonts'
A.mkdir(parents=True,exist_ok=True);F.mkdir(parents=True,exist_ok=True)
def get(url,p):
    if p.exists() and p.stat().st_size>1000:return
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req,timeout=40) as r:p.write_bytes(r.read())
    print(p.name,p.stat().st_size,flush=True)
get('https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip',F/'Inter-4.1.zip')
with zipfile.ZipFile(F/'Inter-4.1.zip') as z:
    for n in z.namelist():
        if n.endswith(('InterVariable.ttf','InterVariable.woff2','InterDisplay-Bold.ttf','Inter-SemiBold.ttf','OFL.txt','LICENSE.txt')):
            (F/Path(n).name).write_bytes(z.read(n))
try:
    get('https://freepd.com/',A/'freepd-license-page.html')
    get('https://freepd.com/music/Emotional%20Piano.mp3',A/'emotional-piano.mp3')
except Exception as e: print(type(e).__name__,str(e),flush=True)
