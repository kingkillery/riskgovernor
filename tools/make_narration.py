"""Generate the demo narration as per-beat segments and assemble the full MP3.

    py -3.13 tools/make_narration.py [extra-output-dir]

Writes the narration to docs/demo.mp3 in this repo (where the video tooling
expects it) and, if an extra directory is given, copies it there too.

Also writes tools/narration-timing.json:

    {"beats": {"intro": {"dur": 4.51, "span": 4.89, "start": 0.0}, ...},
     "_total": 37.99, "_gap_ms": 380}

`dur` is the spoken line, `span` is the line plus the trailing silence, and
`start` is the beat's offset in the assembled file. make_demo_video.py paces
each beat to its `span` - not its `dur` - so the picture advances in step with
the audio instead of drifting a gap further ahead on every beat.

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
RATE = "+6%"
GAP_MS = 380  # silence between beats

# key -> spoken line. Keys match the beat names used by the video renderer.
SEGMENTS: list[tuple[str, str]] = [
    ("intro", "Install it. Then one command. The demo walks through every verdict."),
    ("s1", "A fresh session. Every strategy is on the table, and the choice is yours."),
    ("s2", "Then a loss. It rotates away from the loser, and sizes the recovery "
           "to the loss. One twenty."),
    ("s3", "A second loss, and the stake halves."),
    ("s4", "A third consecutive loss, and it stops."),
    ("s5", "Equity below the floor? It stops too, whatever the ledger says."),
    ("s6", "And every override is recorded. Counted. Never silent."),
    ("close", "riskgovernor. Gates halt. Losses rotate. Overrides leave a trail."),
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
    print(f"{'beat':>6} {'speech':>8} {'span':>8} {'start':>8}")
    for key, _ in SEGMENTS:
        b = beats[key]
        print(f"{key:>6} {b['dur']:>8.3f} {b['span']:>8.3f} {b['start']:>8.3f}")
    print(f"{'TOTAL':>6} {'':>8} {cursor:>8.3f}  (file {total:.3f}s)")
    print(f"\nwrote {target} ({target.stat().st_size / 1e3:.0f} kB)")
    if extra is not None:
        extra.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, extra / "demo.mp3")
        print(f"copied -> {extra / 'demo.mp3'}")
    print(f"wrote {TIMING}")


if __name__ == "__main__":
    main()