'use strict';
// N4 "Passagem de turno": skeleton first (deterministic), model summary only on demand; textContent only.
(() => {
 const el=(t,x,c)=>{const n=document.createElement(t);if(x!==undefined)n.textContent=x;if(c)n.className=c;return n;};
 const call=async(path,body)=>{const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
  const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||('Falha '+r.status));return d;};
 function render(box,data,sk){
  box.replaceChildren();
  const s=data.summary;
  if(s){box.append(el('p',s.label_pt,s.status==='model'?'handover-model':'handover-fallback'));
   if(data.handover_id)box.append(el('small','Registrado: '+data.handover_id+' · '+data.actor));
   for(const x of s.sentences||[])box.append(el('p',x.text+' ['+x.cites.join(', ')+']'));}
  for(const sec of sk.sections){
   const d=el('details');d.open=sec.count>0&&!sec.unavailable_pt;
   d.append(el('summary',sec.title_pt+' · '+sec.count));
   if(sec.unavailable_pt)d.append(el('p',sec.unavailable_pt));
   for(const i of sec.items)d.append(el('p',i.text_pt+' ['+i.id+']'));
   if(sec.truncated)d.append(el('p','… mostrando os primeiros '+sec.items.length+' de '+sec.count));
   box.append(d);}
  box.append(el('small',sk.clock_note_pt+' Replay: '+sk.now));
 }
 async function open(){
  const day=document.getElementById('date').value,dlg=el('dialog',undefined,'handover-panel'),box=el('div');
  const close=el('button','Fechar');close.type='button';close.onclick=()=>dlg.close();
  const actor=el('input');actor.placeholder='Operador que passa o turno';actor.maxLength=80;
  const save=el('button','Registrar passagem');save.type='button';
  const sum=el('button','Registrar com resumo do modelo');sum.type='button';
  dlg.append(el('h2','Passagem de turno'),close,actor,save,sum,box);
  document.body.append(dlg);dlg.addEventListener('close',()=>dlg.remove(),{once:true});dlg.showModal();
  let sk;try{sk=await call('/api/handover?date='+day);render(box,{},sk);}catch(e){box.append(el('p',e.message));return;}
  const go=async summary=>{save.disabled=sum.disabled=true;box.prepend(el('p',summary?'Gerando resumo (pode levar 1-2 min)…':'Registrando…'));
   try{const d=await call('/api/handover',{date:day,replay_time:sk.now,summary,actor:actor.value||'operador'});render(box,d,d.skeleton);}
   catch(e){box.prepend(el('p',e.message));}finally{save.disabled=sum.disabled=false;}};
  save.onclick=()=>go(false);sum.onclick=()=>go(true);
 }
 const b=el('button','Passagem de turno');b.type='button';b.id='handover';b.onclick=open;
 const anchor=document.getElementById('resources');if(anchor)anchor.before(b);
})();
