"""Generate Kyanth's app icon and menu-bar glyphs — Level.

The mark is a meter, not a microphone. Three rounded bars in 34 : 62 : 46,
centre bar carrying the only colour. The argument for dropping the vintage
microphone is that **the 16 pt rendering is the same drawing as the 1024 pt
one** — a mic needs grille slots and a chevron to read, and those die below
64 pt. Check the 16 pt output by eye; that claim is the whole point.

Four shapes, three gradients, all expressible in CoreGraphics, so this file
keeps its job and no external asset pipeline is required.

Outputs:
  assets/kyanth.icns              app icon, every size
  assets/menubar-<state>.png/@2x six 20 pt template glyphs

Run:  uv run make_icons.py
"""

import subprocess
import sys
from pathlib import Path

import Quartz
from CoreFoundation import CFURLCreateWithFileSystemPath, kCFURLPOSIXPathStyle

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"

ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]

#  rumps hard-codes the status image to 20x20 pt.
MENUBAR_PT = 20

# ----------------------------------------------------------- icon geometry
#  On a 1024 canvas, top-left origin (the spec's frame). DESIGN.md §3.1.
TILE_R = 228.8                       # 22.37%, the macOS squircle radius
BARS = [
    (224, 376, 128, 272),            # left    ratio 34
    (448, 264, 128, 496),            # centre  ratio 62 — the peak
    (672, 328, 128, 368),            # right   ratio 46
]

GROUND = [(0.298, 0.329, 0.408, 1.0),   # #4c5468
          (0.145, 0.169, 0.224, 1.0),   # #252b39
          (0.078, 0.090, 0.122, 1.0)]   # #14171f
GROUND_LOC = [0.0, 0.55, 1.0]
BAR_FILL = [(1.0, 1.0, 1.0, 1.0), (0.812, 0.839, 0.894, 1.0)]        # #fff → #cfd6e4
PEAK_FILL = [(0.490, 0.714, 1.0, 1.0), (0.039, 0.424, 0.961, 1.0)]   # #7db6ff → #0a6cf5


# ------------------------------------------------------------------ canvas

def new_context(size: int):
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, size, size, 8, 0, cs, Quartz.kCGImageAlphaPremultipliedLast)
    Quartz.CGContextSetAllowsAntialiasing(ctx, True)
    Quartz.CGContextSetShouldAntialias(ctx, True)
    return ctx


def write_png(ctx, path: Path):
    image = Quartz.CGBitmapContextCreateImage(ctx)
    url = CFURLCreateWithFileSystemPath(None, str(path), kCFURLPOSIXPathStyle, False)
    dest = Quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, image, None)
    Quartz.CGImageDestinationFinalize(dest)


def gradient(space, colors, locations=None):
    flat = [c for rgba in colors for c in rgba]
    return Quartz.CGGradientCreateWithColorComponents(
        space, flat, locations or [0.0, 1.0], len(colors))


def rounded(ctx, x, y, w, h, r):
    Quartz.CGContextAddPath(
        ctx, Quartz.CGPathCreateWithRoundedRect(
            Quartz.CGRectMake(x, y, w, h), r, r, None))


# -------------------------------------------------------------- app icon

def draw_icon(size: int):
    ctx = new_context(size)
    s = size / 1024.0
    space = Quartz.CGColorSpaceCreateWithName(Quartz.kCGColorSpaceSRGB)

    # ground, clipped to the squircle
    Quartz.CGContextSaveGState(ctx)
    rounded(ctx, 0, 0, size, size, TILE_R * s)
    Quartz.CGContextClip(ctx)
    Quartz.CGContextDrawLinearGradient(
        ctx, gradient(space, GROUND, GROUND_LOC),
        Quartz.CGPointMake(0, size), Quartz.CGPointMake(size * 0.35, 0), 0)

    # top sheen — white .20 fading out by 42%
    Quartz.CGContextDrawLinearGradient(
        ctx, gradient(space, [(1, 1, 1, 0.20), (1, 1, 1, 0.0)]),
        Quartz.CGPointMake(0, size), Quartz.CGPointMake(0, size * 0.58), 0)
    Quartz.CGContextRestoreGState(ctx)

    # bars — the spec is top-left origin, CoreGraphics is bottom-left
    for i, (x, y_top, w, h) in enumerate(BARS):
        rect = Quartz.CGRectMake(x * s, (1024 - y_top - h) * s, w * s, h * s)
        Quartz.CGContextSaveGState(ctx)
        Quartz.CGContextAddPath(
            ctx, Quartz.CGPathCreateWithRoundedRect(
                rect, (w / 2) * s, (w / 2) * s, None))
        Quartz.CGContextClip(ctx)
        Quartz.CGContextDrawLinearGradient(
            ctx, gradient(space, PEAK_FILL if i == 1 else BAR_FILL),
            Quartz.CGPointMake(0, Quartz.CGRectGetMaxY(rect)),
            Quartz.CGPointMake(0, Quartz.CGRectGetMinY(rect)), 0)
        Quartz.CGContextRestoreGState(ctx)

    return ctx


# --------------------------------------------------------- menu-bar glyphs
#  Six states, six SHAPES — not six colours, because the glyph is drawn over
#  an arbitrary wallpaper. One colour on transparent so macOS can invert it
#  for dark menu bars and for an open menu. Geometry from
#  assets/menubar-glyphs.svg, 20x20 with the SVG's top-left origin.

#  (x, y_top, w, h) per bar, at rest
GLYPH_REST = [(4.0, 7.5, 2.6, 5.0), (8.7, 5.0, 2.6, 10.0), (13.4, 6.5, 2.6, 7.0)]
GLYPH_LOUD = [(4.0, 5.5, 2.6, 9.0), (8.7, 3.0, 2.6, 14.0), (13.4, 4.5, 2.6, 11.0)]
GLYPH_STUB = [(4.0, 8.6, 2.6, 2.8), (8.7, 8.6, 2.6, 2.8), (13.4, 8.6, 2.6, 2.8)]


def _glyph_bars(ctx, bars, scale, alpha=1.0, stroke=False, light=False):
    tone = 1.0 if light else 0.0
    for x, y_top, w, h in bars:
        rect = Quartz.CGRectMake(
            x * scale, (MENUBAR_PT - y_top - h) * scale, w * scale, h * scale)
        path = Quartz.CGPathCreateWithRoundedRect(
            rect, (w / 2) * scale, (w / 2) * scale, None)
        Quartz.CGContextAddPath(ctx, path)
        if stroke:
            Quartz.CGContextSetRGBStrokeColor(ctx, tone, tone, tone, alpha)
            Quartz.CGContextSetLineWidth(ctx, 1.4 * scale)
            Quartz.CGContextStrokePath(ctx)
        else:
            Quartz.CGContextSetRGBFillColor(ctx, tone, tone, tone, alpha)
            Quartz.CGContextFillPath(ctx)


def _slash(ctx, scale, x1, y1, x2, y2):
    Quartz.CGContextSetRGBStrokeColor(ctx, 0, 0, 0, 1.0)
    Quartz.CGContextSetLineWidth(ctx, 1.8 * scale)
    Quartz.CGContextSetLineCap(ctx, Quartz.kCGLineCapRound)
    Quartz.CGContextMoveToPoint(ctx, x1 * scale, (MENUBAR_PT - y1) * scale)
    Quartz.CGContextAddLineToPoint(ctx, x2 * scale, (MENUBAR_PT - y2) * scale)
    Quartz.CGContextStrokePath(ctx)


def draw_glyph(state: str, scale: int, phase: int = 0, light: bool = False):
    size = MENUBAR_PT * scale
    ctx = new_context(size)

    if state == "idle":
        _glyph_bars(ctx, GLYPH_REST, scale)

    elif state == "recording":
        _glyph_bars(ctx, GLYPH_LOUD, scale, light=light)
        #  The one template opt-out — at 20 pt a colour change is legible
        #  where a shape change is not. Opting out means macOS will not invert
        #  the bars for a dark menu bar either, so this state ships in two
        #  tones and the app picks by appearance. Without the pair, recording
        #  in dark mode is a lone red dot with the mark missing.
        Quartz.CGContextSetRGBFillColor(ctx, 0.898, 0.216, 0.173, 1.0)
        #  Clear of the right bar, which starts at x=16 and y=4.5. At 2.6/17.2
        #  the dot overlapped it and the two read as one blob at 20 pt.
        r = 1.9 * scale
        Quartz.CGContextFillEllipseInRect(
            ctx, Quartz.CGRectMake(18.0 * scale - r, (MENUBAR_PT - 2.6) * scale - r,
                                   r * 2, r * 2))

    elif state == "transcribing":
        #  Three equal stubs; `phase` moves the taller one left → centre →
        #  right so the state animates without changing shape family.
        bars = []
        for i, (x, y_top, w, h) in enumerate(GLYPH_STUB):
            if i == phase % 3:
                bars.append((x, y_top - 1.6, w, h + 3.2))
            else:
                bars.append((x, y_top, w, h))
        _glyph_bars(ctx, bars, scale)

    elif state == "disabled":
        _glyph_bars(ctx, GLYPH_REST, scale, alpha=0.55)
        _slash(ctx, scale, 3.2, 16.4, 16.8, 3.6)

    elif state == "needs-permission":
        #  Hollow — the shape is there, the substance is not.
        hollow = [(4.2, 7.7, 2.2, 4.6), (8.9, 5.2, 2.2, 9.6), (13.6, 6.7, 2.2, 6.6)]
        _glyph_bars(ctx, hollow, scale, stroke=True)

    elif state == "error":
        #  Faint enough that the cross reads as the subject and the bars as
        #  the thing it is struck through.
        _glyph_bars(ctx, GLYPH_REST, scale, alpha=0.28)
        _slash(ctx, scale, 5.6, 5.6, 14.4, 14.4)
        _slash(ctx, scale, 14.4, 5.6, 5.6, 14.4)

    else:
        raise ValueError(f"unknown glyph state: {state}")

    return ctx


GLYPH_STATES = ["idle", "recording", "transcribing",
                "disabled", "needs-permission", "error"]

#  transcribing animates by swapping between these three frames.
TRANSCRIBING_FRAMES = 3


# ------------------------------------------------------------------ driver

def main() -> int:
    ASSETS.mkdir(exist_ok=True)

    iconset = ASSETS / "kyanth.iconset"
    iconset.mkdir(exist_ok=True)
    for px in ICNS_SIZES:
        ctx = draw_icon(px)
        write_png(ctx, iconset / f"icon_{px}x{px}.png")
        if px // 2 in ICNS_SIZES:
            write_png(ctx, iconset / f"icon_{px // 2}x{px // 2}@2x.png")
    print(f"  iconset: {len(list(iconset.glob('*.png')))} pngs")

    icns = ASSETS / "kyanth.icns"
    result = subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print("iconutil failed:", result.stderr, file=sys.stderr)
        return 1
    print(f"  {icns.name}: {icns.stat().st_size // 1024} KB")

    for state in GLYPH_STATES:
        for scale in (1, 2):
            suffix = "@2x" if scale == 2 else ""
            write_png(draw_glyph(state, scale),
                      ASSETS / f"menubar-{state}{suffix}.png")
    for scale in (1, 2):
        suffix = "@2x" if scale == 2 else ""
        write_png(draw_glyph("recording", scale, light=True),
                  ASSETS / f"menubar-recording-dark{suffix}.png")
    for frame in range(TRANSCRIBING_FRAMES):
        for scale in (1, 2):
            suffix = "@2x" if scale == 2 else ""
            write_png(draw_glyph("transcribing", scale, frame),
                      ASSETS / f"menubar-transcribing-{frame}{suffix}.png")
    print(f"  glyphs: {len(GLYPH_STATES)} states + "
          f"{TRANSCRIBING_FRAMES} transcribing frames + a light-toned "
          f"recording, @1x and @2x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
