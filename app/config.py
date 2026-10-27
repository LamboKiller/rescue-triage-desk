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


# Official template names, read only when the Nightshift name is unset.
ALIASES = {'NIGHTSHIFT_BASE_URL': 'METERLESS_BASE_URL', 'NIGHTSHIFT_API_KEY': 'METERLESS_RUNTIME_TOKEN'}


def setting(name, default=''):
    value = os.getenv(name)
    if value is None and name in ALIASES:
        value = os.getenv(ALIASES[name])
    return default if value is None else value


def safe_error(exc):
    # Provider bodies may echo SQL credentials or input; never expose them.
    return type(exc).__name__
