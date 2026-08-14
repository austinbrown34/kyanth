# shout — Level · surface specs

Seven surfaces. Each section names the prototype file that demonstrates it,
what it must contain, how it behaves, and what changed from v1.2.0.

---

## 1. App icon — `prototype/level-01-identity.html`

Geometry in `DESIGN.md §3.1`, master in `assets/app-icon.svg`.

Ships at 1024 / 512 / 256 / 128 / 64 / 32 / 16 pt. **The 16 pt rendering is
the same drawing**, not a simplified variant — verify this rather than
assuming it, because it is the whole argument for leaving the microphone
behind.

Appears in: Finder / Applications, Launchpad, System Settings → Privacy &
Security (Microphone, Accessibility, Input Monitoring), System Settings →
General → Login Items, and the DMG installer window.

**Changed:** the vintage broadcast microphone loses its grille slots and
chevron below 64 pt. This does not. It also stops reading as a generic audio
tool.

---

## 2. Menu-bar icon — `prototype/level-01-identity.html`

20 × 20 pt, template images, six states → six shapes. Source in
`assets/menubar-glyphs.svg`.

| State | Glyph | Second channel |
|---|---|---|
| `idle` | meter at rest | — |
| `recording` | bars at speaking height + red dot *(non-template)* | overlay + rising tone |
| `transcribing` | three equal stubs, cycling | overlay turns to the dots |
| `disabled` | meter dimmed, struck through | dropdown checkbox is off |
| `needs-permission` | hollow meter | Setup window opens |
| `error` | struck out | two low tones + overlay text |

**Changed:** v1.2.0 collapses six states into three glyphs — `idle` and
`transcribing` are indistinguishable, and `disabled` / `error` /
`needs-permission` share one mark. All six are now separable at a glance, by
shape, with no colour dependency.

---

## 3. Menu-bar dropdown — `prototype/level-02-menubar.html`

**286 pt wide.** Structure, top to bottom:

```
status header (not a menu item — no selection highlight)
  ● dot · state text · live input meter, right-aligned
  "Hold [Right ⌥][Right ⌘] and speak"   ← key caps, not prose
─────
✓ Enabled
  Recent transcriptions ▸        flyout, 320pt, 8 entries
─────
  Settings & History…      ⌘,
  Re-run Setup Check…
─────
  Advanced ▸                     Edit Config, Reload Config,
                                 Restart Model Server, Open Log,
                                 Check for Updates
─────
  Quit shout               ⌘Q
```

Recent entries show **two wrapped lines and a timestamp**, not a truncated
single line; clicking one copies it.

**Changed:** sixteen flat rows → six, in three groups. The five diagnostics
went behind `Advanced ▸`. The status line became a header, so it no longer
truncates to the menu width and can carry the live meter. `Sound cues` and
`Open at Login` moved to Settings, where preferences belong.

---

## 4. Setup window — `prototype/level-03-setup.html`

**620 pt wide**, single pane, first-run and on-demand.

```
band
  title bar        34pt, traffic lights only — no window title
  lockup           top-left
  headline row     h1 + subtitle on the left · progress ring pinned right
grouped boxes
  Permissions      Microphone · Accessibility · Input Monitoring    3 checks
  Hardware & model Input device · Model server · Open at Login      3 checks
  Verification     Shortcut reaches shout · Say something           2 checks
footer             version · "Do this later" · Finish (primary)
```

Brand top-left, progress top-right: the ring is a status readout, not part of
the identity. The window title is dropped because the lockup names the app one
line below it.

**Behaviour**

- All eight checks re-evaluate **every second**, so a switch flipped in System
  Settings turns a row without a relaunch. The prototype stands this in with a
  1.2 s delay after "Open System Settings".
- The blocking step is the only tinted row, owns the primary button, and its
  box carries a peak-coloured edge.
- Optional steps (amber `!`) are surfaced and **never block**; they are
  excluded from the blocking count.
- **Finish stays disabled until step 8 produces real text.** Hold-to-talk in
  the verification row runs a real dictation.
- Satisfied steps are slate, not green — see `DESIGN.md §4.2`.

**Changed:** eight uniform rows became three grouped phases; progress became a
ring plus an `n/8` count; four competing footer buttons became one primary and
one quiet escape; 11 px body copy went to 12.5 px held at ~52 characters.

---

## 5. Settings — Shortcut — `prototype/level-04-settings-shortcut.html`

**800 pt wide.** Full-height source list + pane.

```
sidebar (band)
  lockup
  CAPTURE   Shortcut ·  Audio
  TEXT      History (badge: count) ·  Behaviour
  SYSTEM    Permissions
  Version 1.2.0                                   pinned bottom
pane
  head    "Shortcut" / "What shout listens for, and proof that it is hearing it."
  ACTIVATION  mode segmented (Hold to talk | Toggle) · note ·
              "Ignore presses under [180 ms]"
  KEYS        chord + Change… · note on side-aware modifiers
  RECEPTION   Keys arriving (live pill) ·
              Audio arriving (live meter + device) ·
              Never arrived (count)
  foot    "Changes apply immediately" · Re-run Setup… · Quit shout
```

**Behaviour**

- The chord recorder **builds as keys go down and commits on release**, so
  `⌃ + Right ⌥` is recordable, not just single keys. Modifiers are
  side-aware — `Right ⌥` is not `Left ⌥`; use key *code*, not key symbol.
- The **Keys arriving** pill lights the moment shout receives exactly the
  bound chord. This is the answer to "no live preview that the chosen shortcut
  is being received" and it is the only way to tell a wrong chord apart from a
  chord another app swallowed.
- The **Audio arriving** meter runs whenever the window is open.
- **Never arrived** counts presses that were made but never reached shout.
  That is a different fault from a wrong chord and is invisible in v1.2.0.
- `Ignore presses under` is exposed because the outcome model already has an
  `ignored` result for a press too short to contain speech; the user should be
  able to move that line.

**Changed:** the tab strip is gone. Save/Cancel is gone — mode changes already
applied live, so the buttons were lying about a modal commit; the footer now
says what is true. Reception groups the two "why is nothing happening"
indicators together instead of scattering them.

---

## 6. Settings — History — `prototype/level-05-settings-history.html`

**940 pt wide.** Same shell, `History` selected.

```
pane head   "History" / "Everything you have dictated, newest first.
            Kept on this Mac, capped at 500."   · search field pinned right
filter bar  All · Pasted · Clipboard · Nothing heard    · "n of m · k words"
table       Time | Transcription | Spoken | Landed in | Delay | row actions
            day-heading rows · sticky header · expand-in-place on select
foot        "history.jsonl · on this Mac" · Reveal in Finder · Clear all…
```

**Behaviour**

- Click a row to open a detail row beneath it: the full transcription with the
  peak rule down its left edge, a facts row (landed in / spoken / words /
  key-up-to-text) and Copy · Paste again. Click again to collapse.
- Search filters live and the day counts recount as rows drop out.
- Filters map to the app's existing outcome model — `pasted`, `clipboard`,
  `ignored`. `Clipboard` is the list a user opens when text went missing.
- Per-row Copy and Delete. Delete is the one destructive affordance and it is
  per-row; `Clear all…` confirms.
- Empty state distinguishes "no matches for that search" from "nothing here
  yet", and the second one tells the user the shortcut.

**Changed:** v1.2.0 is a plain `NSTableView` truncating at ~96 characters with
no search, no grouping and no delete, where timestamp, marker and text share
one undifferentiated string. Those are now separate columns, nothing
truncates, and History is the surface that changed most.

---

## 7. Listening overlay — `prototype/level-06-overlay.html`

A floating panel near the top of the active display, above all windows, across
Spaces. **It never takes focus.** ≈ 135 × 36, docked under the notch
(top-centre otherwise) — predictable, so the eye learns one place.

The pill is the band plate carrying the live mark plus one line of text. The
mark **is** the meter:

```
bars grow from the centre axis, not from a baseline
centre bar  live input level, peak gradient, the only bar with a glow
left bar    the same envelope replayed  ~70 ms late   (4 frames @ 60 fps)
right bar   the same envelope replayed ~130 ms late   (8 frames @ 60 fps)
at rest     the icon's own 34 : 62 : 46 proportions
```

The lag is the point: a syllable enters at the centre and travels outward, so
the mark ripples in time with the voice rather than three bars twitching
independently. Nothing about it is random.

| State | Mark | Text |
|---|---|---|
| recording | live, halo scales with level | `Listening` |
| transcribing | three stubs, highlight cycling | `Transcribing…` |
| pasted | settles to rest, peak pulses once | `Pasted into <App>` |
| clipboard only | rest | `Copied — press ⌘V` |
| ignored | flat stubs, dimmed | `Nothing heard` |
| error | flat stubs, centre bar red | `Model server not responding` |

Transcribing is the menu-bar `transcribing` glyph enlarged, so the two
surfaces teach each other.

**Changed:** 108 × 108 with three expanding rings and no text becomes a fifth
of the area that can say *why* something failed. The flat dark scrim becomes
real material. It springs in and fades out instead of appearing and vanishing.
The status dot and the generic bar meter of the first pass were two symbols
doing one job; there is now one symbol — the app's own mark.

---

## 8. State model

Six states drive every surface at once. A redesign has to keep them coherent
across all four channels.

| State | Menu bar | Overlay | Sound | Status line |
|---|---|---|---|---|
| `idle` | meter at rest | hidden | — | `Ready — press …` |
| `recording` | bars + red dot | live mark, `Listening` | rising | `Recording…` |
| `transcribing` | three cycling stubs | stubs, `Transcribing…` | — | `Transcribing…` |
| `disabled` | struck through | hidden | — | `Disabled` |
| `needs-permission` | hollow meter | hidden | — | `Grant permissions…` |
| `error` | struck out | red centre bar + reason | two low tones | `Transcription failed` |

### Outcome feedback

| Outcome | Sound | Overlay | Meaning |
|---|---|---|---|
| pasted | falling tone | `Pasted into <App>` | text landed in the focused field |
| clipboard only | two rising tones | `Copied — press ⌘V` | nothing could receive it |
| ignored | low blip | `Nothing heard` | press too short, or no speech |

**`idle` and `transcribing` must never look the same** on any channel. That
was the single most-cited gap in v1.2.0.
