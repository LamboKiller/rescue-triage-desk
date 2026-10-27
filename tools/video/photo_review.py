from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
R=Path(__file__).resolve().parents[2]
pics=list((R/'tools/video/assets/photos').glob('*.jpg'))
im=Image.new('RGB',(1200,math.ceil(len(pics)/3)*260),'#071017') if False else Image.new('RGB',(1200,520),'#071017')
d=ImageDraw.Draw(im)
for i,p in enumerate(pics):
    a=Image.open(p);a.thumbnail((390,220));x=(i%3)*400;y=(i//3)*260;im.paste(a,(x,y));d.text((x+8,y+228),p.stem,fill='white')
im.save(R/'out/video/final/photos-review.jpg')
