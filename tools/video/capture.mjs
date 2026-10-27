import fs from 'node:fs';
import {spawn} from 'node:child_process';
import {launch,connect,close,sleep,S} from './compositor/cdp.mjs';
let args=Object.fromEntries(process.argv.slice(2).map((x,i,a)=>x.startsWith('--')?[x.slice(2),a[i+1]]:null).filter(Boolean));
let b,c;
if(args.launch){b=await launch(9341,args.url||'http://127.0.0.1:8096/v2/?lang=pt');c=b.cdp;}else c=await connect(9341);
if(args.inspect){console.log(JSON.stringify(await c.evaluate('({x:screenX,y:screenY,ow:outerWidth,oh:outerHeight,iw:innerWidth,ih:innerHeight,dpr:devicePixelRatio,title:document.title,body:document.body.innerText.slice(0,1500)})'),null,2));c.close();process.exit()}
if(args.launch){
 await sleep(2500);
 let w=await c.send('Browser.getWindowForTarget');
 let m=await c.evaluate('({x:screenX,y:screenY,ow:outerWidth,oh:outerHeight,iw:innerWidth,ih:innerHeight})');
 await c.send('Browser.setWindowBounds',{windowId:w.windowId,bounds:{left:1920-Math.round((m.ow-m.iw)/2),top:-Math.round(m.oh-m.ih-(m.ow-m.iw)/2),width:1920+m.ow-m.iw,height:1080+m.oh-m.ih,windowState:'normal'}});
 await sleep(1000);
 console.log(JSON.stringify({pid:b.proc.pid,profile:b.profile,window:await c.send('Browser.getWindowForTarget'),client:await c.evaluate('({x:screenX,y:screenY,ow:outerWidth,oh:outerHeight,iw:innerWidth,ih:innerHeight,dpr:devicePixelRatio})')}));
 await c.send('Page.bringToFront');
 console.log('Capture Edge stays open until this process is stopped.');
 process.on('SIGINT',async()=>{await close(b);process.exit()});
 await sleep(4*3600000);await close(b);process.exit();
}
const spec=JSON.parse(fs.readFileSync(args.spec,'utf8'));
await c.send('Emulation.setFocusEmulationEnabled',{enabled:true});await c.send('Page.bringToFront');
fs.mkdirSync('out/video/raw',{recursive:true});let out=`out/video/raw/${spec.name}.mp4`;
let marks=[],zero=null,fflog='';
const ff=spawn('ffmpeg',['-hide_banner','-y','-thread_queue_size','8','-f','gdigrab','-framerate',String(spec.fps||60),'-offset_x','1920','-offset_y','0','-video_size','1920x1080','-draw_mouse','0','-i','desktop','-an','-filter_threads','2','-c:v','h264_nvenc','-preset','p7','-tune','hq','-rc','constqp','-qp','14','-pix_fmt','yuv420p','-r',String(spec.fps||60),out],{stdio:['pipe','ignore','pipe'],windowsHide:true});
let readyResolve;let ready=new Promise(r=>readyResolve=r);
ff.stderr.on('data',d=>{fflog+=d; if(zero===null && /frame=\s*[1-9]/.test(fflog)){let epoch=/Duration: N\/A, start: ([\d.]+)/.exec(fflog);zero=epoch?performance.now()-(Date.now()/1000-Number(epoch[1]))*1000:performance.now();readyResolve();}});
let exited=new Promise(r=>ff.on('exit',r));
await Promise.race([ready,sleep(12000).then(()=>{if(zero===null)throw Error('Capture did not start '+fflog.slice(-1200))})]);
function mark(name,extra={}){marks.push({name,t:(performance.now()-zero)/1000,...extra});}
const click=async (sel,text)=>{
 let box=await c.evaluate(`(()=>{let e=${text?`[...document.querySelectorAll(${JSON.stringify(sel)})].find(e=>e.textContent.includes(${JSON.stringify(text)}))`:`document.querySelector(${JSON.stringify(sel)})`};if(!e)return null;e.scrollIntoView({block:'nearest'});let r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,text:e.textContent.slice(0,100)}})()`);
 if(!box)throw Error('Missing '+sel+' '+text);mark('click',{box});
 let xy={x:box.x+box.w/2,y:box.y+box.h/2};for(let type of ['mousePressed','mouseReleased'])await c.send('Input.dispatchMouseEvent',{type,...xy,button:'left',clickCount:1});
};
try{
 for(let a of spec.actions){
   mark(a.name||a.do);console.log(a.do,a.name||'');
   if(a.do==='wait')await sleep(a.ms);
   if(a.do==='eval')console.log(JSON.stringify(await c.evaluate(a.expr))??'');
   if(a.do==='click')await click(a.selector,a.text);
   if(a.do==='hover'){let box=await c.evaluate(`(()=>{let r=document.querySelector(${JSON.stringify(a.selector)}).getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()`);mark('hover',{box});await c.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:box.x+box.w/2,y:box.y+box.h/2});}
   if(a.do==='run'){
     let log=fs.openSync(`out/video/raw/${spec.name}-${marks.length}.log`,'w');
     let p=spawn('timeout',['240s','python',...a.args],{env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'},stdio:['ignore',log,log],windowsHide:true});
     let seen='',busy=false;let timer;
     if(a.followRun)timer=setInterval(async()=>{if(busy)return;busy=true;try{let info=JSON.parse(fs.readFileSync(a.followRun,'utf8'));if(info.run_id!==seen&&Date.now()/1000-info.wall<240){seen=info.run_id;await c.evaluate(`window.__videoRun=awaitRun(${JSON.stringify({run_id:info.run_id})});window.__videoRun.catch(()=>{});'Attached native SSE to real run'`);mark('sse_attached',{run_id:info.run_id});}}catch{}finally{busy=false}},250);
     let code=await new Promise(r=>p.on('exit',r));if(timer)clearInterval(timer);fs.closeSync(log);mark('run_end',{code});
   }
   if(a.do==='navigate'){await c.send('Page.navigate',{url:a.url});await sleep(3000)}
 }
}finally{
 mark('end');ff.stdin.write('q');await exited;fs.writeFileSync(out.replace('.mp4','.marks.json'),JSON.stringify({fps:spec.fps||60,firstFrameClock:zero,marks},null,2));fs.writeFileSync(out.replace('.mp4','.ffmpeg.log'),fflog);c.close();
}
