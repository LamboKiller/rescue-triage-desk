'use strict';
window.DeskEvals=(()=>{
 let prov=null;const waiting=[];
 const load=fetch('/api/provenance').then(r=>r.ok?r.json():null).then(p=>{prov=p;waiting.splice(0).forEach(f=>f());}).catch(()=>{});
 const mk=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const kindOf=key=>{const rows=prov?.layers||[];const r=rows.find(x=>x.id===key)||rows.find(x=>x.map_layer===key);return r?{kind:r.kind,rule:r.rule,source:r.source}:null;};
 function fill(span,key,kind){const f=kind?{kind,rule:'',source:''}:kindOf(key),k=f&&prov.kinds[f.kind];span.className='kind-badge kind-'+(f?f.kind:'none');span.textContent=k?k.label_pt:'sem rótulo';span.title=f?`${k.label_en}. ${f.source?f.source+'. ':''}${f.rule}`:'Camada sem origem declarada';}
 function badge(key,kind){const span=mk('span');span.setAttribute('data-kind-for',key||'');if(prov)fill(span,key,kind);else{span.textContent='…';waiting.push(()=>fill(span,key,kind));}return span;}
 function caseBadge(c){const text=String(c?.text||c?.message||c?.facts?.[0]?.text||'');const sim=c?.synthetic||c?.simulated||text.trimStart().startsWith('[SIMULADO]');const s=badge('messages',sim?'simulated':'live_equivalent');s.classList.add('case-kind');return s;}
 const pct=v=>typeof v==='number'&&v<=1?Math.round(v*1000)/10+'%':String(v);
 const when=d=>{const t=Date.parse(d);return Number.isNaN(t)?'—':new Date(t).toLocaleString('pt-BR');};
 async function render(root){
  root.replaceChildren(mk('h1','Evals · rodadas registradas'),mk('p','Valores lidos de eval/gate_last.json e eval/results*.json. Nada é recalculado aqui; ausente aparece como —.','muted'));
  let d;try{const r=await fetch('/api/evals');if(!r.ok)throw new Error('Evals indisponível');d=await r.json();}catch(e){root.append(mk('p',e.message,'danger'));return;}
  root.append(mk('p',`Commit atual ${d.head?d.head.slice(0,7):'desconhecido'} · portão ${d.gate_pass===null?'sem relatório':d.gate_pass?'verde':'vermelho'} · obsoleto = mais de ${d.stale_hours} h ou outro commit.`,'muted'));
  if(d.rows.some(r=>r.stale))root.append(mk('p','Evals desatualizados para este commit','eval-warn'));
  if(!d.rows.length){root.append(mk('p','Nenhuma rodada registrada. Rode: python tools/gate.py --fast','muted'));return;}
  const t=mk('table',undefined,'evals-table'),h=mk('tr');for(const x of ['Avaliação','Métrica','Valor','Modo','Data','Commit','Estado','Reproduzir'])h.append(mk('th',x));const th=mk('thead');th.append(h);t.append(th);
  const b=mk('tbody');t.append(b);
  for(const r of d.rows){const tr=mk('tr',undefined,r.stale?'eval-stale':'');const v=r.value===null||r.value===undefined?'—':(typeof r.value==='number'&&r.value<=1?pct(r.value):String(r.value))+(r.of?` / ${r.of}`:'');
   const state=mk('td',(r.stale?'obsoleto: '+r.stale_reasons.join('; '):'atual')+(r.passed===false?' · reprovou':''));state.title=r.date_note||'';
   const cmd=mk('td');cmd.append(mk('code',r.command||'—'));
   tr.append(mk('td',r.id),mk('td',r.metric),mk('td',v),mk('td',r.mode||'—'),mk('td',when(r.date)),mk('td',r.commit?r.commit.slice(0,7):'—'),state,cmd);b.append(tr);}
  root.append(t);
 }
 return {badge,caseBadge,render,ready:load};
})();
