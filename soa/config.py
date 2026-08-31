"""Credential loading.

The environment variable wins. A .env beside the repo root is the fallback, so
the key survives across shells without living in a dotfile that gets committed
(.env is gitignored).
"""

from __future__ import annotations

import os, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_env(path: pathlib.Path | None = None) -> None:
    """Populate os.environ from a .env file, without overriding what is set."""
    for p in ([path] if path else [ROOT / ".env", ROOT.parent / ".env"]):
        if not p or not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip().removeprefix("export ").strip(), v.strip().strip("'\"")
            os.environ.setdefault(k, v)


def api_key(name: str = "ANTHROPIC_API_KEY") -> str:
    load_env()
    key = os.environ.get(name, "")
    if not key:
        raise RuntimeError(
            f"{name} is not set. Export it, or put it in {ROOT / '.env'} as "
            f"{name}=sk-ant-...")
    return key
