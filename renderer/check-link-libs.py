"""Fails when the Rust static library needs a system library missing from link-libs.txt.

The Builder links exactly the libraries in link-libs.txt (Phase 2 design, section 6.1);
this compares them with what `rustc --print native-static-libs` reports.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMPLICIT = {"System"}  # libSystem is always linked on macOS


def reported(target: str) -> set[str]:
    out = subprocess.run(
        ["cargo", "rustc", "--release", "--locked", "-p", "rwgpu", "--target", target, "--crate-type", "staticlib",
         "--", "--print", "native-static-libs"],
        cwd=HERE, capture_output=True, text=True, check=True,
    ).stderr
    line = next(l for l in out.splitlines() if "native-static-libs:" in l)
    tokens = line.split("native-static-libs:", 1)[1].split()
    libs, i = set(), 0
    while i < len(tokens):
        if tokens[i] == "-framework":
            libs.add(f"framework:{tokens[i + 1]}")
            i += 2
            continue
        match = re.fullmatch(r"-l(.+)", tokens[i])
        if match and match.group(1) not in IMPLICIT:
            libs.add(match.group(1))
        i += 1
    return libs


def main() -> int:
    listed = {l.strip() for l in (HERE / "link-libs.txt").read_text().splitlines() if l.strip()}
    missing = set()
    for target in sys.argv[1:] or ["aarch64-apple-darwin"]:
        missing |= reported(target) - listed
    if missing:
        print("link-libs.txt lacks: " + ", ".join(sorted(missing)), file=sys.stderr)
        return 1
    print("link-libs.txt covers the static library's native libraries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
