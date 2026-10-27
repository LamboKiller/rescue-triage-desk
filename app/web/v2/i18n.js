/* PT-BR <-> EN switch for the whole /v2 desk. Chrome and server templates are translated at the DOM level
   (text nodes + title/aria-label/placeholder) from the phrase tables in i18n_en.js; originals are kept so
   switching back is lossless and nothing needs a reload. EVIDENCE IS NEVER TRANSLATED: citizen messages,
   quoted spans (“…”), JSON dumps, code, place names and ids are skipped or left verbatim; unknown text stays PT. */
(() => {
  'use strict';
  const KEY = 'rtd.lang';
  const NL = String.fromCharCode(10);
  const qs = new URLSearchParams(location.search);
  const norm = v => (String(v || '').toLowerCase().startsWith('en') ? 'en' : 'pt');
  let lang = 'pt';
  try { lang = norm(qs.get('lang') || localStorage.getItem(KEY) || 'pt'); } catch (_) { lang = norm(qs.get('lang')); }
  const DEBUG = qs.get('i18n_debug') === '1';
  const EVIDENCE = '[data-evidence],[translate="no"],.message,.citizen-text,.quote,.rt-msg,pre,code,blockquote,q,textarea,input,select,script,style,canvas,#map-gl,.maplibregl-map,.leaflet-container';
  const ATTRS = ['title', 'aria-label', 'placeholder', 'alt'];
  const textRec = new WeakMap(), seen = new Map();
  const LETTER = 'A-Za-zÀ-ÿ0-9';
  const LEAD = new RegExp('^[^' + LETTER + '“"(\\[]+'), TAIL = new RegExp('[^' + LETTER + '.…!?)\\]”"%]+$');
  const PT_HINT = /[áàâãçéêíóôõúü]|\b(de|do|da|dos|das|para|com|sem|não|em|os|as|uma?|por|ou|ao|pelo|pela|são|está)\b/i;
  let rules = null;
  const tables = () => {
    if (rules) return rules;
    const d = window.I18N_EN || {}, lower = new Map();
    for (const k of Object.keys(d)) lower.set(k.toLowerCase(), d[k]);
    rules = { d, lower, p: (window.I18N_PATTERNS || []).map(([re, out]) => [new RegExp(re, 'i'), out]) };
    return rules;
  };
  const cap = (src, out) => {
    if (!src || !out) return out;
    const up = src[0] !== src[0].toLowerCase(), outUp = out[0] !== out[0].toLowerCase();
    if (up && !outUp) return out[0].toUpperCase() + out.slice(1);
    if (!up && outUp && !/^[A-Z]{2}/.test(out) && src[0] !== src[0].toUpperCase()) return out[0].toLowerCase() + out.slice(1);
    return out;
  };
  function core(s, depth) {
    const { d, lower, p } = tables();
    if (d[s] !== undefined) return d[s];
    if (d[s + '.'] !== undefined) return d[s + '.'].replace(/\.$/, '');
    const l = lower.get(s.toLowerCase());
    if (l !== undefined) return cap(s, l);
    for (const subject of [s, s + '.']) {
      for (const [re, out] of p) {
        const m = re.exec(subject);
        if (!m || m[0].length !== subject.length) continue;
        let verbatimSplit = false;
        out.replace(/\$([tn]?)(\d)/g, (_, t, i) => { if (!t && m[i] && m[i].includes(' · ')) verbatimSplit = true; return ''; });
        if (verbatimSplit) continue; // let the separator split translate each piece instead
        const res = out.replace(/\$([tn]?)(\d)/g, (_, t, i) => (m[i] === undefined ? '' : t === 't' ? (tr(m[i], depth + 1) ?? m[i]) : t === 'n' ? m[i].replace(/(\d),(\d)/g, '$1.$2') : m[i]));
        return subject === s ? res : res.replace(/\.$/, '');
      }
    }
    return null;
  }
  // last resort: swap known PT fragments inside sentences assembled at render time (longest first)
  let fragList = null;
  function frag(s) {
    if (!fragList) fragList = Object.entries(window.I18N_FRAGS || {}).sort((a, b) => b[0].length - a[0].length);
    let out = s, hit = false;
    for (const [k, v] of fragList) if (out.includes(k)) { out = out.split(k).join(v); hit = true; }
    return hit ? out : null;
  }
  // translate one string; null = nothing known. Quoted spans “…” are evidence and copied verbatim.
  function tr(str, depth = 0) {
    if (!str || depth > 6) return null;
    const full = str.trim();
    const lead = (LEAD.exec(str) || [''])[0], rest0 = str.slice(lead.length);
    const tail = (TAIL.exec(rest0) || [''])[0], s = rest0.slice(0, rest0.length - tail.length);
    if (!s) return null;
    if (s.includes(NL)) {
      let any = false;
      const out = s.split(NL).map(x => { const y = tr(x, depth + 1); if (y !== null) any = true; return y === null ? x : y; });
      return any ? lead + out.join(NL) + tail : null;
    }
    if (s.includes('“') || /\[(?!SIMULADO\])[^\]]*\]/.test(s)) {
      const parts = s.split(/(“[^”]*”?|\[(?!SIMULADO\])[^\]]*\])/);
      let any = false;
      const out = parts.map(x => { if (!x || x[0] === '“' || x[0] === '[') return x; const y = tr(x, depth + 1); if (y !== null) any = true; return y === null ? x : y; });
      return any ? lead + out.join('') + tail : null;
    }
    let r = core(full, depth);
    if (r !== null) return r;
    r = core(s, depth);
    if (r === null) {
      const m = /^(.*?)([.…:]+)$/.exec(s);
      if (m) { const c = core(m[1], depth); if (c !== null) r = c + m[2]; }
    }
    if (r === null) {
      for (const sep of [' · ', ' — ', '. ', ': ', '; ', ' + ', ' - ', ' | ', ', ']) {
        if (!s.includes(sep)) continue;
        let any = false;
        const cut = sep === ': ' ? s.indexOf(sep) : -1;
        const pieces = cut < 0 ? s.split(sep) : [s.slice(0, cut), s.slice(cut + 2)];
        const out = pieces.map(x => { const y = tr(x, depth + 1); if (y !== null) any = true; return y === null ? x : y; });
        if (any) { r = out.join(sep); break; }
      }
    }
    if (r === null) r = frag(s);
    return r === null ? null : lead + r + tail;
  }
  const skip = n => { const e = n.nodeType === 1 ? n : n.parentElement; return !e || !!e.closest(EVIDENCE); };
  function note(text, where) {
    const t = text.trim();
    if (!t || !PT_HINT.test(t) || /^[\d\s.,:%/+\-–—·x×]+$/.test(t)) return;
    if (!seen.has(t)) { seen.set(t, where); if (DEBUG) console.debug('[i18n] untranslated:', t); }
  }
  // evidence stays verbatim; only the system-added safety tag in front of it is switched
  function evidenceTag(el) {
    const n = el.firstChild;
    if (!n || n.nodeType !== 3 || !/^\s*\[SIMULADO\]/.test(n.data)) return;
    let rec = textRec.get(n);
    if (!rec || n.data !== rec.en) rec = { pt: n.data, en: n.data.replace('[SIMULADO]', '[SIMULATED]') };
    textRec.set(n, rec);
    n.data = rec.en;
  }
  function textNode(n) {
    let rec = textRec.get(n);
    if (!rec || n.data !== rec.en) rec = { pt: n.data, en: n.data };
    const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(rec.pt);
    const en = m[2] ? tr(m[2]) : null;
    if (en === null) { if (m[2]) note(m[2], n.parentElement && n.parentElement.tagName); rec.en = rec.pt; }
    else rec.en = m[1] + en + m[3];
    textRec.set(n, rec);
    if (n.data !== rec.en) n.data = rec.en;
  }
  function attrs(el) {
    const st = el.__i18n || (el.__i18n = {});
    for (const a of ATTRS) {
      if (!el.hasAttribute(a)) continue;
      const cur = el.getAttribute(a), rec = st[a];
      const pt = rec && cur === rec.en ? rec.pt : cur, en = tr(pt);
      if (en === null) { note(pt, el.tagName + '[' + a + ']'); delete st[a]; continue; }
      st[a] = { pt, en };
      if (cur !== en) el.setAttribute(a, en);
    }
    if (el.tagName === 'INPUT' && /^(button|submit)$/.test(el.type) && el.value) { const en = tr(el.value); if (en !== null) el.value = en; }
  }
  function walk(root) {
    if (root.nodeType === 3) { if (!skip(root)) textNode(root); return; }
    if (root.nodeType !== 1 || root.closest('script,style')) return;
    if (root.matches(EVIDENCE) && !root.matches('input,textarea,select')) { attrs(root); evidenceTag(root); return; }
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode: n => (n.nodeType === 1 && n !== root && n.matches(EVIDENCE) ? (n.matches('input,textarea,select') ? attrs(n) : evidenceTag(n), NodeFilter.FILTER_REJECT) : NodeFilter.FILTER_ACCEPT),
    });
    attrs(root);
    for (let n = w.nextNode(); n; n = w.nextNode()) { if (n.nodeType === 3) textNode(n); else attrs(n); }
  }
  function restore() {
    const w = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (n.nodeType === 3) { const r = textRec.get(n); if (r && n.data === r.en) n.data = r.pt; }
      else if (n.__i18n) for (const a of Object.keys(n.__i18n)) { const r = n.__i18n[a]; if (n.getAttribute(a) === r.en) n.setAttribute(a, r.pt); }
    }
  }
  let busy = false;
  const obs = new MutationObserver(list => {
    if (busy || lang !== 'en') return;
    busy = true;
    try {
      for (const m of list) {
        if (m.type === 'childList') m.addedNodes.forEach(walk);
        else if (m.type === 'characterData') walk(m.target);
        else if (m.type === 'attributes') attrs(m.target);
      }
    } finally { obs.takeRecords(); busy = false; }
  });
  const watch = () => obs.observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  function apply() {
    document.documentElement.lang = lang === 'en' ? 'en' : 'pt-BR';
    document.querySelectorAll('#lang-toggle button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.lang === lang)));
    obs.disconnect(); busy = true;
    try {
      if (lang === 'en') { walk(document.body); const t = tr(window.__ptTitle || (window.__ptTitle = document.title)); if (t) document.title = t; }
      else { restore(); if (window.__ptTitle) document.title = window.__ptTitle; }
    } finally { busy = false; }
    if (lang === 'en') watch();
  }
  function set(next) {
    next = norm(next);
    try { localStorage.setItem(KEY, next); } catch (_) { /* private mode */ }
    if (next === lang) return;
    lang = next; apply();
    document.dispatchEvent(new CustomEvent('desk:lang', { detail: { lang } }));
  }
  const css = document.createElement('style');
  css.textContent = '.lang-toggle{display:inline-flex;border:1px solid var(--line,#8886);border-radius:4px;overflow:hidden}.lang-toggle button{border:0;border-radius:0;padding:2px 8px;min-width:0;font-weight:600;background:transparent;color:inherit}.lang-toggle button[aria-pressed=true]{background:var(--accent,#2b6cb0);color:#fff}html[lang=en] .message::before{content:"original PT · ";font-size:.8em;opacity:.7}';
  document.head.append(css);
  document.addEventListener('click', e => { const b = e.target.closest && e.target.closest('#lang-toggle button[data-lang]'); if (b) set(b.dataset.lang); });
  // dialogs: translate native confirm/alert text (never evidence: only our own template strings match)
  for (const f of ['alert', 'confirm']) { const o = window[f].bind(window); window[f] = m => o(lang === 'en' ? (tr(String(m)) ?? m) : m); }
  const t = (key, vars) => {
    let s = lang === 'en' ? (tr(String(key)) ?? String(key)) : String(key);
    if (vars) s = s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] === undefined ? '' : vars[k]));
    return s;
  };
  window.I18N = { t, tr, get lang() { return lang; }, set, apply, untranslated: () => [...seen.keys()],
    known: t => { const { d, lower } = tables(); const v = d[t] !== undefined ? d[t] : lower.get(String(t).toLowerCase()); return v !== undefined && v.toLowerCase() !== String(t).toLowerCase(); }, walk };
  window.t = window.t || t;
  const boot = () => apply();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  if (lang === 'en') document.documentElement.lang = 'en';
})();
