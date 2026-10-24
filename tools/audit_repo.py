"""Small packaging check; prints paths/counts only, never matching secret values."""
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT


def audit():
    files = [p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.relative_to(ROOT).parts]
    public = [p for p in files if not any(part in p.relative_to(ROOT).parts
              for part in ('runtime', '.tmp', '__pycache__'))
              and ('logs' not in p.relative_to(ROOT).parts or p.name == 'sample_trace.jsonl')
              and p.name != '.env']
    patterns = {
        'CPF_like': r'(?<!\w)\d{3}\.?\d{3}\.?\d{3}[- ]?\d{2}(?!\w)',
        'phone_like': r'(?<!\w)(?:\+55[ -]*)?\(?\d{2}\)?[ -]+9?\d{4}[- ]\d{4}(?!\w)',
        'credential_prefix': r'(?:sk-proj-|sk-ant-|ghp_)[A-Za-z0-9_-]{15,}',
    }
    findings = {k: [] for k in patterns}
    for path in public:
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            continue
        for key, pattern in patterns.items():
            if re.search(pattern, text):
                findings[key].append(str(path.relative_to(ROOT)))
    result = {'bytes_excluding_git': sum(p.stat().st_size for p in files),
              'public_files': len(public), 'public_bytes': sum(p.stat().st_size for p in public),
              'findings_paths_only': findings,
              'scope': 'Heuristic pattern scan, not proof of absence of every possible secret.'}
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    result = audit()
    sys.exit(int(result['bytes_excluding_git'] >= 25*1024*1024 or any(result['findings_paths_only'].values())))
