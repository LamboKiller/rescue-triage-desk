"""Build the frame-exact edit and an auditable shot/reading/caption manifest."""
import json,math,shutil,subprocess,wave,textwrap,html,csv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'out/video/final';ASSETS=ROOT/'tools/video/assets'
OUT.mkdir(parents=True,exist_ok=True);(ASSETS/'photos').mkdir(exist_ok=True)
ids=['148627042','148626731','148627043','148626759','148627029','148627049']
for id in ids:shutil.copyfile(ROOT/f'docs/submission/deck2/assets/photos/{id}.jpg',ASSETS/f'photos/{id}.jpg')
photo=lambda n:'/tools/video/assets/photos/'+ids[n%len(ids)]+'.jpg'
script=json.loads((OUT/'script.json').read_text(encoding='utf-8'))
durations=[20,15,10,29,23,26,18,12,22,14,17,31]
starts=[];pos=0
for d in durations:starts.append(pos);pos+=d
T={'width':1920,'height':1080,'fps':60,'duration':pos,'version':'v0','shots':[],'scenes':[],'blocks':[],'captions':[],'actBreaks':[45,175]}
def B(at,until,text=None,html=None,**kw):
    b={'at':at,'until':until,**kw}
    if text is not None:b['text']=text
    if html is not None:b['html']=html
    T['blocks'].append(b);return b
def shot(scene,a,b,kind='photo',**kw):T['shots'].append({'scene':scene,'start':a,'end':b,'kind':kind,**kw})
def splits(a,b,maxdur=5):
    n=math.ceil((b-a)/maxdur)
    return [(a+(b-a)*j/n,a+(b-a)*(j+1)/n) for j in range(n)]
def ui(scene,a,b,clip,sourceStart=0,sourceEnd=None,live=False,focus=(.65,.5,1.32)):
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(ROOT/f'out/video/raw/{clip}.mp4')],timeout=30))
    full=float(probe['format']['duration']);sourceEnd=min(sourceEnd or sourceStart+(b-a),full-.12);sourceStart=max(0,min(sourceStart,sourceEnd-.2));speed=(sourceEnd-sourceStart)/(b-a)
    # Keep real-time footage real-time unless a measured wait is accelerated.
    for j,(x,y) in enumerate(splits(a,b)):
        cam={'x':focus[0] if j%2 else .5,'y':focus[1] if j%2 else .5,'z':focus[2] if j%2 else 1.02}
        marks=json.loads((ROOT/f'out/video/raw/{clip}.marks.json').read_text(encoding='utf-8')).get('marks',[])
        ss=sourceStart+(x-a)*speed;rings=[]
        for m in marks:
            if m.get('box') and ss<=m['t']<ss+(y-x)*speed:
                box=m['box'];rings.append({'t':(m['t']-ss)/speed,'x':box['x']+box['w']/2,'y':box['y']+box['h']/2})
        label={9:'Synthetic surge · offline sample',10:'Historical flood map · photo comparison'}.get(scene)
        shot(scene,x,y,'ui',frames=f'/out/video/frames/{clip}',sourceFps=30,sourceStart=ss,speed=speed,realSeconds=sourceEnd-sourceStart,live=live,camera=cam,clip=clip,placeholder=False,offlineFallback=not live and scene in [5,6,7,8],modeLabel=label,rings=rings)
def photoseq(scene,a,b,n=0,opacity=1,wash=.7):
    for j,(x,y) in enumerate(splits(a,b)):
        shot(scene,x,y,image=photo(n+j),mediaOpacity=opacity,wash=wash)

# Act one: each statistic gets its own four-second full-bleed photograph.
for j in range(5):shot(1,j*4,(j+1)*4,image=photo(j),wash=.64)
B(.2,4,text='Rio Grande do Sul\nMay 2024',x=88,y=410,w=1500,**{'class':'title'},wipe=True)
for at,value,label in [(4,'185','people died'),(8,'478 / 497','municipalities affected'),(12,'2.4 million','people affected'),(16,'5.35 m','Guaíba peak · 1941: 4.76 m')]:
    B(at+.05,at+4,html=f'<div class="number">{value}</div><div class="sub">{label}</div>',readingText=f'{value} {label}',x=88,y=520,w=1700,stat=True,reveal=.55)
B(.1,20,text='© CarolSiBa · CC BY 4.0 · Wikimedia Commons · 21 May 2024, post-peak illustration',x=88,y=825,w=1740,**{'class':'foot'},credit=True,reveal=0)
B(.1,20,text='Statistics: Defesa Civil RS, final bulletin 19 Aug 2025 · Guaíba: SGB / G1, 3 Sep 2024',x=88,y=1020,w=1740,**{'class':'foot'},credit=True,reveal=0)
photoseq(2,20,35,2,.34,.9)
B(20,35,text='Every channel.\nOne queue.',x=88,y=114,w=1400,**{'class':'title'},wipe=True)
for at,text,x,y,w in [(21.4,'WhatsApp · grupo de resgate<br><b>socorro, minha mãe está acamada</b>',100,390,765),(23.2,'Ligação · transcrição<br><b>a água chegou na janela</b>',970,335,760),(25,'Rede social · pedido de ajuda<br><b>tem uma família no telhado</b>',100,610,765),(26.8,'Mensagem · ▂ sinal<br><b>estamos aqui, por favor</b>',970,560,760)]:
    B(at,35,html=text,x=x,y=y,w=w,**{'class':'bubble'})
B(29,35,text='Every request enters the same queue',x=300,y=775,w=1320,**{'class':'sub card'})
B(20,35,text='Illustrative Portuguese messages · fictional examples · source context: Exame / SalvaRS, May 2024',x=88,y=1020,w=1750,**{'class':'foot'},credit=True,reveal=0)
photoseq(3,35,41,3,.48,.85)
B(35,41,html='<div class="number blue">&gt;83%</div><div class="sub">Strong El Niño likely through early 2027</div>',readingText='Over 83 percent. Strong El Niño likely through early 2027',x=88,y=330,w=1600,stat=True,reveal=.55)
B(35,41,text='NOAA CPC · 8 Oct 2026 · ENSO Diagnostic Discussion · impacts are not guaranteed',x=88,y=1015,w=1740,**{'class':'foot'},credit=True,reveal=0)
ui(3,41,45,'live1',15,19,True)

# First complete cut. Source modes are explicit; never relabel offline material as live.
ui(4,45,74,'live1',17,58,True,focus=(.5,.53,1.32))
ui(5,74,97,'brief-snapshot-rest',.5,27,False,focus=(.79,.48,1.48))
ui(6,97,123,'brief-snapshot-rest',29,62,False,focus=(.77,.50,1.40))
ui(7,123,136,'brief-snapshot-rest',63,97,False,focus=(.75,.48,1.36))
ui(7,136,141,'brief-snapshot-rest',129,134,False,focus=(.75,.48,1.36))
ui(8,141,153,'brief-snapshot-rest',98,121,False,focus=(.75,.5,1.36))
if (ROOT/'out/video/raw/surge.mp4').exists():ui(9,153,175,'surge',8,34,False,focus=(.27,.40,1.45))
else:ui(9,153,175,'offline-rest',28,50,False,focus=(.25,.45,1.4))
if (ROOT/'out/video/raw/map.mp4').exists():ui(10,175,189,'map',11,37,False,focus=(.61,.47,1.16))
else:photoseq(10,175,189,0,1,.25)
B(45.6,51.8,text='Intake → location → verifier',x=88,y=760,w=1100,**{'class':'tag'})
B(52.5,59.4,text='3 people · exact quoted evidence',x=88,y=760,w=1200,**{'class':'tag'})
B(60.5,67,text='Bedridden mother → medical priority',x=88,y=760,w=1300,**{'class':'tag'})
B(74.4,82,text='Clarify. Re-triage.',x=88,y=745,w=1100,**{'class':'tag'})
B(84,96,text='Callback policy differs from the scripted question',x=88,y=780,w=1400,**{'class':'sub card'})
B(98,105,text='Stretcher capacity · route · landing',x=88,y=760,w=1350,**{'class':'tag'})
B(107,115,text='Every dispatch needs human approval',x=88,y=760,w=1350,**{'class':'tag'})
B(124,131,text='Fleet / GPS [SIMULADO]',x=88,y=760,w=1100,**{'class':'tag'})
B(133,140,text='Supervisor: alert → fix → closed',x=88,y=760,w=1350,**{'class':'tag'})
B(142,152,text='New P1 · reroute proposal · human approval',x=88,y=760,w=1430,**{'class':'tag'})
B(154,161,text='60 requests · synthetic surge',x=88,y=760,w=1200,**{'class':'tag'})
B(164,174,text='Urgent requests first',x=88,y=760,w=1100,**{'class':'tag'})
B(176,188,text='Flooded streets. Real photographs.',x=88,y=135,w=1400,**{'class':'title'},wipe=True)
B(175,189,text='Photo comparison: 21 May 2024 · post-peak illustration · © CarolSiBa / CC BY 4.0',x=88,y=1015,w=1750,**{'class':'foot'},credit=True,reveal=0)

photoseq(11,189,206,1,.34,.95)
B(189,206,text='A whole rescue operation',x=88,y=88,w=1710,**{'class':'title'},wipe=True)
rows=[('Shift handover','Handover agent'),('Family reunification','Reunification agent'),('Shelter vacancies','Shelter agent'),('Unreached neighbourhoods','Coverage agent'),('Volunteer boats','Volunteer agent'),('Conflicting reports','Contradiction agent'),('Attack. Learn. Improve.','Red-team agent')]
for j,(task,agent) in enumerate(rows):B(190.4+j*1.55,206,html=f'<span class="blue">{j+1:02}</span> &nbsp; {task} &nbsp; <small>{agent}</small>',x=100,y=250+j*82,w=1700,**{'class':'roster'})
B(202,206,text='Intake · location · verifier · callback · logistics / route · supervisor',x=88,y=817,w=1750,**{'class':'foot'},credit=True,reveal=0)

photoseq(12,206,237,4,.28,.96)
B(206.2,213.4,html='<div class="sub">Development set (live) · 11.3 s mean</div>',readingText='29 of 30 correct. Development set live. 11.3 seconds mean.',x=88,y=265,w=1690,stat=True,counter={'to':29,'suffix':'/30','seconds':1.2},color='green',reveal=.6)
B(206,213.4,text='Author-written development set · 27 Oct 2026 · source: POSITIONING.md / live realdev30',x=88,y=1015,w=1750,**{'class':'foot'},credit=True,reveal=0)
B(213.6,220.5,html='<div class="number">34/50 &nbsp; 29/50</div><div class="sub">Never-seen sets · blind, run once<br>Most misses cautious</div>',readingText='34 of 50 and 29 of 50. Never-seen sets. Blind, run once. Most misses cautious.',x=88,y=265,w=1720,stat=True,reveal=.6)
B(213.6,220.5,text='Blind evaluation results · no claim of deployment · results supplied in BRIEF_VID.md',x=88,y=1015,w=1750,**{'class':'foot'},credit=True,reveal=0)
B(220.8,227.6,html='<div class="number green">0 unsafe</div><div class="sub">On development &amp; red-team sets<br>Every dispatch needs human approval</div>',readingText='0 unsafe on development and red-team sets. Every dispatch needs human approval.',x=88,y=265,w=1700,stat=True,reveal=.6)
B(228,232.5,text='NVIDIA Nemotron · Nightshift / Meterless · Zetaris',x=88,y=360,w=1730,**{'class':'sub'},reveal=.5)
B(230,237,text='github.com/LamboKiller/rescue-triage-desk',x=88,y=550,w=1730,**{'class':'sub'},reveal=.5)
B(233,237,text='Every request heard.',x=88,y=700,w=1740,**{'class':'title'},wipe=True)

# WordBoundary offsets remain the source of caption timing. No estimated word times.
for i,(start,duration,text) in enumerate(zip(starts,durations,script),1):
    wp=OUT/f'narration/{i:02}.wav'
    with wave.open(str(wp)) as w:length=w.getnframes()/w.getframerate()
    cue=start+.45
    T['scenes'].append({'scene':i,'start':start,'end':start+duration,'narrationStart':cue,'narrationDuration':length,'narration':text,'wav':f'narration/{i:02}.wav'})
    events=json.loads((OUT/f'narration/{i:02}.json').read_text(encoding='utf-8'))
    groups=[];group=[];count=0
    for e in events:
        n=len(e['text'].split())
        if count+n>7:groups.append(group);group=[];count=0
        group.append(e);count+=n
    if group:groups.append(group)
    for j,g in enumerate(groups):
        cap=' '.join(html.unescape(e['text']) for e in g)
        lines=textwrap.wrap(cap,width=42,break_long_words=False)
        if len(lines)>2:raise ValueError(f'Caption too long: {cap}')
        a=cue+g[0]['offset']/1e7;b=cue+(g[-1]['offset']+g[-1]['duration'])/1e7
        nxt=cue+groups[j+1][0]['offset']/1e7 if j+1<len(groups) else start+duration-.2
        b=min(max(b,a+.95),nxt)
        if b-a<.9:raise ValueError(f'Caption flash: {cap}')
        T['captions'].append({'start':a,'end':b,'text':'\n'.join(lines),'scene':i,'wordBoundary':True})
T['shots'].sort(key=lambda s:s['start'])
(OUT/'timeline.json').write_text(json.dumps(T,ensure_ascii=False,indent=2),encoding='utf-8')
def tc(t):return f'{int(t//60):02}:{t%60:04.1f}'
def srt(t):return f'{int(t//3600):02}:{int(t//60)%60:02}:{int(t)%60:02},{round(t%1*1000):03}'
(OUT/'rtd_demo_en.srt').write_text('\n\n'.join(f'{i}\n{srt(c["start"])} --> {srt(c["end"])}\n{c["text"]}' for i,c in enumerate(T['captions'],1))+'\n',encoding='utf-8')
md=['# Every second of the cut','',f'Master: {pos} s · 1920×1080 · 60 fps. UI source mode is explicit in every shot.','', '| Start–end | Scene | On screen | Narration words in this shot | On-screen text / fully visible hold | Speed | Purpose |','|---|---|---|---|---|---|---|']
for s in T['shots']:
    words=' '.join(c['text'].replace('\n',' ') for c in T['captions'] if s['start']<=c['start']<s['end'])
    blocks=[b for b in T['blocks'] if b['at']<s['end'] and b['until']>s['start']]
    display='; '.join((b.get('text') or b.get('readingText') or b.get('html','')).replace('\n',' / ')+' ['+str(round(b['until']-b['at']-b.get('reveal',.55)-.3,2))+' s]' for b in blocks if not b.get('credit'))
    purpose={1:'Impact, cited real flood context',2:'Intake across channels',3:'Climate context; actual desk',4:'Agent cooperation and evidence',5:'Callback and re-triage; policy limit disclosed',6:'Logistics and human approval',7:'Fleet / supervisor loop',8:'Reroute proposal',9:'Surge intake',10:'Geospatial evidence',11:'Breadth of agent team',12:'Scoped evaluation, limitations, sponsors'}[s['scene']]
    content=('Live UI: ' if s.get('live') else 'OFFLINE PLACEHOLDER: ') + s.get('clip','') if s['kind']=='ui' else 'Real flood photo '+Path(s.get('image','')).name
    md.append(f'| {tc(s["start"])}–{tc(s["end"])} | {s["scene"]} | {content} | {words} | {display} | {s.get("speed",1):.2f}× | {purpose} |')
(OUT/'TIMELINE.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
ns=['# Narration stems and timed cues','','Voice: en-US-AndrewMultilingualNeural, rate −4%. Three comparison samples are retained.','Word timing: Edge TTS WordBoundary events, 100 ns units.','']
for scene in T['scenes']:
    ns.extend([f'## Scene {scene["scene"]:02} · {tc(scene["narrationStart"])}–{tc(scene["narrationStart"]+scene["narrationDuration"])}',scene['narration'],''])
    ev=json.loads((OUT/f'narration/{scene["scene"]:02}.json').read_text(encoding='utf-8'));sentence=[];a=None
    for e in ev:
        if a is None:a=scene['narrationStart']+e['offset']/1e7
        sentence.append(html.unescape(e['text']))
        if e['text'].endswith(('.', '?', '!')):
            ns.append(f'- {tc(a)}–{tc(scene["narrationStart"]+(e["offset"]+e["duration"])/1e7)}: '+ ' '.join(sentence));sentence=[];a=None
    if sentence:ns.append(f'- {tc(a)}: '+' '.join(sentence))
(OUT/'narration_script.md').write_text('\n'.join(ns)+'\n',encoding='utf-8')
credits=['# Credits','','Music: Soul Release — Ruskerdax (2023). CC0 1.0.','Source / licence page: https://opengameart.org/content/soul-release','Original file: https://opengameart.org/sites/default/files/ruskerdax_-_soul_release.mp3','Legal text: CC0-1.0.txt in this directory; https://creativecommons.org/publicdomain/zero/1.0/','Licence page archived locally as soul-release-license.html.','The track is time-stretched by approximately 2% and ducked beneath narration.','','Typeface: Inter 4.1 — Rasmus Andersson; SIL Open Font License 1.1.','Source: https://github.com/rsms/inter/releases/tag/v4.1','Full licence: ../fonts/LICENSE.txt','','Narration: Microsoft Edge TTS, Andrew Multilingual Neural (AI voice).','Compatibility endpoint follows https://github.com/rany2/edge-tts/issues/490 .','','Photographs: © CarolSiBa, CC BY 4.0, Wikimedia Commons.','Cropped / graded / animated for this film. Taken 21 May 2024, post-peak illustration.']
rows={r['id']:r for r in csv.DictReader((ROOT/'data/photos/photos.csv').open(encoding='utf-8'))}
for id in ids:
    r=rows.get(id)
    if r:credits.append(f'- {id}: {r["source_url"]} · {r["license_url"]}')
    else:raise ValueError('Missing photo credit '+id)
(ASSETS/'CREDITS.md').write_text('\n'.join(credits)+'\n',encoding='utf-8');shutil.copyfile(ASSETS/'CREDITS.md',OUT/'CREDITS.md')
print(f'Built {len(T["shots"])} shots, {len(T["captions"])} word-timed captions, {pos} seconds')
