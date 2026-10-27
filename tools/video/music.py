import urllib.request,re,json
from pathlib import Path
A=Path(__file__).resolve().parents[2]/'tools/video/assets'
headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36'}
url='https://pixabay.com/music/ambient-cinematic-documentary-piano-162733/'
with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=30) as r:html=r.read().decode()
(A/'pixabay-track.html').write_text(html,encoding='utf-8')
urls=list(dict.fromkeys(re.findall(r'https[^\s"<>]+?\.mp3(?:\?[^\s"<>]*)?',html.replace('\\u002F','/').replace('\\/','/'))))
print(urls[:8],flush=True)
if not urls:raise RuntimeError('No downloadable track URL')
with urllib.request.urlopen(urllib.request.Request(urls[0].replace('&amp;','&'),headers=headers),timeout=40) as r:(A/'cinematic-documentary-piano.mp3').write_bytes(r.read())
with urllib.request.urlopen(urllib.request.Request('https://pixabay.com/service/license-summary/',headers=headers),timeout=30) as r:(A/'pixabay-license.html').write_bytes(r.read())
print('music downloaded',flush=True)
