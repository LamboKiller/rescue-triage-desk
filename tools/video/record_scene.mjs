// Scene recorder: Edge/Chromium over CDP (Page.startScreencast, PNG frames) -> ffmpeg -> one mp4 per scene.
//
//   node tools/video/record_scene.mjs --spec tools/video/scenes/test_scene.json --out out/video/test_scene.mp4 [--port 9338] [--launch] [--fps 30]
//
// --launch   start a headless Edge on --port with its own throw-away profile (closed on exit). Without it, attach to an Edge you started with
//            --remote-debugging-port=PORT (e.g. the visible one Orbit drives).
// Scene spec (JSON):  {"name":"...", "width":1920, "height":1080, "base":"http://127.0.0.1:8095", "actions":[ ... ]}
// Actions (executed in order; the whole list is recorded unless the list contains startRecording/stopRecording):
//   {"do":"navigate","url":"/v2/?lang=pt"}                 absolute or relative to "base"
//   {"do":"wait","ms":1500}
//   {"do":"waitFor","selector":"#queue li","timeout":20000}  or  {"do":"waitFor","expr":"window.DeskMap","timeout":20000}
//   {"do":"click","selector":"#live-open"}                   scrolls into view, real mouse click at the element centre
//   {"do":"clickText","selector":"button","text":"Meios"}    first element matching selector whose text contains `text`
//   {"do":"type","selector":"#request-text","text":"...","delayMs":35}
//   {"do":"key","key":"Escape"}
//   {"do":"evaluate","expr":"select(S.cases[0].case_id)","ms":500}   any JS in the page (awaited)
//   {"do":"cameraPath","opts":{"duration":6000}}            DeskPhotoTour.cameraPath: 2D -> tilt to 3D (loads photocompare.js on demand)
//   {"do":"photoTour","interval":3200}                      DeskPhotoTour.start: cards fade in with leader lines
//   {"do":"run","cmd":"python","args":["tools/demo_hero.py","--live","--url","...","--only","1"],"wait":false}
//                                                           spawn a process (hero steps, surge). wait:true blocks until it exits
//   {"do":"waitRun","timeoutMs":120000}                     wait until all spawned processes exited
//   {"do":"mark","name":"callback"}                         timestamp marker -> <out>.marks.json (for captions/cuts)
//   {"do":"shot","path":"out/video/x.png"}                  single PNG
//   {"do":"startRecording"} / {"do":"stopRecording"}        explicit control (default: records the whole action list)
// Frames only arrive when the page changes; they are re-timed to constant fps from the CDP timestamps, so pauses are real time.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((a, x, i, all) => x.startsWith('--') ? [...a, [x.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : true]] : a, []));
if (!args.spec || !args.out) { console.error('usage: node record_scene.mjs --spec scene.json --out out.mp4 [--port 9338] [--launch] [--fps 30]'); process.exit(2); }
const BASE = args.base || '';
const spec = JSON.parse(fs.readFileSync(args.spec, 'utf8').replaceAll('{{base}}', BASE || 'http://127.0.0.1:8095'));   // --base overrides {{base}} in the spec
const W = spec.width || 1920, H = spec.height || 1080, FPS = Number(args.fps || spec.fps || 30), PORT = Number(args.port || 9338);
const EDGE = args.edge || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const OUT = path.resolve(args.out);
const FRAMES = OUT.replace(/\.mp4$/i, '') + '_frames';
fs.mkdirSync(path.dirname(OUT), { recursive: true });
try { fs.rmSync(FRAMES, { recursive: true, force: true, maxRetries: 5 }); } catch (e) { console.error('aviso: não limpou', FRAMES); }
fs.mkdirSync(FRAMES, { recursive: true });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const children = [];
let edge = null, profile = null;

async function launch() {
  profile = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'edge-rec-'));
  edge = spawn(EDGE, [`--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--headless=new', `--window-size=${W},${H}`, '--hide-scrollbars',
    '--no-first-run', '--no-default-browser-check', '--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--ignore-gpu-blocklist', '--mute-audio', 'about:blank'], { stdio: 'ignore' });
  for (let i = 0; i < 60; i++) { try { await fetch(`http://127.0.0.1:${PORT}/json/version`); return; } catch { await sleep(250); } }
  throw new Error('Edge não abriu a porta ' + PORT);
}

async function connect() {
  const targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
  let page = targets.find(t => t.type === 'page');
  if (!page) page = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const pending = new Map(); const listeners = new Map();
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { const { res, rej } = pending.get(m.id); pending.delete(m.id); m.error ? rej(new Error(m.error.message)) : res(m.result); }
    else if (m.method) (listeners.get(m.method) || []).forEach(f => f(m.params));
  };
  return {
    send: (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); }),
    on: (method, f) => listeners.set(method, [...(listeners.get(method) || []), f]),
    close: () => ws.close(),
  };
}

const marks = [];
let recording = false, frameNo = 0, firstTs = null;
const frames = [];   // {file, t}

async function main() {
  if (args.launch) await launch();
  const cdp = await connect();
  await cdp.send('Page.enable'); await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });
  cdp.on('Page.screencastFrame', p => {
    cdp.send('Page.screencastFrameAck', { sessionId: p.sessionId }).catch(() => {});
    if (!recording) return;
    const t = p.metadata.timestamp;
    if (firstTs === null) firstTs = t;
    const file = path.join(FRAMES, `f${String(frameNo++).padStart(6, '0')}.png`);
    fs.writeFileSync(file, Buffer.from(p.data, 'base64'));
    frames.push({ file, t: t - firstTs });
  });
  const evalJs = async expr => {
    const r = await cdp.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error('evaluate: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result.value;
  };
  const abs = u => /^https?:/.test(u) ? u : (spec.base || '').replace(/\/$/, '') + u;
  const center = async sel => evalJs(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});if(!e)return null;e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2];})()`);
  const click = async (x, y) => {
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
  };
  const start = async () => { if (recording) return; recording = true; marks.push({ name: 'start', wall: Date.now() });
    await cdp.send('Page.startScreencast', { format: 'png', maxWidth: W, maxHeight: H, everyNthFrame: 1 }); };
  const stop = async () => { if (!recording) return; await sleep(400); await cdp.send('Page.stopScreencast'); recording = false; };
  const explicit = spec.actions.some(a => a.do === 'startRecording');
  if (!explicit) await start();
  const wall0 = Date.now();
  const loadTour = `new Promise(r=>{if(window.DeskPhotoTour)return r();const s=document.createElement('script');s.src='/v2/photocompare.js';s.onload=r;document.head.append(s);})`;

  for (const [i, a] of spec.actions.entries()) {
    process.stderr.write(`[${i + 1}/${spec.actions.length}] ${a.do} ${a.url || a.selector || a.expr || a.name || a.ms || ''}\n`);
    switch (a.do) {
      case 'navigate': await cdp.send('Page.navigate', { url: abs(a.url) }); await sleep(a.settleMs ?? 1500); break;
      case 'wait': await sleep(a.ms); break;
      case 'waitFor': {
        const deadline = Date.now() + (a.timeout || 20000);
        const test = a.expr ? `!!(${a.expr})` : `!!document.querySelector(${JSON.stringify(a.selector)})`;
        while (!(await evalJs(test))) { if (Date.now() > deadline) throw new Error('waitFor timeout: ' + (a.expr || a.selector)); await sleep(250); }
        break;
      }
      case 'click': { const c = await center(a.selector); if (!c) throw new Error('click: sem ' + a.selector); await click(...c); await sleep(a.settleMs ?? 400); break; }
      case 'clickText': {
        const c = await evalJs(`(()=>{const e=[...document.querySelectorAll(${JSON.stringify(a.selector)})].find(x=>x.textContent.includes(${JSON.stringify(a.text)}));if(!e)return null;e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2];})()`);
        if (!c) throw new Error('clickText: sem ' + a.text); await click(...c); await sleep(a.settleMs ?? 400); break;
      }
      case 'type': {
        const c = await center(a.selector); if (!c) throw new Error('type: sem ' + a.selector); await click(...c);
        for (const ch of a.text) { await cdp.send('Input.insertText', { text: ch }); await sleep(a.delayMs ?? 35); } break;
      }
      case 'key': await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: a.key }); await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: a.key }); break;
      case 'evaluate': await evalJs(a.expr); if (a.ms) await sleep(a.ms); break;
      case 'cameraPath': await evalJs(loadTour); console.log('cameraPath:', await evalJs(`DeskPhotoTour.cameraPath(${JSON.stringify(a.opts || {})})`)); break;
      case 'photoTour': await evalJs(loadTour); await evalJs(`(DeskPhotoTour.start({interval:${a.interval || 3200}}).catch(console.error),true)`); break;
      case 'run': {
        const p = spawn(a.cmd, a.args || [], { stdio: ['ignore', 'inherit', 'inherit'], cwd: a.cwd || process.cwd() });
        const done = new Promise(r => p.on('exit', r)); children.push(done);
        if (a.wait) await done; break;
      }
      case 'waitRun': await Promise.race([Promise.all(children), sleep(a.timeoutMs || 120000)]); break;
      case 'mark': marks.push({ name: a.name, scene_t: frames.length ? frames.at(-1).t : (Date.now() - wall0) / 1000 }); break;
      case 'shot': { const r = await cdp.send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(a.path, Buffer.from(r.data, 'base64')); break; }
      case 'startRecording': await start(); break;
      case 'stopRecording': await stop(); break;
      default: throw new Error('ação desconhecida: ' + a.do);
    }
  }
  await stop();
  fs.writeFileSync(OUT.replace(/\.mp4$/i, '') + '.marks.json', JSON.stringify(marks, null, 1));
  cdp.close();
  console.log(`frames: ${frames.length}`);
  if (frames.length < 2) throw new Error('nenhum frame gravado');
  const lines = ['ffconcat version 1.0'];
  frames.forEach((f, i) => { const next = frames[i + 1]?.t ?? f.t + 0.5; lines.push(`file '${f.file.replace(/\\/g, '/')}'`, `duration ${Math.max(0.001, next - f.t).toFixed(4)}`); });
  lines.push(`file '${frames.at(-1).file.replace(/\\/g, '/')}'`);
  const list = path.join(FRAMES, 'list.txt'); fs.writeFileSync(list, lines.join('\n'));
  await new Promise((res, rej) => spawn(args.ffmpeg || 'ffmpeg', ['-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', list, '-vf', `fps=${FPS},scale=${W}:${H}:flags=lanczos,format=yuv420p`,
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-movflags', '+faststart', OUT]).on('exit', c => c === 0 ? res() : rej(new Error('ffmpeg exit ' + c))));
  if (!args.keepFrames) { try { fs.rmSync(FRAMES, { recursive: true, force: true, maxRetries: 5 }); } catch {} }
  console.log('ok', OUT);
}

try { await main(); } catch (e) { console.error('ERRO:', e.message); process.exitCode = 1; }
finally { if (edge) edge.kill(); if (profile) setTimeout(() => fs.rmSync(profile, { recursive: true, force: true }), 1500); setTimeout(() => process.exit(process.exitCode || 0), 2000); }
