"""Shared window furniture — Level.

Setup and Settings are the same window with different contents: a brand band
across the top, grouped boxes below it, a footer with one primary action. This
module is that shared vocabulary, so the two surfaces cannot drift apart.

Everything is hand-drawn against `tokens`. There is no autolayout: the app has
no Interface Builder, sizes are known, and manual frames are far easier to
reason about than constraint conflicts logged at runtime.

The one rule worth restating here, because this file is where it would be
broken: the lockup has ONE construction, ONE size and ONE position — top-left,
full strength, painted with the icon's own gradient stops. No ghosted variant,
no small variant. DESIGN.md §3.2.
"""

import math

import objc
from objc import python_method
from AppKit import (
    NSAttributedString,
    NSBezelStyleRounded,
    NSBezierPath,
    NSButton,
    NSColor,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSGradient,
    NSImage,
    NSKernAttributeName,
    NSLineBreakByWordWrapping,
    NSMakePoint,
    NSMakeRect,
    NSMakeSize,
    NSMenu,
    NSMenuItem,
    NSPopUpButton,
    NSStringDrawingUsesLineFragmentOrigin,
    NSTextField,
    NSView,
)

import tokens

# ---------------------------------------------------------------- geometry

WIN_W = 620.0            # SURFACES.md §4 — Setup and Settings share this width
TITLEBAR_H = 34.0
BAND_H = 163.0
FOOTER_H = 46.0

PAD = tokens.PANE_X      # 22
ROW_PAD_X = 14.0
ROW_PAD_Y = 11.0
MARK_COL = 20.0
MARK_GAP = 12.0
DOT = 18.0

RING_D = 54.0
RING_R = 23.0
RING_W = 4.0

#  The lockup, from level.css .mark / .wordmark. 34 : 62 : 46 at 24 pt tall,
#  6 pt bars, 4.5 pt gaps — the icon's own 4:3 width-to-gap ratio.
MARK_H = 24.0
MARK_BAR_W = 6.0
MARK_BAR_GAP = 4.5
MARK_W = MARK_BAR_W * 3 + MARK_BAR_GAP * 2
LOCKUP_GAP = 11.0


# ------------------------------------------------------------------ text

def label(text, role, color=None, width=None, x=0.0, y=0.0, wrap=False):
    """A non-editable NSTextField carrying a type role from `tokens`."""
    f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width or 10, 18))
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setAttributedStringValue_(
        tokens.attributed(text, role, color or tokens.FG))
    if wrap:
        f.setLineBreakMode_(NSLineBreakByWordWrapping)
        f.cell().setWraps_(True)
        f.cell().setScrollable_(False)
    if width:
        f.setFrameSize_(NSMakeSize(width, text_height(text, role, width)))
    else:
        f.sizeToFit()
    return f


def text_height(text, role, width):
    """Wrapped height for `text` at `role` in `width` points."""
    s = tokens.attributed(text, role)
    rect = s.boundingRectWithSize_options_(
        NSMakeSize(width, 10000), NSStringDrawingUsesLineFragmentOrigin)
    return math.ceil(rect.size.height) + 2


def set_text(field, text, role, color=None):
    field.setAttributedStringValue_(
        tokens.attributed(text, role, color or tokens.FG))


# ---------------------------------------------------------------- buttons

def button(title, target, action, primary=False, quiet=False,
           x=0.0, y=0.0, width=None):
    b = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width or 100, 28))
    b.setBezelStyle_(NSBezelStyleRounded)
    b.setTarget_(target)
    b.setAction_(action)
    b.setFont_(tokens.font(12.0, tokens.W_MEDIUM))
    b.setTitle_(title)
    if primary:
        #  bezelColor is how AppKit tints a push button; combined with a white
        #  title it is the design's primary without reimplementing the bezel.
        b.setBezelColor_(tokens.ACCENT)
        b.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                title, {NSFontAttributeName: tokens.font(12.0, tokens.W_MEDIUM),
                        NSForegroundColorAttributeName: tokens.ACCENT_FG}))
    elif quiet:
        b.setBordered_(False)
        b.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                title, {NSFontAttributeName: tokens.font(12.0, tokens.W_REGULAR),
                        NSForegroundColorAttributeName: tokens.MUTED}))
    b.sizeToFit()
    size = b.frame().size
    b.setFrameSize_(NSMakeSize(max(width or 0, size.width + 20), 28))
    b.setFrameOrigin_(NSMakePoint(x, y))
    return b


def popup(title, items, target, action, x=0.0, y=0.0):
    """A quiet pop-up used as an overflow menu. `items` is [(title, tag)]."""
    p = NSPopUpButton.alloc().initWithFrame_pullsDown_(
        NSMakeRect(x, y, 96, 28), True)
    p.setBezelStyle_(NSBezelStyleRounded)
    p.setFont_(tokens.font(12.0, tokens.W_REGULAR))
    menu = NSMenu.alloc().init()
    menu.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        title, None, ""))          # pull-down item 0 is the label
    for item_title, tag in items:
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            item_title, action, "")
        mi.setTarget_(target)
        mi.setTag_(tag)
        menu.addItem_(mi)
    p.setMenu_(menu)
    p.sizeToFit()
    p.setFrameOrigin_(NSMakePoint(x, y))
    return p


# ------------------------------------------------------------------- band

class BandView(NSView):
    """The brand band: a 152° gradient with a sheen over its top 46%.

    Identical in both appearances apart from a small lift for legibility. The
    Dock tile does not change appearance, so neither does the band.
    """

    def isFlipped(self):
        return False

    @python_method
    def _stops(self):
        dark = self.effectiveAppearance().bestMatchFromAppearancesWithNames_(
            ["NSAppearanceNameAqua", "NSAppearanceNameDarkAqua"]) \
            == "NSAppearanceNameDarkAqua"
        return tokens.BAND_DARK if dark else tokens.BAND_LIGHT

    def drawRect_(self, rect):
        bounds = self.bounds()
        stops = self._stops()
        grad = NSGradient.alloc().initWithColors_atLocations_colorSpace_(
            [tokens.rgb(c) for c in stops],
            tokens.BAND_LOCATIONS,
            NSColor.blackColor().colorSpace())
        #  CSS 152deg: 0deg points up and the angle runs clockwise, so the
        #  ramp travels right and down. NSGradient measures counter-clockwise
        #  from +x, hence 90 - 152.
        grad.drawInRect_angle_(bounds, 90.0 - 152.0)

        sheen = NSGradient.alloc().initWithColors_atLocations_colorSpace_(
            [tokens.rgb("#ffffff", 0.13), tokens.rgb("#ffffff", 0.0)],
            (0.0, 1.0), NSColor.blackColor().colorSpace())
        sheen.drawInRect_angle_(
            NSMakeRect(0, bounds.size.height * 0.54,
                       bounds.size.width, bounds.size.height * 0.46), -90.0)


class LockupView(NSView):
    """The mark and the wordmark. One size, one construction, full strength."""

    def drawRect_(self, rect):
        cy = self.bounds().size.height / 2.0
        for i, ratio in enumerate(tokens.MARK_RATIOS):
            h = MARK_H * (ratio / 0.62)
            x = i * (MARK_BAR_W + MARK_BAR_GAP)
            bar = NSMakeRect(x, cy - h / 2.0, MARK_BAR_W, h)
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bar, MARK_BAR_W / 2.0, MARK_BAR_W / 2.0)
            stops = tokens.LOGO_PEAK if i == 1 else tokens.LOGO_BAR
            NSGradient.alloc().initWithStartingColor_endingColor_(
                tokens.rgb(stops[0]), tokens.rgb(stops[1])
            ).drawInBezierPath_angle_(path, -90.0)

        tokens.attributed("shout", "wordmark", tokens.BAND_FG).drawAtPoint_(
            NSMakePoint(MARK_W + LOCKUP_GAP, cy - 10.0))


def lockup(x, y):
    v = LockupView.alloc().initWithFrame_(NSMakeRect(x, y, 120.0, MARK_H))
    return v


class RingView(NSView):
    """Progress as a ring plus `n/8`. A status readout, not part of the mark —
    which is why it sits at the opposite end of the headline row."""

    def initWithFrame_(self, frame):
        self = objc.super(RingView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.done = 0
        self.total = 8
        return self

    @python_method
    def set_progress(self, done, total):
        if (done, total) != (self.done, self.total):
            self.done, self.total = done, total
            self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        c = self.bounds().size.width / 2.0
        box = NSMakeRect(c - RING_R, c - RING_R, RING_R * 2, RING_R * 2)

        track = NSBezierPath.bezierPathWithOvalInRect_(box)
        track.setLineWidth_(RING_W)
        tokens.rgb("#ffffff", 0.22).set()
        track.stroke()

        if self.done:
            fill = NSBezierPath.bezierPath()
            fill.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                NSMakePoint(c, c), RING_R, 90.0,
                90.0 - 360.0 * self.done / float(self.total), True)
            fill.setLineWidth_(RING_W)
            fill.setLineCapStyle_(1)     # round
            tokens.PEAK.set()
            fill.stroke()

        num = NSAttributedString.alloc().initWithString_attributes_(
            f"{self.done}/{self.total}",
            {NSFontAttributeName: tokens.tabular(15.0, tokens.W_SEMIBOLD),
             NSForegroundColorAttributeName: tokens.BAND_FG,
             NSKernAttributeName: -0.3})
        size = num.size()
        num.drawAtPoint_(NSMakePoint(c - size.width / 2.0, c - size.height / 2.0))


# ------------------------------------------------------------ grouped box

class BoxView(NSView):
    """The System Settings shape: hairline-separated rows inside a 9 pt box.

    Not NSBox, which brings its own inset and title styling you then fight.
    """

    def initWithFrame_(self, frame):
        self = objc.super(BoxView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.separators = []       # y offsets from the top of the box
        self.blocking = False      # peak-coloured edge when it owns the step
        return self

    def isFlipped(self):
        #  Rows are appended top-down, which is the order they are written and
        #  the order the user reads them. Without this the first step lands at
        #  the bottom of its box.
        return True

    def drawRect_(self, rect):
        box = self.bounds()
        inset = NSMakeRect(0.5, 0.5, box.size.width - 1, box.size.height - 1)
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            inset, tokens.RADIUS_BOX, tokens.RADIUS_BOX)
        tokens.FOOTER.set()
        path.fill()

        for y in self.separators:
            tokens.BORDER.set()
            NSBezierPath.fillRect_(NSMakeRect(0, y, box.size.width, 1.0))

        (tokens.ACCENT.colorWithAlphaComponent_(0.42) if self.blocking
         else tokens.BORDER).set()
        path.setLineWidth_(1.0)
        path.stroke()


COUNT_W = 70.0


def group_label(text, count_text, y, width):
    """The uppercase phase label and its `n of m`, outside the box.

    Uppercase always carries >= 0.06em tracking — uppercase at default
    tracking is the most reliable tell that a screen was not drawn by a
    designer. The `groupLabel` role supplies 0.11em.
    """
    left = label(text.upper(), "groupLabel", tokens.MUTED, x=PAD + 13.0, y=y)
    right = label(count_text, "version", tokens.MUTED,
                  width=COUNT_W, x=PAD + width - COUNT_W - 2.0, y=y)
    right.setAlignment_(2)              # NSTextAlignmentRight
    right.setFrameSize_(NSMakeSize(COUNT_W, 15.0))
    return left, right


class CheckRow(NSView):
    """One setup step: status dot, title, reason, and at most one button.

    The reason text changes with the state — a row that says "Granted" when it
    is not granted is the failure mode this window exists to prevent.
    """

    def initWithFrame_(self, frame):
        self = objc.super(CheckRow, self).initWithFrame_(frame)
        if self is None:
            return None
        self.mark = "todo"        # done | live | warn | todo
        self.tinted = False
        return self

    @python_method
    def set_mark(self, mark, tinted):
        if (mark, tinted) != (self.mark, self.tinted):
            self.mark, self.tinted = mark, tinted
            self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        box = self.bounds()
        if self.tinted:
            tokens.ACCENT.colorWithAlphaComponent_(0.07).set()
            NSBezierPath.fillRect_(box)

        top = box.size.height - ROW_PAD_Y
        circle = NSMakeRect(ROW_PAD_X, top - DOT + 1.0, DOT, DOT)
        path = NSBezierPath.bezierPathWithOvalInRect_(circle)

        if self.mark == "todo":
            tokens.BORDER.set()
            path.setLineWidth_(1.5)
            path.setLineDash_count_phase_([2.5, 2.5], 2, 0.0)
            path.stroke()
            return

        {"done": tokens.MARK_DONE, "warn": tokens.WARN,
         "live": tokens.ACCENT}.get(self.mark, tokens.MARK_DONE).set()
        path.fill()

        glyph = "!" if self.mark == "warn" else "✓"
        fg = tokens.SILVER if self.mark == "done" else tokens.ACCENT_FG
        s = NSAttributedString.alloc().initWithString_attributes_(
            glyph, {NSFontAttributeName: tokens.font(11.0, tokens.W_SEMIBOLD),
                    NSForegroundColorAttributeName: fg})
        size = s.size()
        s.drawAtPoint_(NSMakePoint(
            circle.origin.x + (DOT - size.width) / 2.0,
            circle.origin.y + (DOT - size.height) / 2.0 + 0.5))


# ------------------------------------------------------------------ footer

class FooterView(NSView):
    def drawRect_(self, rect):
        box = self.bounds()
        tokens.FOOTER.set()
        NSBezierPath.fillRect_(box)
        tokens.BORDER.set()
        NSBezierPath.fillRect_(
            NSMakeRect(0, box.size.height - 1.0, box.size.width, 1.0))
