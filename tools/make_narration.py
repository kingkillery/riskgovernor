"""Generate the demo narration as per-scene segments and assemble the full MP3.

    py -3.13 tools/make_narration.py [extra-output-dir]

Writes the narration to docs/demo.mp3 in this repo (where the video tooling
expects it) and, if an extra directory is given, copies it there too.

Also writes tools/narration-timing.json:

    {"beats": {"hook": {"dur": 9.8, "span": 10.2, "start": 0.0}, ...},
     "_total": 74.9, "_gap_ms": 380}

`dur` is the spoken line, `span` is the line plus the trailing silence, and
`start` is the scene's offset in the assembled file. make_demo_video.py paces
each scene to its `span` so picture and audio stay in step.

Dependencies: edge-tts (neural TTS), imageio-ffmpeg (concat + probing).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg

REPO = Path(__file__).resolve().parent.parent
TIMING = REPO / "tools" / "narration-timing.json"

VOICE = "en-US-AndrewMultilingualNeural"
RATE = "+5%"
GAP_MS = 380  # silence between scenes

# key -> spoken line. Keys match the scene names used by the video renderer.
SEGMENTS: list[tuple[str, str]] = [
    ("hook",
     "Every trading bot has risk rules. And almost all of them share one flaw: "
     "the rules live inside the bot. The day they become inconvenient, someone "
     "switches them off. That is how accounts die."),
    ("what",
     "riskgovernor puts the rules somewhere your bot cannot touch. A pure "
     "decision engine: your ledger, your equity, and your policy go in. One "
     "allowed action comes out."),
    ("gates",
     "The hard gates come first. Equity below the floor: halt. Three losses in "
     "a row: halt. Drawdown past the limit: halt. No strategy gets a vote, and "
     "nothing inside the loop can wave it through."),
    ("rotation",
     "Then rotation. After a loss, the governor never re-runs the strategy that "
     "just lost. It rotates forward and sizes the recovery to the size of that "
     "loss. One twenty lost means one twenty targeted, and stakes halve as "
     "losses stack."),
    ("overrides",
     "And when you override it - and someday you will - the override is written "
     "into the ledger. Counted. Visible on every run that follows."),
    ("benefits",
     "Pure Python. Zero dependencies. A pure function you can unit test. If you "
     "run anything with a bankroll - trading bots, backtests, poker sessions - "
     "the risk rules belong outside it."),
    ("cta",
     "pip install riskgovernor. The governor decides. You approve."),
]


def ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def duration_s(path: Path) -> float:
    """Read a media file's duration via ffmpeg's stderr banner."""
    out = subprocess.run([ffmpeg(), "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out)
    if not m:
        raise RuntimeError(f"could not read duration of {path}")
    h, mm, s = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(s)


def synth(text: str, out: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "edge_tts", "--voice", VOICE, "--rate", RATE,
         "--text", text, "--write-media", str(out)],
        check=True, capture_output=True,
    )


def main() -> None:
    extra = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    out_dir = REPO / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix="rg_narr_"))
    silence = work / "silence.mp3"
    subprocess.run(
        [ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "anullsrc=r=24000:cl=mono", "-t", str(GAP_MS / 1000), str(silence)],
        check=True,
    )

    beats: dict[str, dict[str, float]] = {}
    concat_lines: list[str] = []
    cursor = 0.0
    last = len(SEGMENTS) - 1
    for idx, (key, text) in enumerate(SEGMENTS):
        seg = work / f"{key}.mp3"
        synth(text, seg)
        dur = duration_s(seg)
        span = dur + (0.0 if idx == last else GAP_MS / 1000)
        beats[key] = {
            "dur": round(dur, 3),
            "span": round(span, 3),
            "start": round(cursor, 3),
        }
        cursor += span
        concat_lines.append(f"file '{seg.as_posix()}'")
        if idx != last:
            concat_lines.append(f"file '{silence.as_posix()}'")

    list_file = work / "concat.txt"
    list_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    target = out_dir / "demo.mp3"

    # Re-encode rather than stream-copy: concatenating discrete MP3s with
    # -c copy leaves non-monotonic timestamps at the joins, which can click.
    subprocess.run(
        [ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(list_file), "-c:a", "libmp3lame", "-b:a", "96k",
         "-ar", "24000", "-ac", "1", str(target)],
        check=True,
    )

    total = duration_s(target)
    TIMING.parent.mkdir(parents=True, exist_ok=True)
    TIMING.write_text(
        json.dumps(
            {"beats": beats, "_total": round(total, 3), "_gap_ms": GAP_MS}, indent=1
        ) + "\n",
        encoding="utf-8",
    )

    print(f"voice: {VOICE}  rate: {RATE}")
    print(f"{'scene':>10} {'speech':>8} {'span':>8} {'start':>8}")
    for key, _ in SEGMENTS:
        b = beats[key]
        print(f"{key:>10} {b['dur']:>8.3f} {b['span']:>8.3f} {b['start']:>8.3f}")
    print(f"{'TOTAL':>10} {'':>8} {cursor:>8.3f}  (file {total:.3f}s)")
    print(f"\nwrote {target} ({target.stat().st_size / 1e3:.0f} kB)")
    if extra is not None:
        extra.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, extra / "demo.mp3")
        print(f"copied -> {extra / 'demo.mp3'}")
    print(f"wrote {TIMING}")


if __name__ == "__main__":
    main()