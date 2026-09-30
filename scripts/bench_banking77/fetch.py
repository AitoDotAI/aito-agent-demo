"""Download banking77 (PolyAI, CC BY 4.0) into data/ and check it against the pinned sha256.

    python3 scripts/bench_banking77/fetch.py
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request

from common import DATA, SHA256, SOURCE


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    for name, want in SHA256.items():
        path = DATA / name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != want:
            with urllib.request.urlopen(f"{SOURCE}/{name}", timeout=60) as r:
                path.write_bytes(r.read())
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != want:
            print(f"{name}: sha256 {got}, expected {want}. The upstream file changed; stopping.")
            return 1
        print(f"{name}: ok ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
