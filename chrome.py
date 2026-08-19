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
    NSColorSpace,
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


_measure = None


def text_height(text, role, width):
    """Wrapped height for `text` at `role` in `width` points.

    Measured with an NSTextField cell rather than boundingRectWithSize_,
    because the two disagree and the cell is the one that decides. For a
    three-line note at 384 pt: boundingRect says 42, adding UsesFontLeading
    says 39, and the control itself lays out at 56. Trusting boundingRect
    clipped the last line off every wrapped note in the app — visible in the
    Intelligence pane as a sentence ending mid-clause.
    """
    global _measure
    if _measure is None:
        _measure = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, width, 10))
        _measure.setBezeled_(False)
        _measure.setDrawsBackground_(False)
        _measure.setEditable_(False)
        _measure.setLineBreakMode_(NSLineBreakByWordWrapping)
        _measure.cell().setWraps_(True)
        _measure.cell().setScrollable_(False)
    _measure.setAttributedStringValue_(tokens.attributed(text, role))
    size = _measure.cell().cellSizeForBounds_(NSMakeRect(0, 0, width, 10000))
    return math.ceil(size.height) + 1


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
            NSColorSpace.sRGBColorSpace())
        #  CSS 152deg: 0deg points up and the angle runs clockwise, so the
        #  ramp travels right and down. NSGradient measures counter-clockwise
        #  from +x, hence 90 - 152.
        grad.drawInRect_angle_(bounds, 90.0 - 152.0)

        sheen = NSGradient.alloc().initWithColors_atLocations_colorSpace_(
            [tokens.rgb("#ffffff", 0.13), tokens.rgb("#ffffff", 0.0)],
            (0.0, 1.0), NSColorSpace.sRGBColorSpace())
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

        tokens.attributed("Kyanth", "wordmark", tokens.BAND_FG).drawAtPoint_(
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


# ------------------------------------------------------------- form rows
#  The Settings shape, from IMPLEMENTATION.md §5: a 132 pt label column, a
#  14 pt gutter, then the controls. Notes wrap inside the box at 11.5 pt.

LABEL_COL = 132.0
VALUE_X = ROW_PAD_X + LABEL_COL + 14.0


class FormRow(NSView):
    """One labelled row inside a grouped box. Draws nothing itself — the box
    paints the fill and the hairlines, so a row can be shown or hidden without
    leaving a gap in the separators."""

    def isFlipped(self):
        return True


def form_row(width, label_text, controls, note=None, note_indent=False,
             trailing=None):
    """Build a row and return (view, height).

    `controls` are laid out left to right from the value column; each is
    vertically centred on the label. `note` wraps under them — indented to the
    value column when it explains a control, flush left when it explains the
    row.
    """
    x = VALUE_X
    top = ROW_PAD_Y
    everything = list(controls) + ([trailing] if trailing else [])
    tallest = max([c.frame().size.height for c in everything] + [16.0])
    for c in controls:
        size = c.frame().size
        c.setFrameOrigin_(NSMakePoint(x, top + (tallest - size.height) / 2.0))
        x += size.width + 8.0
    if trailing is not None:
        size = trailing.frame().size
        trailing.setFrameOrigin_(NSMakePoint(
            width - ROW_PAD_X - size.width, top + (tallest - size.height) / 2.0))

    note_x = VALUE_X if note_indent else ROW_PAD_X
    note_w = width - note_x - ROW_PAD_X
    note_h = text_height(note, "note", note_w) if note else 0.0

    height = ROW_PAD_Y * 2 + tallest + (note_h + 6.0 if note else 0.0)
    row = FormRow.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))

    lab = label(label_text, "body", MUTED_ROLE, x=ROW_PAD_X,
                y=top + (tallest - 16.0) / 2.0, width=LABEL_COL)
    row.addSubview_(lab)
    for c in everything:
        row.addSubview_(c)
    if note:
        n = label(note, "note", tokens.MUTED, width=note_w, x=note_x,
                  y=top + tallest + 6.0, wrap=True)
        row.addSubview_(n)
        row.note = n
    row.label_field = lab
    return row, height


#  `label()` takes a colour, and the form label is always muted.
MUTED_ROLE = tokens.MUTED


def stack_box(width, rows):
    """Put built rows into a BoxView, hairline-separated, and size it."""
    box = BoxView.alloc().initWithFrame_(NSMakeRect(0, 0, width, 10))
    y = 0.0
    seps = []
    for row in rows:
        row.setFrameOrigin_(NSMakePoint(0, y))
        if y:
            seps.append(y)
        y += row.frame().size.height
        box.addSubview_(row)
    box.separators = seps
    box.setFrameSize_(NSMakeSize(width, y))
    return box


# ---------------------------------------------------------------- meter

class MeterView(NSView):
    """The input meter, the same object as the icon's bars and the overlay's
    mark. A microphone that is selected but hearing nothing has to look
    different from one that works."""

    BARS = 16
    BAR_W = 3.0
    GAP = 2.0

    def initWithFrame_(self, frame):
        self = objc.super(MeterView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.level = 0.0
        self.live = True
        return self

    @python_method
    def set_level(self, level):
        if abs(level - self.level) > 0.005:
            self.level = level
            self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        box = self.bounds()
        for i in range(self.BARS):
            frac = (i + 1) / float(self.BARS)
            lit = self.live and self.level >= frac * 0.92
            h = 3.0 + (box.size.height - 3.0) * (0.35 + 0.65 * frac)
            (tokens.PEAK if lit else tokens.METER_IDLE).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(i * (self.BAR_W + self.GAP), 0,
                           self.BAR_W, h if lit else 3.0), 1.5, 1.5).fill()

    @classmethod
    def width(cls):
        return cls.BARS * cls.BAR_W + (cls.BARS - 1) * cls.GAP


class StatusPill(NSView):
    """A small status pill: dot plus one phrase. Used for "Keys arriving",
    which is the only way to tell a wrong chord apart from one another app
    swallowed.

    Named StatusPill rather than PillView because a pyobjc class name IS its
    Objective-C class name, and the overlay already registers a PillView. Two
    modules claiming one runtime name is a hard crash at import, and nothing
    warns until both are loaded in the same process.
    """

    def initWithFrame_(self, frame):
        self = objc.super(StatusPill, self).initWithFrame_(frame)
        if self is None:
            return None
        self.text = ""
        self.on = False
        return self

    @python_method
    def set_state(self, text, on):
        if (text, on) != (self.text, self.on):
            self.text, self.on = text, on
            self.sizeToFit()
            self.setNeedsDisplay_(True)

    @python_method
    def sizeToFit(self):
        s = tokens.attributed(self.text, "note")
        self.setFrameSize_(NSMakeSize(s.size().width + 34.0, 24.0))

    def drawRect_(self, rect):
        box = self.bounds()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(0.5, 0.5, box.size.width - 1, box.size.height - 1),
            box.size.height / 2.0, box.size.height / 2.0)
        (tokens.ACCENT.colorWithAlphaComponent_(0.12) if self.on
         else tokens.CTL).set()
        path.fill()
        (tokens.ACCENT.colorWithAlphaComponent_(0.5) if self.on
         else tokens.BORDER).set()
        path.setLineWidth_(1.0)
        path.stroke()

        (tokens.ACCENT if self.on else tokens.MUTED).set()
        NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(11.0, box.size.height / 2.0 - 3.0, 6.0, 6.0)).fill()
        tokens.attributed(self.text, "note",
                          tokens.FG if self.on else tokens.MUTED).drawAtPoint_(
            NSMakePoint(23.0, box.size.height / 2.0 - 8.0))


# ---------------------------------------------------------------- sidebar

SIDEBAR_W = tokens.SIDEBAR_W          # 198
SOURCE_H = 30.0
SOURCE_INSET = 10.0


class SidebarView(BandView):
    """The band, full height down the left edge. Same gradient as Setup's
    header, so the two windows read as one app."""


class SourceRow(NSView):
    """One item in the source list: glyph, title, optional count badge."""

    def initWithFrame_(self, frame):
        self = objc.super(SourceRow, self).initWithFrame_(frame)
        if self is None:
            return None
        self.title = ""
        self.symbol = ""
        self.badge = ""
        self.selected = False
        self.hover = False
        self.on_press = None
        return self

    #  A hand-drawn view is invisible to accessibility unless it says
    #  otherwise: no role, no label, nothing to press. The tab strip this
    #  replaced was navigable for free, so leaving it out would be a
    #  regression, not merely an omission.
    def isAccessibilityElement(self):
        return True

    def accessibilityRole(self):
        return "AXRadioButton"

    def accessibilityLabel(self):
        return self.title

    def accessibilityTitle(self):
        #  AXTitle is what assistive tools and UI scripting read as the
        #  element's name; AXLabel alone leaves it nameless.
        return self.title

    def accessibilityValue(self):
        return 1 if self.selected else 0

    def accessibilityPerformPress(self):
        if self.on_press is not None:
            self.on_press()
            return True
        return False

    @python_method
    def set_selected(self, on):
        if on != self.selected:
            self.selected = on
            self.setNeedsDisplay_(True)

    @python_method
    def set_badge(self, text):
        if text != self.badge:
            self.badge = text
            self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        box = self.bounds()
        inner = NSMakeRect(SOURCE_INSET, 1.0,
                           box.size.width - SOURCE_INSET * 2, box.size.height - 2)
        if self.selected:
            tokens.ACCENT.set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                inner, tokens.RADIUS_ROW, tokens.RADIUS_ROW).fill()
        elif self.hover:
            tokens.rgb("#ffffff", 0.07).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                inner, tokens.RADIUS_ROW, tokens.RADIUS_ROW).fill()

        fg = tokens.ACCENT_FG if self.selected else tokens.BAND_FG
        cy = box.size.height / 2.0

        icon = tinted_symbol(self.symbol, 13.0, fg)
        if icon is not None:
            size = icon.size()
            icon.drawAtPoint_fromRect_operation_fraction_(
                NSMakePoint(SOURCE_INSET + 10.0, cy - size.height / 2.0),
                NSMakeRect(0, 0, size.width, size.height), 2, 1.0)

        tokens.attributed(self.title, "rowLabel", fg).drawAtPoint_(
            NSMakePoint(SOURCE_INSET + 34.0, cy - 9.0))

        if self.badge:
            s = tokens.attributed(
                self.badge, "version",
                tokens.ACCENT_FG if self.selected else tokens.BAND_DIM)
            s.drawAtPoint_(NSMakePoint(
                box.size.width - SOURCE_INSET - 10.0 - s.size().width, cy - 7.0))


def tinted_symbol(name, size, color):
    """An SF Symbol filled with `color`.

    Template images take their colour from the control that draws them, which
    is no help inside a hand-drawn view — so the fill is baked in with
    sourceAtop, the standard AppKit idiom for exactly this.
    """
    from AppKit import NSImageSymbolConfiguration, NSRectFillUsingOperation

    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if image is None:
        return None
    image = image.imageWithSymbolConfiguration_(
        NSImageSymbolConfiguration.configurationWithPointSize_weight_scale_(
            size, tokens.W_MEDIUM, 2))          # NSImageSymbolScaleMedium
    out = image.copy()
    out.setTemplate_(False)
    out.lockFocus()
    color.set()
    NSRectFillUsingOperation(
        NSMakeRect(0, 0, out.size().width, out.size().height), 5)  # sourceAtop
    out.unlockFocus()
    return out


def bring_to_front(window, center=False):
    """Actually put `window` in front of the user.

    NSApp.activateIgnoringOtherApps_ no longer reliably raises an accessory
    app on current macOS — it is deprecated and the window comes back buried
    a hundred deep in the stacking order, which looks exactly like nothing
    happened. NSRunningApplication still activates, and it has to happen
    before the window is ordered front, not after.
    """
    from AppKit import (NSApp, NSApplicationActivateAllWindows,
                        NSApplicationActivateIgnoringOtherApps,
                        NSRunningApplication)

    NSRunningApplication.currentApplication().activateWithOptions_(
        NSApplicationActivateIgnoringOtherApps | NSApplicationActivateAllWindows)
    NSApp.activateIgnoringOtherApps_(True)      # harmless, helps on older macOS
    if center:
        center_on_pointer(window)
    window.makeKeyAndOrderFront_(None)
    window.orderFrontRegardless()


def center_on_pointer(window):
    """Centre on the display the user is actually looking at.

    NOT window.center(), which uses the main screen — and the main screen
    follows keyboard focus, so on a multi-display setup the window opens on a
    monitor nobody is watching and reads as "it never opened". The overlay
    already learned this; the windows had not. The pointer is the best
    available proxy for attention.
    """
    from AppKit import NSEvent, NSScreen

    try:
        point = NSEvent.mouseLocation()
        target = None
        for screen in NSScreen.screens():
            f = screen.frame()
            if (f.origin.x <= point.x < f.origin.x + f.size.width
                    and f.origin.y <= point.y < f.origin.y + f.size.height):
                target = screen
                break
        if target is None:
            window.center()
            return
        visible = target.visibleFrame()
        size = window.frame().size
        window.setFrameOrigin_(NSMakePoint(
            visible.origin.x + (visible.size.width - size.width) / 2.0,
            visible.origin.y + (visible.size.height - size.height) / 2.0))
    except Exception:
        window.center()
