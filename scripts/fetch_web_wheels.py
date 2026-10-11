"""Download the pinned pure-Python wheels the web Studio installs.

Pins come from web/wheels.txt (``name==version`` lines). Packages Pyodide ships
(fonttools, lxml, pyclipper) are loaded from the Pyodide distribution, and the
engine itself comes from this checkout, so neither is fetched here. Writes
web/public/wheels/*.whl and manifest.json; each wheel's sha256 is checked
against PyPI.

    python scripts/fetch_web_wheels.py
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PINS = ROOT / "web" / "wheels.txt"
OUT = ROOT / "web" / "public" / "wheels"


def pins() -> list[tuple[str, str]]:
    lines = (ln.split("#", 1)[0].strip() for ln in PINS.read_text().splitlines())
    return [tuple(ln.split("==")) for ln in lines if ln]


def fetch(name: str, version: str) -> str:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json") as r:
        meta = json.load(r)
    wheel = next((u for u in meta["urls"] if u["filename"].endswith("-none-any.whl")), None)
    if wheel is None:
        raise SystemExit(f"{name}=={version} has no pure-Python wheel")
    with urllib.request.urlopen(wheel["url"]) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != wheel["digests"]["sha256"]:
        raise SystemExit(f"sha256 mismatch for {wheel['filename']}")
    (OUT / wheel["filename"]).write_bytes(data)
    return wheel["filename"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.whl"):
        old.unlink()
    files = [fetch(name, version) for name, version in pins()]
    (OUT / "manifest.json").write_text(json.dumps({"wheels": files}, indent=2) + "\n")
    print("\n".join(files))


if __name__ == "__main__":
    main()
