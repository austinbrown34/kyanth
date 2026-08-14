# shout — Level · implementation notes

Mapping the prototype onto the real stack. **Python + PyObjC / AppKit, no
Interface Builder, no SwiftUI**; custom drawing in `NSView.drawRect_` with
`NSBezierPath`; icons generated procedurally with CoreGraphics. Vibrancy,
materials and blur are available through `NSVisualEffectView` and are not used
today — this design uses them.

PyObjC selector convention throughout: `setTemplate:` → `setTemplate_(True)`.

---

## 1. Dynamic colours

Define the token set once as appearance-aware `NSColor`s. Everything except
the brand layer flips.

```python
from AppKit import NSColor, NSAppearance, NSAppearanceNameDarkAqua

def _rgb(hex_str, a=1.0):
    h = hex_str.lstrip('#')
    r, g, b = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a)

def dynamic(name, light, dark):
    def provider(appearance):
        match = appearance.bestMatchFromAppearancesWithNames_(
            ["NSAppearanceNameAqua", NSAppearanceNameDarkAqua])
        return dark if match == NSAppearanceNameDarkAqua else light
    return NSColor.colorWithName_dynamicProvider_(name, provider)

FG      = dynamic("shout.fg",      _rgb("#1b1b1f"), _rgb("#f0f0f2"))
MUTED   = dynamic("shout.muted",   _rgb("#77777f"), _rgb("#96969e"))
SURFACE = dynamic("shout.surface", _rgb("#ffffff"), _rgb("#232326"))
FOOTER  = dynamic("shout.footer",  _rgb("#f7f7f9"), _rgb("#1e1e21"))
BORDER  = dynamic("shout.border",  _rgb("#000000", .11), _rgb("#ffffff", .12))
PEAK    = dynamic("shout.peak",    _rgb("#0a6cf5"), _rgb("#3d8bff"))
MARKDONE= dynamic("shout.markDone",_rgb("#2c3444"), _rgb("#46516a"))
```

Do **not** wire the peak to `NSColor.controlAccentColor` — a user who has set
their system accent to pink will break the relationship between the peak bar
in the icon and the peak colour in the UI, which is the whole cohesion
argument. It is a brand colour that happens to sit near system blue.

The band and the logo gradients are **not** dynamic. Same values in both
appearances (the band's two variants in `tokens.css` are a deliberate lift
for legibility, not an appearance flip of hue).

---

## 2. The app icon in CoreGraphics

Keep `make_icons.py`. The drawing is four rounded rects and three gradients.

```python
import Quartz as Q

GROUND = [(0.298,0.329,0.408,1.0),   # #4c5468
          (0.145,0.169,0.224,1.0),   # #252b39
          (0.078,0.090,0.122,1.0)]   # #14171f
GROUND_LOC = [0.0, 0.55, 1.0]
BAR  = [(1,1,1,1), (0.812,0.839,0.894,1)]        # #ffffff → #cfd6e4
PEAK = [(0.490,0.714,1.0,1), (0.039,0.424,0.961,1)]  # #7db6ff → #0a6cf5

# 1024-canvas geometry; scale by size/1024 for every other rendering
TILE_R = 228.8
BARS = [(224, 376, 128, 272),   # left
        (448, 264, 128, 496),   # centre — the peak
        (672, 328, 128, 368)]   # right

def _grad(space, colors, locations=None):
    flat = [c for rgba in colors for c in rgba]
    return Q.CGGradientCreateWithColorComponents(
        space, flat, locations or [0.0, 1.0], len(colors))

def draw_icon(ctx, size):
    s = size / 1024.0
    space = Q.CGColorSpaceCreateWithName(Q.kCGColorSpaceSRGB)

    # ground, clipped to the squircle
    tile = Q.CGPathCreateWithRoundedRect(
        Q.CGRectMake(0, 0, size, size), TILE_R * s, TILE_R * s, None)
    Q.CGContextSaveGState(ctx)
    Q.CGContextAddPath(ctx, tile)
    Q.CGContextClip(ctx)
    Q.CGContextDrawLinearGradient(
        ctx, _grad(space, GROUND, GROUND_LOC),
        Q.CGPointMake(0, size), Q.CGPointMake(size * 0.35, 0), 0)

    # top sheen: white .20 → clear at 42%
    sheen = _grad(space, [(1,1,1,0.20), (1,1,1,0.0)])
    Q.CGContextDrawLinearGradient(
        ctx, sheen, Q.CGPointMake(0, size), Q.CGPointMake(0, size * 0.58), 0)
    Q.CGContextRestoreGState(ctx)

    # bars — note CoreGraphics origin is bottom-left, the spec is top-left
    for i, (x, y_top, w, h) in enumerate(BARS):
        rect = Q.CGRectMake(x * s, (1024 - y_top - h) * s, w * s, h * s)
        path = Q.CGPathCreateWithRoundedRect(rect, (w / 2) * s, (w / 2) * s, None)
        Q.CGContextSaveGState(ctx)
        Q.CGContextAddPath(ctx, path)
        Q.CGContextClip(ctx)
        Q.CGContextDrawLinearGradient(
            ctx, _grad(space, PEAK if i == 1 else BAR),
            Q.CGPointMake(0, Q.CGRectGetMaxY(rect)),
            Q.CGPointMake(0, Q.CGRectGetMinY(rect)), 0)
        Q.CGContextRestoreGState(ctx)
```

Render at 1024 / 512 / 256 / 128 / 64 / 32 / 16 and `iconutil` into `.icns`.
**Check the 16 pt output by eye** — the claim that it is the same drawing at
every size is the reason the microphone was dropped.

---

## 3. Menu-bar glyphs

`rumps` hard-codes the status image size at 20 × 20 pt. Draw each glyph in a
drawing handler and mark it as a template, except `recording`.

```python
from AppKit import (NSImage, NSMakeSize, NSBezierPath, NSColor,
                    NSMakeRect, NSStatusBar, NSVariableStatusItemLength)

def _bar(x, h):
    """20x20 space, bars centred on y = 10."""
    return NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(x, 10 - h / 2.0, 2.6, h), 1.3, 1.3)

def glyph(state):
    def draw(rect):
        NSColor.blackColor().set()          # template: colour is ignored
        if state == "idle":
            for x, h in ((4, 5), (8.7, 10), (13.4, 7)): _bar(x, h).fill()
        elif state == "recording":
            for x, h in ((4, 9), (8.7, 14), (13.4, 11)): _bar(x, h).fill()
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.898,0.216,0.173,1).set()
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(14.6, 14.2, 5.2, 5.2)).fill()
        elif state == "transcribing":
            for x in (4, 8.7, 13.4): _bar(x, 2.8).fill()
        # disabled / needs-permission / error: see assets/menubar-glyphs.svg
        return True
    img = NSImage.imageWithSize_flipped_drawingHandler_(
        NSMakeSize(20, 20), False, draw)
    img.setTemplate_(state != "recording")   # the one opt-out
    return img
```

`transcribing` animates: swap the image on a ~180 ms timer, moving the taller
stub left → centre → right. Stop the timer the moment the state leaves
`transcribing`; a status item that keeps ticking is a battery complaint.

Never let the glyph be the only channel — see `SURFACES.md §8`.

---

## 4. Window shell — full-height sidebar

The sidebar runs under the traffic lights.

```python
window.setTitlebarAppearsTransparent_(True)
window.setTitleVisibility_(NSWindowTitleHidden)
window.setStyleMask_(window.styleMask() | NSWindowStyleMaskFullSizeContentView)
window.setToolbar_(None)
```

Use `NSSplitViewController`. Note that `NSSplitViewItem
sidebarWithViewController:` gives you the *system* vibrant sidebar material —
which is not what this design wants, because the sidebar is the band. Use a
plain `splitViewItemWithViewController:`, fix the width at 198 pt, and draw
the band yourself. You then own the top inset: 13 pt above the traffic lights,
lockup at 17 / 9 / 6.

Because the app is `LSUIElement`, opening Settings from the status menu will
not bring it forward on its own:

```python
NSApp.activateIgnoringOtherApps_(True)
window.makeKeyAndOrderFront_(None)
```

### Drawing the band

One layer for the whole header so the gradient never restarts:

```python
from Quartz import CAGradientLayer

def band_layer(dark=False):
    g = CAGradientLayer.layer()
    g.setColors_([_cg("#333c4e" if dark else "#414a5e"),
                  _cg("#1e2430" if dark else "#262c3a"),
                  _cg("#12151c" if dark else "#171b24")])
    g.setLocations_([0.0, 0.54, 1.0])
    g.setStartPoint_((0.0, 1.0))      # 152° ≈ top-left → bottom-right
    g.setEndPoint_((0.47, 0.0))
    return g

def sheen_layer():
    g = CAGradientLayer.layer()
    g.setColors_([_cg("#ffffff", 0.13), _cg("#ffffff", 0.0)])
    g.setLocations_([0.0, 0.46])
    g.setStartPoint_((0.5, 1.0)); g.setEndPoint_((0.5, 0.0))
    return g
```

Add the sheen as a sublayer of the band, both resized in
`viewDidChangeEffectiveAppearance` / `layout`.

### The lockup

Bars as three rounded rects in `drawRect_`, gradient-filled; wordmark as an
`NSTextField` (label style), SF Pro Display 15.5 / semibold, tracking
`-0.022em` via `NSAttributedString` `NSKernAttributeName`
(≈ `-0.34 pt` at 15.5 pt). The peak bar's glow is a layer shadow:

```python
bar.layer().setShadowColor_(_cg("#7db6ff"))
bar.layer().setShadowOpacity_(0.5)
bar.layer().setShadowRadius_(6.0)     # CSS blur 12px ≈ radius 6
bar.layer().setShadowOffset_((0, 0))
```

---

## 5. Grouped boxes

A plain layer-backed `NSView`: 1 pt `BORDER` stroke, 9 pt corner radius,
`FOOTER` fill, `masksToBounds = True`. Rows are subviews separated by 1 pt
hairline views — not `NSBox`, which brings its own inset and title styling you
would then have to fight.

Row metrics: label column 132 pt right-aligned to the gutter, 14 pt gap,
11 / 14 padding. Note text is a wrapping label inside the box, 11.5 pt,
`MUTED`, max ~62 characters.

---

## 6. History table

View-based `NSTableView`, `NSTableViewStyleFullWidth`, no alternating row
colours, 1 pt hairline row separators.

- **Day headings** — group rows via
  `tableView:isGroupRow:` returning `True`, or a synthetic row model. Keep the
  header row sticky with a floating group-row style.
- **Spoken column** — a custom `NSTableCellView` drawing a 46 × 4 track and a
  fill whose width is `min(1, sec / 12)`. Neutral `FG @ 34%`; swap to the peak
  gradient when the row is selected.
- **Expand in place** — insert a detail row beneath the selected row
  (`insertRowsAtIndexes:withAnimation:`) rather than pushing a detail pane.
  Remove it on deselect. `NSTableViewAnimationSlideDown` is the right feel.
- **Numerics** — apply
  `NSFontDescriptorFeatureSettings` with the monospaced-numbers selector, or
  use `NSFont.monospacedDigitSystemFontOfSize_weight_`.
- Backing store stays JSONL, capped at 500, newest first.

---

## 7. The overlay panel

The single most delicate piece. It must float above everything, across
Spaces, and **never become key**.

```python
from AppKit import (NSPanel, NSWindowStyleMaskNonactivatingPanel,
                    NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
                    NSStatusWindowLevel, NSColor,
                    NSWindowCollectionBehaviorCanJoinAllSpaces,
                    NSWindowCollectionBehaviorFullScreenAuxiliary,
                    NSWindowCollectionBehaviorStationary,
                    NSWindowCollectionBehaviorIgnoresCycle)

panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
    rect,
    NSWindowStyleMaskNonactivatingPanel | NSWindowStyleMaskBorderless,
    NSBackingStoreBuffered, False)

panel.setLevel_(NSStatusWindowLevel)
panel.setCollectionBehavior_(
    NSWindowCollectionBehaviorCanJoinAllSpaces |
    NSWindowCollectionBehaviorFullScreenAuxiliary |
    NSWindowCollectionBehaviorStationary |
    NSWindowCollectionBehaviorIgnoresCycle)
panel.setFloatingPanel_(True)
panel.setBecomesKeyOnlyIfNeeded_(True)
panel.setHidesOnDeactivate_(False)
panel.setIgnoresMouseEvents_(True)      # it is a readout, not a control
panel.setOpaque_(False)
panel.setBackgroundColor_(NSColor.clearColor())
panel.setHasShadow_(True)
```

Belt and braces: subclass and return `False` from `canBecomeKeyWindow` and
`canBecomeMainWindow`. Show with `orderFrontRegardless()`, **never**
`makeKeyAndOrderFront_`.

Plate: `NSVisualEffectView`, material `NSVisualEffectMaterialHUDWindow`,
blending `BehindWindow`, state `Active`, `wantsLayer = True`, corner radius
18, `masksToBounds = True`. Tint the band gradient over it at low opacity so
it reads as the icon's ground rather than generic HUD grey.

Placement: centred horizontally on the display holding the pointer, top edge
33 pt below the menu bar; on a notched display that puts it directly under the
notch. Recompute on `NSApplicationDidChangeScreenParametersNotification`.

Entrance: `scale .9 → 1` with a spring over 0.28 s and opacity over 0.17 s.
Exit: opacity only. Use `CASpringAnimation` (`damping ≈ 14`, `stiffness ≈ 260`)
or `NSAnimationContext` with a custom timing function.

---

## 8. The mark meter

### Level from the microphone

```python
engine = AVAudioEngine.alloc().init()
node = engine.inputNode()
fmt = node.outputFormatForBus_(0)

def tap(buf, when):
    rms = compute_rms(buf)                     # see note below
    db = 20.0 * math.log10(max(rms, 1e-7))
    level = max(0.0, min(1.0, (db + 50.0) / 50.0))   # -50 dBFS .. 0 → 0..1
    meter.push(level)

node.installTapOnBus_bufferSize_format_block_(0, 1024, fmt, tap)
engine.startAndReturnError_(None)
```

PyObjC hands you `buf.floatChannelData()` as a pointer; wrap the first
channel's `buf.frameLength()` samples with `numpy.frombuffer` over the
buffer's memory, or compute the RMS in a tiny C helper. Do not iterate sample
by sample in Python inside the tap.

### The lag buffer

The whole character of the mark lives here. Centre reads now; the flanks
replay the same envelope 4 and 8 frames late at 60 fps.

```python
REST = (13.2, 24.0, 17.8)     # the icon's 34 : 62 : 46 at 24 pt
MAXH = 24.0
LAG_L, LAG_R = 4, 8

class MarkMeter:
    def __init__(self):
        self.hist = [0.0] * 16
        self.i = 0
        self.env = 0.0

    def push(self, level):
        self.env += (level - self.env) * 0.17      # smoothing
        self.i = (self.i + 1) % len(self.hist)
        self.hist[self.i] = self.env

    def _past(self, lag):
        return self.hist[(self.i - lag) % len(self.hist)]

    def heights(self):
        e = self.hist[self.i]
        return (REST[0] + (MAXH - REST[0]) * self._past(LAG_L),
                REST[1] + (MAXH - REST[1]) * e,
                REST[2] + (MAXH - REST[2]) * self._past(LAG_R))
```

Bars grow from the **centre axis**, so each rect is
`NSMakeRect(x, mid - h/2, 6, h)` with a 3 pt corner radius. Drive redraw from
a `CVDisplayLink` or a 60 Hz `NSTimer`; `setNeedsDisplay_(True)` in the audio
tap directly will hammer the main thread.

The halo behind the mark scales with `e`: radius `9 + e*14`, opacity
`0.08 + e*0.36`.

`transcribing` ignores the level entirely — three stubs at 4.4 pt with the
highlight cycling every ~180 ms.

Under `NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion()`
hold the bars at `REST` and let the text carry the state.

---

## 9. Shortcut capture

Modifiers are side-aware, so bind on **key code**, not on the modifier mask
alone. `kVK_RightOption = 0x3D`, `kVK_RightCommand = 0x36`,
`kVK_RightControl = 0x3E`, `kVK_RightShift = 0x3C`.

- Build the chord as keys go **down**; commit on the first key **up**. This is
  what makes `⌃ + Right ⌥` recordable rather than only single keys.
- The **Keys arriving** pill is a separate global monitor
  (`NSEvent.addGlobalMonitorForEventsMatchingMask_handler_` with
  `NSEventMaskFlagsChanged | NSEventMaskKeyDown`) that lights when the bound
  set is exactly held. Global monitors require Input Monitoring — which is
  precisely the permission Setup blocks on, so the pill doubles as a live
  proof that the grant took.
- **Never arrived** = chord observed by the global monitor but not delivered
  to the hotkey handler within one run loop turn.
- `Ignore presses under` gates on press duration before any audio is sent for
  transcription; under threshold → `ignored` outcome, low blip, nothing
  written to history.

---

## 10. Setup

- Re-evaluate all eight checks on a 1 s timer while the window is open, so a
  switch flipped in System Settings turns a row without a relaunch.
- Permissions cannot be granted programmatically. Open the panes directly:
  `x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent`
  (Input Monitoring), `…?Privacy_Accessibility`, `…?Privacy_Microphone`.
- Login item: `SMAppService.mainAppService().registerAndReturnError_(None)`.
- **`Finish` stays disabled until step 8 succeeds.** Wire it to the real
  dictation path, not to a mock.

---

## 11. Accessibility

- Every status change posts an `NSAccessibilityAnnouncementRequested`
  notification; the overlay is the visual half of that, not the whole of it.
- Menu-bar glyphs get `accessibilityLabel` per state — the shape distinction
  is invisible to VoiceOver.
- Hit targets in the dropdown and Settings ≥ 22 pt tall.
- Contrast: body text ≥ 4.5:1, UI components ≥ 3:1 against their adjacent
  surface, in **both** appearances. The band is dark in both, so check
  `--band-muted` against it specifically.
- Respect Reduce Motion and Reduce Transparency (fall back from
  `NSVisualEffectView` to a solid band fill).

---

## 12. Ship checklist

- [ ] 16 pt icon is legible and is the same drawing as 1024
- [ ] All six menu-bar glyphs distinguishable in a light **and** dark menu bar
- [ ] `idle` and `transcribing` never look alike on any channel
- [ ] Overlay never becomes key — dictate into TextEdit with the overlay up
- [ ] Overlay reachable with the status item hidden (fill the menu bar and test)
- [ ] Peak colour appears at most twice per screen
- [ ] No green on satisfied setup steps
- [ ] `Finish` cannot be reached without a real dictation
- [ ] All-caps labels carry ≥ 0.06em tracking
- [ ] Numeric columns are tabular
- [ ] Both appearances checked on every surface
- [ ] Nothing in the UI implies audio leaves the machine
