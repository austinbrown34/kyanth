"""Design tokens — Level.

Ported verbatim from shout-level-handoff/tokens/tokens.css. That file is the
source of truth; if the two disagree, it wins.

Two appearances. Everything except the brand layer flips with the system
setting, because the app icon does not change appearance and the brand layer
is read off the icon.

The peak is deliberately NOT wired to NSColor.controlAccentColor: a user whose
system accent is pink would break the relationship between the peak bar in the
icon and the peak colour in the UI, which is the whole cohesion argument.
"""

from AppKit import NSColor, NSFont

# ----------------------------------------------------------------- helpers

def rgb(hex_str: str, alpha: float = 1.0):
    h = hex_str.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, alpha)


def cg(hex_str: str, alpha: float = 1.0):
    """CGColor, for CALayer properties."""
    return rgb(hex_str, alpha).CGColor()


def dynamic(name: str, light, dark):
    """An NSColor that resolves per appearance."""
    from AppKit import NSAppearanceNameDarkAqua

    def provider(appearance):
        match = appearance.bestMatchFromAppearancesWithNames_(
            ["NSAppearanceNameAqua", NSAppearanceNameDarkAqua])
        return dark if match == NSAppearanceNameDarkAqua else light

    return NSColor.colorWithName_dynamicProvider_(name, provider)


# ------------------------------------------------------------ surfaces etc

SURFACE = dynamic("shout.surface", rgb("#ffffff"), rgb("#232326"))
FOOTER = dynamic("shout.footer", rgb("#f7f7f9"), rgb("#1e1e21"))
TITLEBAR = dynamic("shout.titlebar", rgb("#f0f0f2"), rgb("#2c2c30"))
BORDER = dynamic("shout.border", rgb("#000000", .11), rgb("#ffffff", .12))
HOVER = dynamic("shout.hover", rgb("#000000", .05), rgb("#ffffff", .07))
CTL = dynamic("shout.ctl", rgb("#ffffff"), rgb("#ffffff", .09))
WIN_HAIRLINE = dynamic("shout.winHairline", rgb("#000000", .14), rgb("#ffffff", .10))

FG = dynamic("shout.fg", rgb("#1b1b1f"), rgb("#f0f0f2"))
MUTED = dynamic("shout.muted", rgb("#77777f"), rgb("#96969e"))

ACCENT = dynamic("shout.accent", rgb("#0a6cf5"), rgb("#3d8bff"))
ACCENT_FG = rgb("#ffffff")
RECORD = dynamic("shout.record", rgb("#e5372c"), rgb("#ff5f52"))
WARN = dynamic("shout.warn", rgb("#d4820a"), rgb("#f0a52a"))
OK = dynamic("shout.ok", rgb("#1f9c4a"), rgb("#3ec46d"))
METER_IDLE = dynamic("shout.meterIdle", rgb("#000000", .14), rgb("#ffffff", .16))

#  Satisfied setup steps use this, NOT green — see DESIGN.md §4.2. Seven green
#  ticks shout, and the Setup window's own argument is that green permissions
#  are not proof.
MARK_DONE = dynamic("shout.markDone", rgb("#2c3444"), rgb("#46516a"))

PEAK = dynamic("shout.peak", rgb("#0a6cf5"), rgb("#3d8bff"))

# ------------------------------------------------------------- brand layer
#  Identical in both appearances. The band's two variants below are a
#  deliberate lift for legibility, not an appearance flip of hue.

BAND_LIGHT = ("#414a5e", "#262c3a", "#171b24")
BAND_DARK = ("#333c4e", "#1e2430", "#12151c")
BAND_LOCATIONS = (0.0, 0.54, 1.0)
BAND_SHEEN = (("#ffffff", 0.13), ("#ffffff", 0.0))
BAND_SHEEN_LOCATIONS = (0.0, 0.46)

BAND_FG = rgb("#eef1f7")
BAND_MUTED = rgb("#eef1f7", .58)
BAND_DIM = rgb("#eef1f7", .42)
BAND_HAIR = rgb("#ffffff", .13)
SILVER = rgb("#dfe4ee")

#  The two gradients the logo bars are painted with — icon stops verbatim.
#  A flat #dfe4ee bar reads as a duller object than the tile in the Dock;
#  that is the single easiest way to make this look off-brand.
LOGO_BAR = ("#ffffff", "#cfd6e4")
LOGO_PEAK = ("#7db6ff", "#0a6cf5")
LOGO_GLOW = ("#7db6ff", 0.5)          # blur 12px CSS ≈ shadow radius 6

# --------------------------------------------------------------- geometry

RADIUS_WIN = 11.0
RADIUS_BOX = 9.0
RADIUS_CTL = 6.0
RADIUS_ROW = 7.0
HAIRLINE = 1.0

PANE_X, PANE_Y = 22.0, 18.0
BOX_ROW_X, BOX_ROW_Y = 14.0, 11.0
GROUP_GAP = 20.0
SIDEBAR_W = 198.0

# ------------------------------------------------------------------- type
#  Three weights only: 400 read, 550 emphasise, 590-600 announce.
#  All-caps always carries >= 0.06em tracking — uppercase at default tracking
#  is the most reliable tell that a screen was not drawn by a designer.

W_REGULAR = 0.0
W_MEDIUM = 0.23        # ~550
W_SEMIBOLD = 0.3       # ~590-600


def font(size: float, weight: float = W_REGULAR, display: bool = False):
    f = NSFont.systemFontOfSize_weight_(size, weight)
    if display:
        # SF Pro Display is selected by size on modern macOS; nudge the
        # descriptor so titles pick it up below the automatic threshold.
        desc = f.fontDescriptor().fontDescriptorByAddingAttributes_(
            {"NSFontOpticalSizeAttribute": size})
        f = NSFont.fontWithDescriptor_size_(desc, size) or f
    return f


def mono(size: float, weight: float = W_REGULAR):
    return NSFont.monospacedSystemFontOfSize_weight_(size, weight)


def tabular(size: float, weight: float = W_REGULAR):
    """Numerics that sit in a column: times, ms, counts, n/8."""
    return NSFont.monospacedDigitSystemFontOfSize_weight_(size, weight)


#  role -> (size, weight, tracking in em)
TYPE = {
    "wordmark":    (15.5, W_SEMIBOLD, -0.022),
    "windowTitle": (13.0, W_SEMIBOLD, -0.005),
    "paneTitle":   (17.0, W_SEMIBOLD, -0.015),
    "setupTitle":  (19.0, W_SEMIBOLD, -0.015),
    "body":        (12.5, W_REGULAR,   0.0),
    "rowLabel":    (12.5, W_MEDIUM,    0.0),
    "note":        (11.5, W_REGULAR,   0.01),
    "groupLabel":  (9.5,  W_SEMIBOLD,  0.11),
    "tableHead":   (9.5,  W_SEMIBOLD,  0.11),
    "version":     (10.5, W_REGULAR,   0.02),
}


def kern(role: str) -> float:
    """Tracking in points for NSKernAttributeName."""
    size, _, tracking = TYPE[role]
    return size * tracking


def attributed(text: str, role: str, color=None, display: bool = False):
    """Text with the role's font and tracking already applied."""
    from AppKit import NSAttributedString, NSFontAttributeName
    from AppKit import NSForegroundColorAttributeName, NSKernAttributeName

    size, weight, _ = TYPE[role]
    attrs = {
        NSFontAttributeName: font(size, weight, display),
        NSKernAttributeName: kern(role),
    }
    if color is not None:
        attrs[NSForegroundColorAttributeName] = color
    return NSAttributedString.alloc().initWithString_attributes_(text, attrs)


# ------------------------------------------------------------------- mark
#  The icon's 34 : 62 : 46 proportions. Used by the logo lockup, the overlay
#  mark and the menu-bar glyphs so all three are provably the same object.

MARK_RATIOS = (0.34, 0.62, 0.46)
MARK_WIDTH_TO_GAP = (4.0, 3.0)        # 128 : 96 on the 1024 canvas
