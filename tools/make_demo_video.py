"""Render the riskgovernor product video: hook, model, demo, audience, CTA.

    py -3.13 tools/make_narration.py            # narration -> docs/demo.mp3 + timings
    py -3.13 tools/make_demo_video.py           # picture, scene-synced to narration

Produces:
    docs/demo.mp4         1760x990 @ 60fps H.264, silent master
    docs/demo-voiced.mp4  same picture + narration (48 kHz stereo AAC)
    docs/demo.gif         README hero, cut from the terminal demo segment

Structure (each scene paced to its narration span):
    hook       title card  - the problem: rules that live inside the bot
    what       diagram     - ledger + equity + policy -> GOVERNOR -> decision
    gates      card        - the three hard stops
    rotation   terminal    - loss -> rotate away, size to the loss, halve stakes
    overrides  terminal    - streak halt, and the override going on the record
    benefits   card        - pure function, zero deps, who it's for
    cta        card        - install line and repo

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

W, H = 1760, 990
TITLE_H = 64
MARGIN_X = 56
LINE_H = 44
FPS = 60
CHAR_FRAMES = 2
FADE_N = 10        # cross-fade length between card states
STATE_HOLD = 8     # frames a card state holds before the next fades in

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
BOX_BG = (22, 27, 34)
BOX_BORDER = (63, 66, 74)


def _truetype(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except OSError:
            continue
    raise RuntimeError(f"no font among {names}")


F_TERM = _truetype(["consola.ttf", "CascadiaCode.ttf"], 30)
F_BIG = _truetype(["consolab.ttf", "consola.ttf"], 58)
F_MED = _truetype(["consola.ttf", "CascadiaCode.ttf"], 42)
F_SMALL = _truetype(["consola.ttf", "CascadiaCode.ttf"], 27)


def text_width(font: ImageFont.FreeTypeFont, s: str) -> int:
    return font.getbbox(s)[2] if s else 0


Line = tuple[str, tuple[int, int, int]]
CardLine = tuple[str, tuple[int, int, int], ImageFont.FreeTypeFont]

FALLBACK_SECONDS = {
    "hook": 11.0, "what": 10.0, "gates": 12.0, "rotation": 14.0,
    "overrides": 8.0, "benefits": 11.0, "cta": 5.0,
}


def load_timings() -> dict[str, float]:
    if TIMING.exists():
        data = json.loads(TIMING.read_text(encoding="utf-8"))
        beats = data.get("beats") or {}
        if beats:
            print(f"pacing: {TIMING.name} ({data.get('_total', '?')}s narration)")
            return {k: float(v["span"]) for k, v in beats.items()}
    print("pacing: no narration timings found, using fallback")
    return dict(FALLBACK_SECONDS)


def load_starts() -> dict[str, float]:
    if TIMING.exists():
        data = json.loads(TIMING.read_text(encoding="utf-8"))
        return {k: float(v["start"]) for k, v in (data.get("beats") or {}).items()}
    return {}


# ---------------------------------------------------------------- cards ----

def render_card(state: list[CardLine]) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    total_h = sum((f.size + 26) for _, _, f in state)
    y = (H - total_h) // 2
    for text, colour, font in state:
        d.text((W // 2 - text_width(font, text) // 2, y), text, font=font, fill=colour)
        y += font.size + 26
    return img


def card_frames(states: list[list[CardLine]]) -> list[Image.Image]:
    imgs = [render_card(s) for s in states]
    frames = [imgs[0]] * STATE_HOLD
    for prev, cur in zip(imgs, imgs[1:]):
        for i in range(1, FADE_N + 1):
            frames.append(Image.blend(prev, cur, i / (FADE_N + 1)))
        frames.extend([cur] * STATE_HOLD)
    return frames


def hook_frames() -> list[Image.Image]:
    return card_frames([
        [("Every bot has risk rules.", FG, F_MED)],
        [("Every bot has risk rules.", FG, F_MED),
         ("The day they become inconvenient,", FG, F_MED)],
        [("Every bot has risk rules.", FG, F_MED),
         ("The day they become inconvenient,", FG, F_MED),
         ("someone switches them off.", RED, F_MED)],
        [("Every bot has risk rules.", FG, F_MED),
         ("The day they become inconvenient,", FG, F_MED),
         ("someone switches them off.", RED, F_MED),
         ("", FG, F_SMALL),
         ("That's how accounts die.", WHITE, F_BIG)],
    ])


def gates_frames() -> list[Image.Image]:
    states = [
        [("THE HARD GATES", WHITE, F_BIG)],
        [("THE HARD GATES", WHITE, F_BIG),
         ("equity  <  floor              HALT", RED, F_MED)],
        [("THE HARD GATES", WHITE, F_BIG),
         ("equity  <  floor              HALT", RED, F_MED),
         ("3 consecutive losses           HALT", RED, F_MED)],
        [("THE HARD GATES", WHITE, F_BIG),
         ("equity  <  floor              HALT", RED, F_MED),
         ("3 consecutive losses           HALT", RED, F_MED),
         ("drawdown  >=  limit            HALT", RED, F_MED)],
        [("THE HARD GATES", WHITE, F_BIG),
         ("equity  <  floor              HALT", RED, F_MED),
         ("3 consecutive losses           HALT", RED, F_MED),
         ("drawdown  >=  limit            HALT", RED, F_MED),
         ("", FG, F_SMALL),
         ("evaluated first. no exceptions.", DIM, F_MED)],
    ]
    return card_frames(states)


def benefits_frames() -> list[Image.Image]:
    return card_frames([
        [("Pure Python. Zero dependencies.", WHITE, F_BIG)],
        [("Pure Python. Zero dependencies.", WHITE, F_BIG),
         ("a pure function you can unit test", FG, F_MED)],
        [("Pure Python. Zero dependencies.", WHITE, F_BIG),
         ("a pure function you can unit test", FG, F_MED),
         ("", FG, F_SMALL),
         ("trading bots  -  backtests  -  paper trading  -  poker", GREEN, F_MED)],
        [("Pure Python. Zero dependencies.", WHITE, F_BIG),
         ("a pure function you can unit test", FG, F_MED),
         ("", FG, F_SMALL),
         ("trading bots  -  backtests  -  paper trading  -  poker", GREEN, F_MED),
         ("", FG, F_SMALL),
         ("74 tests   -   CI on 3.9-3.13   -   MIT", DIM, F_SMALL)],
    ])


def cta_frames() -> list[Image.Image]:
    return card_frames([
        [("$ pip install riskgovernor", GREEN, F_BIG)],
        [("$ pip install riskgovernor", GREEN, F_BIG),
         ("", FG, F_SMALL),
         ("The governor decides.  You approve.", WHITE, F_MED)],
        [("$ pip install riskgovernor", GREEN, F_BIG),
         ("", FG, F_SMALL),
         ("The governor decides.  You approve.", WHITE, F_MED),
         ("", FG, F_SMALL),
         ("github.com/kingkillery/riskgovernor", BLUE, F_MED)],
    ])


# -------------------------------------------------------------- diagram ----

def render_diagram(stage: int) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    def box(cx: int, cy: int, w: int, h: int, label: str, colour, font) -> None:
        d.rounded_rectangle([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2],
                            radius=14, fill=BOX_BG, outline=colour, width=3)
        d.text((cx - text_width(font, label) // 2, cy - font.size // 2 - 4),
               label, font=font, fill=colour)

    def arrow(x1: int, y1: int, x2: int, y2: int, colour) -> None:
        d.line([x1, y1, x2, y2], fill=colour, width=4)
        # head
        import math
        ang = math.atan2(y2 - y1, x2 - x1)
        for da in (2.6, -2.6):
            d.line([x2, y2,
                    x2 - 18 * math.cos(ang + da), y2 - 18 * math.sin(ang + da)],
                   fill=colour, width=4)

    top_y, mid_y, bot_y = 300, 520, 740
    box(390, top_y, 340, 96, "LEDGER", FG, F_MED)
    box(880, top_y, 340, 96, "EQUITY", FG, F_MED)
    box(1370, top_y, 340, 96, "POLICY", FG, F_MED)
    if stage >= 1:
        arrow(390, top_y + 48, 790, mid_y - 60, BORDER)
        arrow(880, top_y + 48, 880, mid_y - 60, BORDER)
        arrow(1370, top_y + 48, 970, mid_y - 60, BORDER)
        box(880, mid_y, 520, 130, "GOVERNOR", WHITE, F_BIG)
    if stage >= 2:
        arrow(880, mid_y + 65, 880, bot_y - 70, GREEN)
        box(880, bot_y, 560, 110, "DECISION", GREEN, F_BIG)
    if stage >= 3:
        d.text((W // 2 - text_width(F_SMALL,
                "pure function of (ledger, equity, policy) - no clock, no filesystem, no randomness") // 2,
               bot_y + 110),
               "pure function of (ledger, equity, policy) - no clock, no filesystem, no randomness",
               font=F_SMALL, fill=DIM)
    return img


def diagram_frames() -> list[Image.Image]:
    imgs = [render_diagram(s) for s in range(4)]
    frames = [imgs[0]] * STATE_HOLD
    for prev, cur in zip(imgs, imgs[1:]):
        for i in range(1, FADE_N + 1):
            frames.append(Image.blend(prev, cur, i / (FADE_N + 1)))
        frames.extend([cur] * STATE_HOLD)
    return frames


# ------------------------------------------------------------- terminal ----

def viewport_rows() -> int:
    return (H - TITLE_H - 40) // LINE_H


class Terminal:
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


def draw_terminal(term: Terminal, cursor_line: Line | None = None) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, TITLE_H - 1], radius=10, fill=TITLE_BG)
    d.rectangle([0, TITLE_H - 12, W - 1, TITLE_H - 1], fill=TITLE_BG)
    for i, colour in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = 34 + i * 44
        d.ellipse([cx, 22, cx + 20, 42], fill=colour)
    title = "riskgovernor - demo"
    d.text((W // 2 - text_width(F_TERM, title) // 2, 22), title, font=F_TERM, fill=DIM)
    d.line([0, TITLE_H, W, TITLE_H], fill=BORDER)

    base_y = TITLE_H + 26
    offset = term.scroll_px
    start_idx = int(offset // LINE_H)
    sub = offset - start_idx * LINE_H
    y = base_y - sub
    for text, colour in term.lines[start_idx:]:
        if TITLE_H <= y and y + LINE_H <= H:
            d.text((MARGIN_X, y), text, font=F_TERM, fill=colour)
        y += LINE_H
    if cursor_line is not None:
        text, colour = cursor_line
        if y + LINE_H <= H:
            d.rectangle([MARGIN_X + text_width(F_TERM, text) + 6, y + 6,
                         MARGIN_X + text_width(F_TERM, text) + 23, y + LINE_H - 10],
                        fill=colour)
    return img


def terminal_frames(term: Terminal, events) -> list[Image.Image]:
    out: list[Image.Image] = []

    def settle(steps: int = 8) -> None:
        for _ in range(steps):
            if not term.ease_scroll(0.34):
                break
            out.append(draw_terminal(term))

    for kind, payload in events:
        if kind == "type":
            for i in range(1, len(payload) + 1):
                typed = "$ " + payload[:i]
                for _ in range(CHAR_FRAMES):
                    out.append(draw_terminal(term, cursor_line=(typed, WHITE)))
            term.append(("$ " + payload, WHITE))
            settle()
        elif kind == "line":
            term.append(payload)
            out.append(draw_terminal(term))
            out.append(draw_terminal(term))
            settle()
        elif kind == "gap":
            term.append(("", FG))
            out.append(draw_terminal(term))
            settle(4)
    return out


ROTATION_EVENTS = [
    ("type", "riskgovernor demo"),
    ("gap", None),
    ("line", ("riskgovernor demo - every verdict, in order. Nothing touches disk.", BLUE)),
    ("gap", None),
    ("line", ("2. 'steady' lost 120. Rotate away from the loser,", FG)),
    ("line", ("   and size the recovery to the loss:", FG)),
    ("line", ("VERDICT: RECOVERY defensive", YELLOW)),
    ("line", ("  set max_profit = 120    <- sized to the loss", GREEN)),
    ("line", ("  set base_stake = 50", GREEN)),
    ("gap", None),
    ("line", ("3. 'defensive' lost 80. Rotate again, halve the stake:", FG)),
    ("line", ("VERDICT: RECOVERY aggressive", YELLOW)),
    ("line", ("  set max_profit = 80", GREEN)),
    ("line", ("  set base_stake = 25    <- halved", GREEN)),
]

OVERRIDE_EVENTS = [
    ("gap", None),
    ("line", ("4. A third consecutive loss trips the streak gate:", FG)),
    ("line", ("VERDICT: HALT (3 consecutive losses)", RED)),
    ("gap", None),
    ("line", ("6. The operator overrides - and it is recorded:", FG)),
    ("line", ("overrides used: 1", YELLOW)),
    ("line", ("VERDICT: RECOVERY steady", YELLOW)),
]


# ----------------------------------------------------------------- build ----


def build():
    """Return a list of frames with every scene padded to its narration span."""
    timings = load_timings()
    starts = load_starts()
    term = Terminal()
    scenes: list[tuple[str, list[Image.Image]]] = [
        ("hook", hook_frames()),
        ("what", diagram_frames()),
        ("gates", gates_frames()),
        ("rotation", terminal_frames(term, ROTATION_EVENTS)),
        ("overrides", terminal_frames(term, OVERRIDE_EVENTS)),
        ("benefits", benefits_frames()),
        ("cta", cta_frames()),
    ]
    frames: list[Image.Image] = []
    for key, content in scenes:
        target = round(timings.get(key, FALLBACK_SECONDS.get(key, 4.0)) * FPS)
        if len(content) > target > 0:
            print(f"  note: scene {key!r} content ({len(content)}f) "
                  f"exceeded its narration slot ({target}f)")
        frames.extend(content)
        frames.extend([content[-1]] * max(0, target - len(content)))
    print(f"picture: {len(frames)} frames = {len(frames) / FPS:.1f}s "
          f"(narration spans {sum(timings.values()):.1f}s)")
    return frames, starts


def encode_mp4(frames: list[Image.Image], dest: Path) -> None:
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
    for frame in frames:
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        sys.exit(f"ffmpeg encode failed with {proc.returncode}")
    print(f"mp4: {len(frames)} frames, {len(frames) / FPS:.1f}s -> {dest.name} "
          f"({dest.stat().st_size / 1e6:.1f} MB)")


def mux_narration() -> None:
    if not NARRATION.exists():
        print(f"no narration at {NARRATION}; skipping voiced master")
        return
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error",
         "-i", str(MP4), "-i", str(NARRATION),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
         "-map", "0:v:0", "-map", "1:a:0", "-shortest",
         "-movflags", "+faststart", str(VOICED)],
        check=True,
    )
    print(f"voiced: -> {VOICED.name} ({VOICED.stat().st_size / 1e6:.1f} MB)")


def encode_gif(starts: dict[str, float]) -> None:
    """README hero: just the terminal demo segment (rotation + overrides)."""
    begin = starts.get("rotation", 0.0)
    end = starts.get("benefits")
    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-ss", f"{begin:.2f}", "-i", str(MP4),
    ]
    if end is not None:
        cmd += ["-to", f"{end:.2f}"]
    cmd += [
        "-vf",
        "fps=12,scale=880:-1:flags=lanczos,split[s0][s1];"
        "[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4",
        "-loop", "0", str(GIF),
    ]
    subprocess.run(cmd, check=True)
    print(f"gif: -> {GIF.name} ({GIF.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    frames, starts = build()
    encode_mp4(frames, MP4)
    mux_narration()
    encode_gif(starts)


if __name__ == "__main__":
    main()