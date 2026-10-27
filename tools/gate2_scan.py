"""Gate 2 public-repo safety scan (standard library only, offline, read-only).

Scans every file Git would publish (tracked + untracked-but-not-ignored) for:
  secrets, personal data (e-mail, BR phone, CPF), absolute personal paths,
  files > 50 MB, sealed/holdout material, and checks that .gitignore covers
  .env, runtime/, logs/, out/ and review/.

It never opens `.env*` files other than `.env.example`, and prints only
masked evidence (path:line, rule, first 3 characters), never a full match.

    python tools/gate2_scan.py            # table + exit 1 on any FAIL
    python tools/gate2_scan.py --md out/GATE2_SCAN.md
"""
import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 50 * 1024 * 1024
CONTENT_LIMIT = 40 * 1024 * 1024
SELF = 'tools/gate2_scan.py'
# Docs that describe the rules themselves are allowed to name them.
POLICY_DOCS = {'docs/submission/GATE2_SCAN.md', 'docs/submission/GATE2_CHECKLIST.md'}
USER = 'yus' + 'se'  # split so this file does not match its own rule
USER_RE = re.compile(r'(?i)(?:[A-Z]:[\/]+Users[\/]+|/Users/|/home/)' + USER + r'|\b' + USER + r'\b(?!f)')
NAME_RE = re.compile(r'(?i)\b' + USER + r'f\b')  # author first name: informational only

SECRET_RULES = [
    ('NVIDIA key', re.compile(r'\bnvapi-[A-Za-z0-9_\-]{20,}')),
    ('OpenAI-style key', re.compile(r'\bsk-[A-Za-z0-9_\-]{20,}')),
    ('AWS access key id', re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ('GitHub token', re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}')),
    ('Slack token', re.compile(r'\bxox[abprs]-[A-Za-z0-9\-]{10,}')),
    ('Google API key', re.compile(r'\bAIza[0-9A-Za-z_\-]{35}\b')),
    ('Private key block', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('JWT', re.compile(r'\beyJ[A-Za-z0-9_\-]{10,}.eyJ[A-Za-z0-9_\-]{10,}.[A-Za-z0-9_\-]{10,}')),
    ('Bearer literal', re.compile(r'(?i)authorization["\']?\s*[:=]\s*["\']?bearer\s+[A-Za-z0-9._\-]{24,}')),
    ('Assigned secret', re.compile(
        r'(?i)\b[A-Z0-9_]*(?:API_?KEY|SECRET|TOKEN|PASSWORD|ACCESS_KEY)[A-Z0-9_]*\s*[:=]\s*["\']?([A-Za-z0-9/+_\-]{20,})["\']?')),
]
PLACEHOLDER = re.compile(r'(?i)replace_with|your[_-]|example|placeholder|changeme|xxxx|<[^>]+>|\$\{|\{\{|os.environ|getenv|setting\(')

EMAIL = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')
EMAIL_OK = re.compile(r'(?i)@(?:[0-9]|(example\.(com|org|net)|exemplo\.com(|\.br)|test|localhost|users\.noreply\.github\.com|noreply))|^(git|noreply)@')
PHONE = re.compile(r'(?<![\d.])(?:\+55\s?)?(?:\(\d{2}\)\s?|\b\d{2}\s)9?\d{4}[-\s]\d{4}(?!\d)')
# Dummy numbers used in synthetic fixtures (sequential / repeated digits): reported as INFO, not FAIL.
PHONE_SYN = re.compile(r'(?:99123|99555|99777|98765|99876|98877|99700|98111|98000|3333|9999|9XXXX)[-\s]?(?:4321|5432|1122|3344|2233|1111|4444|0000|XXXX|4567|0102|1000)')
PHONE_OK = re.compile(r'(?:0000|XXXX|9{4}|1234[-\s]?5678)')  # synthetic markers used in fixtures
CPF = re.compile(r'(?<!\d)\d{3}.\d{3}.\d{3}-\d{2}(?!\d)')

TEXT_SUFFIX = {'.py', '.md', '.txt', '.json', '.jsonl', '.csv', '.js', '.mjs', '.html', '.css', '.yml', '.yaml',
               '.toml', '.cfg', '.ini', '.sql', '.example', '.sh', '.ps1', '.geojson', '.xml', '.tsv', ''}
# Big generated data tables: scan for secrets/paths, but phone-like digits are coordinates/ids there.
NUMERIC_DATA = ('.csv', '.geojson', '.tsv')


def git_files():
    out = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard', '-z'], cwd=ROOT, capture_output=True, check=True).stdout
    return sorted(p for p in out.decode('utf-8', 'replace').split('\0') if p)


def tracked():
    out = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True).stdout
    return set(out.decode('utf-8', 'replace').split('\0'))


def ignored(path):
    return subprocess.run(['git', 'check-ignore', '-q', path], cwd=ROOT).returncode == 0


def mask(text):
    text = text.strip()
    return (text[:3] + '***') if len(text) > 3 else '***'


def scan():
    files = git_files()
    trk = tracked()
    hits = {k: [] for k in ('phone_syn', 'names', 'secrets', 'email', 'phone', 'cpf', 'paths', 'large', 'sealed', 'envfile', 'gitignore', 'tracked_runtime')}
    scanned = 0
    for rel in files:
        if rel == SELF or rel in POLICY_DOCS:
            continue
        path = ROOT / rel
        name = path.name
        if not path.is_file():
            continue
        if name == '.env' or (name.startswith('.env.') and name != '.env.example'):
            hits['envfile'].append(f'{rel} would be published')
            continue
        size = path.stat().st_size
        if size > MAX_BYTES:
            hits['large'].append(f'{rel} ({size / 1048576:.0f} MB)')
        low = rel.lower()
        if any(s in low for s in ('sealed50', 'holdout2', '/review/', 'review/')) and not low.startswith('docs/'):
            hits['sealed'].append(f'path {rel}')
        if rel.split('/')[0] in ('runtime', 'logs') and rel != 'logs/sample_trace.jsonl':
            hits['tracked_runtime'].append(rel)
        if path.suffix.lower() not in TEXT_SUFFIX or size > CONTENT_LIMIT:
            continue
        try:
            data = path.read_text(encoding='utf-8', errors='strict')
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        numeric = path.suffix.lower() in NUMERIC_DATA
        for n, line in enumerate(data.splitlines(), 1):
            if len(line) > 4000 and numeric:
                line = line[:4000]
            for label, rx in SECRET_RULES:
                m = rx.search(line)
                if m and not PLACEHOLDER.search(line):
                    hits['secrets'].append(f'{rel}:{n} {label} ({mask(m.group(0))})')
            for m in EMAIL.finditer(line):
                if not EMAIL_OK.search(m.group(0)):
                    hits['email'].append(f'{rel}:{n} ({mask(m.group(0))})')
            if not numeric and '/vendor/' not in rel and '.min.' not in rel:
                for m in PHONE.finditer(line):
                    if PHONE_SYN.search(m.group(0)):
                        hits['phone_syn'].append(f'{rel}:{n}')
                    elif not PHONE_OK.search(m.group(0)) and 'FONE-TESTE' not in line and not re.search(r'(?i)\b(?:id|fid|osm|ts|timestamp|lat|lon|seed|version|rcpt|tile|\d{4}-\d{2}-\d{2})', line[max(0, m.start() - 14):m.end() + 4]):
                        hits['phone'].append(f'{rel}:{n} ({mask(m.group(0))})')
            for m in CPF.finditer(line):
                hits['cpf'].append(f'{rel}:{n} ({mask(m.group(0))})')
            if USER_RE.search(line):
                hits['paths'].append(f'{rel}:{n}')
            elif NAME_RE.search(line):
                hits['names'].append(f'{rel}:{n}')
            if re.search(r'(?i)review[\\/](?:sealed50|holdout2)|sealed50[\\/]|holdout2[\\/]', line) and rel.startswith(('app/', 'tools/', 'eval/', 'tests/')):
                hits['sealed'].append(f'ref {rel}:{n}')
    # .gitignore coverage
    for probe, why in ((".env", ".env"), ("runtime/x", "runtime/"), ("logs/run_x.jsonl", "logs/"), ("out/x", "out/"), ("review/x", "review/"), ("data-backup/x", "data-backup/")):
        if not ignored(probe):
            hits['gitignore'].append(f'{why} is NOT ignored')
    for t in trk:
        if t == '.env' or t.startswith(('runtime/', 'review/', 'out/')) or (t.startswith('logs/') and t != 'logs/sample_trace.jsonl'):
            hits['tracked_runtime'].append(f'tracked: {t}')
    return files, scanned, hits


ROWS = [
    ('secrets', 'Secrets / key patterns', 'FAIL'),
    ('envfile', '.env files in publishable tree', 'FAIL'),
    ('gitignore', '.gitignore covers .env, runtime/, logs/, out/, review/, data-backup/', 'FAIL'),
    ('tracked_runtime', 'Runtime/log/out/review files tracked', 'FAIL'),
    ('paths', 'Absolute personal paths / username', 'FAIL'),
    ('email', 'E-mail addresses (non-placeholder)', 'FAIL'),
    ('phone', 'Phone numbers (non-synthetic)', 'FAIL'),
    ('cpf', 'CPF numbers', 'FAIL'),
    ('large', 'Files > 50 MB', 'FAIL'),
    ('sealed', 'Sealed50 / holdout2 paths or references', 'FAIL'),
    ('phone_syn', 'Dummy phone numbers in synthetic fixtures (informational)', 'INFO'),
    ('names', 'Author first name in comments/docs (informational)', 'INFO'),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--md', type=Path, help='also write a Markdown report here')
    ap.add_argument('--show', type=int, default=8, help='max evidence lines per rule')
    args = ap.parse_args()
    files, scanned, hits = scan()
    lines = ['| Check | Result | Hits |', '|---|---|---:|']
    failed = 0
    for key, label, level in ROWS:
        n = len(hits[key])
        res = 'PASS' if n == 0 else level
        failed += n > 0 and level == 'FAIL'
        lines.append(f'| {label} | {res} | {n} |')
    head = f'Files considered: {len(files)} (text files scanned: {scanned}); commit: {subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()}'
    print(head)
    print('\n'.join(lines))
    detail = []
    for key, label, _ in ROWS:
        if hits[key]:
            detail.append(f'\n{label} - evidence (masked, first {args.show}):')
            detail += [f'  {h}' for h in hits[key][:args.show]]
    print('\n'.join(detail))
    print('\nOVERALL:', 'FAIL' if failed else 'PASS')
    if args.md:
        now = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
        md = ['# Gate 2 safety scan', '',
              f'Generated {now} (local time) by `python tools/gate2_scan.py --md out/GATE2_SCAN.md`. {head}.', '',
              'Scope: every file Git would publish (tracked plus untracked-and-not-ignored). `.env` and other `.env.*` files are never opened. Evidence is masked (path:line + first 3 characters).', '']
        md += lines
        md += ['', f'**Overall: {"FAIL" if failed else "PASS"}**', '']
        if detail:
            md += ['## Evidence', '', '```'] + detail + ['```', '']
        todo = []
        if hits['paths']:
            todo.append('Replace absolute personal paths with repo-relative or environment-driven paths (or move the file out of the public repo).')
        if hits['sealed']:
            todo.append('Remove references to sealed50/holdout2 locations from published code; those sets must never be reachable from the public tree.')
        if hits['secrets'] or hits['envfile']:
            todo.append('Remove the secret/.env file, rotate the key, and re-scan git history before pushing.')
        if hits['phone'] or hits['email'] or hits['cpf']:
            todo.append('Replace the personal-data hits with obviously fictional values.')
        if todo:
            md += ['## Fix before publishing', ''] + [f'- {t}' for t in todo] + ['']
        md += ['Informational rows: dummy phone numbers (sequential/repeated digits, `@exemplo.com`) are fictional fixtures; the author first name appears in decision comments and review metadata (decide whether you want that public).', '']
        md += ['## What the scan cannot see', '',
               '- Real people in free-text fixtures that look like ordinary words (names without digits); review `eval/*.jsonl` and `examples/` by eye.',
               '- Photos in `data/` (Wikimedia Commons, credited per file in `data/ATTRIBUTION.md`); the scan checks size only.',
               '- Git history: this scan reads the working tree. Run `git log -p` searches or a history scanner before the first push if any secret was ever committed.',
               '- Ignored folders (`runtime/`, `logs/`, `out/`, `review/`) are verified as ignored but not inspected; do not force-add them.', '']
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text('\n'.join(md), encoding='utf-8', newline='\n')
        print('wrote', args.md)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
