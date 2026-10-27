// v5 deterministic renderer: seek(t) -> screenshot -> ffmpeg.  usage:
//   RHTTP=9346 RCDP=9347 node render4.mjs [timeline.json] --start 0 --end 30 --out x.mp4 [--draft 1] [--shot t] [--fmt png|jpeg]
import fs from 'node:fs'; import path from 'node:path'; import http from 'node:http';
import { spawn } from 'node:child_process'; import { once } from 'node:events';
import { launch, close, sleep } from './cdp.mjs';
const arg = Object.fromEntries(process.argv.slice(2).map((x, i, a) => x.startsWith('--') ? [x.slice(2), a[i + 1]] : null).filter(Boolean));
const input = process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : 'out/video/v5/timeline_v5.json';
const T = JSON.parse(fs.readFileSync(input, 'utf8'));
const root = process.cwd();
const types = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.jpg': 'image/jpeg', '.png': 'image/png', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.ttf': 'font/ttf' };
const server = http.createServer((req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, 'http://local').pathname); const p = path.resolve(root, '.' + pathname);
  if (!p.startsWith(root + path.sep) || !['tools/video/', 'out/video/'].some(x => pathname.slice(1).startsWith(x))) { res.writeHead(403); res.end(); return; }
  fs.stat(p, (e, st) => { if (e || !st.isFile()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'Content-Type': types[path.extname(p)] || 'application/octet-stream', 'Cache-Control': 'max-age=600' }); fs.createReadStream(p).pipe(res); });
});
const hp = Number(process.env.RHTTP || 9346);
await new Promise(r => server.listen(hp, '127.0.0.1', r));
const start = Number(arg.start || 0), stop = Number(arg.end || T.duration), fps = 60, frames = Math.round((stop - start) * fps);
const out = arg.out || 'out/video/v5/picture.mp4'; fs.mkdirSync(path.dirname(out), { recursive: true });
let b, enc, log = '';
try {
  b = await launch(Number(process.env.RCDP || 9347), `http://127.0.0.1:${hp}/tools/video/compositor/v5.html?timeline=/${input.replaceAll('\\', '/')}`, true);
  await b.cdp.send('Emulation.setDeviceMetricsOverride', { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
  for (let n = 0; n < 300; n++) { if (await b.cdp.evaluate('window.__ready===true')) break; if (n === 299) throw Error('compositor not ready'); await sleep(100); }
  const fmt = arg.fmt || 'jpeg';
  const shotOpts = fmt === 'png' ? { format: 'png' } : { format: 'jpeg', quality: 97, optimizeForSpeed: true };
  if (arg.shot !== undefined) {
    await b.cdp.evaluate(`window.__seek(${Number(arg.shot)})`);
    const r = await b.cdp.send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(out, Buffer.from(r.data, 'base64')); console.log('still', arg.shot, out);
  } else if (arg.shots !== undefined) {  // comma list of times -> out is a directory prefix
    for (const t of arg.shots.split(',')) { await b.cdp.evaluate(`window.__seek(${Number(t)})`); const r = await b.cdp.send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(`${out}_${Number(t).toFixed(2)}.png`, Buffer.from(r.data, 'base64')); }
    console.log('stills done');
  } else {
    const codec = arg.draft ? ['-c:v', 'h264_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', '24'] : ['-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-threads', '6'];
    enc = spawn('ffmpeg', ['-hide_banner', '-y', '-f', 'image2pipe', '-framerate', '60', '-vcodec', fmt === 'png' ? 'png' : 'mjpeg', '-i', 'pipe:0', '-an', ...codec, '-profile:v', 'high', '-pix_fmt', 'yuv420p',
      '-vf', 'scale=in_range=full:out_range=tv:flags=lanczos,format=yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv', '-r', '60', '-fps_mode', 'cfr', out],
      { stdio: ['pipe', 'ignore', 'pipe'], windowsHide: true });
    enc.stderr.on('data', d => { log += d; }); const exit = once(enc, 'exit');
    const t0 = Date.now();
    for (let f = 0; f < frames; f++) {
      await b.cdp.evaluate(`window.__seek(${(start + f / 60).toFixed(6)})`);
      const r = await b.cdp.send('Page.captureScreenshot', { ...shotOpts, captureBeyondViewport: false, fromSurface: true });
      if (!enc.stdin.write(Buffer.from(r.data, 'base64'))) await once(enc.stdin, 'drain');
      if (f % 120 === 0) { fs.writeFileSync(out + '.progress.json', JSON.stringify({ frame: f, total: frames, t: start + f / 60, fps_render: +(f / ((Date.now() - t0) / 1000)).toFixed(1) })); }
    }
    enc.stdin.end(); const [code] = await exit; fs.writeFileSync(out + '.ffmpeg.log', log); if (code !== 0) throw Error('encoder failed ' + log.slice(-1500));
    console.log('done', out, frames, 'frames', ((Date.now() - t0) / 1000).toFixed(0) + 's');
  }
} finally { if (b) await close(b); server.close(); }
