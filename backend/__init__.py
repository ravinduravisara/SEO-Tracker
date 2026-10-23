"""Load KEY=VALUE pairs from the project .env before any backend module reads os.environ.

Real environment variables always win, so hosted deployments (Vercel, Docker) are unaffected.
"""
import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
if _ENV_FILE.is_file():
    for _line in _ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _value = _line.split("=", 1)
        _value = _value.strip()
        if len(_value) >= 2 and _value[0] == _value[-1] and _value[0] in "\"'":
            _value = _value[1:-1]
        if _value:
            os.environ.setdefault(_key.strip(), _value)
