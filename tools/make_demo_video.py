"""Render the demo showcase video, synced to the narration.

Regenerate:
    py -3.13 tools/make_narration.py            # narration -> docs/demo.mp3 + timings
    py -3.13 tools/make_demo_video.py           # picture, synced to those timings

Produces:
    docs/demo.mp4         1760x990 @ 60fps H.264, silent master
    docs/demo-voiced.mp4  same picture + narration (AAC)
    docs/demo.gif         880px palette-optimised, for the README hero

Pacing is driven by tools/narration-timing.json when present: each beat of the
picture is stretched to its narration *span* (spoken line plus the trailing
silence), so audio and video stay in step. Pacing to speech length alone would
advance the picture one gap ahead of the audio on every beat.

Content is the real verified `riskgovernor demo` output, abridged for pacing;
every verdict, sizing and halving value is what the tool prints.

Dependencies: Pillow, imageio-ffmpeg.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
MP4 = DOCS / "demo.mp4"
VOICED = DOCS / "demo-voiced.mp4"
GIF = DOCS / "demo.gif"
NARRATION = DOCS / "demo.mp3"
TIMING = REPO / "tools" / "narration-timing.json"

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# -- geometry (rendered at 2x for crispness) -------------------------------------
W, H = 1760, 990
TITLE_H = 64
MARGIN_X = 56
LINE_H = 44
FPS = 60
CHAR_FRAMES = 2  # frames per typed character

BG = (13, 17, 23)
TITLE_BG = (22, 27, 34)
BORDER = (48, 54, 61)
FG = (201, 209, 216)
DIM = (139, 148, 158)
GREEN = (63, 185, 80)
WHITE = (240, 246, 252)
BLUE = (88, 166, 255)
YELLOW = (227, 179, 81)
RED = (248, 81, 73)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("consola.ttf", "CascadiaCode.ttf", "lucon.ttf", "cour.ttf"):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except OSError:
            continue
    raise RuntimeError("no monospace TrueType font found in C:/Windows/Fonts")


FONT = load_font(30)
CURSOR_W = 17


def text_width(s: str) -> int:
    return FONT.getbbox(s)[2] if s else 0


Line = tuple[str, tuple[int, int, int]]

# -- beats: each key matches a narration segment --------------------------------
# ("type", command)          prompt command, typed char by char
# ("line", (text, colour))   program output, prints instantly
# ("gap", None)              blank output line
BEATS: list[tuple[str, list[tuple[str, object]]]] = [
    ("intro", [
        ("type", "pip install riskgovernor"),
        ("line", ("Successfully installed riskgovernor-0.1.0", DIM)),
        ("type", "riskgovernor demo"),
        ("gap", None),
        ("line", ("riskgovernor demo - every verdict, in order. Nothing touches disk.", BLUE)),
    ]),
    ("s1", [
        ("gap", None),
        ("line", ("1. A fresh session. Nothing has happened, so every strategy is", FG)),
        ("line", ("   on the table and the choice is yours:", FG)),
        ("line", ("VERDICT: STANDARD", BLUE)),
        ("line", ("  [1] python my_runner.py 1 steady.json --note \"E1 steady standard streak=0\"", DIM)),
        ("line", ("  [2] python my_runner.py 1 defensive.json --note \"E1 defensive standard streak=0\"", DIM)),
        ("line", ("  [3] python my_runner.py 1 aggressive.json --note \"E1 aggressive standard streak=0\"", DIM)),
    ]),
    ("s2", [
        ("gap", None),
        ("line", ("2. Episode 1 ran 'steady' and lost 120. The governor rotates AWAY", FG)),
        ("line", ("   from the loser and sizes the recovery to the loss:", FG)),
        ("line", ("VERDICT: RECOVERY defensive", YELLOW)),
        ("line", ("  set max_profit = 120", GREEN)),
        ("line", ("  set base_stake = 50", GREEN)),
    ]),
    ("s3", [
        ("gap", None),
        ("line", ("3. Episode 2 ran 'defensive' and lost 80. Two losses in a row:", FG)),
        ("line", ("   rotation moves on AND the stake is halved:", FG)),
        ("line", ("VERDICT: RECOVERY aggressive", YELLOW)),
        ("line", ("  set max_profit = 80", GREEN)),
        ("line", ("  set base_stake = 25", GREEN)),
    ]),
    ("s4", [
        ("gap", None),
        ("line", ("4. A third consecutive loss trips the streak gate. Hard stop:", FG)),
        ("line", ("VERDICT: HALT (3 consecutive losses)", RED)),
    ]),
    ("s5", [
        ("gap", None),
        ("line", ("5. Equity below the floor halts everything, whatever the ledger", FG)),
        ("line", ("   says. Gate 1 always wins:", FG)),
        ("line", ("VERDICT: HALT (equity below floor)", RED)),
    ]),
    ("s6", [
        ("gap", None),
        ("line", ("6. An operator override is recorded - never silent. The streak", FG)),
        ("line", ("   clears, but the override count is on the record:", FG)),
        ("line", ("overrides used: 1", YELLOW)),
        ("line", ("VERDICT: RECOVERY steady", YELLOW)),
    ]),
    ("close", [
        ("gap", None),
        ("line", ("Gates halt, losses rotate, recovery is sized to the loss,", FG)),
        ("line", ("and overrides are on the record.", FG)),
        ("gap", None),
        ("line", ("pip install riskgovernor  |  riskgovernor demo", GREEN)),
        ("line", ("github.com/kingkillery/riskgovernor", BLUE)),
    ]),
]

FALLBACK_SECONDS = {
    "intro": 4.5, "s1": 5.0, "s2": 7.0, "s3": 2.4,
    "s4": 2.8, "s5": 4.0, "s6": 4.2, "close": 5.2,
}


def load_timings() -> dict[str, float]:
    """Beat -> span in seconds (spoken line plus its trailing silence).

    Spans, not speech durations: the audio file contains a gap after every
    beat, so pacing to speech length alone would advance the picture ahead of
    the narration by one gap on every beat.
    """
    if TIMING.exists():
        data = json.loads(TIMING.read_text(encoding="utf-8"))
        beats = data.get("beats") or {}
        if beats:
            print(f"pacing: {TIMING.name} ({data.get('_total', '?')}s narration)")
            return {k: float(v["span"]) for k, v in beats.items()}
    print("pacing: no narration timings found, using fallback")
    return dict(FALLBACK_SECONDS)


def viewport_rows() -> int:
    return (H - TITLE_H - 40) // LINE_H


class Terminal:
    """Scrollback buffer + fractional pixel scroll for smooth motion."""

    def __init__(self) -> None:
        self.lines: list[Line] = []
        self.scroll_px = 0.0

    def append(self, line: Line) -> None:
        self.lines.append(line)

    def scroll_target(self) -> float:
        overflow = max(0, len(self.lines) - viewport_rows())
        return overflow * LINE_H

    def ease_scroll(self, fraction: float) -> bool:
        target = self.scroll_target()
        gap = target - self.scroll_px
        if gap <= 0.5:
            self.scroll_px = target
            return False
        self.scroll_px += gap * fraction
        return True


def draw_frame(term: Terminal, cursor_line: Line | None = None) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([0, 0, W - 1, TITLE_H - 1], radius=10, fill=TITLE_BG)
    d.rectangle([0, TITLE_H - 12, W - 1, TITLE_H - 1], fill=TITLE_BG)
    for i, colour in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = 34 + i * 44
        d.ellipse([cx, 22, cx + 20, 42], fill=colour)
    title = "riskgovernor - demo"
    d.text((W // 2 - text_width(title) // 2, 22), title, font=FONT, fill=DIM)
    d.line([0, TITLE_H, W, TITLE_H], fill=BORDER)

    base_y = TITLE_H + 26
    offset = term.scroll_px
    start_idx = int(offset // LINE_H)
    sub = offset - start_idx * LINE_H
    y = base_y - sub
    for text, colour in term.lines[start_idx:]:
        if TITLE_H <= y and y + LINE_H <= H:
            d.text((MARGIN_X, y), text, font=FONT, fill=colour)
        y += LINE_H

    if cursor_line is not None:
        text, colour = cursor_line
        if y + LINE_H <= H:
            d.rectangle(
                [MARGIN_X + text_width(text) + 6, y + 6,
                 MARGIN_X + text_width(text) + 6 + CURSOR_W, y + LINE_H - 10],
                fill=colour,
            )
    return img


def beat_instant_frames(term: Terminal, events) -> list[Image.Image]:
    """Frames for a beat's actual content: typing, printing, scrolling."""
    out: list[Image.Image] = []

    def settle(steps: int = 8) -> None:
        for _ in range(steps):
            if not term.ease_scroll(0.34):
                break
            out.append(draw_frame(term))

    for kind, payload in events:
        if kind == "type":
            for i in range(1, len(payload) + 1):
                typed = "$ " + payload[:i]
                for _ in range(CHAR_FRAMES):
                    out.append(draw_frame(term, cursor_line=(typed, WHITE)))
            term.append(("$ " + payload, WHITE))
            settle()
        elif kind == "line":
            term.append(payload)
            out.append(draw_frame(term))
            out.append(draw_frame(term))
            settle()
        elif kind == "gap":
            term.append(("", FG))
            out.append(draw_frame(term))
            settle(4)
    return out


def build_frames():
    timings = load_timings()
    term = Terminal()
    total = 0
    for key, events in BEATS:
        instant = beat_instant_frames(term, events)
        target = round(timings.get(key, FALLBACK_SECONDS.get(key, 3.0)) * FPS)
        yield from instant
        total += len(instant)
        pad = max(0, target - len(instant))
        if instant and pad == 0 and target > 0:
            print(f"  note: beat {key!r} content ({len(instant)}f) exceeded its "
                  f"narration slot ({target}f)")
        last = term.lines[-1] if term.lines else ("", FG)
        for i in range(pad):
            blink = (i // 22) % 2 == 0
            yield draw_frame(term, cursor_line=(last[0], WHITE) if blink else ("", WHITE))
        total += pad
    while term.ease_scroll(0.2):
        yield draw_frame(term)
        total += 1
    print(f"picture: {total} frames = {total / FPS:.1f}s")


def encode_mp4(frames, dest: Path) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
        "-i", "-",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(dest),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    count = 0
    for frame in frames:
        proc.stdin.write(frame.tobytes())
        count += 1
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        sys.exit(f"ffmpeg encode failed with {proc.returncode}")
    print(f"mp4: {count} frames, {count / FPS:.1f}s -> {dest.name} "
          f"({dest.stat().st_size / 1e6:.1f} MB)")


def mux_narration() -> None:
    if not NARRATION.exists():
        print(f"no narration at {NARRATION}; skipping voiced master")
        return
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error",
         "-i", str(MP4), "-i", str(NARRATION),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
         "-map", "0:v:0", "-map", "1:a:0", "-shortest",
         "-movflags", "+faststart", str(VOICED)],
        check=True,
    )
    print(f"voiced: -> {VOICED.name} ({VOICED.stat().st_size / 1e6:.1f} MB)")


def encode_gif() -> None:
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(MP4), "-vf",
         "fps=12,scale=880:-1:flags=lanczos,split[s0][s1];"
         "[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4",
         "-loop", "0", str(GIF)],
        check=True,
    )
    print(f"gif: -> {GIF.name} ({GIF.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    encode_mp4(build_frames(), MP4)
    mux_narration()
    encode_gif()


if __name__ == "__main__":
    main()