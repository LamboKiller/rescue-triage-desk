'use strict';
(()=>{
const ST={pending_verification:'Aguardando verificação',available:'Verificado · disponível',rejected:'Rejeitado'};
const FD=[['asset_type','Tipo'],['capacity','Lugares'],['motor','Motor'],['base_place','Cidade'],['base_detail','Local'],['availability','Janela'],['crew_size','Equipe'],['pets_ok','Pets'],['night_ok','Noite']];
const sh=x=>x===true?'sim':x===false?'não':x&&typeof x==='object'?(x.kind==='remo'?'remo':'motor '+(x.hp||'')+' hp'):String(x);
function card(v,x,reload,who){
const {el,button,notice,api}=x,c=el('article',undefined,'mission-card'),dl=el('dl');
c.append(el('h4',`${v.label_pt}${v.id} · ${ST[v.status]}${v.merged_into?' · fundida em '+v.merged_into:''}`),(()=>{const p=el('p',v.text,'muted');p.dataset.evidence='1';return p;})());
for(const [k,n] of FD){const f=v.fields[k];if(f)dl.append(el('dt',n),el('dd',`${sh(f.value)} — “${f.quote}” · ${f.source}`));}
c.append(dl,el('small',`Contato: ${v.contact.present||'não informado'} (só hash) · Extração: ${v.extraction.label_pt||v.extraction.method}`));
for(const w of v.warnings)c.append(el('p','⚠ '+w.text_pt,w.code==='SYNTHETIC'?'muted':'danger'));
for(const p of v.merge_proposals)c.append(el('p',`Duplicata de ${p.with}? ${p.reason_pt}`,'muted'));
const act=async(n,b)=>{try{await api(`/api/volunteers/${v.id}/${n}`,{actor:who(),...b});await reload();}catch(e){notice(e.message,true);}};
if(v.status==='pending_verification'){
const row=el('div',undefined,'row'),m=el('select'),t=el('select'),ask=v.fields.asset_type?.value==='desconhecido';
for(const [k,s] of [['ligacao','Liguei'],['visto','Vi o barco'],['video','Vi foto/vídeo']])m.append(new Option(s,k));
for(const k of ['barco_aluminio','bote_inflavel','jet_ski','caminhao_alto'])t.append(new Option(k,k));
row.append(m);if(ask)row.append(t);
row.append(button('Verificar → disponível',()=>act('verify',{method:m.value,...(ask?{type:t.value}:{})})),button('Rejeitar',()=>{const r=prompt('Motivo da rejeição');if(r&&r.trim())act('reject',{reason:r.trim()});}));
const p=v.merge_proposals[0];if(p&&!v.merged_into)row.append(button('Fundir com '+p.with,()=>act('merge',{into:p.with})));
if(v.merged_into)row.append(button('Desfazer',()=>act('unmerge',{})));
c.append(row);
}else c.append(el('p',v.status==='rejected'?`Motivo: ${v.rejection.reason} (${v.rejection.actor})`:`Verificado por ${v.verification.actor} (${v.verification.method}) · ${v.unit_id}`));
return c;}
async function panel(d,x){
const {el,api}=x,box=el('section'),who=el('input'),body=el('div');
who.placeholder='Operador';
box.append(el('h3','Voluntários'),el('p','Oferta ≠ meio disponível até um operador verificar.','muted'),who,body);d.append(box);
const reload=async()=>{try{const r=await api('/api/volunteers');body.replaceChildren();
for(const s in ST){const l=r.volunteers.filter(v=>v.status===s);if(l.length)body.append(el('h4',`${ST[s]} (${l.length})`),...l.map(v=>card(v,x,reload,()=>who.value.trim()||'operador')));}
}catch(e){body.replaceChildren(el('p',e.message,'danger'));}};
await reload();}
const f=window.DeskFleet;
if(f&&!f.vw){const o=f.resources;f.vw=1;f.resources=async x=>{await o(x);const d=[...document.querySelectorAll('dialog')].pop();if(d)await panel(d,x);};}
})();
