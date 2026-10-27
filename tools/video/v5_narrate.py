"""v5 narration: per-scene edge-tts wavs + WordBoundary json.  usage: v4_narrate.py [--voice V] [--rate +10%] [--samples] [--force]"""
import asyncio, json, subprocess, sys
from pathlib import Path
import edge_tts
import edge_tts.communicate as _c
_c.WSS_URL = 'wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1?Ocp-Apim-Subscription-Key=6A5AA1D4EAFF4E9FB37E23D68491D6F4'

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'out/video/v5/narration'
# scene -> VO text (VIDEO_PLAN_v4). Trims only; facts unchanged.
SCRIPT = {
 1: "May 2024. Rio Grande do Sul. The worst climate disaster in the state's history.",
 2: "Calls for help came from everywhere — dozens of WhatsApp groups, phone calls, social media. Every one was someone waiting for a boat.",
 3: "A strong El Niño is coming again. So we built a team of AI agents that answers every call.",
 4: "Noon. A woman writes from a second floor: her bedridden mother, her eight-year-old son, the water still rising.",
 5: "Within a minute, a team of AI agents running on NVIDIA Nemotron reads her message, quotes every fact, finds the address in Zetaris — and checks each other's work.",
 6: "The fleet agent checks every boat on shift — and finds the one that can reach her through this water. The route follows real streets to the water's edge, then the flooded blocks by boat, to a landing with an ambulance request and a shelter with free beds.",
 7: "A dispatcher approves with one click. Every step is written to a log, the Meterless World Model. It can be replayed, and nothing moves without a human's command.",
 8: "A supervisor agent watches every boat until the job is done.",
 9: "A new emergency nearby? The agents propose fitting it into the boat already on the water — a human approves.",
 10: "Three people, out of the water.",
 11: "When a message is vague, one agent asks a single, precise question — and the whole team checks the case again the moment they answer.",
 12: "When the next surge hits, every request is taken in instantly — the most urgent first, none lost.",
 13: "These are the streets they were working on.",
 14: "The agents read, locate, check, plan and watch on their own — around the clock. People make the one decision that matters: send the boat.",
 15: "Next, we connect it to the real channels and live river gauges — and pilot it with Defesa Civil before the next El Niño.",
 16: "Every request heard. Every agent working together. When the next flood comes, no call for help gets lost.",
 17: "When the facts don't add up, they hand it to a human.",
}

async def make(text, voice, rate, stem, pitch='+0Hz'):
    ev = []
    with stem.with_suffix('.mp3').open('wb') as f:
        async for e in edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary='WordBoundary').stream():
            if e['type'] == 'audio': f.write(e['data'])
            elif e['type'] == 'WordBoundary': ev.append({'text': e['text'], 'start': e['offset']/1e7, 'end': (e['offset']+e['duration'])/1e7})
    stem.with_suffix('.json').write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding='utf-8')
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(stem.with_suffix('.mp3')),'-ar','48000','-ac','1',str(stem.with_suffix('.wav'))], check=True, timeout=60)

def arg(n, d):
    return sys.argv[sys.argv.index(n)+1] if n in sys.argv else d

async def main():
    voice = arg('--voice', 'en-US-AndrewMultilingualNeural'); rate = arg('--rate', '+12%'); pitch = arg('--pitch', '+0Hz')
    OUT.mkdir(parents=True, exist_ok=True)
    if '--samples' in sys.argv:
        t = "May 2024. Rio Grande do Sul. The worst climate disaster in the state's history. A team of Nemotron agents takes over."
        for v in ['en-US-AndrewMultilingualNeural','en-US-BrianMultilingualNeural','en-US-ChristopherNeural']:
            for r in ['+8%','+12%']:
                s = OUT/f'sample_{v}_{r}'.replace('%','p').replace('+','')
                await make(t, v, r, s)
                d = float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(s.with_suffix('.wav'))]))
                print(v, r, round(d,2), flush=True)
        return
    for i, text in SCRIPT.items():
        only = arg('--only', None)
        if only and int(only) != i: continue
        stem = OUT/f'{i:02}'
        if '--force' in sys.argv or not stem.with_suffix('.wav').exists():
            for a in range(3):
                try: await make(text, voice, rate, stem, pitch); break
                except Exception as ex:
                    print('retry', ex)
                    if a == 2: raise
                    await asyncio.sleep(2)
        d = float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(stem.with_suffix('.wav'))]))
        print(f'{i:02} {d:5.2f}s  {len(text.split())} words', flush=True)
    (OUT.parent/'script.json').write_text(json.dumps({'voice': voice, 'rate': rate, 'pitch': pitch, 'script': SCRIPT}, ensure_ascii=False, indent=1), encoding='utf-8')

if __name__ == '__main__': asyncio.run(main())
