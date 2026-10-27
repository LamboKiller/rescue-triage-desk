"""Per-scene Edge TTS stems and word boundaries; no application state is changed."""
import asyncio, json, subprocess, sys
from pathlib import Path
import edge_tts
import edge_tts.communicate as _communicate
# Match the installed Edge protocol revision; leave the shared package untouched.
_communicate.WSS_URL='wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1?Ocp-Apim-Subscription-Key=6A5AA1D4EAFF4E9FB37E23D68491D6F4'

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'out/video/final/narration'
SCRIPT=[
"May 2024. Rio Grande do Sul. The worst climate disaster in the state's history.",
"Calls for help came from everywhere — dozens of WhatsApp groups, phone lines, social media, a single text sent with the last bar of signal. Every one of them was someone waiting for a boat.",
"A strong El Niño is coming again. So we built a team of rescue agents that hears every one of those calls.",
"A team of Nemotron agents takes over. The intake agent reads messy Portuguese and quotes every fact it finds — three people, a bedridden mother, a child. The location agent searches Zetaris for the place.",
"Near the bus station is dozens of flooded blocks — no crew can find a family there. The moment they answer, the whole team re-triages.",
"The logistics agents choose a boat that can carry a stretcher, plan the land and water route, the landing point, the ambulance and a shelter with space. A dispatcher approves with one click.",
"The supervisor agent watches the boat until the job is done. Three people, out of the water.",
"And when a new emergency appears nearby, the agents fit it into a boat that's already on the water.",
"In a surge, the team scales: every request is taken in instantly, the most urgent go first.",
"These are the streets they were working on.",
"Behind them, more agents keep the whole operation running — handing over shifts, reuniting families, tracking every shelter's free beds, finding neighbourhoods no one has reached, and attacking our own system to make it safer.",
"On our development sets the agents now get 29 of 30 right in about 11 seconds. On messages they had never seen, they still miss more — and when they miss, they mostly ask again rather than guess. Every dispatch still needs a human's approval. Every request heard. Every agent working together. When the next flood comes, no call for help gets lost."
]

async def make(text, voice, stem):
    events=[]
    with stem.with_suffix('.mp3').open('wb') as f:
        async for e in edge_tts.Communicate(text,voice,rate='-4%',boundary='WordBoundary').stream():
            if e['type']=='audio': f.write(e['data'])
            elif e['type']=='WordBoundary': events.append(e)
    stem.with_suffix('.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(stem.with_suffix('.mp3')),'-ar','48000','-ac','1',str(stem.with_suffix('.wav'))],check=True,timeout=60)

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if '--samples' in sys.argv:
        for name in ['en-US-AndrewMultilingualNeural','en-US-BrianMultilingualNeural','en-GB-RyanNeural']:
            await make('May 2024. Rio Grande do Sul. Every request heard. Every agent working together.',name,OUT/('sample_'+name))
            print(name,flush=True)
        return
    for i,text in enumerate(SCRIPT,1):
        if '--only' in sys.argv and i!=int(sys.argv[sys.argv.index('--only')+1]):continue
        stem=OUT/f'{i:02}'
        if '--force' in sys.argv or not stem.with_suffix('.wav').exists():
            for attempt in range(3):
                try: await make(text,'en-US-AndrewMultilingualNeural',stem); break
                except Exception:
                    if attempt==2: raise
                    await asyncio.sleep(2)
        print(f'{i:02} ready',flush=True)
    (OUT.parent/'script.json').write_text(json.dumps(SCRIPT,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__': asyncio.run(main())
