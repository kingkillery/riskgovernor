"""Render the demo showcase video (MP4 + GIF) from the real demo output.

Regenerate:  py -3.13 tools/make_demo_video.py

Produces:
    docs/demo.mp4   1760x990 @ 60fps H.264 (crf 18) - the showcase video
    docs/demo.gif   880px wide, palette-optimised    - README hero

Content is the actual verified output of `riskgovernor demo`, abridged for
pacing; every verdict, sizing and halving value is exactly what the tool
prints. Commands are typed; program output prints instantly - as a real
terminal behaves.

Dependencies: Pillow, imageio-ffmpeg.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
MP4 = DOCS / "demo.mp4"
GIF = DOCS / "demo.gif"

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# -- geometry (rendered at 2x for crispness) -------------------------------------
W, H = 1760, 990
TITLE_H = 64
MARGIN_X = 56
LINE_H = 44
FPS = 60

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
CURSOR_W = 17  # roughly one character cell


def text_width(s: str) -> int:
    return FONT.getbbox(s)[2] if s else 0


Line = tuple[str, tuple[int, int, int]]

# -- the script ------------------------------------------------------------------
# ("type", command)             a prompt command, typed char by char
# ("line", (text, colour))      program output, prints instantly
# ("beat", frames)              hold
# ("gap", None)                 blank output line
SCRIPT: list[tuple[str, object]] = [
    ("type", "pip install riskgovernor"),
    ("beat", 22),
    ("line", ("Successfully installed riskgovernor-0.1.0", DIM)),
    ("beat", 50),
    ("type", "riskgovernor demo"),
    ("beat", 16),
    ("gap", None),
    ("line", ("riskgovernor demo - every verdict, in order. Nothing touches disk.", BLUE)),
    ("gap", None),
    ("line", ("1. A fresh session. Nothing has happened, so every strategy is", FG)),
    ("line", ("   on the table and the choice is yours:", FG)),
    ("line", ("VERDICT: STANDARD", BLUE)),
    ("line", ("  [1] python my_runner.py 1 steady.json --note \"E1 steady standard streak=0\"", DIM)),
    ("line", ("  [2] python my_runner.py 1 defensive.json --note \"E1 defensive standard streak=0\"", DIM)),
    ("line", ("  [3] python my_runner.py 1 aggressive.json --note \"E1 aggressive standard streak=0\"", DIM)),
    ("gap", None),
    ("line", ("2. Episode 1 ran 'steady' and lost 120. The governor rotates AWAY", FG)),
    ("line", ("   from the loser and sizes the recovery to the loss:", FG)),
    ("line", ("VERDICT: RECOVERY defensive", YELLOW)),
    ("line", ("  set max_profit = 120", GREEN)),
    ("line", ("  set base_stake = 50", GREEN)),
    ("gap", None),
    ("line", ("3. Episode 2 ran 'defensive' and lost 80. Two losses in a row:", FG)),
    ("line", ("   rotation moves on AND the stake is halved:", FG)),
    ("line", ("VERDICT: RECOVERY aggressive", YELLOW)),
    ("line", ("  set max_profit = 80", GREEN)),
    ("line", ("  set base_stake = 25", GREEN)),
    ("gap", None),
    ("line", ("4. A third consecutive loss trips the streak gate. Hard stop:", FG)),
    ("line", ("VERDICT: HALT (3 consecutive losses)", RED)),
    ("gap", None),
    ("line", ("5. Equity below the floor halts everything, whatever the ledger", FG)),
    ("line", ("   says. Gate 1 always wins:", FG)),
    ("line", ("VERDICT: HALT (equity below floor)", RED)),
    ("gap", None),
    ("line", ("6. An operator override is recorded - never silent. The streak", FG)),
    ("line", ("   clears, but the override count is on the record:", FG)),
    ("line", ("overrides used: 1", YELLOW)),
    ("line", ("VERDICT: RECOVERY steady", YELLOW)),
    ("gap", None),
    ("line", ("Gates halt, losses rotate, recovery is sized to the loss,", FG)),
    ("line", ("and overrides are on the record.", FG)),
    ("gap", None),
    ("line", ("pip install riskgovernor  |  riskgovernor demo", GREEN)),
    ("line", ("github.com/kingkillery/riskgovernor", BLUE)),
    ("beat", 260),
]


def viewport_rows() -> int:
    return (H - TITLE_H - 40) // LINE_H


class Terminal:
    """Scrollback buffer + fractional pixel scroll for smooth motion."""

    def __init__(self) -> None:
        self.lines: list[Line] = []
        self.scroll_px = 0.0  # pixels scrolled off the top of the viewport

    def append(self, line: Line) -> None:
        self.lines.append(line)

    def scroll_target(self) -> float:
        overflow = max(0, len(self.lines) - viewport_rows())
        return overflow * LINE_H

    def ease_scroll(self, fraction: float) -> None:
        """Move scroll_px a step toward its target; True when still moving."""
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

    # window chrome
    d.rounded_rectangle([0, 0, W - 1, TITLE_H - 1], radius=10, fill=TITLE_BG)
    d.rectangle([0, TITLE_H - 12, W - 1, TITLE_H - 1], fill=TITLE_BG)
    for i, colour in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = 34 + i * 44
        d.ellipse([cx, 22, cx + 20, 42], fill=colour)
    title = "riskgovernor - demo"
    d.text((W // 2 - text_width(title) // 2, 22), title, font=FONT, fill=DIM)
    d.line([0, TITLE_H, W, TITLE_H], fill=BORDER)

    # body with fractional scroll
    base_y = TITLE_H + 26
    offset = term.scroll_px
    start_idx = int(offset // LINE_H)
    sub = offset - start_idx * LINE_H
    visible = term.lines[start_idx:]
    y = base_y - sub
    for text, colour in visible:
        if y >= TITLE_H and y + LINE_H <= H:
            d.text((MARGIN_X, y), text, font=FONT, fill=colour)
        y += LINE_H

    # block cursor, on its own line after the visible content
    if cursor_line is not None:
        text, colour = cursor_line
        cy = y  # next line position after the last visible line
        if cy + LINE_H <= H:
            d.rectangle(
                [MARGIN_X + text_width(text) + 6, cy + 6,
                 MARGIN_X + text_width(text) + 6 + CURSOR_W, cy + LINE_H - 10],
                fill=colour,
            )
    return img


CHAR_FRAMES = 4      # frames per typed character (67 ms/char)
LINE_HOLD = 9        # frames after a normal output line
VERDICT_HOLD = 22    # frames after a VERDICT: line - let it land
GAP_HOLD = 8
FADE = 18            # fade-in / fade-out length in frames


def _hold_for(text: str) -> int:
    if text.startswith(("VERDICT:", "  set ", "overrides")):
        return VERDICT_HOLD
    return LINE_HOLD


def build_frames():
    term = Terminal()
    prompt_prefix = ("$ ", GREEN)

    def settle_scroll(steps: int = 8):
        for _ in range(steps):
            if not term.ease_scroll(0.34):
                break
            yield draw_frame(term)

    for kind, payload in SCRIPT:
        if kind == "type":
            for i in range(1, len(payload) + 1):
                for _ in range(CHAR_FRAMES):
                    typed = prompt_prefix[0] + payload[:i]
                    yield draw_frame(term, cursor_line=(typed, WHITE))
            term.append((prompt_prefix[0] + payload, WHITE))
            yield from settle_scroll()
        elif kind == "line":
            text, colour = payload
            term.append(payload)
            yield draw_frame(term)
            for _ in range(_hold_for(text)):
                yield draw_frame(term)
            yield from settle_scroll()
        elif kind == "gap":
            term.append(("", FG))
            for _ in range(GAP_HOLD):
                yield draw_frame(term)
        elif kind == "beat":
            for i in range(int(payload)):
                blink = (i // 22) % 2 == 0
                last = term.lines[-1] if term.lines else ("", FG)
                cursor = (last[0], WHITE) if blink else ("", WHITE)
                yield draw_frame(term, cursor_line=cursor)
    while term.ease_scroll(0.2):
        yield draw_frame(term)


def with_fades(frames):
    """Fade the first and last FADE frames toward the background colour."""
    tail = list(frames)
    for idx in range(len(tail)):
        if idx < FADE:
            factor = (idx + 1) / (FADE + 1)
            tail[idx] = Image.blend(Image.new("RGB", (W, H), BG), tail[idx], factor)
        remaining = len(tail) - 1 - idx
        if remaining < FADE:
            factor = (remaining + 1) / (FADE + 1)
            tail[idx] = Image.blend(Image.new("RGB", (W, H), BG), tail[idx], factor)
    return tail


def encode_mp4(frames) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
        "-i", "-",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(MP4),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    count = 0
    for frame in frames:
        proc.stdin.write(frame.tobytes())
        count += 1
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        sys.exit(f"ffmpeg mp4 encode failed with {proc.returncode}")
    print(f"mp4: {count} frames, {count / FPS:.1f}s -> {MP4} ({MP4.stat().st_size/1e6:.1f} MB)")


def encode_gif() -> None:
    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-i", str(MP4),
        "-vf",
        "fps=12,scale=880:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];"
        "[s1][p]paletteuse=dither=bayer:bayer_scale=4",
        "-loop", "0",
        str(GIF),
    ]
    subprocess.run(cmd, check=True)
    print(f"gif: -> {GIF} ({GIF.stat().st_size/1e6:.1f} MB)")


def main() -> None:
    encode_mp4(with_fades(build_frames()))
    encode_gif()


if __name__ == "__main__":
    main()