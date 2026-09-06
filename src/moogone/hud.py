"""A heads-up display on the instrument's own screen.

`fb1` is a hardware overlay plane — `2-layer-fb-fg` in the Freescale IPU's terms —
sitting above `fb0`, where X and `las-dwm` draw the Moog's own interface. So a HUD
composites over that interface instead of fighting it, and switching it off
restores the screen exactly. The boot splash uses the same path and then parks the
plane at 10x10 to get out of the way.

Three things this learned the hard way, all from copying what the splash does:

* `fbset` has to be called **twice** or the geometry does not stick.
* The mode must then be written separately to `/sys/class/graphics/fb1/mode`.
* The plane appears at the **bottom** of the panel, not at the origin. Confirmed
  by eye, and convenient — it leaves the instrument's own display alone.

Pixels are BGRA to match `fb0`'s reported `rgba 8/16,8/8,8/0,8/24`.

There is no font on the instrument and Pillow is not a dependency of this project
— its core dependency list is deliberately empty — so `FONT` below is a 5x7 bitmap
defined here. It covers what a HUD needs and nothing more.
"""

from __future__ import annotations

import numpy as np

WIDTH, HEIGHT = 832, 120
BYTES_PER_PIXEL = 4

#: 5x7 glyphs, one line each: seven rows of five bits, MSB left.
FONT: dict[str, str] = {
    "0": "01110 10001 10011 10101 11001 10001 01110",
    "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111",
    "3": "11111 00010 00100 00010 00001 10001 01110",
    "4": "00010 00110 01010 10010 11111 00010 00010",
    "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110",
    "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110",
    "9": "01110 10001 10001 01111 00001 00010 01100",
    "A": "01110 10001 10001 11111 10001 10001 10001",
    "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110",
    "D": "11100 10010 10001 10001 10001 10010 11100",
    "E": "11111 10000 10000 11110 10000 10000 11111",
    "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111",
    "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110",
    "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001",
    "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001",
    "N": "10001 10001 11001 10101 10011 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110",
    "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101",
    "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110",
    "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110",
    "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 11011 10001",
    "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100",
    "Z": "11111 00001 00010 00100 01000 10000 11111",
    " ": "00000 00000 00000 00000 00000 00000 00000",
    ".": "00000 00000 00000 00000 00000 01100 01100",
    ":": "00000 01100 01100 00000 01100 01100 00000",
    "-": "00000 00000 00000 11111 00000 00000 00000",
    "+": "00000 00100 00100 11111 00100 00100 00000",
    "/": "00001 00010 00010 00100 01000 01000 10000",
    "%": "11001 11010 00010 00100 01000 01011 10011",
    "#": "01010 01010 11111 01010 11111 01010 01010",
    "*": "00000 10101 01110 11111 01110 10101 00000",
    "!": "00100 00100 00100 00100 00100 00000 00100",
    "?": "01110 10001 00001 00010 00100 00000 00100",
    "=": "00000 00000 11111 00000 11111 00000 00000",
}

GLYPH_W, GLYPH_H = 5, 7

# Colours as (B, G, R).
BG = (0, 0, 0)
DIM = (90, 90, 90)
TEXT = (220, 220, 220)
CARRIER = (120, 240, 120)
SIDEBAND = (230, 190, 60)
REFLECTED = (110, 130, 255)
WARN = (80, 80, 255)


class Canvas:
    """A BGRA image with just enough drawing to make a readable HUD."""

    def __init__(self, width: int = WIDTH, height: int = HEIGHT):
        self.width = width
        self.height = height
        self.buf = np.zeros((height, width, BYTES_PER_PIXEL), dtype=np.uint8)
        self.buf[:, :, 3] = 255  # opaque; the plane's alpha is global

    def fill(self, colour: tuple[int, int, int]) -> None:
        self.buf[:, :, 0:3] = colour

    def rect(self, x: int, y: int, w: int, h: int, colour: tuple[int, int, int]) -> None:
        """Draw a filled rectangle, clipped to the canvas.

        Clipping rather than raising: a HUD that vanishes because one value grew
        unexpectedly is worse than one that draws a slightly clipped bar.
        """
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        self.buf[y0:y1, x0:x1, 0:3] = colour

    def text(
        self, x: int, y: int, message: str, colour: tuple[int, int, int] = TEXT, scale: int = 1
    ) -> int:
        """Draw text, returning the x just past it. Unknown characters skip."""
        cursor = x
        for char in message.upper():
            glyph = FONT.get(char)
            if glyph is None:
                cursor += (GLYPH_W + 1) * scale
                continue
            for row, bits in enumerate(glyph.split()):
                for col, bit in enumerate(bits):
                    if bit == "1":
                        self.rect(cursor + col * scale, y + row * scale, scale, scale, colour)
            cursor += (GLYPH_W + 1) * scale
        return cursor

    def to_bytes(self) -> bytes:
        return self.buf.tobytes()


def text_width(message: str, scale: int = 1) -> int:
    return len(message) * (GLYPH_W + 1) * scale


def render_fm(state: dict, width: int = WIDTH, height: int = HEIGHT) -> Canvas:
    """The FM engine as a picture: what is sounding, and what it will contain.

    The spectrum is the point. FM sidebands sit at `fc ± n·fm` with amplitude
    `Jn(index)`, so drawing them turns the index from an opaque knob into
    something you can read off the screen before you play it. Reflected partials
    -- those whose frequency came out negative and folded back up -- get their own
    colour, because they land on top of other partials and are the usual reason a
    small ratio change sounds much bigger than it looks.
    """
    c = Canvas(width, height)
    c.fill(BG)
    c.rect(0, 0, width, 1, DIM)

    mode = str(state.get("mode", "self"))
    ratio = float(state.get("ratio", 0.0))
    index = float(state.get("index", 0.0))
    voices = state.get("voices", []) or []
    cpu = float(state.get("cpu_estimate", 0.0))

    c.text(8, 6, "FM", CARRIER, scale=2)
    name = str(state.get("preset") or "")
    if name:
        c.text(40, 6, name, TEXT, scale=2)
        c.text(40, 24, f"RATIO {ratio:.2f}   INDEX {index:.2f}   {mode}", DIM)
    else:
        c.text(40, 8, f"RATIO {ratio:.2f}   INDEX {index:.2f}", TEXT)
        c.text(40, 20, f"MODE {mode}", DIM)

    # -- the spectrum ---------------------------------------------------------
    spectrum = state.get("spectrum", []) or []
    left, top, plot_w, plot_h = 8, 36, width - 220, height - 48
    c.rect(left, top + plot_h, plot_w, 1, DIM)

    if spectrum:
        span = max(abs(float(s["ratio"])) for s in spectrum) or 1.0
        for s in spectrum:
            r = float(s["ratio"])
            amp = float(s["amplitude"])
            reflected = bool(s.get("reflected"))
            x = left + int(abs(r) / span * (plot_w - 6))
            h = max(1, int(amp * (plot_h - 4)))
            colour = CARRIER if s["order"] == 0 else (REFLECTED if reflected else SIDEBAND)
            c.rect(x, top + plot_h - h, 3, h, colour)
        c.text(left, top - 10, "PARTIALS", DIM)
    else:
        c.text(left, top + plot_h // 2, "LIVE ANALOG MODULATOR - NO PREDICTION", DIM)

    # -- voices and load ------------------------------------------------------
    right = width - 200
    c.text(right, 8, f"VOICES {len(voices)}", TEXT)
    for i, v in enumerate(voices[:6]):
        c.text(right, 22 + i * 10, f"{int(v['note']):>3}  {float(v['freq']):>7.1f}HZ", DIM)

    meter_y = height - 18
    c.text(right, meter_y - 12, f"CPU {cpu * 100:.0f}%", TEXT)
    c.rect(right, meter_y, 180, 8, (40, 40, 40))
    filled = max(0, min(180, int(cpu * 180)))
    c.rect(right, meter_y, filled, 8, WARN if cpu > 0.85 else CARRIER)
    return c


FB = "/dev/fb1"
_SETUP = (
    "export PATH=/usr/sbin:/sbin:/usr/bin:/bin; "
    "echo 0 > /sys/class/graphics/fb1/blank; "
    # Twice. Once does not stick -- the boot splash does the same and it is not
    # superstition: with a single call the geometry silently stays at its old value.
    "fbset --geometry {w} {h} {w} {h} 32 --timings 51313 20 60 10 10 20 10 -fb /dev/fb1; "
    "fbset --geometry {w} {h} {w} {h} 32 --timings 51313 20 60 10 10 20 10 -fb /dev/fb1; "
    "echo 'U:{w}x{h}p-40' > /sys/class/graphics/fb1/mode"
)


def _ssh(host: str, command: str, stdin: bytes | None = None):
    import subprocess

    return subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes", f"root@{host}", command],
        input=stdin,
        capture_output=True,
        timeout=120,
        check=False,
    )


def show(canvas: Canvas, host: str, alpha: int = 255) -> None:
    """Put a canvas on the instrument's screen.

    Sent over SSH, which runs on TCP and therefore paces itself. That matters:
    a burst of unpaced traffic wedges this instrument's USB network gadget past
    the point the host can reset it. See `docs/MOOG-ONE-INTERNALS.md` section 8c.
    """
    _ssh(host, _SETUP.format(w=canvas.width, h=canvas.height))
    _ssh(
        host,
        f"cat > /tmp/vox-hud.raw && dd if=/tmp/vox-hud.raw of={FB} bs=64k 2>/dev/null",
        stdin=canvas.to_bytes(),
    )
    _ssh(
        host,
        f"export PATH=/usr/sbin:/sbin:/usr/bin:/bin; las-fb-config 1 {max(0, min(255, int(alpha)))}",
    )


def hide(host: str) -> None:
    """Return the screen to the instrument, exactly as the splash script leaves it."""
    _ssh(
        host,
        "export PATH=/usr/sbin:/sbin:/usr/bin:/bin; "
        "las-fb-config 1 0; "
        "fbset --geometry 10 10 10 10 32 -fb /dev/fb1; "
        "echo 'U:10x10p-40' > /sys/class/graphics/fb1/mode",
    )
