'use strict';
// Nova emergência + Importar lote: both go through the real intake queue (POST /api/intake) and show each message's
// state (em fila / analisando / pronto / falhou) until the case is in the desk queue.
(()=>{
  const $=id=>document.getElementById(id),dlg=$('new-dialog');
  if(!dlg||!window.DeskApp)return;
  const A=window.DeskApp,{api}={api:async(p,b)=>{const r=await fetch(p,b===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});let d;try{d=await r.json();}catch{throw new Error(`Resposta inválida (${r.status})`);}if(!r.ok)throw new Error(d.error||`Falha ${r.status}`);return d;}};
  const mk=(t,txt,cls,attrs)=>{const n=document.createElement(t);if(txt!==undefined)n.textContent=txt;if(cls)n.className=cls;for(const [k,v] of Object.entries(attrs||{}))n.setAttribute(k,v);return n;};
  const CHANNELS=['WhatsApp','Telefone (193/190/199)','Rádio','Redes sociais','Presencial / equipe em campo'];
  const EXAMPLE=['Rua Voluntários da Pátria 1250, Navegantes: 4 pessoas no segundo andar, água subindo, 2 crianças','Av. Mathias Velho 500, Canoas: idosa acamada sozinha, sem energia, água na cintura','Rua Sertório 300, Porto Alegre: família de 5 presa no telhado, precisamos de barco','Cachorro e gato presos no térreo da Rua Farrapos 88, moradores já saíram','Estrada do Conde 40, Eldorado do Sul: 3 pessoas ilhadas, uma gestante','Rua da República 700: ninguém atende desde ontem, vizinho ouviu gritos'];
  const form=$('request-form');form.replaceChildren();
  const head=mk('div',undefined,'row spread'),close=mk('button','×',undefined,{type:'button','aria-label':'Fechar',id:'close-dialog'});close.onclick=()=>dlg.close();
  head.append(mk('h2','Nova emergência'),close);
  const tabs=mk('div',undefined,'in-tabs'),t1=mk('button','Uma mensagem',undefined,{type:'button',id:'single-tab','aria-pressed':'true'}),t2=mk('button','Importar lote',undefined,{type:'button',id:'batch-tab','aria-pressed':'false'});tabs.append(t1,t2);
  // single
  const single=mk('div',undefined,'in-pane');
  const txt=mk('textarea',undefined,undefined,{id:'request-text',required:'',maxlength:'12000',rows:'5',placeholder:'Cole ou digite a mensagem recebida: endereço, quantas pessoas, situação da água…'});
  const lbl=(t,f)=>mk('label',t,undefined,{for:f});
  const ch=mk('select',undefined,undefined,{id:'request-channel'});for(const c of CHANNELS)ch.append(mk('option',c));
  const when=mk('input',undefined,undefined,{id:'received',type:'datetime-local',required:''});
  const pin=mk('button','📍 Marcar ponto no mapa (opcional)',undefined,{type:'button',id:'pick-point'}),pinOut=mk('span',undefined,'muted',{id:'pin-out'});
  const pinClear=mk('button','limpar',undefined,{type:'button'});pinClear.hidden=true;
  const row=mk('div',undefined,'in-row');row.append(mk('div'),mk('div'),mk('div'));
  row.children[0].append(lbl('Canal','request-channel'),ch);row.children[1].append(lbl('Recebida em (BRT)','received'),when);row.children[2].append(lbl('Ponto no mapa','pick-point'),pin,pinOut,pinClear);
  single.append(lbl('Mensagem','request-text'),txt,row);
  // batch
  const batch=mk('div',undefined,'in-pane');batch.hidden=true;
  const bt=mk('textarea',undefined,undefined,{id:'batch-text',rows:'8',placeholder:'Uma mensagem por linha. Linhas vazias são ignoradas.'});
  const bcount=mk('small','0 mensagens',undefined,{id:'batch-count'}),ex=mk('button','Preencher exemplo',undefined,{type:'button',id:'batch-example'});
  ex.onclick=()=>{bt.value=EXAMPLE.join('\n');bt.dispatchEvent(new Event('input'));};
  const lines=()=>bt.value.split('\n').map(s=>s.trim()).filter(Boolean);
  bt.oninput=()=>{const n=lines().length;bcount.textContent=`${n} mensagen${n===1?'':'s'}${n>200?' (máximo 200)':''}`;};
  batch.append(lbl('Mensagens (uma por linha)','batch-text'),bt,mk('div',undefined,'row spread'));batch.lastChild.append(bcount,ex);
  const foot=mk('div',undefined,'row spread'),hint=mk('span','Entra na fila e é analisada pelas regras (modo amostra) ou pelos agentes (ao vivo).','muted');
  const go=mk('button','Enviar para a fila','primary',{id:'submit-request',type:'submit'}),goB=mk('button','Enviar lote','primary',{id:'submit-batch',type:'button'});goB.hidden=true;
  foot.append(hint,go,goB);
  const status=mk('div',undefined,'in-status',{id:'intake-status','aria-live':'polite'});
  form.append(head,tabs,single,batch,foot,status);
  const old=$('run-stages');if(old)old.hidden=true;
  function mode(b){t1.setAttribute('aria-pressed',String(!b));t2.setAttribute('aria-pressed',String(b));single.hidden=b;batch.hidden=!b;go.hidden=b;goB.hidden=!b;txt.required=!b;}
  t1.onclick=()=>mode(false);t2.onclick=()=>mode(true);
  // map point
  let point=null;
  pin.onclick=()=>{const gl=window.DeskMap?.telemetrySurface?.().gl;if(!gl){pinOut.textContent='mapa 3D indisponível neste navegador';return;}
    dlg.close();A.S.picking=true;const note=A.S.pickNote=mk('div','Clique no mapa para marcar o local da emergência (Esc cancela)','undo-toast');document.body.append(note);
    const done=ll=>{note.remove();A.S.picking=false;if(ll){point=[+ll.lat.toFixed(5),+ll.lng.toFixed(5)];pinOut.textContent=`${point[0]}, ${point[1]}`;pinClear.hidden=false;}dlg.showModal();};
    gl.once('click',e=>done(e.lngLat));document.addEventListener('keydown',function k(e){if(e.key==='Escape'&&A.S.picking){document.removeEventListener('keydown',k);gl.off('click',()=>{});done(null);}},{once:true});};
  pinClear.onclick=()=>{point=null;pinOut.textContent='';pinClear.hidden=true;};
  // open dialog: default time = replay clock
  const clockLocal=()=>{const iso=window.DeskReplay?.iso()||$('date').value+'T12:00:00-03:00';return iso.slice(0,16);};
  $('new-request').onclick=()=>{when.value=clockLocal();status.replaceChildren();dlg.showModal();(single.hidden?bt:txt).focus();};
  // submit
  const channelId=()=>CHANNELS[ch.selectedIndex].split(' ')[0].toLowerCase();
  const stamp=()=>Date.now().toString(36);
  async function send(texts,kind){
    const received=`${when.value}:00-03:00`,clock=window.DeskReplay?.iso()||received,replay=Date.parse(clock)>=Date.parse(received)?clock:received;
    const batchId=stamp();
    const messages=texts.map((t,i)=>({text:t,received_at:received,message_id:`ui-${channelId()}-${batchId}-${i}`}));
    status.replaceChildren(mk('p','Enviando…'));
    const r=await api('/api/intake',{replay_time:replay,messages});
    track(r.messages,kind);return r;
  }
  function track(acks,kind){
    const ids=acks.map(a=>a.message_id),state=new Map(acks.map(a=>[a.message_id,a])),line=mk('p'),list=mk('ul'),open=mk('button','Abrir primeiro caso',undefined,{type:'button',id:'open-first'});open.hidden=true;
    status.replaceChildren(line,list,open);let stop=false,refreshed=0;
    const label={queued:'em fila',running:'analisando',final:'pronto',failed:'falhou'};
    const draw=()=>{const c={queued:0,running:0,final:0,failed:0};for(const a of state.values())c[a.state]=(c[a.state]||0)+1;
      line.textContent=`${state.size} enviada${state.size>1?'s':''} · ${c.queued} em fila · ${c.running} analisando · ${c.final} pronta${c.final===1?'':'s'}${c.failed?` · ${c.failed} falhou`:''}`;
      list.replaceChildren(...[...state.values()].slice(0,8).map(a=>{const li=mk('li',`${label[a.state]||a.state}${a.state==='queued'&&a.position?` (posição ${a.position})`:''}${a.duplicate_of?' · possível duplicata':''}${a.state==='failed'?' · '+(a.error||''):''}`);
        if(a.priority?.level)li.prepend(mk('b',a.priority.level+' ')); return li;}));
      if(c.final){open.hidden=false;open.onclick=()=>{const f=[...state.values()].find(a=>a.state==='final');dlg.close();A.select(f.case_id);};}
      return c.queued+c.running===0;};
    draw();
    const loop=async()=>{
      while(!stop&&dlg.isConnected){
        await new Promise(r=>setTimeout(r,1200));
        const part=ids.slice(0,40);
        await Promise.all(part.map(async id=>{try{const s=await api('/api/queue/'+encodeURIComponent(id));state.set(id,{...state.get(id),...s});}catch{}}));
        const fin=draw();
        if(Date.now()-refreshed>3000||fin){refreshed=Date.now();A.refresh().then(()=>A.mapRefresh()).catch(()=>{});}
        if(fin){line.textContent+=' — concluído';stop=true;break;}
      }
    };loop();
  }
  form.onsubmit=async e=>{e.preventDefault();go.disabled=true;try{
    let text=txt.value.trim();if(!text)throw new Error('Escreva a mensagem.');
    if(point)text+=`\nPonto marcado no mapa: ${point[0]}, ${point[1]}.`;
    if(!when.value)throw new Error('Informe a hora de recebimento.');
    await send([text],'single');txt.value='';}catch(err){status.replaceChildren(mk('p',err.message,'danger'));}finally{go.disabled=false;}};
  goB.onclick=async()=>{goB.disabled=true;try{const L=lines();if(!L.length)throw new Error('Cole pelo menos uma linha.');if(L.length>200)throw new Error('Máximo de 200 linhas por lote.');if(!when.value)throw new Error('Informe a hora.');await send(L,'batch');}catch(err){status.replaceChildren(mk('p',err.message,'danger'));}finally{goB.disabled=false;}};
  bt.oninput();
})();
