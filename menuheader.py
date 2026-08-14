"""The dropdown's status header — Level.

Not a menu item: a custom NSView hosted in one, so it takes no selection
highlight and is not clickable. That matters because the status line is a
readout, and a row that highlights on hover invites a click that does nothing.

It carries three things a menu row could not:
  * the state dot and text, without truncating to the menu width
  * the live input meter, so "is it hearing me" is answered before you open
    anything
  * the shortcut as key caps rather than prose — the one thing users forget
    is the one thing the menu should lead with

rumps has no API for this, so it reaches through to the underlying NSMenuItem
and calls setView_. That is the only place in the app that drops below rumps.
"""

import objc
from objc import python_method
from AppKit import (
    NSBezierPath,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSKernAttributeName,
    NSMakeRect,
    NSString,
    NSView,
)

import tokens

WIDTH = 286.0            # SURFACES.md §3
HEIGHT = 58.0
PAD_X = 14.0

#  Meter: a row of 3 pt bars 2 pt apart growing from a common baseline. Used
#  here, beside the microphone picker, and in Setup's verification step.
METER_BARS = 13
METER_BAR_W = 3.0
METER_GAP = 2.0
METER_H = 13.0

STATE_TEXT = {
    "idle": "Ready",
    "recording": "Listening",
    "working": "Transcribing…",
    "disabled": "Disabled",
    "needs-permission": "Waiting for permissions",
    "error": "Something went wrong",
}


class HeaderView(NSView):
    """State dot · text · live meter, then the chord in key caps."""

    def initWithFrame_(self, frame):
        self = objc.super(HeaderView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.state = "idle"
        self.level = 0.0
        self.chord = []          # e.g. ["Right ⌥", "Right ⌘"]
        self.mode_hint = "Hold"
        return self

    @python_method
    def _dot_color(self):
        return {
            "recording": tokens.RECORD,
            "working": tokens.WARN,
            "error": tokens.RECORD,
            "needs-permission": tokens.WARN,
            "disabled": tokens.MUTED,
        }.get(self.state, tokens.MUTED)

    @python_method
    def _draw_text(self, text, x, y, size, weight, color, tracking=0.0):
        attrs = {
            NSFontAttributeName: NSFont.systemFontOfSize_weight_(size, weight),
            NSForegroundColorAttributeName: color,
            NSKernAttributeName: size * tracking,
        }
        s = NSString.stringWithString_(text)
        s.drawAtPoint_withAttributes_((x, y), attrs)
        return s.sizeWithAttributes_(attrs).width

    @python_method
    def _draw_keycap(self, text, x, y):
        """A key cap, not prose — the shortcut should look like keys."""
        attrs = {
            NSFontAttributeName: NSFont.systemFontOfSize_weight_(10.5, tokens.W_MEDIUM),
            NSForegroundColorAttributeName: tokens.FG,
            NSKernAttributeName: 0.1,
        }
        s = NSString.stringWithString_(text)
        w = s.sizeWithAttributes_(attrs).width
        box = NSMakeRect(x, y - 3.0, w + 12.0, 17.0)
        tokens.CTL.set()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(box, 4.0, 4.0)
        path.fill()
        tokens.BORDER.set()
        path.setLineWidth_(1.0)
        path.stroke()
        s.drawAtPoint_withAttributes_((x + 6.0, y), attrs)
        return box.size.width

    def drawRect_(self, rect):
        bounds = self.bounds()
        top = bounds.size.height

        #  ---- state row
        y = top - 24.0
        self._dot_color().set()
        NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(PAD_X, y + 3.5, 6.0, 6.0)).fill()
        self._draw_text(STATE_TEXT.get(self.state, self.state),
                        PAD_X + 12.0, y, 12.5, tokens.W_MEDIUM, tokens.FG)

        #  ---- live meter, right-aligned. A microphone that is selected but
        #  hearing nothing must look different from one that works.
        meter_w = METER_BARS * METER_BAR_W + (METER_BARS - 1) * METER_GAP
        mx = bounds.size.width - PAD_X - meter_w
        base = y + 1.0
        for i in range(METER_BARS):
            frac = (i + 1) / float(METER_BARS)
            lit = self.state == "recording" and self.level >= frac * 0.92
            h = 3.0 + (METER_H - 3.0) * (0.35 + 0.65 * frac)
            (tokens.PEAK if lit else tokens.METER_IDLE).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(mx + i * (METER_BAR_W + METER_GAP), base,
                           METER_BAR_W, h if lit else 3.0),
                1.5, 1.5).fill()

        #  ---- shortcut row, in key caps
        y2 = top - 46.0
        x = PAD_X
        x += self._draw_text(f"{self.mode_hint} ", x, y2, 11.5,
                             tokens.W_REGULAR, tokens.MUTED, 0.01)
        for i, cap in enumerate(self.chord):
            if i:
                x += self._draw_text(" + ", x, y2, 11.5,
                                     tokens.W_REGULAR, tokens.MUTED)
            x += self._draw_keycap(cap, x, y2) + 1.0
        self._draw_text("  and speak", x, y2, 11.5,
                        tokens.W_REGULAR, tokens.MUTED, 0.01)


def make(chord_labels, mode_hint="Hold"):
    """Returns (nsview, host) — attach `host` to a menu item via setView_."""
    view = HeaderView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, HEIGHT))
    view.chord = list(chord_labels)
    view.mode_hint = mode_hint
    return view
