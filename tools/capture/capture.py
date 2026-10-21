"""Reproducible captures of reVC builds for comparing renderers (Phase 2 design, §10).

Development tool, not part of the Builder. Standard library only.

    python3 tools/capture/capture.py prepare --home H --renderer gl3|wgpu [--rwgpu-dir D] GAME
        Runs the Builder from fetch to verify in H (nothing is installed), applies
        revc-capture-harness.patch to H's reVC checkout and rebuilds the build directory.
    python3 tools/capture/capture.py run --home H --renderer R --game G --out DIR [options]
        Writes the capture settings and GamePath=G into H's reVC.ini, starts the rebuilt
        reVC.app with HOME=H, the harness and the frame dumps switched on, and stops it
        after the last requested frame (or the timeout). Give each renderer its own copy of
        the game data (txd.img and CAPS.DAT differ per renderer), e.g. an APFS clone made
        with `cp -cR`.
    python3 tools/capture/capture.py compare A.png B.png --out PREFIX
        Prints MAE, share of pixels differing by more than 16 and PSNR, and writes
        PREFIX-side-by-side.png and PREFIX-diff.png.

Frame dumps of the game are copyrighted content: keep them out of the repository.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import signal
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent / "revc-capture-harness.patch"


# --- PNG (8-bit RGB/RGBA, non-interlaced) --------------------------------------------------


def read_png(path: Path) -> tuple[int, int, bytearray]:
    """Returns (width, height, RGB bytes, top row first); grey, RGB, grey+alpha or RGBA input."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    pos, idat, width = 8, b"", 0
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
            if depth != 8 or color not in (0, 2, 4, 6) or interlace:
                raise ValueError(f"{path}: unsupported PNG (depth {depth}, colour {color}, interlace {interlace})")
            channels = {0: 1, 2: 3, 4: 2, 6: 4}[color]
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"IEND":
            break
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * channels
    out = bytearray(width * height * 3)
    prev = bytearray(stride)
    for y in range(height):
        filt = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if filt == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 255
        elif filt == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif filt == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif filt == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 255
        if channels == 3:
            out[y * width * 3:(y + 1) * width * 3] = line
        else:
            row = out[y * width * 3:(y + 1) * width * 3]
            if channels >= 3:
                row[0::3], row[1::3], row[2::3] = line[0::4], line[1::4], line[2::4]
            else:
                grey = line[0::channels]
                row[0::3], row[1::3], row[2::3] = grey, grey, grey
            out[y * width * 3:(y + 1) * width * 3] = row
        prev = line
    return width, height, out


def write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    raw = b"".join(b"\0" + bytes(rgb[y * width * 3:(y + 1) * width * 3]) for y in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# --- comparison --------------------------------------------------------------------------------


def compare(a: Path, b: Path, out_prefix: Path | None = None) -> dict:
    wa, ha, pa = read_png(a)
    wb, hb, pb = read_png(b)
    if (wa, ha) != (wb, hb):
        raise ValueError(f"sizes differ: {wa}x{ha} and {wb}x{hb}")
    n = wa * ha
    total_abs = 0
    total_sq = 0
    over16 = 0
    diff = bytearray(n * 3)
    for i in range(n):
        j = i * 3
        d0 = abs(pa[j] - pb[j])
        d1 = abs(pa[j + 1] - pb[j + 1])
        d2 = abs(pa[j + 2] - pb[j + 2])
        total_abs += d0 + d1 + d2
        total_sq += d0 * d0 + d1 * d1 + d2 * d2
        m = max(d0, d1, d2)
        if m > 16:
            over16 += 1
        v = min(255, m * 4)
        diff[j] = v
        diff[j + 1] = v if m <= 16 else 0
        diff[j + 2] = v if m <= 16 else 0
    mse = total_sq / (n * 3)
    result = {
        "a": str(a),
        "b": str(b),
        "size": [wa, ha],
        "mae": total_abs / (n * 3),
        "over16_percent": 100.0 * over16 / n,
        "psnr_db": float("inf") if mse == 0 else 10 * math.log10(255 * 255 / mse),
    }
    if out_prefix is not None:
        side = bytearray(n * 2 * 3)
        for y in range(ha):
            row = y * wa * 3
            side[y * wa * 6:y * wa * 6 + wa * 3] = pa[row:row + wa * 3]
            side[y * wa * 6 + wa * 3:(y + 1) * wa * 6] = pb[row:row + wa * 3]
        write_png(Path(f"{out_prefix}-side-by-side.png"), wa * 2, ha, side)
        write_png(Path(f"{out_prefix}-diff.png"), wa, ha, diff)
    return result


# --- running ---------------------------------------------------------------------------------------


def locations(home: Path, renderer: str) -> tuple[Path, Path, Path]:
    cache = home / "Library" / "Caches" / "reVC Builder"
    build = cache / "build" / ("reVC" if renderer == "gl3" else f"reVC-{renderer}")
    return cache / "src" / "reVC", build, home / "Library" / "Application Support" / "reVC" / "reVC.ini"


def set_ini(path: Path, values: dict[str, dict[str, str]]) -> None:
    """Sets keys in reVC.ini, keeping every other line."""
    lines = path.read_text().splitlines() if path.exists() else []
    for section, keys in values.items():
        header = f"[{section}]"
        if header not in [line.strip() for line in lines]:
            lines += ["", header]
        start = [line.strip() for line in lines].index(header) + 1
        end = start
        while end < len(lines) and not lines[end].strip().startswith("["):
            end += 1
        for key, value in keys.items():
            for i in range(start, end):
                if lines[i].split("=", 1)[0].strip() == key:
                    lines[i] = f"{key}={value}"
                    break
            else:
                lines.insert(end, f"{key}={value}")
                end += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def cmd_prepare(args) -> int:
    builder = [sys.executable, "-m", "vcbuilder", str(args.game), "--home", str(args.home), "--renderer", args.renderer,
               "--from-stage", "fetch", "--stop-after", "verify"]
    if args.rwgpu_dir:
        builder += ["--rwgpu-dir", str(args.rwgpu_dir)]
    subprocess.run(builder, check=True, cwd=REPO)
    checkout, build, _ = locations(args.home, args.renderer)
    subprocess.run(["/usr/bin/git", "-C", str(checkout), "apply", str(HARNESS)], check=True)
    from vcbuilder.toolchain import cmake_executable  # the Builder's pinned CMake

    cmake = str(cmake_executable())
    env = {"HOME": os.environ["HOME"], "PATH": f"/usr/bin:/bin:{Path(cmake).parent}", "LC_ALL": "C"}
    subprocess.run([cmake, str(build)], check=True, env=env)  # new harness files: re-glob
    subprocess.run([cmake, "--build", str(build)], check=True, env=env)
    return 0


def cmd_run(args) -> int:
    _, build, ini = locations(args.home, args.renderer)
    app = build / "src" / "reVC.app" / "Contents" / "MacOS" / "reVC"
    graphics = {"VSync": str(args.vsync), "FrameLimiter": str(args.frame_limiter)}
    set_ini(ini, {
        "VideoMode": {"Width": str(args.width), "Height": str(args.height), "Depth": "32", "Windowed": "1"},
        "Graphics": graphics,
        "Rendering": {"NewRenderer": "0"},
        "General": {"NoMovies": "1", "GamePath": str(args.game)},
    })
    args.out.mkdir(parents=True, exist_ok=True)
    frames = sorted(int(f) for f in args.frames.split(",") if f) if args.frames else []
    env = dict(os.environ, HOME=str(args.home), REVC_FRAME_DUMP_DIR=str(args.out),
               REVC_FRAME_DUMP_FRAMES=",".join(map(str, frames)), REVC_FRAME_STATS=str(args.stats))
    if not args.no_capture:
        env.update(REVC_CAPTURE="1", REVC_CAPTURE_NEWGAME=str(args.newgame), REVC_CAPTURE_SKIPCUTSCENE=str(args.skip),
                   REVC_CAPTURE_WINDOW=args.window, REVC_CAPTURE_WEATHER=args.weather)
    log = (args.out / "run.log").open("w")
    process = subprocess.Popen([str(app)], env=env, stdout=log, stderr=subprocess.STDOUT, cwd="/")
    print(f"reVC started (PID {process.pid}); stop it with: kill {process.pid}", flush=True)
    deadline = time.monotonic() + args.timeout
    last = args.out / f"frame-{frames[-1]:06d}.png" if frames else None
    rss = []
    try:
        while time.monotonic() < deadline and process.poll() is None:
            if last is not None and last.exists():
                time.sleep(1.0)
                break
            if args.sample_rss:
                out = subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(process.pid)], capture_output=True, text=True)
                if out.stdout.strip():
                    rss.append((round(args.timeout - (deadline - time.monotonic()), 1), int(out.stdout.strip())))
            time.sleep(args.sample_rss or 0.5)
    finally:
        crashed = process.poll()
        if crashed is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        log.close()
    summary = {"exit_status_before_stop": crashed, "rss_kib": rss}
    (args.out / "run.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({"exit_status_before_stop": crashed, "rss_samples": len(rss)}))
    return 0 if crashed is None else 1


def cmd_compare(args) -> int:
    result = compare(args.a, args.b, args.out)
    print(json.dumps(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("game", type=Path)
    p.add_argument("--home", type=Path, required=True)
    p.add_argument("--renderer", choices=["gl3", "wgpu"], required=True)
    p.add_argument("--rwgpu-dir", type=Path)
    p.set_defaults(func=cmd_prepare)
    r = sub.add_parser("run")
    r.add_argument("--home", type=Path, required=True)
    r.add_argument("--renderer", choices=["gl3", "wgpu"], required=True)
    r.add_argument("--game", type=Path, required=True, help="game data folder (written as GamePath)")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--window", default="960x540", help="window size in screen points")
    r.add_argument("--frames", default="")
    r.add_argument("--newgame", type=int, default=0)
    r.add_argument("--skip", type=int, default=0)
    r.add_argument("--weather", default="", help="<frame>:<weather>, e.g. 3000:2 forces rain at frame 3000")
    r.add_argument("--stats", type=int, default=0)
    r.add_argument("--timeout", type=float, default=120.0)
    r.add_argument("--width", type=int, default=1280)
    r.add_argument("--height", type=int, default=720)
    r.add_argument("--vsync", type=int, default=1)
    r.add_argument("--frame-limiter", type=int, default=0)
    r.add_argument("--no-capture", action="store_true", help="no harness: real time and input")
    r.add_argument("--sample-rss", type=float, default=0.0, help="sample resident memory every N seconds")
    r.set_defaults(func=cmd_run)
    c = sub.add_parser("compare")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    c.add_argument("--out", type=Path)
    c.set_defaults(func=cmd_compare)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
