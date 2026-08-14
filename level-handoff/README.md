# shout — Level

Complete redesign handoff for the macOS push-to-talk dictation app.
Seven surfaces, two appearances, one concept: **shout is a meter.**

Open `prototype/index.html` first.

---

## What's here

```
README.md            this file
DESIGN.md            the system — brand, colour, type, components, motion
SURFACES.md          spec per surface + the six-state model
IMPLEMENTATION.md    AppKit / PyObjC mapping, real code, ship checklist

tokens/
  tokens.css         the token set as CSS custom properties
  tokens.json        the same values, machine-readable

assets/
  app-icon.svg       master icon, 1024, procedurally redrawable
  logo-mark.svg      the mark alone, for window headers
  menubar-glyphs.svg six 20 pt template glyphs, one per state

prototype/
  index.html         launcher — start here
  level-01-identity.html            app icon + menu-bar glyphs
  level-02-menubar.html             menu-bar dropdown
  level-03-setup.html               setup window
  level-04-settings-shortcut.html   Settings — Shortcut
  level-05-settings-history.html    Settings — History
  level-06-overlay.html             listening overlay
  css/base.css       layout chassis, geometry only
  css/level.css      Level's tokens + components (same values as tokens/)
  js/shout.js        shared behaviour + the transcript corpus
```

No build step, no dependencies, no network. Open the HTML files directly.

---

## Reading order

1. **`prototype/index.html`** — click through all six pages in both
   appearances. Everything is interactive: hold `⌥` to dictate, press
   `Right ⌥ + Right ⌘` on Settings — Shortcut, search and filter History.
2. **`DESIGN.md`** — the argument and the rules. §2 (what must not change),
   §3 (brand) and §4.1 (accent budget) are the ones that get broken first.
3. **`SURFACES.md`** — what each screen must contain and how it behaves,
   with a "changed from v1.2.0" note per surface.
4. **`IMPLEMENTATION.md`** — how to build it in PyObjC/AppKit without
   re-deriving the hard parts (the non-activating overlay panel, the mark's
   lag buffer, side-aware modifier capture, procedural icon drawing).

---

## The five things that matter most

If everything else drifts, hold these.

1. **The overlay must never become key window.** This is functional, not
   cosmetic — focus theft redirects the user's dictation into the overlay.
   `IMPLEMENTATION.md §7`.
2. **Assume the menu-bar icon is invisible.** macOS hides status items
   silently on a full menu bar. Every state resolves on the overlay too.
3. **One lockup: one size, one construction, one position.** Top-left, full
   strength, painted with the icon's own gradient stops. No ghosted or
   shrunken variants. `DESIGN.md §3.2`.
4. **At most two visible uses of the peak colour per screen.**
   `DESIGN.md §4.1`.
5. **Setup completes on a real dictation, not on green checkboxes.** And
   satisfied steps are slate, not green — `DESIGN.md §4.2`.

---

## What this replaces

The v1.2.0 reference names six weaknesses. Each surface answers one:

| v1.2.0 | Level |
|---|---|
| Six states, three glyphs — `idle` and `transcribing` identical | Six states, six shapes; transcribing is three cycling stubs |
| Icon detail dies below 64 pt, metaphor is generic | Three bars; the 16 pt render is the same drawing |
| Sixteen flat dropdown rows, six of them diagnostics | Six rows in three groups, diagnostics behind `Advanced ▸` |
| Eight-row setup wall, implicit progress, four footer buttons | Three grouped phases, ring + `n/8`, one primary action |
| History is an inert table view truncating at ~96 characters | Sortable columns, expand-in-place, search, filters, delete |
| 108 px wordless ripple with no transition | ≈135 × 36 pill that carries text, springs in, and *is* the mark |

---

## Known stand-ins

Honest list of what is simulated in the prototype and must be wired for real:

- **Input level** — `SHOUT.meter` and the overlay's `MarkMeter` run a
  synthetic speech envelope. Replace with an `AVAudioEngine` tap
  (`IMPLEMENTATION.md §8`); the smoothing constants and the 4 / 8-frame lag
  are the design and should carry over unchanged.
- **Transcription latency** — fixed ~850 ms delays stand in for the local
  model. Real figures are 150–300 ms from key release.
- **Permission grants** — the Setup window's "Open System Settings" flips the
  row after 1.2 s to stand in for the real 1 s re-poll.
- **The transcript corpus** in `js/shout.js` is written sample content, not
  captured user data.

Everything else — the state machine, the chord recorder's side-aware capture
and commit-on-release, search, filtering, expand-in-place, copy — is the
app's actual behaviour.
