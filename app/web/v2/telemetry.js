'use strict';
window.DeskTelemetry=(()=>{
  const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  let data={units:[],pending:[],bindings:{}},overlay,svg,enabled=true,frame=0,started=0,size={width:1,height:1},error='',busy=null;
  const markers=new Map(),age=r=>r.age_seconds==null?'sem fix':r.age_seconds<60?`${r.age_seconds} s`:`${Math.floor(r.age_seconds/60)} min`;
  async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);const p=await r.json();if(!r.ok)throw Error(p.error||'Telemetria indisponível');return p;}
  function key(r){return r.unit_id+':'+r.source;}
  function label(r){return `${r.source==='simulated'?'[SIMULADO] ':''}${r.unit_id} · ${age(r)} · ${r.eta_label_pt||'ETA indisponível'}`;}
  function card(row){
    const d=el('dialog');d.setAttribute('aria-label','Unidade da frota ao vivo');
    const close=el('button','Fechar');close.onclick=()=>d.close();d.append(el('h2',label(row)),close,
      el('p',`Estado informado: ${row.status} · missão ${row.mission_id||'sem missão'} · último fix há ${age(row)}`),
      el('p',row.eta_label_pt||'ETA indisponível'),el('p',`Fonte: ${row.source}; GPS não confirma resgate.`));
    d.append(el('p',row.route_label_pt||'Rota não comprovada'));
    for(const text of row.route_review_pt||[])d.append(el('p',text));
    if(row.arrival_proposal){d.append(el('p',row.arrival_proposal.label_pt),el('p','Confirme com a equipe e registre o estado em Recursos → Relatar estado.'));}
    for(const a of row.alerts||[])d.append(el('p',a.facts[0].text_pt));
    d.addEventListener('close',()=>d.remove());document.body.append(d);d.showModal();
  }
  function reconcile(){
    if(!overlay)return;
    const keys=new Set();started=performance.now();
    for(const row of data.units.filter(r=>r.fix)){
      const id=key(row);keys.add(id);let item=markers.get(id);
      if(!item){const b=el('button'),heading=el('span','▲'),caption=el('span');b.append(heading,caption);b.style.cssText='position:absolute;left:0;top:0;pointer-events:auto;white-space:nowrap;padding:3px;font-size:11px;background:#14212a';heading.style.display='inline-block';
        const trail=document.createElementNS('http://www.w3.org/2000/svg','polyline');trail.setAttribute('fill','none');trail.setAttribute('stroke-width','2');svg.append(trail);overlay.append(b);item={b,heading,caption,trail,current:[row.fix.lon,row.fix.lat]};markers.set(id,item);}
      item.from=item.current;item.to=[row.fix.lon,row.fix.lat];item.row=row;
      item.caption.textContent=label(row);item.b.setAttribute('aria-label',label(row));item.b.onclick=()=>card(item.row);
      const color=row.fresh?'#51d6ae':'#f5a524';item.b.style.color=color;item.trail.setAttribute('stroke',color);
      item.heading.style.transform=`rotate(${row.fix.bearing}deg)`;
    }
    for(const [id,item]of markers)if(!keys.has(id)){item.b.remove();item.trail.remove();markers.delete(id);}
    animate();
  }
  function draw(now){
    frame=0;if(document.hidden||!enabled||!overlay)return;
    const state=window.DeskMap?.telemetrySurface?.();if(!state)return;
    const project=p=>{if(state.gl){const v=state.gl.project(p);return [v.x,v.y];}const scale=Math.min(size.width/.036,size.height/.028);return [size.width/2+(p[0]-state.center[0])*scale*Math.cos(state.center[1]*Math.PI/180),size.height/2-(p[1]-state.center[1])*scale];};
    const reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches,t=reduce?1:Math.min(1,(now-started)/1500);
    for(const item of markers.values()){
      item.current=item.from.map((v,i)=>v+(item.to[i]-v)*t);const p=project(item.current);
      item.b.style.transform=`translate(${p[0]}px,${p[1]}px)`;
      item.trail.setAttribute('points',item.row.trail.slice(-10).map(f=>project([f.lon,f.lat]).join(',')).join(' '));
    }
    if(t<1)frame=requestAnimationFrame(draw);
  }
  function animate(){if(!frame&&!document.hidden&&enabled)frame=requestAnimationFrame(draw);}
  async function poll(){
    if(document.hidden)return;if(busy)return busy;
    busy=(async()=>{
      try{data=await api('/api/telemetry');error='';reconcile();}
      catch(e){error=e.message;for(const item of markers.values()){item.b.style.color='#f5a524';item.caption.textContent='Sem atualização · '+item.row.unit_id;}}
      finally{busy=null;}
    })();return busy;
  }
  function mount(){
    const stage=document.querySelector('.map-stage'),options=document.getElementById('layer-options');if(!stage||!options)return;
    overlay=el('div');overlay.setAttribute('aria-label','Frota ao vivo');overlay.style.cssText='position:absolute;inset:0;overflow:hidden;pointer-events:none;z-index:3';
    svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('width','100%');svg.setAttribute('height','100%');svg.style.position='absolute';overlay.append(svg);stage.append(overlay);
    const toggle=el('label'),check=el('input');check.type='checkbox';check.checked=true;toggle.append(check,document.createTextNode(' Frota ao vivo'));options.append(toggle);
    check.onchange=()=>{enabled=check.checked;overlay.hidden=!enabled;animate();};
    new ResizeObserver(entries=>{size=entries[0].contentRect;animate();}).observe(stage);
    // Map transforms change without new fixes. Paint only on map movement.
    let hooked=null;setInterval(()=>{const gl=window.DeskMap?.telemetrySurface?.().gl;if(gl&&gl!==hooked){hooked=gl;gl.on('move',animate);}},1000);
    document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAnimationFrame(frame);frame=0;}else poll();});
    document.getElementById('date')?.addEventListener('change',()=>poll());poll();setInterval(poll,4000);
  }
  async function resources(section,unit,ctx){
    const note=el('p','Consultando GPS…');section.append(note);
    try{
      await poll();const rows=data.units.filter(r=>r.unit_id===unit.id);
      note.textContent=error||rows.map(label).join(' | ')||'GPS: sem fix; vincule um dispositivo confirmado.';
      for(const row of rows){const b=el('button','Ver telemetria');b.onclick=()=>card(row);section.append(b);}
      const details=el('details');details.append(el('summary','Vincular dispositivo GPS (operador)'));
      details.append(el('p','Dispositivos não reconhecidos ficam pendentes. Demo: sim:'+unit.id));
      if(data.pending.length)details.append(el('p','Pendentes: '+data.pending.map(p=>p.device).join(', ')));
      const input=el('input');input.maxLength=120;input.setAttribute('aria-label','Identificador do dispositivo');
      input.value=Object.keys(data.bindings).find(d=>data.bindings[d]===unit.id)||'';
      const bind=el('button','Confirmar vínculo');bind.onclick=async()=>{try{await api('/api/telemetry/bindings',{device:input.value,unit_id:unit.id,actor:'operador'});ctx.notice('Vínculo GPS confirmado.');await poll();}catch(e){ctx.notice(e.message,true);}};
      details.append(input,bind);section.append(details);
    }catch(e){note.textContent=e.message;}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount);else mount();
  return {resources};
})();
