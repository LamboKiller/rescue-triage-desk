'use strict';
// RTD v5 compositor: every visual is a pure function of t. window.__seek(t) -> Promise.
const FPS = 60, W = 1920, H = 1080;
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, k) => a + (b - a) * k;
const eoExpo = x => x >= 1 ? 1 : 1 - Math.pow(2, -10 * x);
const eoCubic = x => 1 - Math.pow(1 - x, 3);
const eoQuart = x => 1 - Math.pow(1 - x, 4);
const ioCubic = x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
function bezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx, cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const X = t => ((ax * t + bx) * t + cx) * t, Y = t => ((ay * t + by) * t + cy) * t, dX = t => (3 * ax * t + 2 * bx) * t + cx;
  return x => { if (x <= 0) return 0; if (x >= 1) return 1; let t = x; for (let i = 0; i < 8; i++) { const d = dX(t); if (Math.abs(d) < 1e-6) break; t -= (X(t) - x) / d; } return Y(clamp(t)); };
}
const camEase = bezier(.2, .8, .2, 1);
function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const el = (tag, cls, parent, css) => { const e = document.createElement(tag); if (cls) e.className = cls; if (css) e.style.cssText = css; if (parent) parent.appendChild(e); return e; };

let T, root, capEl, flashEl, fadeEl, floorEl, grainEl;
const mods = [];

// ---------- text -----------------------------------------------------------
function initText(it) {
  const n = el('div', 'txt ' + (it.cls || ''), root);
  n.style.cssText += `font-size:${it.size || 120}px;color:${it.color || '#F5F7FA'};z-index:${it.z || 20};`;
  n.style.left = it.x + 'px'; n.style.top = it.y + 'px';
  const ax = it.ax ?? .5, ay = it.ay ?? .5;
  n.style.transformOrigin = `${ax * 100}% ${ay * 100}%`;
  if (it.html) n.innerHTML = it.html; else if (it.stagger) {
    it.text.split(' ').forEach(w => { const s = el('span', 'w', n); s.textContent = w + '\u00a0'; });
  } else n.textContent = it.text;
  if (it.weight) n.style.fontWeight = it.weight;
  if (it.shadow === false) n.style.textShadow = 'none';
  return { item: it, node: n, update(t) {
    const u = t - it.start, tx = `translate(${-ax * 100}%,${-ay * 100}%)`;
    if (t < it.start || t >= it.end) { n.style.opacity = 0; return; }
    const outD = it.out ?? .25, out = clamp((t - (it.end - outD)) / outD);
    let op = 1, tf = tx, fl = 'none';
    const a = it.anim || 'slam';
    if (a === 'slam') {
      const k = eoExpo(clamp(u / (it.in ?? .22)));
      op = clamp(u / .1); tf = `${tx} scale(${lerp(1.32, 1, k)})`; fl = `blur(${lerp(16, 0, k)}px)`;
    } else if (a === 'rise') {
      const k = eoExpo(clamp(u / (it.in ?? .55)));
      if (it.stagger) { [...n.children].forEach((c, i) => { const kk = eoExpo(clamp((u - i * .05) / (it.in ?? .5))); c.style.opacity = kk; c.style.transform = `translateY(${lerp(30, 0, kk)}px)`; }); }
      else { op = k; tf = `${tx} translateY(${lerp(34, 0, k)}px)`; fl = `blur(${lerp(8, 0, k)}px)`; }
    } else if (a === 'wipe') {
      const k = eoExpo(clamp(u / (it.in ?? .6)));
      n.style.clipPath = `inset(-20px ${lerp(100, 0, k)}% -20px 0)`;
    } else if (a === 'fade') { op = eoCubic(clamp(u / (it.in ?? .4))); }
    if (out > 0) { op *= 1 - out; tf += ` translateY(${-10 * out}px)`; }
    n.style.opacity = op; n.style.transform = tf; n.style.filter = fl;
    if (it.count) {
      const c = it.count, k = eoQuart(clamp((u - (c.delay || 0)) / c.dur));
      n.innerHTML = (c.pre || '') + lerp(c.from, c.to, k).toFixed(c.dec || 0) + (c.suf || '');
    }
  } };
}

// ---------- photo ------------------------------------------------------------
function initPhoto(it) {
  const n = el('div', 'photo', root);
  const im = el('img', '', n); im.src = it.src; im.style.objectPosition = `${(it.fx ?? .5) * 100}% ${(it.fy ?? .5) * 100}%`;
  el('div', 'tint', n); el('div', 'shade', n);
  n.style.zIndex = it.z || 1;
  return { item: it, node: n, update(t) {
    if (t < it.start || t >= it.end) { n.style.display = 'none'; return; }
    n.style.display = 'block';
    const k = (t - it.start) / (it.end - it.start), kb = it.kb || { s0: 1.0, s1: 1.07, dx: 0, dy: 0 };
    const e = ioCubic(clamp(k)) * .35 + k * .65;
    im.style.transform = `translate(${lerp(0, kb.dx, e)}%,${lerp(0, kb.dy, e)}%) scale(${lerp(kb.s0, kb.s1, e)})`;
  } };
}

// ---------- UI footage w/ camera ----------------------------------------------
function initUI(it) {
  const n = el('div', 'ui', root); n.style.zIndex = it.z || 2;
  const cv = el('canvas', '', n); cv.width = W; cv.height = H; const g = cv.getContext('2d'); g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
  const dim = el('div', 'dim', n);
  const rings = (it.rings || []).map(r => ({ r, node: el('div', 'ring', n) }));
  const badge = it.badge ? el('div', 'badge', n) : null;
  const cache = new Map();
  const url = i => `${it.dir}/${String(i + 1).padStart(5, '0')}.jpg`;
  const load = i => { if (cache.has(i)) return cache.get(i); const im = new Image(); im.src = url(i); const p = im.decode().then(() => im).catch(() => null); cache.set(i, p); return p; };
  function camAt(tl) {
    let st = { cx: it.cam0.cx, cy: it.cam0.cy, s: it.cam0.s };
    for (const seg of it.cam) {
      if (tl < seg.t0) break;
      const k = camEase(clamp((tl - seg.t0) / seg.dur));
      st = { cx: lerp(seg.from.cx, seg.to.cx, k), cy: lerp(seg.from.cy, seg.to.cy, k), s: lerp(seg.from.s, seg.to.s, k) };
      if (tl < seg.t0 + seg.dur) break;
    }
    const sw = W / st.s, sh = H / st.s;
    st.cx = clamp(st.cx, sw / 2, it.W - sw / 2); st.cy = clamp(st.cy, sh / 2, it.H - sh / 2);
    return st;
  }
  return { item: it, node: n, async update(t) {
    if (t < it.start || t >= it.end) { n.style.display = 'none'; return; }
    n.style.display = 'block';
    const tl = t - it.start, fi = clamp(Math.round(tl * FPS), 0, it.n - 1);
    const im = await load(fi);
    for (let k = 1; k <= 3; k++) if (fi + k < it.n) load(fi + k);
    for (const key of [...cache.keys()]) if (key < fi - 2) cache.delete(key);
    const st = camAt(tl), sw = W / st.s, sh = H / st.s, sx = st.cx - sw / 2, sy = st.cy - sh / 2;
    if (im) g.drawImage(im, sx, sy, sw, sh, 0, 0, W, H);
    for (const m of it.masks || []) { g.fillStyle = m.c || '#0d1518'; g.fillRect((m.x - sx) * st.s, (m.y - sy) * st.s, m.w * st.s, m.h * st.s); }
    let dimA = 0, dimBox = null;
    for (const { r, node } of rings) {
      const u = tl - r.at;
      if (u < 0 || u > r.dur) { node.style.opacity = 0; continue; }
      const a = eoCubic(clamp(u / .25)) * (1 - clamp((u - (r.dur - .45)) / .45));
      const pad = 8, x = (r.box.x - sx) * st.s - pad, y = (r.box.y - sy) * st.s - pad, w = r.box.w * st.s + 2 * pad, h = r.box.h * st.s + 2 * pad;
      node.style.left = x + 'px'; node.style.top = y + 'px'; node.style.width = w + 'px'; node.style.height = h + 'px';
      node.style.opacity = a; node.style.transform = `scale(${lerp(1.05, 1, eoExpo(clamp(u / .35)))})`;
      if (a > dimA) { dimA = a; dimBox = [x, y, w, h]; }
    }
    if (dimBox) { const [x, y, w, h] = dimBox; dim.innerHTML = `<div style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;border-radius:14px;box-shadow:0 0 0 2400px rgba(2,6,12,${(.30 * dimA).toFixed(3)})"></div>`; }
    else if (dim.innerHTML) dim.innerHTML = '';
    if (badge) {
      const b = it.badge, u = tl - b.at; let a = 0;
      if (u >= 0 && u <= b.dur) a = eoCubic(clamp(u / .3)) * (1 - clamp((u - (b.dur - .3)) / .3));
      badge.style.opacity = a; badge.textContent = b.text; badge.style.transform = `translateY(${lerp(-14, 0, a)}px)`;
    }
  } };
}

// ---------- GFX modules ----------------------------------------------------------
const GFX = {};
const mkTxt = (host, txt, css, cls) => { const e = el('div', 'txt ' + (cls || ''), host); e.style.cssText += css; e.innerHTML = txt; return e; };

GFX.mosaic = (it, host) => {
  const p = it.p, R = rng(2024), msgs = p.msgs, N = msgs.length;
  host.style.background = 'radial-gradient(ellipse at 50% 40%,#0d1b2a,#04080d 75%)';
  const slow = p.slow || [.05, .45, .85, 1.2]; const s0 = p.s0 || 1.4, sd = p.sd || 3.2;
  const bubbles = msgs.map((m, i) => {
    const b = el('div', '', host); b.style.cssText = 'position:absolute;left:0;top:0;width:640px;padding:18px 24px 16px;border-radius:22px;background:#13202e;border:1px solid rgba(255,255,255,.14);box-shadow:0 14px 50px rgba(0,0,0,.5);opacity:0;will-change:transform,opacity';
    const tagc = { wa: '#25D366', sms: '#FFB224', call: '#3BA3FF', post: '#B084FF' }[m.k] || '#aaa';
    let h = `<div style="font:700 19px Inter;letter-spacing:.06em;color:${tagc};margin-bottom:6px;text-transform:uppercase">${m.tag}</div>`;
    if (m.k === 'call') h += `<div class="wave" style="display:flex;gap:4px;align-items:center;height:36px;margin:4px 0 6px">${Array.from({ length: 26 }, () => '<i style="width:6px;border-radius:3px;background:#3BA3FF;display:block;height:10px"></i>').join('')}</div>`;
    h += `<div style="font:600 30px/1.18 Inter;color:#F5F7FA">${m.pt}</div><div style="font:500 23px/1.3 Inter;color:#b4c4d4;margin-top:3px">${m.en}</div>`;
    if (m.k === 'sms') h += `<div style="position:absolute;right:20px;top:14px;display:flex;gap:3px;align-items:flex-end">${[8, 13, 18, 23].map((x, j) => `<i style="display:block;width:6px;height:${x}px;background:${j ? '#3a4a5c' : '#FFB224'}"></i>`).join('')}</div>`;
    if (m.dup) h += `<div style="position:absolute;right:-10px;top:-14px;background:#FF4D4D;color:#fff;font:700 20px Inter;padding:4px 12px;border-radius:999px">${m.dup}</div>`;
    b.innerHTML = h;
    const t0 = i < 4 ? slow[i] : s0 + sd * (1 - Math.pow(1 - (i - 3) / (N - 3), 1.6));
    return { b, t0, bx: 40 + R() * (W - 680), by: 230 + R() * (H - 520), rot: (R() - .5) * 5, wave: m.k === 'call' ? [...b.querySelectorAll('.wave i')] : null };
  });
  const title = mkTxt(host, p.title, 'left:960px;top:96px;font-size:84px;color:#F5F7FA;opacity:0;z-index:900');
  const sub = mkTxt(host, p.sub, 'left:960px;top:172px;font-size:36px;color:#9fb2c6;opacity:0;z-index:900', 'body');
  const rows = p.queue.map((q, i) => {
    const d = el('div', '', host, `position:absolute;left:${960 - 480}px;top:${250 + i * 84}px;width:960px;height:72px;border-radius:16px;background:rgba(18,32,46,.97);border:1px solid rgba(255,255,255,.16);display:flex;align-items:center;gap:20px;padding:0 24px;opacity:0;z-index:800;will-change:transform,opacity`);
    const pc = { P1: '#FF4D4D', P2: '#FFB224', P3: '#3BA3FF' }[q.pri];
    d.innerHTML = `<b style="font:800 26px Inter;color:#fff;background:${pc};border-radius:8px;padding:5px 12px">${q.pri}</b><span style="font:600 29px Inter;color:#F5F7FA;flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${q.pt}</span><span style="font:600 21px Inter;color:#8fa4b8">${q.ch}</span>`;
    return d;
  });
  const tC = p.converge, tQ = tC + .9;
  return { update(u) {
    for (const bb of bubbles) {
      const a = u - bb.t0;
      if (a < 0) { bb.b.style.opacity = 0; continue; }
      const pop = eoExpo(clamp(a / .16));
      let x = bb.bx, y = bb.by, s = lerp(.82, 1, pop), op = pop, rot = bb.rot; bb.b.style.filter = `brightness(${lerp(1, .55, clamp(a / 2.6))})`, rot = bb.rot;
      if (bb.wave) bb.wave.forEach((w, j) => w.style.height = (8 + 26 * Math.abs(Math.sin(u * 7 + j * .8) * Math.sin(u * 2.3 + j * .3))) + 'px');
      if (u > tC) { const k = ioCubic(clamp((u - tC) / .9)); x = lerp(x, 660, k); y = lerp(y, 480, k); s = lerp(s, .12, k); rot = lerp(rot, 0, k); op *= 1 - clamp((u - tC - .5) / .4); }
      bb.b.style.transform = `translate(${x}px,${y}px) rotate(${rot}deg) scale(${s})`;
      bb.b.style.opacity = op; bb.b.style.zIndex = Math.round(bb.t0 * 10);
    }
    const ta = eoExpo(clamp((u - tQ) / .5)); title.style.opacity = ta; title.style.filter = `blur(${lerp(10, 0, ta)}px)`;
    title.style.transform = `translate(-50%,-50%) translateY(${lerp(26, 0, ta)}px)`;
    sub.style.opacity = clamp((u - tQ - .15) / .5); sub.style.transform = 'translate(-50%,-50%)';
    rows.forEach((d, i) => { const k = eoExpo(clamp((u - tQ - .1 - i * .09) / .4)); d.style.opacity = clamp((u - tQ - .1 - i * .09) / .1); d.style.transform = `translateY(${lerp(-60, 0, k)}px) scale(${lerp(.9, 1, k)})`; });
  } };
};

GFX.noaa = (it, host) => {
  const p = it.p;
  host.style.background = 'radial-gradient(ellipse at 30% 40%,#10263a,#04080d 75%)';
  const k = mkTxt(host, p.kicker, 'left:150px;top:250px;font-size:34px;color:#FFB224;letter-spacing:.08em', 'body');
  const big = mkTxt(host, '', 'left:140px;top:440px;font-size:330px;color:#F5F7FA');
  const lab = mkTxt(host, p.label, 'left:150px;top:640px;font-size:62px;color:#F5F7FA');
  const src = mkTxt(host, p.src, 'left:150px;top:740px;font-size:26px;color:#8fa4b8;', 'src');
  const bar = el('div', '', host, 'position:absolute;left:150px;top:830px;height:10px;width:820px;background:rgba(255,255,255,.12);border-radius:5px');
  const fill = el('div', '', bar, 'height:100%;width:0;background:linear-gradient(90deg,#3BA3FF,#FFB224);border-radius:5px');
  return { update(u) {
    const a = eoExpo(clamp(u / .5)); k.style.opacity = a; k.style.transform = `translateY(${lerp(20, 0, a)}px)`;
    big.innerHTML = '&gt;' + Math.round(83 * eoQuart(clamp((u - .15) / .9))) + '<span style="font-size:170px">%</span>';
    big.style.opacity = clamp(u / .12); big.style.transform = `translateY(-50%) scale(${lerp(1.18, 1, eoExpo(clamp(u / .3)))})`; big.style.transformOrigin = 'left center';
    lab.style.opacity = eoCubic(clamp((u - .7) / .5)); lab.style.transform = `translateY(${lerp(24, 0, eoExpo(clamp((u - .7) / .6)))}px)`;
    src.style.opacity = clamp((u - 1.0) / .5); fill.style.width = (83 * eoQuart(clamp((u - .3) / 1.2))) + '%';
  } };
};


const svgPerson = c => `<svg width="54" height="54" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4.2" fill="${c}"/><path d="M3.5 21c.8-4.6 4.2-7 8.5-7s7.7 2.4 8.5 7z" fill="${c}"/></svg>`;
const fadeIn = (e, u, a0, d = .45, dy = 26, base = '') => { const k = eoExpo(clamp((u - a0) / d)); e.style.opacity = clamp((u - a0) / .12); e.style.transform = `${base} translateY(${lerp(dy, 0, k)}px)`; e.style.filter = `blur(${lerp(8, 0, k)}px)`; return k; };

// message arrives: chat bubble (PT + EN) + who is there
GFX.message = (it, host) => {
  const p = it.p;
  host.style.background = 'radial-gradient(ellipse at 30% 40%,#0f2234,#04080d 78%)';
  const head = mkTxt(host, `<span style="display:inline-block;width:14px;height:14px;border-radius:50%;background:#25D366;margin-right:14px;vertical-align:2px"></span>${p.tag}`, 'left:150px;top:150px;font-size:30px;color:#25D366;letter-spacing:.06em', 'body');
  const bub = el('div', 'card', host, 'left:140px;top:205px;width:940px;padding:34px 40px 30px;border-radius:30px 30px 30px 8px;background:linear-gradient(160deg,#173326,#0f231a);border-color:rgba(37,211,102,.35);opacity:0');
  const words = p.pt.split(' ');
  bub.innerHTML = `<div class="pt" style="font:600 40px/1.25 Inter;color:#F5F7FA">${words.map(w => `<span style="opacity:0">${w} </span>`).join('')}</div><div class="en" style="font:500 29px/1.35 Inter;color:#a9c4b4;margin-top:18px;opacity:0">${p.en}</div><div style="position:absolute;right:26px;bottom:14px;font:500 22px Inter;color:#7fa892">${p.time}</div>`;
  const spans = [...bub.querySelectorAll('.pt span')], en = bub.querySelector('.en');
  const who = p.who.map((w, i) => { const d = el('div', 'card', host, `left:1200px;top:${210 + i * 180}px;width:600px;height:150px;padding:26px 30px;display:flex;gap:26px;align-items:center;opacity:0`);
    d.innerHTML = `<div style="flex:none;width:96px;height:96px;border-radius:50%;background:rgba(255,255,255,.07);display:flex;align-items:center;justify-content:center">${svgPerson(w.c)}</div><div><div style="font:700 44px/1.05 InterD,Inter;color:#F5F7FA">${w.name}</div><div style="font:600 28px/1.3 Inter;color:${w.c};margin-top:8px">${w.sub}</div></div>`; return { d, at: w.at }; });
  const pill = mkTxt(host, p.alert, 'left:1200px;top:770px;font-size:34px;color:#fff;background:#d93636;padding:14px 28px;border-radius:999px;opacity:0', 'body');
  return { update(u) {
    fadeIn(head, u, 0); fadeIn(bub, u, .1, .5, 40);
    spans.forEach((s, i) => s.style.opacity = clamp((u - .25 - i * p.wordDt) / .08));
    en.style.opacity = clamp((u - p.enAt) / .4);
    who.forEach(w => fadeIn(w.d, u, w.at, .5, 40));
    fadeIn(pill, u, p.alertAt, .4, 20); if (u > p.alertAt) pill.style.boxShadow = `0 0 ${20 + 14 * Math.abs(Math.sin(u * 4))}px rgba(255,70,70,.6)`;
  } };
};

// generic overlay callouts on top of UI footage: [{at, end, x, y, w, html, cls}]
GFX.callouts = (it, host) => {
  const p = it.p;
  const cs = p.items.map(c => { const d = el('div', 'card', host, `left:${c.x}px;top:${c.y}px;width:${c.w}px;padding:${c.pad || '22px 28px'};opacity:0;${c.css || ''}`); d.innerHTML = c.html; return { d, c }; });
  const scrim = p.scrim ? el('div', '', host, 'position:absolute;inset:0;background:rgba(2,6,12,1);opacity:0') : null;
  if (scrim) host.insertBefore(scrim, host.firstChild);
  return { update(u) {
    let sa = 0;
    cs.forEach(({ d, c }) => { const o = Math.min(clamp((u - c.at) / .15), 1 - clamp((u - (c.end - .25)) / .25)); const k = eoExpo(clamp((u - c.at) / .45));
      d.style.opacity = o; d.style.transform = `translateY(${lerp(30, 0, k)}px) scale(${lerp(.96, 1, k)})`; if (c.scrim && o > 0) sa = Math.max(sa, o * c.scrim);
      if (c.swapAt !== undefined) { const a = d.querySelector('.sa'), b = d.querySelector('.sb'); if (a && b) { const kk = clamp((u - c.swapAt) / .3); a.style.opacity = 1 - kk; b.style.opacity = kk; } }
      if (c.count) { const n = d.querySelector('.cnt'); if (n) n.textContent = Math.round(lerp(c.count.from, c.count.to, eoQuart(clamp((u - c.at - (c.count.delay || 0)) / c.count.dur)))); }
      d.querySelectorAll('[data-bar]').forEach((b, j) => { b.style.width = (Number(b.dataset.bar) * eoQuart(clamp((u - c.at - .3 - j * .12) / .8))) + '%'; });
    });
    if (scrim) scrim.style.opacity = sa;
  } };
};

GFX.build = (it, host) => {
  const p = it.p;
  host.style.background = 'radial-gradient(ellipse at 50% 35%,#0f2234,#04080d 78%)';
  const ttl = mkTxt(host, p.title, 'left:960px;top:104px;font-size:64px;opacity:0');
  const cols = 4, cw = 400, ch = 150, gx = 28, gy = 24, y0 = 168;
  const n = p.agents.length;
  const cards = p.agents.map((a, i) => {
    const r = Math.floor(i / cols), c = i % cols, rowCount = Math.min(cols, n - r * cols);
    const x0 = (W - (rowCount * cw + (rowCount - 1) * gx)) / 2;
    const d = el('div', 'card', host, `left:${x0 + c * (cw + gx)}px;top:${y0 + r * (ch + gy)}px;width:${cw}px;height:${ch}px;padding:20px 24px;opacity:0`);
    d.innerHTML = `<div style="display:flex;align-items:center;gap:12px"><i class="dot" style="display:block;width:13px;height:13px;border-radius:50%;background:${a.c}"></i><span style="font:700 34px/1.05 InterD,Inter;letter-spacing:-.01em">${a.name}</span></div>
      <div style="font:500 23px/1.3 Inter;color:#a9bccf;margin-top:10px">${a.sub}</div>
      <div class="bars" style="position:absolute;left:24px;right:24px;bottom:14px;height:16px;display:flex;gap:4px;align-items:flex-end">${Array.from({ length: 22 }, () => `<b style="flex:1;display:block;border-radius:2px;background:${a.c};opacity:.75;height:4px"></b>`).join('')}</div>`;
    return { d, t0: a.at, bars: [...d.querySelectorAll('.bars b')], dot: d.querySelector('.dot') };
  });
  const hum = el('div', 'card', host, `left:${960 - 560}px;top:${y0 + 3 * (ch + gy) + 10}px;width:1120px;height:120px;display:flex;align-items:center;gap:28px;padding:0 40px;border-color:rgba(255,178,36,.75);background:linear-gradient(160deg,rgba(58,40,10,.97),rgba(30,20,6,.97));opacity:0`);
  hum.innerHTML = `${svgPerson('#FFB224')}<div style="font:700 44px InterD,Inter;color:#FFD27A">${p.human}</div>`;
  return { update(u) {
    const ta = eoExpo(clamp(u / .5)); ttl.style.opacity = ta; ttl.style.transform = `translate(-50%,-50%) translateY(${lerp(20, 0, ta)}px)`;
    cards.forEach((c, i) => {
      const a = u - c.t0; if (a < 0) { c.d.style.opacity = 0; return; }
      const k = eoExpo(clamp(a / .38));
      c.d.style.opacity = clamp(a / .1) * (u > p.humanAt ? lerp(1, .55, clamp((u - p.humanAt) / .5)) : 1); c.d.style.transform = `translateY(${lerp(50, 0, k)}px) scale(${lerp(.92, 1, k)})`; c.d.style.filter = `blur(${lerp(10, 0, k)}px)`;
      c.bars.forEach((b, j) => b.style.height = (4 + 12 * Math.abs(Math.sin(u * 5 + j * .7 + i)) * clamp(a / 1.2)) + 'px');
      c.dot.style.opacity = .6 + .4 * Math.sin(u * 8 + i);
    });
    const k = fadeIn(hum, u, p.humanAt, .5, 40); hum.style.boxShadow = `0 0 ${30 * k}px rgba(255,178,36,.45)`;
  } };
};

GFX.future = (it, host) => {
  const p = it.p;
  host.style.background = 'radial-gradient(ellipse at 30% 35%,#10263a,#04080d 76%)';
  const k = mkTxt(host, p.kicker, 'left:150px;top:200px;font-size:34px;color:#3BA3FF;letter-spacing:.12em', 'body');
  const rows = p.rows.map((r, i) => { const d = el('div', '', host, `position:absolute;left:150px;top:${290 + i * 170}px;display:flex;align-items:center;gap:36px;opacity:0`);
    d.innerHTML = `<div style="width:84px;height:84px;border-radius:22px;background:${r.c}22;border:2px solid ${r.c};display:flex;align-items:center;justify-content:center;font:700 40px InterD,Inter;color:${r.c}">${i + 1}</div><div><div style="font:700 62px/1.05 InterD,Inter;color:#F5F7FA;letter-spacing:-.02em">${r.t}</div><div style="font:500 30px/1.3 Inter;color:#9fb2c6;margin-top:8px">${r.s}</div></div>`; return { d, at: r.at }; });
  return { update(u) { fadeIn(k, u, 0); rows.forEach(r => fadeIn(r.d, u, r.at, .5, 36)); } };
};

GFX.close = (it, host) => {
  const p = it.p;
  host.style.background = 'radial-gradient(ellipse at 50% 38%,#10263a,#04080d 76%)';
  const C = 'translate(-50%,-50%)';
  const sub = mkTxt(host, p.sponsorLine, `left:960px;top:250px;font-size:32px;color:#8fa4b8;letter-spacing:.14em;transform:${C}`, 'body');
  const row = el('div', '', host, 'position:absolute;left:0;right:0;top:310px;display:flex;justify-content:center;gap:48px;opacity:0');
  row.innerHTML = p.logos.map(l => `<div style="width:460px;height:220px;border-radius:26px;background:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;box-shadow:0 20px 60px rgba(0,0,0,.5)">${l.src ? `<img src="${l.src}" style="${l.css}">` : `<div style="font:800 64px InterD,Inter;color:#0b1520;letter-spacing:-.03em">${l.word}</div>`}<div style="font:600 26px Inter;color:#3c4a58">${l.cap}</div></div>`).join('');
  const repo = mkTxt(host, p.repo, `left:960px;top:640px;font-size:56px;color:#3BA3FF;transform:${C}`, 'body');
  const l1 = mkTxt(host, p.l1, `left:960px;top:440px;font-size:108px;transform:${C}`);
  const l2 = mkTxt(host, p.l2, `left:960px;top:590px;font-size:108px;transform:${C}`);
  const l3 = mkTxt(host, p.l3, `left:960px;top:520px;font-size:92px;transform:${C};line-height:1.12;text-align:center;white-space:normal;width:1560px`);
  const set = (e, u, a0, a1, dy = 36, base = C) => { const k = eoExpo(clamp((u - a0) / .5)), o = Math.min(clamp((u - a0) / .12), 1 - clamp((u - a1) / .3)); e.style.opacity = o; e.style.filter = `blur(${lerp(10, 0, k)}px)`; e.style.transform = `${base} translateY(${lerp(dy, 0, k)}px)`; };
  return { update(u) {
    set(l1, u, p.t1, p.t3); set(l2, u, p.t2, p.t3); set(l3, u, p.t3, p.tS);
    set(sub, u, p.tS, 999); set(row, u, p.tS + .1, 999, 36, ''); set(repo, u, p.tS + .5, 999);
  } };
};


// kinetic stat on black (replaces weak photos): dots grid or rising water level
GFX.stat = (it, host) => {
  const p = it.p;
  host.style.background = 'radial-gradient(ellipse at 30% 45%,#0c1a28,#020407 75%)';
  const big = mkTxt(host, p.big, 'left:150px;top:430px;font-size:250px;transform:translateY(-50%)');
  const lab = mkTxt(host, p.label, 'left:156px;top:600px;font-size:60px;transform:translateY(-50%)');
  const src = mkTxt(host, p.src, 'left:156px;top:672px;font-size:24px;color:#c3d0dc;transform:translateY(-50%)', 'src');
  let dots = null, lvl = null;
  if (p.dots) {
    const g = el('div', '', host, 'position:absolute;left:1060px;top:190px;width:720px;display:flex;flex-wrap:wrap;gap:6px');
    dots = Array.from({ length: p.dots.total }, () => el('i', '', g, 'display:block;width:22px;height:22px;border-radius:5px;background:rgba(255,255,255,.12)'));
  }
  if (p.level) {
    const box = el('div', '', host, 'position:absolute;left:1180px;top:150px;width:420px;height:720px;border-left:3px solid rgba(255,255,255,.35)');
    const water = el('div', '', box, 'position:absolute;left:0;right:0;bottom:0;height:0;background:linear-gradient(180deg,rgba(59,163,255,.85),rgba(20,70,130,.9));border-top:3px solid #9fd2ff');
    const rec = el('div', '', box, `position:absolute;left:-40px;right:-40px;bottom:${p.level.rec / p.level.max * 100}%;border-top:3px dashed #FFB224`);
    rec.innerHTML = `<span style="position:absolute;left:100%;margin-left:18px;top:-17px;font:600 26px Inter;color:#FFB224;white-space:nowrap">${p.level.recLabel}</span>`;
    const now = el('div', '', box, 'position:absolute;left:20px;font:700 30px Inter;color:#fff;opacity:0'); now.textContent = p.level.nowLabel;
    lvl = { water, now };
  }
  return { update(u) {
    fadeIn(big, u, 0, .4, 30, 'translateY(-50%)'); fadeIn(lab, u, .15, .45, 24, 'translateY(-50%)'); fadeIn(src, u, .35, .4, 10, 'translateY(-50%)');
    if (dots) { const k = eoQuart(clamp((u - .1) / 1.3)), n = Math.round(p.dots.lit * k); dots.forEach((d, i) => d.style.background = i < n ? '#ff5a4d' : 'rgba(255,255,255,.24)'); }
    if (lvl) { const k = eoCubic(clamp((u - .1) / 1.5)); lvl.water.style.height = (p.level.val / p.level.max * 100 * k) + '%'; lvl.now.style.bottom = `calc(${p.level.val / p.level.max * 100 * k}% + 12px)`; lvl.now.style.opacity = clamp((u - 1.2) / .3); }
  } };
};
function initChapter(it) {
  const n = el('div', '', root, 'position:absolute;left:28px;top:22px;z-index:32;display:flex;align-items:center;gap:14px;opacity:0;white-space:nowrap;transform-origin:0 50%;padding:8px 20px 8px 10px;border-radius:14px;background:rgba(5,9,15,.88);border:1px solid rgba(255,255,255,.12)');
  n.innerHTML = `<b style="font:800 30px InterD,Inter;color:#05090f;background:#FFB224;border-radius:10px;padding:4px 13px">${it.num}</b><span style="font:700 34px InterD,Inter;color:#F5F7FA;text-shadow:0 2px 14px rgba(0,0,0,.8)">${it.text}</span>`;
  return { item: it, node: n, update(t) {
    if (t < it.start || t >= it.end) { n.style.opacity = 0; return; }
    const u = t - it.start, k = eoExpo(clamp(u / .45)), sh = eoCubic(clamp((u - 2.6) / .5));
    n.style.opacity = Math.min(clamp(u / .12), clamp((it.end - t) / .2)) * lerp(1, .85, sh);
    n.style.transform = `translateX(${lerp(-30, 0, k)}px) scale(${lerp(1.35, .8, sh)})`;
  } };
}

function initBand(it) {
  const n = el('div', '', root, `position:absolute;left:0;top:0;bottom:0;width:${it.w || 820}px;z-index:${it.z || 10};opacity:0;background:linear-gradient(90deg,rgba(3,8,14,.86),rgba(3,8,14,.78) 72%,rgba(3,8,14,0));-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);-webkit-mask-image:linear-gradient(90deg,#000 78%,transparent);mask-image:linear-gradient(90deg,#000 78%,transparent)`);
  return { item: it, node: n, update(t) { n.style.opacity = t < it.start || t >= it.end ? 0 : Math.min(clamp((t - it.start) / .35), clamp((it.end - t) / .35)); } };
}
function initChip(it) {
  const n = el('div', 'chip', root); n.innerHTML = `<i style="background:${it.dot || '#ff4d4d'};box-shadow:0 0 10px ${it.dot || '#ff4d4d'}"></i>${it.text}`;
  return { item: it, node: n, update(t) { n.style.opacity = t < it.start || t >= it.end ? 0 : (it.op || .9) * Math.min(clamp((t - it.start) / .25), clamp((it.end - t) / .2)); } };
}

function initGFX(it) {
  const host = el('div', 'gfx', root); host.style.zIndex = it.z || 3;
  const m = GFX[it.name](it, host);
  return { item: it, node: host, update(t) {
    if (t < it.start || t >= it.end) { host.style.display = 'none'; return; }
    host.style.display = 'block'; m.update(t - it.start);
  } };
}

// ---------- global ---------------------------------------------------------------
window.__seek = async function (t) {
  for (const m of mods) { const r = m.update(t); if (r && r.then) await r; }
  let c = null; for (const k of T.captions) { if (t >= k.start && t < k.end) { c = k; break; } }
  if (c) { capEl.textContent = c.text; capEl.style.opacity = clamp((t - c.start) / .12) * clamp((c.end - t) / .1); capEl.style.transform = `translateX(-50%) translateY(${lerp(6, 0, clamp((t - c.start) / .14))}px)`; } else capEl.style.opacity = 0;
  let f = 0; for (const x of T.flashes || []) { const u = t - x.at; if (u >= 0 && u < .14) f = Math.max(f, (x.a || .18) * (1 - u / .14)); }
  flashEl.style.opacity = f;
  let dp = 0; for (const x of T.dips || []) { const u = Math.abs(t - x.at); if (u < (x.half || .05)) dp = Math.max(dp, (x.a || .9) * (1 - u / (x.half || .05))); }
  document.getElementById('dip').style.opacity = dp;
  let fd = 0; for (const x of T.fades || []) { const u = t - x.at; if (u >= 0) fd = x.to === 1 ? clamp(u / x.dur) : 1 - clamp(u / x.dur); }
  fadeEl.style.opacity = fd;
  let ui = false; for (const m of mods) if (m.item.type === 'ui' && t >= m.item.start && t < m.item.end) ui = true;
  floorEl.style.opacity = ui ? .75 : 1; grainEl.style.opacity = ui ? 0 : .05;
  const fr = Math.round(t * FPS); grainEl.style.transform = `translate(${(fr * 37) % 64 - 32}px,${(fr * 53) % 64 - 32}px)`;
  return true;
};
(async () => {
  const q = new URLSearchParams(location.search);
  T = await (await fetch(q.get('timeline'))).json();
  root = document.getElementById('root'); capEl = document.getElementById('cap'); flashEl = document.getElementById('flash'); fadeEl = document.getElementById('fade'); floorEl = document.getElementById('floor'); grainEl = document.getElementById('grain');
  await document.fonts.load('700 100px InterD'); await document.fonts.load('600 40px Inter'); await document.fonts.load('500 20px Inter');
  for (const it of T.items) {
    if (it.type === 'photo') mods.push(initPhoto(it)); else if (it.type === 'ui') mods.push(initUI(it));
    else if (it.type === 'gfx') mods.push(initGFX(it)); else if (it.type === 'text') mods.push(initText(it)); else if (it.type === 'band') mods.push(initBand(it)); else if (it.type === 'chip') mods.push(initChip(it)); else if (it.type === 'chapter') mods.push(initChapter(it));
  }
  mods.sort((a, b) => (a.item.z || 0) - (b.item.z || 0));
  await Promise.all([...document.images].map(i => i.decode().catch(() => 0)));
  window.__ready = true;
})();
