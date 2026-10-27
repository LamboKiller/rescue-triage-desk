import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import {spawn} from 'node:child_process';import {once} from 'node:events';
import {launch,close,sleep} from './cdp.mjs';import {validate} from './validate.mjs';
const input=process.argv[2]||'out/video/final/timeline.json',T=JSON.parse(fs.readFileSync(input,'utf8'));console.log(validate(T));
const root=process.cwd(),types={'.html':'text/html','.json':'application/json','.jpg':'image/jpeg','.png':'image/png','.woff2':'font/woff2','.ttf':'font/ttf'};
const server=http.createServer((req,res)=>{let pathname=decodeURIComponent(new URL(req.url,'http://local').pathname),p=path.resolve(root,'.'+pathname);if(!p.startsWith(root+path.sep)||!['tools/video/','out/video/'].some(x=>pathname.slice(1).startsWith(x))){res.writeHead(403);res.end();return}fs.stat(p,(e,st)=>{if(e||!st.isFile()){res.writeHead(404);res.end();return}res.writeHead(200,{'Content-Type':types[path.extname(p)]||'application/octet-stream','Cache-Control':'no-store'});fs.createReadStream(p).pipe(res)})});
await new Promise(r=>server.listen(Number(process.env.RHTTP||9348),'127.0.0.1',r));
const arg=Object.fromEntries(process.argv.slice(3).map((x,i,a)=>x.startsWith('--')?[x.slice(2),a[i+1]]:null).filter(Boolean));
const start=Number(arg.start||0),stop=Number(arg.end||T.duration),fps=60,frames=Math.round((stop-start)*fps),out=arg.out||'out/video/final/picture-v0.mp4';fs.mkdirSync(path.dirname(out),{recursive:true});
let b,encoder,log='';
try{
 b=await launch(Number(process.env.RCDP||9342),`http://127.0.0.1:${process.env.RHTTP||9348}/tools/video/compositor/index.html?timeline=/${input.replaceAll('\\','/')}`,true);
 await b.cdp.send('Emulation.setDeviceMetricsOverride',{width:1920,height:1080,deviceScaleFactor:1,mobile:false});
 for(let n=0;n<150;n++){if(await b.cdp.evaluate('typeof window.__seek === "function"'))break;if(n===149)throw Error('Compositor did not load');await sleep(100)}
 await b.cdp.evaluate('window.__ready');
 if(arg.shot!==undefined){let t=Number(arg.shot);await b.cdp.evaluate(`window.__seek(${t})`);let r=await b.cdp.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(out,Buffer.from(r.data,'base64'));console.log('Still',t,out);}
 else{
 let codec=arg.draft?['-c:v','h264_nvenc','-preset','p7','-rc','vbr','-cq','17']:['-c:v','libx264','-preset','slow','-crf','16','-threads','4'];
 encoder=spawn('ffmpeg',['-hide_banner','-y','-f','image2pipe','-framerate','60','-vcodec','mjpeg','-i','pipe:0','-an',...codec,'-profile:v','high','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-r','60','-fps_mode','cfr','-movflags','+faststart',out],{stdio:['pipe','ignore','pipe'],windowsHide:true});
 encoder.stderr.on('data',d=>{log+=d;fs.appendFileSync(out+'.ffmpeg.log',d)});let exit=once(encoder,'exit');
 for(let f=0;f<frames;f++){
  await b.cdp.evaluate(`window.__seek(${(start+f/60).toFixed(8)})`);
  let r=await b.cdp.send('Page.captureScreenshot',{format:'jpeg',quality:96,captureBeyondViewport:false,fromSurface:true,optimizeForSpeed:true});
  if(!encoder.stdin.write(Buffer.from(r.data,'base64')))await once(encoder.stdin,'drain');
  if(f%30===0){let p={frame:f,total:frames,t:start+f/60,at:new Date().toISOString()};fs.writeFileSync(out+'.progress.json',JSON.stringify(p));console.log(JSON.stringify(p));}
 }
 encoder.stdin.end();let [code]=await exit;fs.writeFileSync(out+'.ffmpeg.log',log);if(code!==0)throw Error('Encoder failed '+log.slice(-1500));
 }
}finally{if(b)await close(b);server.close();}
