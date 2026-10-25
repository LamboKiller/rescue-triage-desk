'use strict';
globalThis.DeskMemory = (() => {
 function trace(c,{el}) {
  const note=c.agents?.location?.memory_note;
  return note?el('p',note,'memory-provenance'):el('span');
 }
 async function open({api,el,button,notice,day}) {
  const dialog=el('dialog',undefined,'memory-panel'),content=el('div');
  dialog.append(el('h2','Memória'),button('Fechar',()=>dialog.close()),el('p','Só referências aprovadas por uma pessoa são usadas. Para usar uma aprovação feita hoje, escolha um replay de hoje ou posterior.'),content);
  document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
  async function change(entry,action) {
   if(!actor.reportValidity())return;
   try {await api('/api/memory',{id:entry.id,action,actor:actor.value});notice('Memória registrada no World Model.');await load();}
   catch(error){notice(error.message,true);}
  }
  const actor=el('input');actor.placeholder='Nome do operador';actor.maxLength=120;actor.required=true;
  const label=el('label','Operador que revisa a referência');label.append(actor);dialog.insertBefore(label,content);
  async function load(){
   // Show current decisions for review; each location read separately uses replay time.
   const data=await api('/api/memory');content.replaceChildren();
   for(const [status,title]of [['pending','Propostas pendentes'],['approved','Referências aprovadas'],['rejected','Rejeitadas'],['revoked','Revogadas']]){
    const section=el('section');section.append(el('h3',title));const rows=data.entries.filter(e=>e.status===status);
    if(!rows.length)section.append(el('p','Nenhuma referência.'));
    for(const e of rows){const row=el('article',undefined,'memory-entry');row.append(el('strong',`${e.phrase} → ${e.place_name} · ${e.city}`),el('p',`Fonte: caso ${e.evidence_case_id} · versão ${e.evidence_version} · “${e.quote}”`));
     if(e.approved_at)row.append(el('p',`Aprovado em ${e.approved_at} por ${e.approved_by} · learned`));
     if(status==='pending')row.append(button('Aprovar',()=>change(e,'approve')),button('Rejeitar',()=>change(e,'reject')));
     if(status==='approved')row.append(button('Revogar',()=>change(e,'revoke')));section.append(row);
    }content.append(section);
   }
   const cases=(await api('/api/cases')).cases.filter(c=>c.location_confirmed), form=el('form'),caseSelect=el('select'),placeSelect=el('select'),phrase=el('input');
   for(const c of cases){const o=el('option',`${c.message_id} · ${c.text.slice(0,90)}`);o.value=c.case_id;caseSelect.append(o);}
   for(const p of data.places){const o=el('option',`${p.name} · ${p.city}`);o.value=p.id;placeSelect.append(o);}
   phrase.maxLength=180;phrase.required=true;
   form.append(el('h3','Propor referência de um caso confirmado'));
   for(const [title,input]of [['Caso confirmado',caseSelect],['Local do catálogo',placeSelect],['Referência exata da mensagem',phrase]]){const l=el('label',title);l.append(input);form.append(l);}
   const quote=el('p');const update=()=>{quote.textContent=cases.find(c=>c.case_id===caseSelect.value)?.text||'Confirme a localização de um caso primeiro.';};caseSelect.onchange=update;update();form.append(quote);
   const submit=el('button','Propor para revisão');submit.type='submit';submit.disabled=!cases.length;form.append(submit);
   form.onsubmit=async event=>{event.preventDefault();submit.disabled=true;try{await api('/api/memory',{action:'propose',case_id:caseSelect.value,place_id:placeSelect.value,phrase:phrase.value});await load();}catch(error){notice(error.message,true);submit.disabled=false;}};
   content.append(form);
  }
  try{await load();}catch(error){content.append(el('p',error.message,'danger'));}
 }
 return {open,trace};
})();
document.addEventListener('DOMContentLoaded',()=>{
 const date=document.getElementById('date'),today=new Date().toISOString().slice(0,10);
 if(date.max<today)date.max=today;
 document.querySelector('.status-bar').append(button('Memória',()=>DeskMemory.open({api,el,button,notice,day:date.value})));
});
