"""Generate shout's app icon and menu-bar glyphs.

Draws a vintage broadcast microphone (Shure 55 / RCA ribbon style: capsule
grille in a yoke, on a stand) with CoreGraphics — no image dependencies, since
pyobjc is already required.

Outputs:
  assets/shout.icns              app icon, all sizes
  assets/menubar-idle.png/@2x    template glyph (auto light/dark)
  assets/menubar-rec.png/@2x     recording glyph, with red dot
  assets/menubar-off.png/@2x     disabled glyph, with slash

Run:  uv run make_icons.py
"""

import math
import subprocess
import sys
from pathlib import Path

import Quartz
from CoreFoundation import CFURLCreateWithFileSystemPath, kCFURLPOSIXPathStyle

ROOT = Path(__file__).parent
ASSETS = ROOT / "assets"

ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]

#  rumps hard-codes the status item image to 20x20pt, so render at exactly
#  that to avoid a resample.
MENUBAR_PT = 20


# ------------------------------------------------------------------ canvas

def new_context(size: int):
    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(
        None, size, size, 8, 0, cs, Quartz.kCGImageAlphaPremultipliedLast
    )
    Quartz.CGContextSetAllowsAntialiasing(ctx, True)
    Quartz.CGContextSetShouldAntialias(ctx, True)
    Quartz.CGContextSetLineCap(ctx, Quartz.kCGLineCapRound)
    Quartz.CGContextSetLineJoin(ctx, Quartz.kCGLineJoinRound)
    return ctx


def write_png(ctx, path: Path):
    image = Quartz.CGBitmapContextCreateImage(ctx)
    url = CFURLCreateWithFileSystemPath(None, str(path), kCFURLPOSIXPathStyle, False)
    dest = Quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, image, None)
    Quartz.CGImageDestinationFinalize(dest)


def rounded_rect(ctx, x, y, w, h, r):
    Quartz.CGContextMoveToPoint(ctx, x + r, y)
    Quartz.CGContextAddArcToPoint(ctx, x + w, y, x + w, y + h, r)
    Quartz.CGContextAddArcToPoint(ctx, x + w, y + h, x, y + h, r)
    Quartz.CGContextAddArcToPoint(ctx, x, y + h, x, y, r)
    Quartz.CGContextAddArcToPoint(ctx, x, y, x + w, y, r)
    Quartz.CGContextClosePath(ctx)


# ------------------------------------------------------------------ the mic

def draw_mic(ctx, s: float, rgba, grille=True):
    """Vintage broadcast mic on a unit-ish canvas of side `s`.

    Coordinates are fractions of `s` so the same routine serves a 16px menu-bar
    glyph and a 1024px app icon.
    """
    r, g, b, a = rgba
    Quartz.CGContextSetRGBFillColor(ctx, r, g, b, a)
    Quartz.CGContextSetRGBStrokeColor(ctx, r, g, b, a)

    cx = 0.50 * s
    head_cy = 0.605 * s
    head_w, head_h = 0.40 * s, 0.43 * s
    head_x, head_y = cx - head_w / 2, head_cy - head_h / 2

    # --- yoke: a half-ring hanging below the head's pivot line, not a V.
    # Drawing it first puts the head on top, which is how the real mount looks.
    yoke_r = 0.275 * s
    Quartz.CGContextSetLineWidth(ctx, 0.042 * s)
    Quartz.CGContextAddArc(ctx, cx, head_cy, yoke_r,
                           math.radians(180), math.radians(360), 0)
    Quartz.CGContextStrokePath(ctx)

    # --- stem and base, hanging off the bottom of the yoke
    yoke_bottom = head_cy - yoke_r
    stem_w = 0.055 * s
    Quartz.CGContextFillRect(
        ctx, ((cx - stem_w / 2, 0.145 * s), (stem_w, yoke_bottom - 0.135 * s))
    )
    base_w, base_h = 0.30 * s, 0.05 * s
    rounded_rect(ctx, cx - base_w / 2, 0.095 * s, base_w, base_h, base_h / 2)
    Quartz.CGContextFillPath(ctx)

    # --- grille head: rounded rect, not an oval. The flat-ish sides are what
    # separate a broadcast mic from a generic modern capsule.
    rounded_rect(ctx, head_x, head_y, head_w, head_h, 0.125 * s)
    Quartz.CGContextFillPath(ctx)

    if grille:
        Quartz.CGContextSaveGState(ctx)
        rounded_rect(ctx, head_x, head_y, head_w, head_h, 0.125 * s)
        Quartz.CGContextClip(ctx)
        Quartz.CGContextSetBlendMode(ctx, Quartz.kCGBlendModeClear)

        # thin slots, leaving more metal than air
        bands = 6
        pitch = head_h / (bands + 1.2)
        for i in range(bands):
            by = head_y + pitch * (i + 0.75)
            Quartz.CGContextFillRect(ctx, ((head_x, by), (head_w, pitch * 0.30)))

        # art-deco chevron across the lower third — the signature 55SH detail
        Quartz.CGContextSetBlendMode(ctx, Quartz.kCGBlendModeClear)
        # Points UP. Inverted, it reads as a mouth and the whole head becomes
        # a face.
        chev_y = head_y + head_h * 0.20
        w = head_w * 0.60
        Quartz.CGContextSetLineWidth(ctx, 0.030 * s)
        Quartz.CGContextMoveToPoint(ctx, cx - w / 2, chev_y)
        Quartz.CGContextAddLineToPoint(ctx, cx, chev_y + 0.055 * s)
        Quartz.CGContextAddLineToPoint(ctx, cx + w / 2, chev_y)
        Quartz.CGContextStrokePath(ctx)
        Quartz.CGContextRestoreGState(ctx)

    # --- pivot knobs on the head's centre line, over the grille edge
    Quartz.CGContextSetRGBFillColor(ctx, r, g, b, a)
    for sign in (-1, 1):
        kx = cx + sign * (head_w / 2 + 0.008 * s)
        k = 0.038 * s
        Quartz.CGContextFillEllipseInRect(
            ctx, ((kx - k, head_cy - k), (k * 2, k * 2))
        )


# ------------------------------------------------------------------ app icon

def draw_app_icon(size: int) -> object:
    ctx = new_context(size)
    s = float(size)

    # squircle-ish background with a warm vertical gradient
    Quartz.CGContextSaveGState(ctx)
    rounded_rect(ctx, 0.045 * s, 0.045 * s, 0.91 * s, 0.91 * s, 0.205 * s)
    Quartz.CGContextClip(ctx)

    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    grad = Quartz.CGGradientCreateWithColorComponents(
        cs,
        (0.16, 0.17, 0.21, 1.0,    # slate top
         0.09, 0.09, 0.12, 1.0),   # near-black bottom
        (0.0, 1.0), 2,
    )
    Quartz.CGContextDrawLinearGradient(
        ctx, grad, (0, s), (0, 0), 0
    )

    # warm amber pool behind the mic, so the silver reads against the slate
    glow = Quartz.CGGradientCreateWithColorComponents(
        cs, (0.98, 0.70, 0.28, 0.34, 0.98, 0.70, 0.28, 0.0), (0.0, 1.0), 2
    )
    Quartz.CGContextDrawRadialGradient(
        ctx, glow, (0.5 * s, 0.55 * s), 0.0, (0.5 * s, 0.55 * s), 0.46 * s, 0
    )
    Quartz.CGContextRestoreGState(ctx)

    # mic in warm silver
    draw_mic(ctx, s, (0.90, 0.91, 0.93, 1.0))
    return ctx


# ------------------------------------------------------------ menubar glyphs

def draw_menubar(pt: int, scale: int, variant: str):
    size = pt * scale
    ctx = new_context(size)
    s = float(size)

    # Template images are drawn in solid black; macOS recolors them for the
    # active menu-bar appearance (light, dark, and while a menu is open).
    black = (0.0, 0.0, 0.0, 1.0)
    draw_mic(ctx, s, black, grille=(size >= 32))

    if variant == "rec":
        # Recording is worth breaking the template rule for — a red dot is
        # instantly legible where a shape change is not.
        Quartz.CGContextSetRGBFillColor(ctx, 0.86, 0.16, 0.16, 1.0)
        Quartz.CGContextFillEllipseInRect(
            ctx, ((0.68 * s, 0.66 * s), (0.30 * s, 0.30 * s))
        )
    elif variant == "off":
        Quartz.CGContextSetRGBStrokeColor(ctx, *black)
        Quartz.CGContextSetLineWidth(ctx, 0.075 * s)
        Quartz.CGContextMoveToPoint(ctx, 0.16 * s, 0.14 * s)
        Quartz.CGContextAddLineToPoint(ctx, 0.84 * s, 0.86 * s)
        Quartz.CGContextStrokePath(ctx)

    return ctx


# ------------------------------------------------------------------- driver

def main() -> int:
    ASSETS.mkdir(exist_ok=True)

    iconset = ASSETS / "shout.iconset"
    iconset.mkdir(exist_ok=True)
    for px in ICNS_SIZES:
        ctx = draw_app_icon(px)
        pt = px
        write_png(ctx, iconset / f"icon_{pt}x{pt}.png")
        # retina variant of the next size down
        if pt // 2 in ICNS_SIZES:
            write_png(ctx, iconset / f"icon_{pt//2}x{pt//2}@2x.png")
    print(f"  iconset: {len(list(iconset.glob('*.png')))} pngs")

    icns = ASSETS / "shout.icns"
    r = subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("iconutil failed:", r.stderr, file=sys.stderr)
        return 1
    print(f"  {icns.name}: {icns.stat().st_size // 1024} KB")

    for variant in ("idle", "rec", "off"):
        for scale in (1, 2):
            ctx = draw_menubar(MENUBAR_PT, scale, variant)
            suffix = "@2x" if scale == 2 else ""
            write_png(ctx, ASSETS / f"menubar-{variant}{suffix}.png")
    print("  menubar glyphs: idle/rec/off @1x @2x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
