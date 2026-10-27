from PIL import Image
import random
from pathlib import Path
r=random.Random(2024);im=Image.new('L',(128,128));im.putdata([r.randrange(256) for _ in range(128*128)])
p=Path(__file__).parent/'assets/grain.png';im.save(p)
h=Path(__file__).parent/'compositor/index.html';s=h.read_text(encoding='utf-8');s=s.replace('</style>','#texture{background-image:url(../assets/grain.png);background-size:128px 128px}</style>');h.write_text(s,encoding='utf-8')
