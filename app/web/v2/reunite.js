'use strict';
globalThis.DeskReunite = (() => {
 const CONF={alta:'evidência forte',média:'evidência média',baixa:'evidência fraca'};
 function person(el,title,r){
  const box=el('div',undefined,'memory-entry');
  box.append(el('strong',title),el('p',`Nomes: ${r.names.join(', ')||'—'} · Idades: ${r.ages.join(', ')||'—'}`),el('p',`“${r.quote}”`,'muted'),el('small',`${r.source}${r.case_id?' · caso '+r.case_id:''} · ${r.at||''}`));
  return box;
 }
 async function open({api,el,button,notice,refresh}) {
  const dialog=el('dialog',undefined,'memory-panel'),content=el('div'),actor=el('input');
  actor.placeholder='Nome do operador';actor.maxLength=120;
  dialog.append(el('h2','Reencontro'),button('Fechar',()=>dialog.close()),el('p','Pares candidatos por dados escritos nas mensagens. Nada é confirmado automaticamente: uma pessoa decide. Telefones e complementos de endereço são ocultados.'),actor,content);
  document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
  async function decide(c,action){
   if(!actor.value.trim()){notice('Informe o operador.',true);return;}
   try{await api('/api/reunite',{pair_id:c.id,action,actor:actor.value.trim(),at:(window.DeskReplay?window.DeskReplay.iso():document.getElementById('date').value+'T23:59:59-03:00')});notice(action==='confirm'?'Reencontro confirmado; nota registrada nos dois casos.':'Par rejeitado.');await load();await refresh?.();}
   catch(error){notice(error.message,true);}
  }
  async function load(){
   const data=await api('/api/reunite?at='+encodeURIComponent((window.DeskReplay?window.DeskReplay.iso():document.getElementById('date').value+'T23:59:59-03:00')));content.replaceChildren(el('small',`Buscas: ${data.counts.missing} · Registros de resgate/abrigo: ${data.counts.found}`));
   if(!data.candidates.length)content.append(el('p','Nenhum par candidato.'));
   for(const c of data.candidates){
    const card=el('article',undefined,'memory-entry');
    card.append(el('h3',`Candidato · ${CONF[c.confidence]} · pontos ${c.score}`),person(el,'Pedido de notícias',c.missing),person(el,'Resgatado / abrigado',c.found));
    const ul=el('ul');for(const e of c.evidence)ul.append(el('li',`${e.label_pt}: ${e.detail}`));
    card.append(ul,el('p',c.notice_pt,'muted'),button('Confirmar reencontro',()=>decide(c,'confirm')),button('Rejeitar',()=>decide(c,'reject')));
    content.append(card);
   }
   if(data.decisions.length){content.append(el('h3','Decisões'));for(const d of data.decisions)content.append(el('p',`${d.action==='confirm'?'Confirmado':'Rejeitado'} por ${d.actor} · ${d.at}`));}
  }
  try{await load();}catch(error){content.append(el('p',error.message,'danger'));}
 }
 async function notes(root,cid,{api,el}){
  try{const data=await api('/api/reunite/notes?case_id='+encodeURIComponent(cid));if(!root.isConnected)return;
   for(const n of data.notes)root.append(el('p',n.note_pt),el('small',n.at+' · '+n.pair_id));
   if(!data.notes.length)root.append(el('p','Nenhum reencontro confirmado para este caso.'));
  }catch(e){if(root.isConnected)root.append(el('p',e.message,'danger'));}
 }
 return {open,notes};
})();
document.addEventListener('DOMContentLoaded',()=>{
 document.querySelector('.status-bar').append(button('Reencontro',()=>DeskReunite.open({api,el,button,notice,refresh})));
});
