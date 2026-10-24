"""Environment-only settings. Importing this module never contacts a service."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env(path=None):
    path = Path(path or ROOT / '.env')
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"\''))


def sample_mode():
    return os.getenv('SAMPLE_MODE', '').lower() in ('true', '1', 'yes')


def setting(name, default=''):
    return os.getenv(name, default)


def safe_error(exc):
    # Provider bodies may echo SQL credentials or input; never expose them.
    return type(exc).__name__
