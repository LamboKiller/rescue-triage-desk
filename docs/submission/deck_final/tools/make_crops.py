# Extract English-UI frames from the live clips and crop them to the one region that matters.
# Run with python3 (needs Pillow; ffmpeg on PATH). Frames come from out/video/v5raw (2560x1440 captures).
import subprocess, os, json
from pathlib import Path
from PIL import Image, ImageEnhance

ROOT = Path(__file__).resolve().parents[4]
RAW = ROOT / 'out/video/v5raw'
D = Path(__file__).resolve().parents[1]
OUT = D / 'assets/shots'
TMP = Path(os.environ.get('TMPDIR', str(D / 'tmp'))) / 'deck6_frames'
OUT.mkdir(parents=True, exist_ok=True); TMP.mkdir(parents=True, exist_ok=True)

def frame(clip, t):
    p = TMP / f'{clip}_{t:.2f}.png'
    if not p.exists():
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(t), '-i', str(RAW / f'{clip}.mp4'),
                        '-frames:v', '1', str(p)], check=True)
    return Image.open(p).convert('RGB')

# name: (clip, time_s, (x0, y0, x1, y1) in 2560x1440 capture px, output width px, why)
CROPS = {
  # S5: case card header after the agents read the message (P1, address, 3 people, reduced mobility, water)
  'case_header':  ('H6_fleet_route', 8.5, (2008, 44, 2556, 142), 1000, 'case header after reading'),
  # S6: live agent graph (rows above y=560 so the dev-only red-team node is not in frame)
  'agents_graph': ('H4_message_agents', 50.5, (16, 226, 1690, 558), 1728, 'live agent graph'),
  # S6: Nemotron receipt tooltip on the Intake node
  'receipt':      ('H4_message_agents', 53.0, (176, 228, 378, 405), 420, 'intake tooltip with receipt'),
  # S6: callback question (vague-message case)
  'callback_q':   ('S5_callback', 3.5, (2008, 1007, 2556, 1101), 760, 'callback main question'),
  # S7: recommended boat card
  'fleet':        ('H6_fleet_route', 8.5, (2012, 326, 2548, 488), 846, 'recommended boat'),
  # S7: route map, launch point + water leg
  'route':        ('H6_fleet_route', 26.0, (610, 502, 1810, 902), 846, 'route map'),
  # S7: landing dialog, shelter + ambulance block
  'landing':      ('H6_fleet_route', 38.5, (970, 640, 1590, 914), 846, 'landing shelter ambulance'),
  # S7: closed case header
  'closed':       ('H10_closed', 24.0, (2008, 44, 2556, 142), 846, 'reported rescue closed'),
  # S7: dispatch checklist ticked by the human dispatcher
  'checklist':    ('H7_dispatch_record', 6.8, (2017, 612, 2544, 815), 846, 'checklist ticked'),
  # S6: evidence quotes in the mission stop
  # S7 (v7): hero route map crop, launch point + water leg, no PT route card / debug strip
  'route_hero':   ('H6_fleet_route', 12.5, (852, 165, 2000, 1026), 1148, 'route map hero'),
  # S7 (v7): English-only header of the recommended boat card (stops above the PT description line)
  'boat_en':      ('H6_fleet_route', 26.0, (2017, 345, 2543, 444), 760, 'recommended boat header'),
  'evidence':     ('H9_reroute', 5.0, (2016, 760, 2550, 885), 700, 'evidence quotes'),
}

# Portuguese on-map overlay labels covered with the surrounding basemap colour (crop px); English chips go on top in the deck
MASKS = {'route_hero': [(682, 434, 766, 460)]}

def mask(im, boxes):
    from statistics import median
    px = im.load()
    for x0, y0, x1, y1 in boxes:
        ring = [px[x, y] for x in range(x0 - 3, x1 + 3) for y in (y0 - 3, y1 + 2)] + [px[x, y] for y in range(y0, y1) for x in (x0 - 3, x1 + 2)]
        c = tuple(int(median(v[i] for v in ring)) for i in range(3))
        for x in range(x0, x1):
            for y in range(y0, y1): px[x, y] = c
    return im

def main(only=None):
    mp = OUT / 'crops.json'
    meta = json.loads(mp.read_text(encoding='utf8')) if mp.exists() else {}
    for name, (clip, t, box, outw, why) in CROPS.items():
        if only and name not in only: continue
        im = frame(clip, t).crop(box)
        if name in MASKS: im = mask(im, MASKS[name])
        w, h = im.size
        outh = round(h * outw / w)
        im = im.resize((outw, outh), Image.LANCZOS)
        im = ImageEnhance.Contrast(im).enhance(1.06)
        im.save(OUT / f'{name}.png', optimize=True)
        meta[name] = dict(clip=clip, t=t, box=box, size=[outw, outh], scale=round(outw / w, 3), why=why)
        print(name, outw, outh, 'scale', round(outw / w, 2))
    (OUT / 'crops.json').write_text(json.dumps(meta, indent=1), encoding='utf8')

if __name__ == '__main__':
    import sys
    main(sys.argv[1:] or None)
