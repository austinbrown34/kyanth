# shout — Level

Design system for the macOS redesign. Read this before `SURFACES.md`.

---

## 1. The bet

**shout is a meter.** The mark is amplitude, not a microphone.

Every other dictation tool draws a microphone. The current shout icon draws a
vintage broadcast microphone in enough detail that it collapses into noise
below 64 pt. Three rounded bars have nothing to lose: the 16 pt Finder
rendering is the same drawing as the 1024 pt one, and it stops looking like
every other audio utility. It is also honest — the thing on screen is not a
microphone, it is what the microphone is *doing*.

The posture is **invisible utility**. This should read as software Apple could
have shipped: system fonts, hairlines, vibrancy, tabular numerals, no invented
palette. The app raises its voice in exactly one place — the level itself.

---

## 2. What must not change

These come from the v1.2.0 reference and are functional, not cosmetic.

| Rule | Why |
|---|---|
| The overlay must never become key window | Focus theft redirects the user's dictation into the overlay instead of the app they were typing into |
| Assume the menu-bar icon can be invisible | macOS silently hides status items on a full menu bar. Every critical signal needs a second channel — that is what the overlay and the sound cues are for |
| Menu-bar glyphs must work as template images | Single colour, legible at 20 pt, inverted by macOS for light/dark and for an open menu |
| Setup completes on a real dictation, not on green checkboxes | Step 8 is the only step that proves the product works |
| Nothing may imply audio leaves the machine | Local processing is the product's core claim |
| The app stays menu-bar only (`LSUIElement`) | No Dock icon, no main window |

---

## 3. Brand

### 3.1 The icon

`assets/app-icon.svg` is the master. Geometry on a 1024 canvas:

```
tile     0,0  1024×1024  r = 228.8      (22.37%, the macOS squircle radius)
bar L  224,376  128×272  r = 64
bar C  448,264  128×496  r = 64          ← the peak; the only colour in the mark
bar R  672,328  128×368  r = 64
```

All three bars are centred on `y = 512`. Bar height ratio **34 : 62 : 46**.
Width-to-gap ratio **4 : 3** (128 : 96). Two gradients and a sheen:

- ground — `152°`… actually a diagonal `x1 0,y1 0 → x2 0.35,y2 1`:
  `#4c5468 0% · #252b39 55% · #14171f 100%`
- sheen — vertical `rgba(255,255,255,.20) → transparent` at 42%
- bar fill — vertical `#ffffff → #cfd6e4`
- peak fill — vertical `#7db6ff → #0a6cf5`

Four shapes, three gradients. It stays procedurally drawable in CoreGraphics;
no external asset pipeline is required. See `IMPLEMENTATION.md §2`.

### 3.2 The logo lockup

`assets/logo-mark.svg` + the wordmark `shout`.

**There is one lockup. One size, one construction, one position.** No small
variant, no ghosted variant, no right-aligned watermark. If the mark appears,
it appears at full strength, top-left, in the slate band.

```
mark        24 pt tall · bar width 6 · gap 4.5 · corner radius 3
            bar heights 13.2 / 24 / 17.8  (the icon's 34 : 62 : 46)
gap to word 11 pt
wordmark    "shout", lowercase, SF Pro Display 15.5 pt / 600 / -0.022em
            colour --band-fg
peak glow   0 0 12px rgba(125,182,255,.5)
```

The bars are painted with the **icon's own gradient stops**, not
approximations of them. A flat `#dfe4ee` bar and a flat `#0a6cf5` bar read as
a different, duller object than the tile in the Dock — that is the single
easiest way to make this feel off-brand.

The lockup is **identical in light and dark**. The Dock tile does not change
appearance, so neither does the logo.

### 3.3 The band

The icon's ground, reused as window material. Anything wearing the band gets
the slate gradient plus the icon's top sheen, running unbroken across all of
its children — never restart the gradient per element, or you get a visible
seam where two "band" boxes meet.

```
light  linear-gradient(152deg, #414a5e 0%, #262c3a 54%, #171b24 100%)
dark   linear-gradient(152deg, #333c4e 0%, #1e2430 54%, #12151c 100%)
sheen  linear-gradient(180deg, rgba(255,255,255,.13), transparent 46%)
```

The band lifts slightly in dark mode so it still separates from the window
body behind it. Where the band appears:

- **Settings** — the full-height sidebar (the whole left column)
- **Setup** — the header, from the title bar down through the headline row
- **Overlay** — the pill's plate

Because the sidebar is the band, the slate reads as a large calm field rather
than a stripe, and the traffic lights sit on it the way they do in any Mac app
with a full-height sidebar.

### 3.4 Menu-bar glyphs

`assets/menubar-glyphs.svg`. Six states, six **shapes** — not six colours,
because the icon is white over an arbitrary wallpaper. 20 × 20 pt, one colour
on transparent, `isTemplate = true`. The red dot in `recording` is the only
template opt-out, preserving the deliberate inconsistency the app already
ships.

---

## 4. Colour

Full values in `tokens/tokens.css` and `tokens/tokens.json`.

### 4.1 Accent budget

**At most two visible uses of the peak colour per screen.** This is the rule
most likely to be broken during implementation. Typical pairs:

| Screen | Use 1 | Use 2 |
|---|---|---|
| Settings — Shortcut | selected sidebar row | receipt pill while the chord is held |
| Settings — History | selected sidebar row | selected row's rule + duration bar |
| Setup | progress ring | the one live/blocking step |

The input meter's hot bars are also the peak, doing exactly the job they do in
the icon — showing there is signal. Everything else is neutral.

### 4.2 Green is reserved, not used

`--ok` exists in the token set but **satisfied setup steps do not use it.**
They use `--mark-done` (slate). Seven green ticks shout, and the Setup
window's own argument is that green permissions are not proof. The only
saturated mark in that list is the step still asking for you.

Green stays available for genuinely positive one-off moments.

### 4.3 Appearance

Everything flips with the system setting except the brand layer. Never pure
black or pure white: `#f0f0f2` on `#232326` in dark, `#1b1b1f` on `#ffffff` in
light. On dark surfaces prefer semi-transparent white borders
(`rgba(255,255,255,.12)`) over solid dark ones.

---

## 5. Typography

System faces only — SF Pro Text for UI, SF Pro Display for titles ≥ 15 pt,
SF Mono for shortcuts, file paths and identifiers. Three weights: 400 read,
550 emphasise, 590–600 announce. Nothing above 600.

| Role | Size | Weight | Tracking |
|---|---:|---:|---:|
| Wordmark | 15.5 | 600 | −0.022em |
| Pane title | 17 | 590 | −0.015em |
| Setup headline | 19 | 590 | −0.015em |
| Window title | 13 | 590 | −0.005em |
| Body / row value | 12.5 | 400 | 0 |
| Row label (emphasis) | 12.5 | 550 | 0 |
| Note / hint | 11.5 | 400 | +0.01em |
| Group label, table head | 9.5 | 600 | **+0.11em**, uppercase |
| Version, timestamps | 10.5–11 | 400 | +0.02em, tabular |

**All caps always carries ≥ 0.06em tracking.** Uppercase at default tracking
is the most reliable tell that a screen was not drawn by a designer. All
numerics that sit in a column — times, milliseconds, word counts, durations,
`n/8` counts — use tabular figures.

Body copy is held to ~52 characters. Note text never drops below 11.5 pt; the
current app's 11 px body copy is one of the named weaknesses.

---

## 6. Layout and components

### 6.1 Window shell

Settings runs a **full-height source list beside a content pane**.

```
side-split   grid 198px | 1fr, min-height 452
sidebar      the band, full height, padding 0 10 12
             traffic lights at 13,4 · lockup at 17,9,6 · version pinned bottom
pane         --surface
  pane-head  17 22 14, hairline bottom — title + one line of purpose,
             optional control (search) pinned right
  pane-body  18 22 22, 20px gap between groups
  pane-foot  11 18, hairline top, --footer, pinned to the bottom
```

A source list scales; three tabs do not. Once diagnostics come out of the
menu bar there are more than three areas worth exposing, and the sidebar gives
each one a name and a badge instead of burying it.

Setup is a first-run window and keeps a single pane, but wears the same band,
the same grouped boxes and the same footer.

### 6.2 Grouped box

The macOS System Settings shape, and the workhorse of this design.

```
label   9.5/600/+0.11em uppercase, --muted, 13px left inset, 7px below
box     1px --border, radius 9, fill --footer
row     grid 132px | 1fr, gap 14, padding 11 14
        label right column --muted 12.5; value column flex, gap 10
note    padding 0 14 11, --muted 11.5, max 62ch — INSIDE the box it explains
```

Rows are separated by hairlines, not by gaps. Explanatory copy lives inside
the box it belongs to, never floating beside a field.

### 6.3 Table (History)

Sticky header, day-heading rows, hairline row separators, no zebra striping.
Selecting a row **expands it in place** — a detail row opens underneath with
the full transcription, its facts and its actions. There is no detail pane;
an empty pane on the right was the weakest part of the earlier attempt.

The **Spoken** column is the meter idea applied to the archive: a bar as wide
as the time spent talking, so an eleven-second paragraph is findable without
reading a word. It is neutral (`--fg` at 34%) until the row is selected, then
it lights with the peak gradient.

### 6.4 Level meter

A row of 3 px bars, 2 px apart, growing from a common baseline; `--meter-idle`
at rest, peak when hot. Used beside the microphone picker, in the menu-bar
dropdown header, and in Setup's verification step. A microphone that is
selected but hearing nothing must look different from one that works — that
is the meter's whole job.

### 6.5 Overlay pill

Band plate, 999 px radius, `≈135 × 36`, docked under the notch (top-centre on
displays without one). It holds the live mark and one line of text. Full spec
in `SURFACES.md §7`.

---

## 7. Motion

Restrained and purposeful. The current app has no motion anywhere except the
overlay ripple, and state changes snap.

| Moment | Motion |
|---|---|
| Overlay in | opacity .17s ease + transform .28s `cubic-bezier(.2,1.35,.4,1)` from `scale(.9)` translateY −7 |
| Overlay out | opacity fade only |
| Mark bars | driven per-frame by input level, no CSS transition |
| Transcribing | three stubs, highlight cycling at ~180 ms |
| Progress ring | `stroke-dasharray` .5s ease |
| Meter bars | height .07s linear |
| Button press | 1px down |

Everything respects `prefers-reduced-motion` / `NSWorkspace
accessibilityDisplayShouldReduceMotion`: the mark holds at rest proportions
and the state is carried by text alone.

---

## 8. Do / don't

**Do**

- Reuse the lockup verbatim; render the mark at 24 pt and nowhere else at another size.
- Paint logo bars with the icon's gradient stops.
- Keep the band's gradient on one wrapper so it never restarts mid-header.
- Use tabular figures in every column of numbers.
- Give all-caps labels ≥ 0.06em tracking.
- Put explanatory copy inside the box it explains.

**Don't**

- Ghost, shrink, right-align or recolour the mark.
- Spend the peak colour more than twice on one screen.
- Use green for satisfied setup steps.
- Let the overlay take focus, or drop text from it.
- Rely on the menu-bar icon being visible.
- Re-introduce tabs, a detail pane, or 11 pt body copy.
