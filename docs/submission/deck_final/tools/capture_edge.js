// Headless Edge renderer: `node capture_edge.js logos` renders white logo PNGs; `node capture_edge.js` renders slide PNGs,
// layout checks and the PDF. Fresh profile under scratch/deck6prof, CDP port 9512; the Edge process tree is killed at the end.
const {spawn, execFileSync} = require('child_process'), fs = require('fs');
const D = require('path').resolve(__dirname, '..').split(String.fromCharCode(92)).join('/');
const PROF = require('path').join(require('os').tmpdir(), 'deck6prof', 'p' + Date.now()).split(String.fromCharCode(92)).join('/');
const PORT = 9512;
const p = spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', ['--headless=new', '--disable-extensions',
  '--disable-background-networking', '--remote-debugging-port=' + PORT, '--user-data-dir=' + PROF, '--no-first-run',
  '--disable-gpu', '--hide-scrollbars', 'about:blank'], {stdio: 'ignore', windowsHide: true});
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  let target;
  for (let i = 0; i < 240; i++) { try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find(t => t.type === 'page'); if (target) break; } catch {} await sleep(300); }
  const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise(r => ws.onopen = r);
  let id = 0, pend = {}; ws.onmessage = m => { const d = JSON.parse(m.data); if (d.id) { pend[d.id](d); delete pend[d.id]; } };
  const c = async (method, params = {}) => { const r = await new Promise(r => { const n = ++id; pend[n] = r; ws.send(JSON.stringify({id: n, method, params})); }); if (r.error) throw Error(method + JSON.stringify(r.error)); return r.result; };
  const ev = async expression => (await c('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true})).result.value;
  await c('Page.enable'); await c('Runtime.enable');
  await c('Emulation.setDeviceMetricsOverride', {width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false});
  if (process.argv.includes('logos')) {
    await c('Emulation.setDefaultBackgroundColorOverride', {color: {r: 0, g: 0, b: 0, a: 0}});
    for (const [name, file, w] of [['nvidia', 'nvidia.svg', 1600], ['zetaris', 'zetaris.svg', 1400]]) {
      const html = `<html><body style="margin:0;background:transparent"><img src="file:///${D}/assets/logos/${file}" style="width:${w}px;filter:brightness(0) invert(1)"></body></html>`;
      fs.writeFileSync(D + '/tmp_logo.html', html);
      await c('Page.navigate', {url: 'file:///' + D + '/tmp_logo.html'}); await sleep(800);
      const s = await c('Page.captureScreenshot', {format: 'png', captureBeyondViewport: false});
      fs.writeFileSync(D + `/assets/logos/${name}_white_raw.png`, Buffer.from(s.data, 'base64'));
    }
    fs.unlinkSync(D + '/tmp_logo.html');
  } else {
    await c('Page.navigate', {url: 'file:///' + D + '/deck.html?clean#1'}); await sleep(1200);
    await ev(`Promise.all([...document.images].map(i=>i.decode().catch(()=>{}))).then(()=>document.fonts.ready).then(()=>true)`);
    const fonts = await ev(`[...document.fonts].filter(f=>f.status==='loaded').map(f=>f.family+' '+f.weight)`);
    const count = await ev(`document.querySelectorAll('.slide').length`);
    const checks = [];
    for (let n = 1; n <= count; n++) {
      await ev(`window.goSlide(${n - 1})`); await sleep(250);
      const s = await c('Page.captureScreenshot', {format: 'png'});
      fs.writeFileSync(D + '/slide_' + String(n).padStart(2, '0') + '.png', Buffer.from(s.data, 'base64'));
      checks.push(await ev(`(()=>{const s=document.querySelector('.slide.active'),r=s.getBoundingClientRect();
        const out=[...s.querySelectorAll('.t,.img,.shape')].filter(e=>{const b=e.getBoundingClientRect();return b.width&&(b.right>r.right+1||b.bottom>r.bottom+1||b.left<r.left-1||b.top<r.top-1)}).map(e=>e.dataset.k);
        const clipped=[...s.querySelectorAll('.t')].filter(e=>e.scrollWidth>e.clientWidth+2||e.scrollHeight>e.clientHeight+2).map(e=>({k:e.dataset.k,sw:e.scrollWidth,cw:e.clientWidth,sh:e.scrollHeight,ch:e.clientHeight}));
        const broken=[...s.querySelectorAll('img')].filter(i=>!i.complete||!i.naturalWidth).map(i=>i.src);
        return {id:s.id,out,clipped,broken};})()`));
    }
    fs.writeFileSync(D + '/tools/validation.json', JSON.stringify({fonts, checks}, null, 1));
    console.log(JSON.stringify({fonts, checks}));
    const pdf = await c('Page.printToPDF', {printBackground: true, preferCSSPageSize: true, marginTop: 0, marginBottom: 0, marginLeft: 0, marginRight: 0});
    fs.writeFileSync(D + '/deck.pdf', Buffer.from(pdf.data, 'base64'));
  }
  ws.close();
})().catch(e => { console.error(e); process.exitCode = 1; }).finally(() => {
  try { execFileSync('taskkill', ['/F', '/T', '/PID', String(p.pid)], {stdio: 'ignore', timeout: 10000, windowsHide: true}); } catch {}
});
