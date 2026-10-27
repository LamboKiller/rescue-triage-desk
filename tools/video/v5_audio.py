"""v4 audio: voice timeline + CC0 bed (beat-aligned loop) + own synthesised hits (boom/hit/tick/riser), sidechain duck, loudnorm -14 LUFS / -1 dBTP.
Run with the hermes venv python (numpy)."""
import json, subprocess, wave, re
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
V5 = ROOT / 'out/video/v5'
T = json.loads((V5 / 'timeline_v5.json').read_text(encoding='utf-8'))
SR = 48000; DUR = float(T['duration']); N = int(SR * DUR)
P, PH = 0.6207, 0.03
MUSIC = ROOT / 'tools/video/assets/determined_pursuit.mp3'

def ff(args):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-nostats', '-y', *args], capture_output=True)
    if r.returncode: raise RuntimeError(r.stderr.decode(errors='ignore')[-2000:])
    return r

def read_wav(p):
    with wave.open(str(p)) as w:
        assert w.getframerate() == SR and w.getsampwidth() == 2
        d = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        return d.reshape(-1, w.getnchannels()) if w.getnchannels() > 1 else d

def write_wav(p, x):
    x = np.clip(x, -1, 1)
    with wave.open(str(p), 'wb') as w:
        w.setnchannels(2 if x.ndim == 2 else 1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((x * 32767).astype('<i2').tobytes())

# ---- voice ----
voice = np.zeros(N, np.float32)
for v in json.loads((V5 / 'voice.json').read_text()):
    x = read_wav(ROOT / v['wav']); a = int(v['start'] * SR); voice[a:a+len(x)] += x[:N-a]
write_wav(V5 / 'a_voice_raw.wav', voice)

# ---- music bed: beat-aligned loop (file beat grid = PH + k*P) ----
ff(['-i', str(MUSIC), '-ar', str(SR), '-ac', '2', str(V5 / 'a_music_src.wav')])
m = read_wav(V5 / 'a_music_src.wav')
def seg(a, b): return m[int(a * SR):int(b * SR)]
A = seg(0, PH + 176 * P)
Bs = PH + 30 * P; xf = 2 * P
B = seg(Bs, Bs + (DUR - (PH + 174 * P)) + 0.5)
bed = np.zeros((N + SR, 2), np.float32)
bed[:len(A)] += A
t0 = int((PH + 174 * P) * SR); n = int(xf * SR)
bed[t0:t0+n] *= (np.linspace(1, 0, n)[:, None] ** .7).astype(np.float32)
bed[t0:t0+len(B)] += B * np.concatenate([np.linspace(0, 1, n)[:, None] ** .7, np.ones((len(B) - n, 1))]).astype(np.float32)
bed = bed[:N]
tt = np.arange(N) / SR
g = np.clip(0.55 + tt / 14, 0, 1) * (1 - 0.38 * np.clip((tt - (DUR - 14.5)) / 1.5, 0, 1)) * np.clip((DUR - tt) / 2.8, 0, 1) ** 1.2
bed *= g[:, None].astype(np.float32)

# ---- sfx (own synthesis, no third-party samples) ----
sfx = np.zeros((N, 2), np.float32); rs = np.random.RandomState(7)
def place(x, t, gain=1.0):
    a = int(t * SR)
    if a < 0 or a >= N: return
    x = x[:N-a]; sfx[a:a+len(x), 0] += x * gain; sfx[a:a+len(x), 1] += x * gain
def boom():
    n = int(1.3 * SR); t = np.arange(n) / SR
    x = np.sin(2 * np.pi * np.cumsum(34 + 70 * np.exp(-t * 9)) / SR) * np.exp(-t * 3.2) * .95
    nz = np.convolve(rs.randn(n), np.ones(24) / 24, 'same') * np.exp(-t * 28) * .5
    return (x + nz).astype(np.float32)
def hit():
    n = int(.55 * SR); t = np.arange(n) / SR
    x = np.sin(2 * np.pi * np.cumsum(55 + 140 * np.exp(-t * 22)) / SR) * np.exp(-t * 8) * .8
    nz = np.convolve(rs.randn(n), np.ones(10) / 10, 'same') * np.exp(-t * 45) * .5
    return (x + nz).astype(np.float32)
def tick():
    n = int(.03 * SR); t = np.arange(n) / SR
    return (np.sin(2 * np.pi * 1900 * t) * np.exp(-t * 160) * .5 + rs.randn(n) * np.exp(-t * 200) * .15).astype(np.float32)
def riser(d=2.2):
    n = int(d * SR); t = np.arange(n) / SR; nz = rs.randn(n)
    lp = np.convolve(nz, np.ones(60) / 60, 'same'); hp = nz - np.convolve(nz, np.ones(6) / 6, 'same')
    k = (t / d) ** 2.2
    return ((lp * (1 - k) + hp * k) * (0.1 + 0.9 * k) * .45).astype(np.float32)
for e in json.loads((V5 / 'sfx.json').read_text()):
    k = e['k']
    if k == 'boom': place(boom(), e['t'], .75)
    elif k == 'hit': place(hit(), e['t'], .6)
    elif k == 'tick': place(tick(), e['t'], .5)
    elif k == 'riser_end': place(riser(2.2), e['t'] - 2.2, .8)

# ---- duck music under the voice ----
env = np.convolve(np.abs(voice), np.ones(int(.05 * SR)) / int(.05 * SR), 'same')
act = (env > 0.015).astype(np.float64)
# one-pole attack/release follower on 1 kHz grid, then upsample
step = SR // 1000; a_att = np.exp(-1 / 30); a_rel = np.exp(-1 / 450)
act_k = act[::step]; dk = np.zeros(len(act_k)); s = 0.0
for i, v in enumerate(act_k):
    s = a_att * s + (1 - a_att) * v if v > s else a_rel * s + (1 - a_rel) * v
    dk[i] = s
d = np.interp(np.arange(N), np.arange(len(dk)) * step, dk)
write_wav(V5 / 'a_music.wav', bed * (10 ** (-(9.0 * d) / 20))[:, None].astype(np.float32))
write_wav(V5 / 'a_sfx_d.wav', sfx * (10 ** (-(3.0 * d) / 20))[:, None].astype(np.float32))

# ---- mix + loudnorm (2 pass) ----
fc = ('[0:a]highpass=f=70,acompressor=threshold=0.1:ratio=3:attack=5:release=120:makeup=3,loudnorm=I=-16:TP=-3:LRA=7,aresample=48000,pan=stereo|c0=c0|c1=c0[v];'
      '[1:a]volume=0.62[m];[2:a]volume=0.9[s];[v][m][s]amix=inputs=3:normalize=0:duration=longest[mix]')
pre = V5 / 'a_premaster.wav'
ff(['-i', str(V5 / 'a_voice_raw.wav'), '-i', str(V5 / 'a_music.wav'), '-i', str(V5 / 'a_sfx_d.wav'), '-filter_complex', fc, '-map', '[mix]', '-ar', str(SR), '-c:a', 'pcm_s24le', str(pre)])
r = ff(['-i', str(pre), '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'])
st = json.loads(re.findall(r'\{\s*"input_i".*?\}', r.stderr.decode(), re.S)[-1])
af = 'loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}:measured_thresh={input_thresh}:offset={target_offset}:linear=true'.format(**st)
ff(['-i', str(pre), '-af', af, '-ar', str(SR), '-ac', '2', '-c:a', 'aac', '-b:a', '256k', str(V5 / 'soundtrack_v5.m4a')])
r = ff(['-i', str(V5 / 'soundtrack_v5.m4a'), '-af', 'ebur128=peak=true', '-f', 'null', '-'])
txt = r.stderr.decode(errors='ignore'); summ = txt[txt.rfind('Summary:'):]
I = re.search(r'I:\s+(-?[\d.]+) LUFS', summ).group(1); LRA = re.search(r'LRA:\s+([\d.]+) LU', summ).group(1); TP = re.search(r'Peak:\s+(-?[\d.]+) dBFS', summ).group(1)
(V5 / 'loudness_verified.json').write_text(json.dumps(dict(input_i=I, input_tp=TP, input_lra=LRA), indent=1))
print('integrated', I, 'LUFS  TP', TP, 'dBTP  LRA', LRA)
