"""Build the 10-slide submission deck without any third-party package.

    python docs/submission/deck/build_deck.py

Writes next to this file:
  Rescue_Triage_Desk.pptx   16:9, dark; hand-written Open XML (standard library only)
  deck.html                 same slides, one 16:9 page each (print to PDF from a browser)
  deck.md                   plain-text outline of the same content

Screenshots come from ./img (offline sample mode, synthetic data). Retake them from the
final connected build if you want them to show live agents.
"""
import html
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
IMG = HERE / 'img'
W, H = 12192000, 6858000  # 16:9 in EMU
BG, FG, MUTED, ACCENT, PANEL, GREEN = '0B1220', 'F1F5F9', '94A3B8', 'F59E0B', '172033', '34D399'
FOOT = 'Rescue Triage Desk | May 2024 RS floods replay | synthetic data | screenshots: offline sample mode'

# ---- content (single source for pptx, html and md) -----------------------------------------------
SLIDES = [
    dict(title='Rescue Triage Desk',
         sub='Messy flood messages in, human-approved rescue dispatch out',
         bullets=['Built and replayed on the May 2024 Rio Grande do Sul floods',
                  'Portuguese rescue requests become evidence-linked cases',
                  'Code checks, agents explain, a human approves every dispatch'],
         images=['ux2_route_1920x1080.png'], layout='hero',
         note='Retrospective replay desk, not a deployed emergency system.'),
    dict(title='The problem: requests are messy, decisions are urgent',
         sub='Users: dispatchers, coordinators, volunteer boat crews',
         bullets=['Citizens write half an address, "my two babies", a landmark, a rumour of rescue',
                  'Dispatchers must decide where, how many, who is vulnerable, what is already rescued',
                  'A wrong guess sends a boat to the wrong street, or leaves a family waiting',
                  'They need evidence they can check, not a black-box score'],
         images=['ux2_new_emergency_1920x1080.png']),
    dict(title='The solution: an evidence-linked dispatch desk',
         sub='From message to approved mission, every step checkable',
         bullets=['Reads PT/EN/ES messages; every extracted field carries an exact quote',
                  'Code verifies places, counts, hazards, freshness and asset safety',
                  'Callback agent asks the citizen at most three questions, then re-triages',
                  'Groups cases into missions, routes land and water legs, tracks field feedback',
                  'Human confirms the location and approves; undo is available'],
         images=['i18n_en_queue.png']),
    dict(title='Agent workflow and architecture',
         sub='An agent exists only where it decides something code cannot',
         flow=['Message', 'Redact + injection check', 'Intake', 'Critic (max 1 revision)', 'Location + tools',
               'Code checks + hazards', 'Human approval'],
         bullets=['Also: Needs, Duplicate reviewer, Callback planner, Field feedback, Mission brief, Supervisor, Red team',
                  'Strict JSON, one retry, visible fallback; unsafe asset or injection blocks dispatch'],
         images=['i18n_en_agentes.png']),
    dict(title='Technology stack',
         sub='Small, auditable, runs on a 16 GB laptop',
         bullets=['Python 3.12 standard library only; no pip install',
                  'Nemotron 3.5 (Super VL 120B, Lightning 30B) via Meterless Nightshift, thinking on',
                  'Zetaris REST + SeaweedFS S3 for streets, landmarks, shelters, pumps',
                  'MapLibre GL, OSM, Copernicus EMS flood extent and HAND depth, IBGE',
                  'SAMPLE_MODE=true runs everything offline; Docker image included']),
    dict(title='Zetaris and Meterless in the product',
         sub='Sponsor technology is used in user-facing features',
         bullets=['Nightshift: every call logs the routed model and a receipt (lanes race)',
                  'World Model engine: append-only journal, replay, 409 on stale versions, human-only transitions; 6 conformance tests',
                  'Zetaris: 5 sources onboarded, 3 semantic views; Rodoviária in flood extent, 4,514 flooded segments',
                  'Data-quality rule: 62 of 734 shelter snapshots over capacity'],
         images=['i18n_en_case_Retorno.png']),
    dict(title='What is different',
         sub='Safety by construction, not by prompt',
         bullets=['Every model claim is tied to a quote or fact id and validated by code',
                  'Counts, distances and ranks are never model output; derived counts are flagged "confirm"',
                  'Red-team attacker declares its expected outcome first; failures become human-approved regressions',
                  'Straight-line water legs and retrospective depth are labelled estimates, never safe-route claims',
                  'Place memory is exact, city-scoped and revocable']),
    dict(title='The product',
         sub='Dispatcher console (offline sample mode shown, synthetic data)',
         images=['ux2_meios_1920x1080.png', 'ux2_route_1920x1080.png', 'ux2_dispatched_1920x1080.png'],
         captions=['Meios: assets ranked, unsafe ones blocked', 'Ver rota: land + labelled water leg', 'Despachar: human decision recorded'],
         layout='triple'),
    dict(title='Results (our own sets, labelled)',
         sub='Commit 4867ff0; live run 26 Oct 2026 19:40',
         bullets=['Live realdev 30-sample: 29/30, 0 unsafe, mean 20.6 s, p95 53 s',
                  'Offline: realdev 134/150, 0 unsafe; red team 42/42; adversarial 24/24; 1170 tests',
                  'dev2 (180 author-written messages), live 60-sample before fixes: 36/46 non-ambiguous, people count 28/29',
                  'Sealed 50: [TBD-sealed50]. Holdout 2: [TBD-holdout2] (run once after freeze)',
                  'Limits: dev sets are ours; fleet and GPS simulated; HAND depth retrospective'],
         images=['i18n_en_evals.png']),
    dict(title='Future enhancements',
         sub='Reproduce it: clone, SAMPLE_MODE=true python run.py serve --sample, open /v2',
         bullets=['Real fleet and GPS feeds; authentication and roles for operators',
                  'Real-message evaluation with responders; sealed and held-out results',
                  'Navigable water routing with verified depth; live gauge data',
                  'Persist the Zetaris semantic views through the product UI',
                  'Repo, video and deck links: [fill in at submission]'],
         layout='text'),
]

# ---- helpers ----------------------------------------------------------------------------------------
def png_size(path):
    import struct
    d = path.read_bytes()[:32]
    return struct.unpack('>II', d[16:24])


def run(text, sz, color, bold=False):
    b = ' b="1"' if bold else ''
    return (f'<a:r><a:rPr lang="en-US" sz="{sz}"{b} dirty="0"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            f'<a:latin typeface="Calibri"/></a:rPr><a:t>{escape(text)}</a:t></a:r>')


def para(text, sz, color, bold=False, bullet=False, space=600):
    ppr = (f'<a:pPr marL="285750" indent="-285750"><a:spcBef><a:spcPts val="{space}"/></a:spcBef>'
           f'<a:buClr><a:srgbClr val="{ACCENT}"/></a:buClr><a:buFont typeface="Arial"/><a:buChar char="&#8226;"/></a:pPr>'
           if bullet else f'<a:pPr marL="0" indent="0"><a:spcBef><a:spcPts val="{space}"/></a:spcBef><a:buNone/></a:pPr>')
    return f'<a:p>{ppr}{run(text, sz, color, bold)}</a:p>'


class Slide:
    def __init__(self):
        self.shapes, self.rels, self.n = [], [], 1  # id 1 is the group root

    def _id(self):
        self.n += 1
        return self.n

    def text(self, x, y, w, h, paras, fill=None, name='Text', anchor='t', geom='rect'):
        i = self._id()
        f = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else '<a:noFill/>'
        self.shapes.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{name} {i}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="{geom}"><a:avLst/></a:prstGeom>{f}<a:ln><a:noFill/></a:ln></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" lIns="91440" tIns="45720" rIns="91440" bIns="45720" anchor="{anchor}"><a:normAutofit/></a:bodyPr><a:lstStyle/>{"".join(paras)}</p:txBody></p:sp>')

    def pic(self, file, x, y, w, h):
        i = self._id()
        rid = f'rId{len(self.rels) + 2}'  # rId1 = layout
        self.rels.append((rid, file))
        self.shapes.append(
            f'<p:pic><p:nvPicPr><p:cNvPr id="{i}" name="Screenshot {i}" descr="Product screenshot"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f'<a:ln w="12700"><a:solidFill><a:srgbClr val="334155"/></a:solidFill></a:ln></p:spPr></p:pic>')

    def xml(self):
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                f'<p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="{BG}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
                '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                + ''.join(self.shapes) + '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


def fit(path, bw, bh):
    iw, ih = png_size(path)
    s = min(bw / iw, bh / ih)
    return int(iw * s), int(ih * s)


def build_slide(s, idx):
    sl = Slide()
    M = 457200
    hero = s.get('layout') == 'hero'
    sl.text(M, 300000, W - 2 * M, 760000, [para(s['title'], 4000 if hero else 3400, FG, bold=True, space=0)], name='Title', anchor='b')
    sl.text(M, 1060000, W - 2 * M, 420000, [para(s['sub'], 1800, ACCENT, space=0)], name='Subtitle')
    top, bottom = 1600000, 6250000
    imgs = s.get('images', [])
    layout = s.get('layout', 'split' if imgs else 'text')
    if layout == 'triple':
        gap = 200000
        cw = (W - 2 * M - 2 * gap) // 3
        for k, f in enumerate(imgs):
            w, h = fit(IMG / f, cw, 3000000)
            x = M + k * (cw + gap)
            sl.pic(f, x, top + 200000, w, h)
            sl.text(x, top + 200000 + h + 60000, cw, 700000, [para(s['captions'][k], 1500, FG, space=0)], name='Caption')
    elif layout == 'text':
        sl.text(M, top, W - 2 * M, bottom - top, [para(b, 2200, FG, bullet=True, space=1200) for b in s['bullets']], name='Body')
    else:
        # split: bullets left (45%), screenshot right
        lw = int((W - 2 * M) * 0.45)
        y = top
        if s.get('flow'):
            fl = s['flow']
            bw_, bh_ = 1040000, 680000
            gapx = (W - 2 * M - len(fl) * bw_) // (len(fl) - 1)
            for k, label in enumerate(fl):
                sl.text(M + k * (bw_ + gapx), top, bw_, bh_, [para(label, 1100, FG, bold=True, space=0)], fill=PANEL, name='Step', anchor='ctr', geom='roundRect')
            y = top + bh_ + 150000
            lw = int((W - 2 * M) * 0.40)
        body = s.get('bullets', [])
        if body:
            sl.text(M, y, lw, bottom - y, [para(b, 1800, FG, bullet=True, space=1000) for b in body], name='Body')
        if imgs:
            ax, aw = M + lw + 200000, W - 2 * M - lw - 200000
            w, h = fit(IMG / imgs[0], aw, bottom - y)
            sl.pic(imgs[0], ax + (aw - w) // 2 if not hero else ax, y + 50000, w, h)
    if s.get('note'):
        sl.text(M, 5900000, W - 2 * M, 380000, [para(s['note'], 1500, GREEN, space=0)], name='Note')
    sl.text(M, 6430000, W - 2 * M - 700000, 300000, [para(FOOT, 1000, MUTED, space=0)], name='Footer')
    sl.text(W - M - 600000, 6430000, 600000, 300000, [para(f'{idx}/{len(SLIDES)}', 1000, MUTED, space=0)], name='Number')
    return sl


THEME = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="RTD">'
         '<a:themeElements><a:clrScheme name="RTD"><a:dk1><a:srgbClr val="0B1220"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="172033"/></a:dk2><a:lt2><a:srgbClr val="F1F5F9"/></a:lt2>'
         '<a:accent1><a:srgbClr val="F59E0B"/></a:accent1><a:accent2><a:srgbClr val="34D399"/></a:accent2><a:accent3><a:srgbClr val="60A5FA"/></a:accent3><a:accent4><a:srgbClr val="F87171"/></a:accent4><a:accent5><a:srgbClr val="A78BFA"/></a:accent5><a:accent6><a:srgbClr val="94A3B8"/></a:accent6>'
         '<a:hlink><a:srgbClr val="60A5FA"/></a:hlink><a:folHlink><a:srgbClr val="A78BFA"/></a:folHlink></a:clrScheme>'
         '<a:fontScheme name="RTD"><a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>'
         '<a:fmtScheme name="RTD"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>'
         '<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>'
         '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
         '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')

NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
EMPTY_TREE = ('<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree>')
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
HDR = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def rels(items):
    return HDR + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(
        f'<Relationship Id="{i}" Type="{t}" Target="{g}"/>' for i, t, g in items) + '</Relationships>'


def write_pptx(path):
    slides = [build_slide(s, k + 1) for k, s in enumerate(SLIDES)]
    imgs = sorted({f for sl in slides for _, f in sl.rels})
    ct = (HDR + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
          '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
          '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
          '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
          '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
          + ''.join(f'<Override PartName="/ppt/slides/slide{k + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for k in range(len(slides)))
          + '</Types>')
    pres = (HDR + f'<p:presentation {NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>'
            + ''.join(f'<p:sldId id="{256 + k}" r:id="rId{k + 3}"/>' for k in range(len(slides)))
            + f'</p:sldIdLst><p:sldSz cx="{W}" cy="{H}"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    master = (HDR + f'<p:sldMaster {NS}><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="{BG}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>{EMPTY_TREE}</p:cSld>'
              '<p:clrMap bg1="dk1" tx1="lt1" bg2="dk2" tx2="lt2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
              '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst></p:sldMaster>')
    layout = HDR + f'<p:sldLayout {NS} type="blank" preserve="1"><p:cSld name="Blank">{EMPTY_TREE}</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ct)
        z.writestr('_rels/.rels', rels([('rId1', REL + '/officeDocument', 'ppt/presentation.xml')]))
        z.writestr('ppt/presentation.xml', pres)
        z.writestr('ppt/_rels/presentation.xml.rels', rels(
            [('rId1', REL + '/slideMaster', 'slideMasters/slideMaster1.xml'), ('rId2', REL + '/theme', 'theme/theme1.xml')]
            + [(f'rId{k + 3}', REL + '/slide', f'slides/slide{k + 1}.xml') for k in range(len(slides))]))
        z.writestr('ppt/slideMasters/slideMaster1.xml', master)
        z.writestr('ppt/slideMasters/_rels/slideMaster1.xml.rels', rels(
            [('rId1', REL + '/slideLayout', '../slideLayouts/slideLayout1.xml'), ('rId2', REL + '/theme', '../theme/theme1.xml')]))
        z.writestr('ppt/slideLayouts/slideLayout1.xml', layout)
        z.writestr('ppt/slideLayouts/_rels/slideLayout1.xml.rels', rels([('rId1', REL + '/slideMaster', '../slideMasters/slideMaster1.xml')]))
        z.writestr('ppt/theme/theme1.xml', THEME)
        for k, sl in enumerate(slides):
            z.writestr(f'ppt/slides/slide{k + 1}.xml', sl.xml())
            z.writestr(f'ppt/slides/_rels/slide{k + 1}.xml.rels', rels(
                [('rId1', REL + '/slideLayout', '../slideLayouts/slideLayout1.xml')] + [(rid, REL + '/image', f'../media/{f}') for rid, f in sl.rels]))
        for f in imgs:
            z.write(IMG / f, f'ppt/media/{f}')


def write_html(path):
    css = (f'body{{margin:0;background:#000;font-family:Calibri,Segoe UI,sans-serif}}'
           f'.s{{width:1280px;height:720px;margin:20px auto;background:#{BG};color:#{FG};position:relative;overflow:hidden;box-sizing:border-box;padding:40px 48px;page-break-after:always}}'
           f'h1{{font-size:38px;margin:0 0 6px}}h2{{font-size:19px;color:#{ACCENT};margin:0 0 22px;font-weight:400}}'
           f'ul{{font-size:21px;line-height:1.35;padding-left:24px}}li{{margin:0 0 12px}}li::marker{{color:#{ACCENT}}}'
           f'.row{{display:flex;gap:28px}}.col{{flex:1}}img{{max-width:100%;border:1px solid #334155}}'
           f'.flow span{{display:inline-block;background:#{PANEL};padding:8px 10px;border-radius:8px;margin:0 6px 6px 0;font-size:14px;font-weight:700}}'
           f'.note{{color:#{GREEN};font-size:16px}}.foot{{position:absolute;left:48px;bottom:14px;color:#{MUTED};font-size:11px}}'
           '.tri{display:flex;gap:16px}.tri div{flex:1;font-size:14px}'
           '@page{size:1280px 720px;margin:0}@media print{.s{margin:0}body{background:none}}')
    out = [f'<!doctype html><meta charset="utf-8"><title>Rescue Triage Desk</title><style>{css}</style>']
    for k, s in enumerate(SLIDES, 1):
        out.append(f'<section class="s"><h1>{html.escape(s["title"])}</h1><h2>{html.escape(s["sub"])}</h2>')
        if s.get('flow'):
            out.append('<div class="flow">' + ' &rarr; '.join(f'<span>{html.escape(f)}</span>' for f in s['flow']) + '</div>')
        if s.get('layout') == 'triple':
            out.append('<div class="tri">' + ''.join(f'<div><img src="img/{f}"><br>{html.escape(c)}</div>' for f, c in zip(s['images'], s['captions'])) + '</div>')
        else:
            lis = ''.join(f'<li>{html.escape(b)}</li>' for b in s.get('bullets', []))
            if s.get('images'):
                out.append(f'<div class="row"><div class="col"><ul>{lis}</ul></div><div class="col"><img src="img/{s["images"][0]}"></div></div>')
            else:
                out.append(f'<ul>{lis}</ul>')
        if s.get('note'):
            out.append(f'<p class="note">{html.escape(s["note"])}</p>')
        out.append(f'<div class="foot">{html.escape(FOOT)} | {k}/{len(SLIDES)}</div></section>')
    path.write_text('\n'.join(out), encoding='utf-8')


def write_md(path):
    lines = ['# Rescue Triage Desk: deck content', '']
    for k, s in enumerate(SLIDES, 1):
        lines += [f'## {k}. {s["title"]}', f'*{s["sub"]}*', '']
        if s.get('flow'):
            lines += ['Flow: ' + ' -> '.join(s['flow']), '']
        lines += [f'- {b}' for b in s.get('bullets', [])]
        if s.get('images'):
            lines += ['', 'Visual: ' + ', '.join(f'`img/{f}`' for f in s['images'])]
        if s.get('note'):
            lines += ['', s['note']]
        lines.append('')
    path.write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    write_pptx(HERE / 'Rescue_Triage_Desk.pptx')
    write_html(HERE / 'deck.html')
    write_md(HERE / 'deck.md')
    print('wrote Rescue_Triage_Desk.pptx, deck.html, deck.md in', HERE)
