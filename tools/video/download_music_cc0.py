import urllib.request
from pathlib import Path
A=Path(__file__).resolve().parents[2]/'tools/video/assets'
for url,name in [('https://opengameart.org/sites/default/files/ruskerdax_-_soul_release.mp3','soul-release.mp3'),('https://opengameart.org/content/soul-release','soul-release-license.html'),('https://creativecommons.org/publicdomain/zero/1.0/legalcode.txt','CC0-1.0.txt')]:
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RescueTriageDeskVideo/1.0'}),timeout=45) as r:(A/name).write_bytes(r.read())
    print(name,flush=True)
