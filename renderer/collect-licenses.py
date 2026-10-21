"""Prints the licences of the Rust crates linked into librwgpu.a (design §3).

Reads `cargo metadata` for the macOS targets, walks rwgpu's normal (non-dev) dependency
graph, and prints each crate's name, version, licence expression and licence files.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TARGETS = ("aarch64-apple-darwin", "x86_64-apple-darwin")
LICENSE_PREFIXES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "COPYRIGHT")


def metadata(target: str) -> dict:
    out = subprocess.run(
        ["cargo", "metadata", "--format-version", "1", "--locked", "--filter-platform", target],
        check=True, capture_output=True, text=True, cwd=Path(__file__).parent,
    ).stdout
    return json.loads(out)


def linked_packages() -> dict[str, dict]:
    found: dict[str, dict] = {}
    for target in TARGETS:
        data = metadata(target)
        packages = {p["id"]: p for p in data["packages"]}
        nodes = {n["id"]: n for n in data["resolve"]["nodes"]}
        root = next(p["id"] for p in data["packages"] if p["name"] == "rwgpu")
        stack, seen = [root], set()
        while stack:
            pid = stack.pop()
            if pid in seen:
                continue
            seen.add(pid)
            for dep in nodes[pid]["deps"]:
                if any(k["kind"] in (None, "build") for k in dep["dep_kinds"]):
                    stack.append(dep["pkg"])
        for pid in seen - {root}:
            found[pid] = packages[pid]
    return found


def main() -> int:
    packages = sorted(linked_packages().values(), key=lambda p: (p["name"], p["version"]))
    print("Third-party Rust crates linked into librwgpu.a\n")
    for p in packages:
        print(f"- {p['name']} {p['version']}: {p.get('license') or 'see licence files'}")
    for p in packages:
        directory = Path(p["manifest_path"]).parent
        files = sorted(f for f in directory.iterdir() if f.is_file() and f.name.upper().startswith(LICENSE_PREFIXES))
        print("\n" + "=" * 78)
        print(f"{p['name']} {p['version']} ({p.get('license') or 'no SPDX expression'})")
        print(p.get("repository") or "")
        for f in files:
            print(f"\n--- {f.name} ---\n")
            print(f.read_text(encoding="utf-8", errors="replace").rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
