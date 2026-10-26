'use strict';
window.DeskRoute={async render(b,c,{api,el,button,evidence,day}){
const box=el('section',undefined,'mission-card'),s=el('select'),o=el('div');let seq=0;
box.setAttribute('aria-label','Rota');
box.append(el('h3','Rota'),s,button('Ver rota',load),o);b.append(box);
s.setAttribute('aria-label','Unidade da rota');s.onchange=load;
window.DeskMap?.showRoute(null);
const say=t=>o.append(el('p',t));
try{for(const u of (await api('/api/resources')).typed_resources||[]){const e=el('option',`${u.id} · ${u.label_pt}`);e.value=u.id;s.append(e);}if(!s.length)say('Sem unidade documentada.');}catch(e){say(`REVISAR: ${e.message}`);}
async function load(){const n=++seq;o.replaceChildren();window.DeskMap?.showRoute(null);
try{const r=await api(`/api/cases/${c.case_id}/route?unit=${encodeURIComponent(s.value)}&date=${day}`);
if(n!==seq||!box.isConnected)return;
for(const t of r.review_pt||[])say(t);
if(r.reachable){const l=r.land||r;say(`Terra: ${l.land_km} km / ${l.land_eta_min} min estimados`);
if(r.water)say(`${r.water.label_pt}: ${r.water.km} km; profundidade máxima amostrada: ${r.water.max_depth_m??'desconhecida'} m; amostras sem dado: ${r.water.unknown_samples}`);
window.DeskMap?.showRoute(r);
for(const a of r.alternatives||[])o.append(button(`${a.launch_point.nearest_street_name} · ${Math.round(a.eta_seconds/60)} min estimados`,()=>window.DeskMap?.showRoute({...r,...a})));
}else say('REVISAR: sem rota.');o.append(evidence('Rota e fontes',r));
}catch(e){if(n===seq&&box.isConnected)say(`REVISAR: ${e.message}`);}
}}};
