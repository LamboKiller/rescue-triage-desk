'use strict';
// Replay clock: calendar (event window 2024-04-29…2024-05-20), hour slider, presets, play/pause and 1×/10×/60×.
// The date input stays the source of truth for the day; this module adds the hour and always shows the replay time.
window.DeskReplay=(()=>{
  const MIN='2024-04-29',MAX='2024-05-20',WD=['dom','seg','ter','qua','qui','sex','sáb'];
  const PRESETS=[['rp-preset-peak','Pico 06/05 08:00','2024-05-06',8*60],['rp-preset-0805','08/05 12:00','2024-05-08',12*60],['rp-preset-1205','12/05 12:00','2024-05-12',12*60]];
  let minutes=1439,playing=false,speed=60,timer=null,lastLoad=0,loading=false,dirty=false,ui={};
  const $=id=>document.getElementById(id),pad=n=>String(n).padStart(2,'0');
  const day=()=>$('date').value;
  const hhmm=m=>{m=Math.floor(m);return `${pad(Math.floor(m/60))}:${pad(m%60)}`;};
  const iso=()=>`${day()}T${hhmm(minutes)}:${minutes>=1439?'59':pad(Math.floor((minutes-Math.floor(minutes))*60))}-03:00`;
  function label(){
    const d=new Date(day()+'T12:00:00-03:00');
    return `${WD[d.getUTCDay()]} ${day().slice(8)}/${day().slice(5,7)}/${day().slice(0,4)} · ${minutes>=1439?'fim do dia (23:59)':hhmm(minutes)} BRT`;
  }
  function paint(){
    if(!ui.clock)return;ui.clock.textContent=label();ui.hour.value=String(Math.min(24,Math.round(minutes/60)));
    ui.play.textContent=playing?'⏸':'▶';ui.play.setAttribute('aria-pressed',String(playing));ui.play.title=playing?'Pausar o relógio do replay':'Avançar o relógio do replay';
    for(const [s,b] of ui.speeds)b.setAttribute('aria-pressed',String(s===speed));
  }
  async function reload(full){
    if(loading){dirty=true;return;}loading=true;lastLoad=Date.now();
    try{if(full)await $('date').onchange?.();else await window.DeskApp.refresh();}catch(e){console.warn('replay reload',e);}
    finally{loading=false;if(dirty){dirty=false;setTimeout(()=>reload(false),50);}}
  }
  let deb=null;const later=(full)=>{clearTimeout(deb);deb=setTimeout(()=>reload(full),full?0:250);};
  function setDay(d,full=true){
    if(d<MIN)d=MIN;if(d>MAX)d=MAX;
    if($('date').value!==d){$('date').value=d;paint();later(true);}else{paint();if(full)later(false);}
  }
  function set(d,m){minutes=Math.max(0,Math.min(1439,m));if(d)setDay(d,true);else{paint();later(false);}}
  function tick(){
    if(!playing)return;minutes+=speed/60;                   // 1× = real time (1 replay-second per second); 60× = 1 replay-minute per second
    if(minutes>=1439.99){const d=new Date(day()+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+1);const nd=d.toISOString().slice(0,10);if(nd>MAX){playing=false;minutes=1439;}else{minutes=0;setDay(nd);}}
    paint();if(Date.now()-lastLoad>4000)later(false);
  }
  function startStop(on){playing=on;clearInterval(timer);if(on)timer=setInterval(tick,1000);paint();}
  function init(){
    const date=$('date'),bar=document.createElement('div');bar.id='replay-bar';bar.setAttribute('role','group');bar.setAttribute('aria-label','Relógio do replay');
    date.min=MIN;date.max=MAX;
    const clock=document.createElement('strong');clock.id='replay-clock';clock.setAttribute('aria-live','polite');
    const hour=document.createElement('input');hour.type='range';hour.min='0';hour.max='24';hour.step='1';hour.id='replay-hour';hour.setAttribute('aria-label','Hora do replay (24 = fim do dia)');
    hour.oninput=()=>{const h=+hour.value;minutes=h>=24?1439:h*60;paint();later(false);};
    const play=document.createElement('button');play.type='button';play.id='rp-play';play.textContent='▶';
    play.onclick=()=>startStop(!playing);
    const speeds=[1,10,60].map(s=>{const b=document.createElement('button');b.type='button';b.id='rp-s'+s;b.textContent=s+'×';b.title=s===1?'Tempo real':`${s}× mais rápido`;b.onclick=()=>{speed=s;paint();};return [s,b];});
    const prev=document.createElement('button'),next=document.createElement('button');
    for(const [b,t,dd] of [[prev,'‹','-1'],[next,'›','1']]){b.type='button';b.textContent=t;b.title=dd==='1'?'Dia seguinte':'Dia anterior';b.id=dd==='1'?'rp-next':'rp-prev';
      b.onclick=()=>{const d=new Date(day()+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+(+dd));setDay(d.toISOString().slice(0,10));};}
    const menu=document.createElement('details');menu.id='rp-presets';const sum=document.createElement('summary');sum.textContent='Ir para ▾';menu.append(sum);
    const list=document.createElement('div');list.className='rp-list';
    for(const [id,text,d,m] of PRESETS){const b=document.createElement('button');b.type='button';b.id=id;b.textContent=text;b.onclick=()=>{menu.open=false;set(d,m);};list.append(b);}
    const hint=document.createElement('small');hint.textContent=`Janela do evento: ${MIN.slice(8)}/04 a ${MAX.slice(8)}/05`;list.append(hint);menu.append(list);
    bar.append(prev,next,clock,hour,play,...speeds.map(x=>x[1]),menu);
    (document.querySelector('.status-bar label.replay')||date.parentElement).after(bar);
    date.addEventListener('change',()=>{paint();});
    document.addEventListener('click',e=>{if(menu.open&&!menu.contains(e.target))menu.open=false;});
    ui={clock,hour,play,speeds};paint();
    document.addEventListener('visibilitychange',()=>{if(document.hidden&&playing)startStop(false);});
  }
  // deep link: /v2?t=2024-05-06T08:00 opens the desk at that replay time (demos, tests, shared links)
  const m=/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})$/.exec(new URLSearchParams(location.search).get('t')||'');
  if(m&&m[1]>=MIN&&m[1]<=MAX&&$('date')){$('date').value=m[1];minutes=Math.min(1439,(+m[2])*60+(+m[3]));}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
  return {iso,set,get minutes(){return minutes;},label,isPlaying:()=>playing};
})();
