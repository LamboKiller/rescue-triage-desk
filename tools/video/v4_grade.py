"""One consistent grade for every flood photo: per-image exposure normalisation to a common luminance target, fixed S-curve, fixed teal/amber split tone."""
import numpy as np, sys
from pathlib import Path
from PIL import Image
ROOT = Path(__file__).resolve().parents[2]; src = ROOT / 'tools/video/assets/photos5'; dst = ROOT / 'tools/video/assets/photos5g'; dst.mkdir(exist_ok=True)
for f in sorted(src.glob('c*.jpg')):
    im = np.asarray(Image.open(f).convert('RGB').resize((2560, int(2560 * Image.open(f).size[1] / Image.open(f).size[0])), Image.LANCZOS)).astype(np.float32) / 255
    y = im @ np.array([.2126, .7152, .0722], np.float32)
    lo, hi = np.percentile(y, [1, 99.5]); im = np.clip((im - lo) / (hi - lo), 0, 1)
    y = im @ np.array([.2126, .7152, .0722], np.float32); g = np.log(.40) / np.log(max(np.median(y), .05)); im = im ** g   # median luminance -> 0.40
    im = im * im * (3 - 2 * im) * .55 + im * .45                         # gentle S curve
    y = (im @ np.array([.2126, .7152, .0722], np.float32))[..., None]
    im = y + (im - y) * .82                                              # saturation
    t = np.clip((y - .5) * 2, -1, 1); im = im + np.array([-.020, .004, .028]) * (1 - np.clip(t, 0, 1)) + np.array([.030, .012, -.022]) * np.clip(t, 0, 1)
    im = np.clip(.035 + im * .93, 0, 1)                                  # lifted black point
    Image.fromarray((im * 255 + .5).astype(np.uint8)).save(dst / f.name, quality=93); print(f.name, round(float(np.median(y)), 3))
