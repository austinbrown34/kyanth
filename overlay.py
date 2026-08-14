"""On-screen "I am listening" indicator.

A floating pulse near the top of the screen, shown while recording and while
transcribing. It exists because every other signal shout has is easy to miss:
the menu-bar icon is hidden whenever the menu bar is full, and the sound cues
are inaudible if the volume is down or headphones are out.

The hard requirement is that this must NEVER take focus. shout pastes into
whatever app is frontmost, so an overlay that becomes key window would redirect
the user's dictation into itself. That is why this is a non-activating panel
that ignores mouse events and is ordered in with orderFrontRegardless() rather
than makeKeyAndOrderFront_().
"""

import math

import objc
from objc import python_method
from AppKit import (
    NSBackingStoreBuffered,
    NSEvent,
    NSBezierPath,
    NSColor,
    NSCompositingOperationSourceOver,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSStatusWindowLevel,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSObject, NSTimer

W, H = 108, 108
TOP_MARGIN = 28          # gap below the menu bar; visibleFrame already
                         # excludes the bar itself
FPS = 30.0
PULSE_SECONDS = 1.25     # one full ripple cycle
RINGS = 3

LISTENING = "listening"
WORKING = "working"


class RippleView(NSView):
    """Concentric rings expanding from a solid core."""

    def initWithFrame_(self, frame):
        self = objc.super(RippleView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.phase = 0.0
        self.mode = LISTENING
        self.level = 0.0
        return self

    @python_method
    def _tint(self):
        if self.mode == WORKING:
            return NSColor.systemOrangeColor()
        return NSColor.systemRedColor()

    def drawRect_(self, rect):
        bounds = self.bounds()
        cx = bounds.size.width / 2.0
        cy = bounds.size.height / 2.0
        tint = self._tint()

        # Soft dark plate so the pulse reads on light and dark backgrounds
        # alike. Drawn first, at low alpha, so it never dominates.
        NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.22).set()
        plate = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(cx - 34, cy - 34, 68, 68), 34, 34)
        plate.fill()

        max_r = 30.0
        for i in range(RINGS):
            # Stagger the rings so one leaves as the next begins.
            p = (self.phase + i / float(RINGS)) % 1.0
            r = 10.0 + p * (max_r - 10.0)
            alpha = (1.0 - p) * 0.55
            if alpha <= 0.01:
                continue
            tint.colorWithAlphaComponent_(alpha).set()
            ring = NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(cx - r, cy - r, r * 2, r * 2))
            ring.setLineWidth_(2.0)
            ring.stroke()

        # Core scales gently with the live input level, so a dead microphone
        # looks different from a working one.
        core = 7.0 + min(self.level, 1.0) * 5.0
        tint.colorWithAlphaComponent_(0.95).set()
        NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(cx - core, cy - core, core * 2, core * 2)).fill()


class Overlay(NSObject):
    """Owns the panel. All methods are safe to call from the main thread only."""

    def init(self):
        self = objc.super(Overlay, self).init()
        if self is None:
            return None
        self.panel = None
        self.view = None
        self.timer = None
        self.visible = False
        return self

    @python_method
    def _build(self):
        if self.panel is not None:
            return
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered, False)
        self.panel.setLevel_(NSStatusWindowLevel)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(False)
        #  Must not intercept clicks: the user is typing into another app.
        self.panel.setIgnoresMouseEvents_(True)
        #  Visible on every Space and above full-screen apps, without pulling
        #  the user out of the one they are in.
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary)

        self.view = RippleView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        self.panel.setContentView_(self.view)
        self._reposition()

    @python_method
    def _target_screen(self):
        """The display the user is actually looking at.

        NOT NSScreen.mainScreen(): that follows keyboard focus, and on a
        multi-display setup it happily returns a screen the user is not looking
        at. On a five-display Mac this placed the indicator at x=-1956 — drawn
        correctly, on a monitor nobody was watching.

        The pointer is the best available proxy for attention. Falls back to
        the primary display, which always holds the menu bar.
        """
        try:
            point = NSEvent.mouseLocation()
            for screen in NSScreen.screens():
                f = screen.frame()
                if (f.origin.x <= point.x < f.origin.x + f.size.width
                        and f.origin.y <= point.y < f.origin.y + f.size.height):
                    return screen
        except Exception:
            pass
        screens = NSScreen.screens()
        return screens[0] if screens else NSScreen.mainScreen()

    @python_method
    def _reposition(self):
        screen = self._target_screen()
        if screen is None or self.panel is None:
            return
        frame = screen.visibleFrame()      # respects the menu bar and Dock
        x = frame.origin.x + (frame.size.width - W) / 2.0
        #  setFrameOrigin_ takes the BOTTOM-left corner, so subtract the height
        #  to leave TOP_MARGIN of clearance above the panel.
        y = frame.origin.y + frame.size.height - TOP_MARGIN - H
        self.panel.setFrameOrigin_((x, y))

    # ------------------------------------------------------------ control

    @python_method
    def show(self, mode: str = LISTENING):
        self._build()
        self.view.mode = mode
        self.view.phase = 0.0
        self._reposition()          # the screen may have changed since last time
        # orderFrontRegardless, never makeKeyAndOrderFront_: taking key status
        # would redirect the paste into this panel.
        self.panel.orderFrontRegardless()
        self.visible = True
        if self.timer is None:
            self.timer = (
                NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    1.0 / FPS, self, "tick:", None, True))

    @python_method
    def set_mode(self, mode: str):
        if self.view is not None:
            self.view.mode = mode
            self.view.setNeedsDisplay_(True)

    @python_method
    def set_level(self, level: float):
        if self.view is not None:
            self.view.level = float(level)

    @python_method
    def hide(self):
        self.visible = False
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None
        if self.panel is not None:
            self.panel.orderOut_(None)

    def tick_(self, timer):
        if not self.visible or self.view is None:
            return
        self.view.phase = (self.view.phase + 1.0 / (FPS * PULSE_SECONDS)) % 1.0
        self.view.setNeedsDisplay_(True)
