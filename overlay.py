"""The listening overlay — Level.

A ≈135 × 36 pill docked under the notch, carrying the app's own mark plus one
line of text. It replaces the 108 × 108 wordless ripple: a fifth of the area,
and it can say *why* something failed.

The mark IS the meter. Bars grow from the centre axis; the centre bar reads the
live input level and the flanks replay the same envelope 4 and 8 frames late.
The lag is the point — a syllable enters at the centre and travels outward, so
the mark ripples in time with the voice instead of three bars twitching
independently. At rest it settles to the icon's own 34 : 62 : 46 proportions,
so the overlay never becomes a different object; it is the app icon breathing.

The hard requirement is unchanged and is functional, not cosmetic: **this must
never become key window.** shout pastes into whatever app is frontmost, so an
overlay that took focus would redirect the user's dictation into itself.
"""

import objc
from objc import python_method
from AppKit import (
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSKernAttributeName,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSStatusWindowLevel,
    NSString,
    NSView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSWorkspace,
)
from Foundation import NSObject, NSTimer
from Quartz import CAGradientLayer

import tokens

#  ≈135 at rest; the pill grows to fit its line so "Model server not
#  responding" is not clipped. Height and radius never change.
W_MIN, H = 135.0, 36.0
TOP_GAP = 33.0            # below the menu bar — under the notch where there is one
FPS = 60.0
CORNER = H / 2.0

#  Mark geometry inside the pill, in the icon's proportions.
MARK_X = 13.0
TEXT_GAP = 11.0
TRAILING = 15.0
MARK_MAX = 20.0
BAR_W = 5.0
BAR_GAP = 3.75            # the icon's 4 : 3 width-to-gap ratio
REST = tuple(MARK_MAX * (r / 0.62) for r in tokens.MARK_RATIOS)

LAG_L, LAG_R = 4, 8       # 4 and 8 frames at 60 fps ≈ 70 ms and 130 ms

LISTENING = "listening"
TRANSCRIBING = "transcribing"
PASTED = "pasted"
CLIPBOARD = "clipboard"
IGNORED = "ignored"
ERROR = "error"

#  Every state carries text. That is the point of the pill over the ripple.
TEXT = {
    LISTENING: "Listening",
    TRANSCRIBING: "Transcribing…",
    PASTED: "Pasted",
    CLIPBOARD: "Copied — press ⌘V",
    IGNORED: "Nothing heard",
    ERROR: "Something went wrong",
}

#  How long an outcome stays up before the pill fades.
DWELL = {PASTED: 1.5, CLIPBOARD: 2.6, IGNORED: 1.5, ERROR: 3.2}


class MarkMeter:
    """Ring buffer of the smoothed envelope, read at three offsets.

    Plain Python rather than an NSObject so the audio thread can push into it
    without bridging cost.
    """

    def __init__(self):
        self.hist = [0.0] * 16
        self.i = 0

    def push(self, level: float):
        env = self.hist[self.i]
        env += (level - env) * 0.17          # smoothing
        self.i = (self.i + 1) % len(self.hist)
        self.hist[self.i] = env

    def _past(self, lag: int) -> float:
        return self.hist[(self.i - lag) % len(self.hist)]

    def heights(self):
        e = self.hist[self.i]
        return (REST[0] + (MARK_MAX - REST[0]) * self._past(LAG_L),
                REST[1] + (MARK_MAX - REST[1]) * e,
                REST[2] + (MARK_MAX - REST[2]) * self._past(LAG_R))

    def level(self) -> float:
        return self.hist[self.i]

    def decay(self):
        self.push(0.0)


def text_attributes():
    return {
        NSFontAttributeName: NSFont.systemFontOfSize_weight_(11.5, tokens.W_MEDIUM),
        NSForegroundColorAttributeName: tokens.BAND_FG,
        NSKernAttributeName: 0.1,
    }


def text_origin_x() -> float:
    return MARK_X + 3 * BAR_W + 2 * BAR_GAP + TEXT_GAP


def width_for(text: str) -> float:
    """Pill width that fits `text` without clipping, never below the rest size."""
    label = NSString.stringWithString_(text or "")
    measured = label.sizeWithAttributes_(text_attributes()).width
    return max(W_MIN, text_origin_x() + measured + TRAILING)


class PillView(NSView):
    """The mark and one line of text, over the band plate."""

    def initWithFrame_(self, frame):
        self = objc.super(PillView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.meter = MarkMeter()
        self.state = LISTENING
        self.text = TEXT[LISTENING]
        self.phase = 0
        self.reduce_motion = False
        return self

    @python_method
    def _bar_heights(self):
        if self.reduce_motion or self.state in (PASTED, CLIPBOARD):
            return REST
        if self.state == TRANSCRIBING:
            #  Three stubs with the highlight cycling — the same shape family
            #  as the menu-bar `transcribing` glyph, so the two surfaces teach
            #  each other.
            return tuple(9.0 if i == self.phase % 3 else 4.4 for i in range(3))
        if self.state in (IGNORED, ERROR):
            return (4.4, 4.4, 4.4)
        return self.meter.heights()

    @python_method
    def _peak_color(self):
        if self.state == ERROR:
            return tokens.RECORD
        if self.state == TRANSCRIBING:
            return tokens.WARN
        return tokens.rgb("#4f9dff")

    def drawRect_(self, rect):
        bounds = self.bounds()
        mid_y = bounds.size.height / 2.0
        heights = self._bar_heights()
        level = 0.0 if self.reduce_motion else self.meter.level()

        #  Only the peak bar glows, and the glow tracks amplitude — a
        #  microphone hearing nothing sits flat and dark.
        if self.state == LISTENING and level > 0.02:
            cx = MARK_X + BAR_W + BAR_GAP + BAR_W / 2.0
            r = 9.0 + level * 14.0
            self._peak_color().colorWithAlphaComponent_(0.08 + level * 0.36).set()
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(cx - r, mid_y - r, r * 2, r * 2)).fill()

        for i, h in enumerate(heights):
            x = MARK_X + i * (BAR_W + BAR_GAP)
            if i == 1:
                self._peak_color().set()
            else:
                tokens.SILVER.colorWithAlphaComponent_(
                    0.45 if self.state in (IGNORED, ERROR) else 0.92).set()
            #  Bars grow from the centre axis, not from a baseline.
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x, mid_y - h / 2.0, BAR_W, h),
                BAR_W / 2.0, BAR_W / 2.0).fill()

        label = NSString.stringWithString_(self.text)
        size = label.sizeWithAttributes_(text_attributes())
        label.drawAtPoint_withAttributes_(
            (text_origin_x(), mid_y - size.height / 2.0), text_attributes())


class OverlayPanel(NSPanel):
    """Belt and braces on top of the non-activating style mask."""

    def canBecomeKeyWindow(self):
        return False

    def canBecomeMainWindow(self):
        return False


class Overlay(NSObject):
    """Owns the panel. Main-thread only."""

    def init(self):
        self = objc.super(Overlay, self).init()
        if self is None:
            return None
        self.panel = None
        self.view = None
        self.timer = None
        self.dismiss_timer = None
        self.visible = False
        return self

    @python_method
    def _build(self):
        if self.panel is not None:
            return
        self.panel = OverlayPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W_MIN, H),
            NSWindowStyleMaskNonactivatingPanel | NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered, False)
        self.panel.setLevel_(NSStatusWindowLevel)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorIgnoresCycle)
        self.panel.setFloatingPanel_(True)
        self.panel.setBecomesKeyOnlyIfNeeded_(True)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setIgnoresMouseEvents_(True)   # a readout, not a control
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(True)

        #  Real material rather than a flat scrim, tinted with the icon's own
        #  ground so the thing under the notch is recognisably this app before
        #  you read a word of it.
        plate = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, W_MIN, H))
        plate.setMaterial_(NSVisualEffectMaterialHUDWindow)
        plate.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        plate.setState_(NSVisualEffectStateActive)
        plate.setWantsLayer_(True)
        plate.layer().setCornerRadius_(CORNER)
        plate.layer().setMasksToBounds_(True)

        band = CAGradientLayer.layer()
        band.setColors_([tokens.cg(c, 0.82) for c in tokens.BAND_LIGHT])
        band.setLocations_(list(tokens.BAND_LOCATIONS))
        band.setStartPoint_((0.0, 1.0))
        band.setEndPoint_((0.47, 0.0))
        band.setFrame_(((0, 0), (W_MIN, H)))
        plate.layer().addSublayer_(band)

        sheen = CAGradientLayer.layer()
        sheen.setColors_([tokens.cg(c, a) for c, a in tokens.BAND_SHEEN])
        sheen.setLocations_(list(tokens.BAND_SHEEN_LOCATIONS))
        sheen.setStartPoint_((0.5, 1.0))
        sheen.setEndPoint_((0.5, 0.0))
        sheen.setFrame_(((0, 0), (W_MIN, H)))
        plate.layer().addSublayer_(sheen)

        self.view = PillView.alloc().initWithFrame_(NSMakeRect(0, 0, W_MIN, H))
        plate.addSubview_(self.view)
        self.panel.setContentView_(plate)
        self._reposition()

    @python_method
    def _target_screen(self):
        """The display the user is looking at.

        NOT NSScreen.mainScreen(): that follows keyboard focus and on a
        multi-display setup returns a screen nobody is watching. The pointer is
        the best available proxy for attention.
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
    def _resize_to_text(self):
        if self.panel is None or self.view is None:
            return
        w = width_for(self.view.text)
        frame = self.panel.frame()
        if abs(frame.size.width - w) < 0.5:
            return
        self.panel.setFrame_display_(
            ((frame.origin.x, frame.origin.y), (w, H)), False)
        plate = self.panel.contentView()
        plate.setFrame_(((0, 0), (w, H)))
        for layer in (plate.layer().sublayers() or []):
            layer.setFrame_(((0, 0), (w, H)))
        self.view.setFrame_(((0, 0), (w, H)))

    @python_method
    def _reposition(self):
        screen = self._target_screen()
        if screen is None or self.panel is None:
            return
        full = screen.frame()
        visible = screen.visibleFrame()
        menubar = (full.origin.y + full.size.height) - (
            visible.origin.y + visible.size.height)
        w = self.panel.frame().size.width
        x = full.origin.x + (full.size.width - w) / 2.0
        y = full.origin.y + full.size.height - menubar - TOP_GAP - H
        self.panel.setFrameOrigin_((x, y))

    @python_method
    def _reduce_motion(self) -> bool:
        try:
            return bool(NSWorkspace.sharedWorkspace()
                        .accessibilityDisplayShouldReduceMotion())
        except Exception:
            return False

    # ------------------------------------------------------------- control

    @python_method
    def show(self, state: str = LISTENING, text: str | None = None):
        self._build()
        first = not self.visible
        self.view.state = state
        self.view.text = text or TEXT.get(state, "")
        self.view.reduce_motion = self._reduce_motion()
        self._cancel_dismiss()
        self._resize_to_text()
        self._reposition()

        #  orderFrontRegardless, never makeKeyAndOrderFront_.
        self.panel.orderFrontRegardless()
        self.visible = True
        self.panel.setAlphaValue_(1.0)
        if first and not self.view.reduce_motion:
            self._spring_in()

        if self.timer is None:
            self.timer = (
                NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    1.0 / FPS, self, "tick:", None, True))
        self._arm_dismiss(state)

    @python_method
    def _spring_in(self):
        from Quartz import CABasicAnimation, CASpringAnimation

        layer = self.panel.contentView().layer()
        if layer is None:
            return
        spring = CASpringAnimation.animationWithKeyPath_("transform.scale")
        spring.setFromValue_(0.9)
        spring.setToValue_(1.0)
        spring.setDamping_(14.0)
        spring.setStiffness_(260.0)
        spring.setMass_(1.0)
        spring.setDuration_(spring.settlingDuration())
        layer.addAnimation_forKey_(spring, "springIn")

        fade = CABasicAnimation.animationWithKeyPath_("opacity")
        fade.setFromValue_(0.0)
        fade.setToValue_(1.0)
        fade.setDuration_(0.17)
        layer.addAnimation_forKey_(fade, "fadeIn")

    @python_method
    def _arm_dismiss(self, state: str):
        dwell = DWELL.get(state)
        if dwell:
            self.dismiss_timer = (
                NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    dwell, self, "dismiss:", None, False))

    @python_method
    def set_state(self, state: str, text: str | None = None):
        if not self.visible:
            self.show(state, text)
            return
        self.view.state = state
        self.view.text = text or TEXT.get(state, "")
        self._cancel_dismiss()
        self._resize_to_text()
        self._reposition()
        self._arm_dismiss(state)
        self.view.setNeedsDisplay_(True)

    @python_method
    def push_level(self, level: float):
        if self.view is not None:
            self.view.meter.push(max(0.0, min(1.0, level)))

    @python_method
    def _cancel_dismiss(self):
        if self.dismiss_timer is not None:
            self.dismiss_timer.invalidate()
            self.dismiss_timer = None

    @python_method
    def hide(self):
        from Foundation import NSAnimationContext

        self._cancel_dismiss()
        self.visible = False
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None
        if self.panel is None:
            return
        #  Exit is opacity only — a spring on the way out reads as a bounce
        #  nobody asked for.
        NSAnimationContext.beginGrouping()
        NSAnimationContext.currentContext().setDuration_(0.18)
        self.panel.animator().setAlphaValue_(0.0)
        NSAnimationContext.endGrouping()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.2, self, "finishHide:", None, False)

    def finishHide_(self, timer):
        if not self.visible and self.panel is not None:
            self.panel.orderOut_(None)

    def dismiss_(self, timer):
        self.dismiss_timer = None
        self.hide()

    def tick_(self, timer):
        if not self.visible or self.view is None:
            return
        if self.view.state == TRANSCRIBING:
            self.view.phase = int(
                NSTimer.timeIntervalSinceReferenceDate() / 0.18)
        elif self.view.state != LISTENING:
            self.view.meter.decay()
        self.view.setNeedsDisplay_(True)
