# Kyanth

Push-to-talk dictation for macOS that runs **entirely on your machine**. Hold a key, speak,
release — the text lands in whatever field you were typing in.

Built as a free replacement for [Voicy](https://usevoicy.com/) ($102/yr), which is a thin
client over a hosted Whisper API: every dictation leaves your machine, there is no offline
mode, and no custom vocabulary. Kyanth transcribes locally in ~150–300 ms, works on a plane,
and never sends your audio anywhere. See [PROPOSAL.md](PROPOSAL.md) for the full
competitive analysis and architecture.

**[kyanth.com](https://kyanth.com)** · [Download the latest release](https://github.com/austinbrown34/kyanth/releases/latest)

---

## Install

### From the release DMG (recommended)

1. Download from **[kyanth.com](https://kyanth.com)**, or grab the latest
   `kyanth-<version>.dmg` straight from [Releases](https://github.com/austinbrown34/kyanth/releases/latest)
2. Open it and drag **Kyanth** to Applications
3. Launch it from Applications

The build is signed and **notarized by Apple**, so it opens normally — no
right-click, no Gatekeeper warning.

That's the whole install. The app is self-contained — Python, the speech model,
and the transcription engine all ship inside it. **No Homebrew, no Python, no `uv`,
nothing to build.**

Requires **macOS 13+ on Apple Silicon**.

### Upgrading from shout

Kyanth is the same app under a new name. It is *not* an in-place update: the
rename changed the bundle identifier, so macOS treats it as a different
application entirely.

1. Install Kyanth as above, then delete `/Applications/shout.app`
2. Grant **Microphone**, **Accessibility** and **Input Monitoring** again —
   permissions are attached to the old identifier and cannot be transferred
3. Your history, shortcut, settings and vocabulary carry over automatically.
   On first launch Kyanth moves `~/Library/Application Support/shout` to
   `.../Kyanth`; the log records it as `[migrate] carried over`

If you had shout set to open at login, re-check that in **Settings →
Behaviour** — the login item is registered per bundle identifier too.

### First run — the setup window walks you through it

On first launch Kyanth opens a **Setup** window with seven checks. Each row shows a live
status, and the one that needs you has a button that opens the right settings pane:

```
1. Microphone            2. Accessibility        3. Input Monitoring
4. Microphone connected  5. Speech engine        6. Shortcut active
7. Try it
```

It re-checks every second, so as you flip a switch in System Settings the row turns green
by itself — no restart, no relaunch.

**Input Monitoring is marked optional.** On some Macs the shortcut works without it; on
others it is required. It shows an orange `!` when missing but never blocks completion,
because step 7 is the real test. If your shortcut already produces text, ignore it.

**Step 7 is the important one.** Setup is not marked complete when the permissions are
green; it is marked complete when a real dictation has round-tripped and produced text.
Green permissions prove configuration, not function.

macOS will not enable Accessibility or Input Monitoring on an app's behalf — you have to
switch **Kyanth** on in each list. The window says so, and tells you which one it is
waiting for.

Reopen it any time from the menu: **Setup Check…**

Both windows carry a **Quit Kyanth** button. That matters more than it sounds: when the
menu bar is full macOS hides the status icon, and the window is then the only way to quit
the app.

> Without Accessibility, `CGEventPost` silently does nothing — no error, no exception.
> The app would look like it was working while nothing reached your document. Kyanth
> checks explicitly and reports it in the menu rather than failing quietly.

---

## Building from source

Only needed if you're changing the code or producing your own release.

```bash
brew install uv whisper-cpp        # build-time only; not needed by the built app
git clone https://github.com/austinbrown34/kyanth.git
cd Kyanth
./build_release.sh                 # -> dist/kyanth-<version>.dmg
```

| Flag | Effect |
|---|---|
| *(none)* | signs with your Developer ID; first launch elsewhere needs right-click → Open |
| `--notarize` | also submits to Apple and staples, so it opens cleanly anywhere |
| `--adhoc` | ad-hoc signature, local testing only |

`build_release.sh` vendors `whisper-server` and its dylib closure, downloads the model,
freezes the app with PyInstaller, signs inside-out, and builds the DMG.

### Notarizing

Store credentials once, then build:

```bash
xcrun notarytool store-credentials kyanth-notary \
  --apple-id you@example.com --team-id YOURTEAMID \
  --password <app-specific-password>      # appleid.apple.com -> Sign-In and Security

./build_release.sh --notarize
./publish_release.sh                      # uploads to the GitHub release
```

`publish_release.sh` **refuses to upload a build that is not notarized.** It mounts the
DMG and checks for a stapled ticket on both the disk image and the app, plus a passing
`spctl` assessment, before touching the release. See
[Engineering notes](#engineering-notes) for why that guard exists.

An app-specific password is not your Apple ID password — generate one at
[appleid.apple.com](https://appleid.apple.com).

### Running from source, without packaging

```bash
uv sync
./run.sh          # terminal daemon, logs to stdout
```

Permissions attach to your *terminal* in this mode, not to Kyanth — see
[Engineering notes](#engineering-notes).

---

## Using it

**Hold Right-Option, speak, release.** The text is pasted into the focused field and your
previous clipboard is restored.

### Activation modes

Set in **Settings → Shortcut** — from the menu-bar icon, or by launching Kyanth again from
your Applications folder. There is no Save button: changes apply as you make them.

| Mode | Behavior |
|---|---|
| **Hold to talk** | hold the key while speaking, release to transcribe |
| **Toggle on / off** | press once to start, press again to stop |

### Choosing a shortcut

Click the shortcut button, then press any key or combination. The button previews the chord
as you build it and commits when you release everything — so `⌃ + Right ⌥` is recordable,
not just single keys. **Press order doesn't matter and there's no timing requirement.** Esc
cancels.

**Modifier-only keys make the best shortcuts.** Right-Option, Right-Command and fn can't be
typed on their own, so binding one steals nothing from other apps. A regular combination
like ⇧⌘V is intercepted system-wide and will shadow whatever else uses it.

### Listening indicator

A small pill appears near the top of the screen and says what is happening in words —
Listening, Transcribing…, Pasted, Copied — press ⌘V, Nothing heard, Something went wrong.
The three bars on its left are the input meter: the centre bar carries your live level and
the outer two replay it a few frames later, so a syllable travels outward and a microphone
picking up nothing looks obviously different from one that is working.

The pill follows the pointer's screen, not the focused one, so on a multi-monitor setup it
appears where you are looking.

It is a non-activating panel: it floats above other windows and across Spaces without ever
taking focus. That is not cosmetic — Kyanth pastes into whatever app is frontmost, so an
overlay that became key window would redirect your dictation into itself.

### Microphone use

Kyanth opens the input device on your first press and **releases it after 30 seconds idle**,
so macOS shows its microphone indicator only while you are actually dictating. Consecutive
dictations stay instant; the first press after a pause costs about 110 ms, which is
absorbed by the start cue and the moment before you begin speaking.

### Sound cues

The menu-bar icon is easily hidden (see [Troubleshooting](#troubleshooting)), so every state
change has a distinct tone. Pitch carries the meaning:

| Cue | Sound | Means |
|---|---|---|
| start | rising | recording |
| stop | falling | pasted into the focused field |
| clipboard | two rising | nothing to paste into — text is on the clipboard |
| ignored | low blip | that press didn't count (too short, or no speech) |
| error | two low blips | transcription failed |

Toggle in **Settings → Audio**, where you can also set the volume.

### Clipboard fallback

If no text field is focused, the transcription is **left on the clipboard** rather than
discarded — press ⌘V. This is the "I thought I was clicked into the document but I wasn't"
case, and it no longer loses your dictation.

### History

Every transcription is kept in **Settings → History**, as a table: time, what you said, how
long you spoke, where it landed and how long transcription took. Search filters as you
type. The filter chips — Pasted, Clipboard, Nothing heard — map to the app's outcomes, and
**Clipboard** is the list to open when text went missing.

Click a row to open it in place: the full transcription, its facts, and **Copy** ·
**Paste again** · **Delete**. Click again to collapse. Nothing is truncated. Stored locally
in `history.jsonl`, capped at 500 entries; **Clear all…** deletes the lot.

### Menu-bar icon

Six states, six shapes — the meaning survives without colour, which matters because the
glyph is drawn over whatever your wallpaper is.

| Icon | Meaning |
|---|---|
| three bars | ready |
| taller bars + red dot | recording |
| three dots, one walking | transcribing |
| bars with a slash | disabled |
| hollow bars | waiting for permissions |
| bars with a cross | something went wrong |

Opening the icon shows the same state in words, with a live meter and your shortcut as key
caps, so "is it hearing me" is answered before you click anything.

---

## Configuration

Two files, both under `~/Library/Application Support/Kyanth/`.

**`settings.json`** — written by the Settings window: shortcut, mode, sound.

**`config.yaml`** — hand-edited: model, VAD, vocabulary, per-app formatting. Open it from
the menu (**Edit Config…**), then **Reload Config**. The two are separate so the GUI never
rewrites and reformats your commented YAML.

### Custom vocabulary

Whisper has no vocabulary API, so Kyanth corrects terms after transcription. This fixes most
jargon errors — and it's something Voicy offers at no price point.

```yaml
vocabulary:
  replacements:
    "cubectl": "kubectl"       # seed from what the model ACTUALLY emits
    "get hub": "GitHub"
    "type script": "TypeScript"
```

Seed these from the daemon's log line, not from guesses. The first version of this config
guessed `"cube control"`; the model actually emits `Cubectl`, so the rule never fired.

### Per-app formatting

```yaml
profiles:
  Slack:   {capitalize_first: false, strip_trailing_period: true}
  Mail:    {capitalize_first: true,  strip_trailing_period: false}
  default: {capitalize_first: true,  strip_trailing_period: false}
```

### Switching models

```yaml
model: models/ggml-base.en.bin     # or ggml-small.en.bin, ggml-large-v3-turbo-q5_0.bin
```

Then **Restart Model Server** from the menu. Bigger is not automatically better —
see [Benchmarks](#benchmarks).

---

## Updating and removing

**Update:** drag the new build over the old one in Applications, then open it. The running
copy notices it has been replaced, hands over, and relaunches into the new version — you
just see a brief "Updating to x.y.z" notification. Your config, settings and history live
in `~/Library/Application Support/Kyanth` and are untouched.

> **Upgrading from 1.0.0 specifically requires quitting Kyanth first** (menu → Quit Kyanth,
> or the Quit button in either window). The handover runs in the process that receives the
> click, and 1.0.0 predates that code. Every upgrade after this one is automatic.

Because the app is signed with a stable Developer ID, macOS keeps your permission grants
across updates. (An ad-hoc signature changes identity on every build, which would make
you re-grant every time.)

**Open at login** is on by default and registered the first time the app starts. Toggle
it from the menu (**Open at Login**), or from `System Settings → General → Login Items`,
where it appears as **Kyanth**. Turning it off there is respected — the app won't re-enable
itself on the next launch.

**Remove:**

```bash
rm -rf /Applications/Kyanth.app
rm -rf ~/Library/Application\ Support/Kyanth    # also deletes history and settings
```

Deleting the app also removes its login-item registration — macOS tracks it against the
bundle rather than a separate file. Then remove the **Kyanth** entries under
`System Settings → Privacy & Security`.

---

## Troubleshooting

**Clicking the app does nothing / no window.** Kyanth is a menu-bar app — it has no
regular window, so opening it just places an icon in the menu bar. If your menu bar is
full that icon is hidden and nothing appears to happen. Opening it again from Applications
surfaces the Settings & History window, which is the reliable route in.

**Two copies of Kyanth in Applications or Spotlight.** Only `/Applications/Kyanth.app` is
real; the others are build artifacts under `dist/` that LaunchServices indexed. Clear them:

```bash
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -u /path/to/repo/dist/Kyanth.app
```

`dist/` is marked never-index so fresh builds no longer register themselves.

**No menu-bar icon.** Your menu bar is full. macOS silently drops status items when there is
no room and reports no error. Free a slot in `System Settings → Control Center`, ⌘-drag an
icon off the bar, or use [Ice](https://github.com/jordanbaird/Ice) (free). Sound cues work
regardless.

**Nothing happens when I press the key.** Open **Setup Check…** from the menu — it names
the failing step directly. Failing that,
`~/Library/Application Support/Kyanth/logs/app.log` records permissions, input device and
every capture; no `● recording` line means the hotkey isn't reaching the app.

**A tap does nothing in hold mode.** Presses under 0.25 s are discarded. Hold longer, or
switch to toggle mode. The `ignored` cue tells you this happened.

**It transcribes but nothing appears.** The text is on your clipboard — press ⌘V. The
`clipboard` cue (two rising tones) means no text field was focused.

**Model server won't start.** `brew install whisper-cpp`, then **Restart Model Server**.
See `logs/server.log`.

---

## Development

```bash
uv run bench.py            # WER + latency across models
uv run make_icons.py       # regenerate app icon and menu-bar glyphs
uv run pyinstaller kyanth.spec --noconfirm    # bundle only, no signing
./vendor_whisper.sh vendor models/ggml-base.en.bin   # vendor + verify standalone
```

See [Building from source](#building-from-source) for the full release flow.

### Layout

| File | Role |
|---|---|
| `kyanth.py` | daemon: event tap, recorder, worker, paste |
| `menubar.py` | menu-bar app: server lifecycle, state, history |
| `hotkey.py` | binding representation, matching, chord recorder |
| `website/` | the kyanth.com landing page — static HTML, no build step |
| `settings_ui.py` | Cocoa settings window: five panes behind a source list |
| `history_view.py` | the History table: columns, search, filters, expand-in-place |
| `chrome.py` | shared window furniture — band, lockup, ring, grouped boxes |
| `tokens.py` | the design tokens: colour, type, geometry |
| `menuheader.py` | the dropdown's status header |
| `history.py` | persistent transcription history |
| `sounds.py` | generated audio cues |
| `vad.py` | silence trimming and the speech gate |
| `postprocess.py` | noise filtering, vocabulary, per-app formatting |
| `config.py` · `config.yaml` | configuration |
| `bench.py` · `make_icons.py` | model comparison, icon generation |
| `paths.py` | bundle-vs-user-data path resolution |
| `build_release.sh` · `kyanth.spec` · `entitlements.plist` | signed release build |
| `vendor_whisper.sh` | vendors whisper-server + dylib closure |
| `install.sh` · `uninstall.sh` · `build_app.sh` | legacy source install (pre-DMG) |
| `run.sh` · `serve.sh` | development entry points |
| `spike.py` | Phase 0 proof-of-concept (superseded) |

---

## Benchmarks

**Latency**, key release → text on screen, `ggml-base.en` on M1 Max:

| Utterance | Transcription |
|---|---|
| 1 s | 149 ms |
| 2 s | 199 ms |
| 3 s | 208 ms |
| 5 s | 289 ms |
| 10 s | 456 ms |

Plus ~50 ms for clipboard + ⌘V.

**Model comparison** (`uv run bench.py`, 8 clips of prose and technical jargon):

| Model | Mean WER | Mean latency | Size |
|---|---|---|---|
| **base.en** | **3.5%** | **71 ms** | 141 MB |
| small.en | 3.5% | 163 ms | 465 MB |
| large-v3-turbo-q5_0 | 3.5% | 475 ms | 547 MB |

Identical accuracy, 6.7× the latency. The two residual errors were a jargon term (fixed by
the vocabulary layer) and a number-formatting difference the WER metric miscounts — neither
is fixable by a bigger model. Caveat: these clips come from macOS `say`, which is
unrealistically clean. Re-run `bench.py` on your own voice before treating it as settled.

---

## Privacy

Audio never leaves the machine. Transcription runs against a local `whisper-server` bound to
`127.0.0.1`. History is a plain local file you can delete at any time. No telemetry, no
account, and no network call beyond the one-time model download.

---

## Roadmap

- **Local LLM cleanup** — `llama-server` for filler removal and rewriting
- **Selection-rewrite hotkey** — copy selection, transform by voice, paste back
- **Vocabulary editor in Settings** — currently requires editing `config.yaml`
- **Presses that never arrived** — a count of presses another app swallowed, which is a
  different fault from a wrong chord and is currently invisible
- **Parakeet comparison** — a transducer model would not hallucinate on silence

---

## Engineering notes

What actually broke while building this. Kept because most of it is non-obvious macOS
behavior that would cost the next person the same time it cost me.

### Packaging notes

**Permissions showed "Python 3.14", not "Kyanth".** The bundle's executable was a shell
script that `exec`'d the framework Python. `exec` *replaces* the process, so the running
process literally was `/opt/homebrew/.../Python.app/Contents/MacOS/Python` — and TCC names
entries by executable. Freezing with PyInstaller makes `Contents/MacOS/Kyanth` a real
Mach-O binary that embeds libpython, so the process, the permission entry, and the icon
are all Kyanth's.

**A signed bundle is read-only.** The app wrote config, history, logs and cues next to its
own code. Inside a signed `.app` that invalidates the signature and macOS refuses to
launch. `paths.py` now separates read-only bundle resources from
`~/Library/Application Support/Kyanth`.

**`install_name_tool` invalidates code signatures, and the failure is silent.** After
rewriting a Mach-O's install names, macOS kills the process with SIGKILL and *no output
at all* — empty stdout, empty stderr, exit 137. Everything must be re-signed afterwards,
dependencies before the binaries that load them. Same inside-out rule applies when signing
the bundle: nested code first, or the outer signature seals unsigned nested binaries and
Gatekeeper rejects the app.

**ggml loads its compute backends at runtime** as separate `.so` files, not as linked
libraries — `otool -L` doesn't mention them. They're placed next to `whisper-server` in
the bundle so ggml finds them without a Homebrew path baked in. `GGML_BACKEND_PATH` points
at a *file*, not a directory, which is worth knowing before you spend time on it.

**Open at login uses SMAppService, not a LaunchAgent plist.** macOS 13 replaced
hand-written `~/Library/LaunchAgents` plists with an API where the app registers itself.
Better here: there's no second file to keep in sync with the bundle's location, deleting
the app can't orphan an agent that then fails on every boot, and the entry appears in
System Settings under the app's own name where users can remove it.

Two things cost time. `SMAppService.mainAppService().status()` returns `notFound` — not
`notRegistered` — until the app has been registered at least once, so gating availability
on status meant never attempting registration and the feature could never turn itself on.
And registration was initially placed in the "permissions granted" branch, which is exactly
backwards: an app that can't run yet is *precisely* the one that needs to come back at
login so the user can finish granting.

**A menu-bar app with a full menu bar can become completely unreachable.** The routes in
are the status icon (hidden when the bar is full), a window (a menu-bar app has none), and
re-opening from Applications. The reopen handler and its notification observer were being
registered only after a *successful* start — so with permissions ungranted the app had no
icon, no window, and no way to be opened at all. They are now wired up before anything that
can fail, and a first run with missing permissions opens the Settings window rather than
sitting invisible.

**Packaging exposed a first-run crash.** `request_permissions()` called
`AXIsProcessTrusted` without importing it — a `NameError` that killed the app on launch.
It never fired in development because permissions were already granted, so the path was
dead code. Fixed, `ruff`/`pyflakes` run clean for undefined names, and `start()` failures
are now non-fatal: the app stays alive in an error state instead of vanishing.

### Phase 0 results

Measured on M1 Max / 64 GB, macOS 26.5.1, `ggml-base.en`, 5.6s clip.

| Stage | Status | Notes |
|---|---|---|
| Mic capture | **works** | `sounddevice`, 16 kHz mono. Mic permission inherited from the terminal. |
| Transcription | **works** | Exact transcription of the test clip. |
| Blank handling | **works** | Silence returns `[BLANK_AUDIO]`, not hallucinated text. Filtered in `clean()`. |
| Clipboard read/write | **works** | `NSPasteboard`. |
| Frontmost-app detection | **works** | `NSWorkspace` — the hook for per-app profiles. |
| Synthetic ⌘V injection | **blocked** | Needs Accessibility. See below. |

#### Finding 1 — the resident server is mandatory

| Path | Latency |
|---|---|
| `whisper-server`, resident | **222–245 ms** |
| `whisper-cli`, warm | 500–1570 ms |
| `whisper-cli`, cold | **up to 17.9 s** |

`ggml_metal_library_init` costs 11–13 s to compile Metal shaders, and the cache is not
reliably warm — a run 60 s after a 500 ms run took 17.9 s. Spawning a subprocess per
utterance is not viable for interactive dictation. `serve.sh` is the real path;
`whisper-cli` is only a fallback so the spike degrades instead of crashing.

#### Finding 2 — Accessibility fails silently

Without the Accessibility grant, `CGEventPost` **returns success and does nothing**. No
exception, no error code. A dictation app would appear to work — recording, transcribing,
logging correct text — while nothing ever lands in the target field. This is why
`preflight()` checks `AXIsProcessTrusted()` explicitly before attempting a paste.

**Identifying the right app is the hard part.** The grant attaches to the *responsible
process* — the ancestor `.app` bundle — which is neither `python` nor whatever window is
frontmost. `NSWorkspace.frontmostApplication()` reported `iTerm2` here while the actual
owner was `cmux.app`; granting to the wrong one looks identical to not granting at all.

`preflight()` now walks the process tree and names it. It skips the interpreter's own
`Python.framework/Resources/Python.app` shim, which otherwise matches first and is never
the grantee.

**To unblock:**

1. `uv run spike.py --check` — read the `Grant it to:` line.
2. `System Settings > Privacy & Security > Accessibility` → add that app.
3. Re-run `--check`. If still `NOT GRANTED`, fully quit and reopen that app — the grant
   is read at launch.

Or run `uv run spike.py --request-access` to trigger the system dialog, which adds the
correct app automatically.

Note for Phase 4: once this is a bundled `.app`, the grant attaches to `Kyanth.app` itself
and this dev-time indirection disappears.

---

#### Finding 3 — the tap callback must never block

macOS disables an event tap whose callback runs long, and it stays disabled until
explicitly re-enabled. Transcription therefore runs on a worker thread; the tap callback
only flips a flag and enqueues audio. `Daemon.on_event` also handles
`kCGEventTapDisabledByTimeout` / `ByUserInput` by re-enabling the tap, so a transient stall
doesn't silently kill dictation for the rest of the session.

The audio device is likewise opened once at startup and left running — `start()` only
flips a flag. Opening the device on the hot path costs ~100 ms.

---

### Phase 2 results

#### Finding 4 — a bigger model buys nothing here

`uv run bench.py` — 8 clips, mixed prose and technical jargon:

| Model | Mean WER | Mean latency | Size |
|---|---|---|---|
| **base.en** | **3.5%** | **71 ms** | 141 MB |
| small.en | 3.5% | 163 ms | 465 MB |
| large-v3-turbo-q5_0 | 3.5% | 475 ms | 547 MB |

Identical accuracy, 6.7× the latency. Inspecting the only two non-zero-WER cases explains
why:

1. `kubectl` → `Cubectl` / `Cubectal`. A **vocabulary** problem. Scaling the model does not
   fix a term it was never trained to spell; the vocabulary pass does, for free.
2. "three hundred milliseconds" → "300 milliseconds". **Not an error** — a numeric
   formatting difference that WER scores as two substitutions over a ten-word reference.

So `base.en` is the default. This contradicts the a-priori recommendation in
[PROPOSAL.md](PROPOSAL.md#33-stt-engine--the-one-real-decision), which favored a larger
model and Parakeet.

**Caveat:** these clips come from macOS `say`, which is unrealistically clean. Real speech —
accents, speed, background noise — is where larger models normally earn their cost. Re-run
`bench.py` against recordings of your own voice before treating this as settled. Switching
is one line in `config.yaml`.

#### Finding 5 — seed the vocabulary from real output, not from guesses

The initial config guessed `"cube control": kubectl`. The model actually emits `Cubectl` and
`Cubectal`, so the rule never fired. Watch the daemon's log line, copy the wrong spelling
verbatim, add it. Guessing at mishearings does not work.

#### VAD

Energy-based leading/trailing silence trim. On a realistic sloppy push-to-talk capture
(1.2 s of silence either side), it removed 2.25 s and cut transcription from 208 ms to
151 ms — a 27% saving. It degrades to passthrough on empty, all-silence, and sub-frame
input rather than returning nothing.

Deliberately not `silero-vad`: that adds a torch dependency and ~30 ms of inference to save
~20 ms of transcription.

---

### Phase 4 results

Three failures, all invisible without instrumentation. Each cost a debugging cycle and
each would have bitten again later.

#### Finding 6 — `~/Documents` is TCC-protected, so the runtime can't live there

An app launched by LaunchServices gets **no access to `~/Documents`, `~/Desktop`, or
`~/Downloads`** without an explicit grant. A terminal-run process inherits the terminal's
grant and works fine; the same code in a bundle dies at interpreter startup:

```
PermissionError: [Errno 1] Operation not permitted:
  '/Users/…/Documents/code/Kyanth/.venv/pyvenv.cfg'
```

Verified with a throwaway probe app: `~/Documents/code/Kyanth/config.yaml` → DENIED,
`~/Library/Application Support` → READABLE.

Hence `install.sh` stages a runtime into `~/Library/Application Support/Kyanth` rather than
running in place. This is also why `build_app.sh` takes the runtime prefix as a parameter.

#### Finding 7 — a modal before `app.run()` hangs the app invisibly

`rumps.alert()` called from `start()` — before `app.run()` starts NSApplication — produces
an alert that is **modal but never rendered**. The result: a live process, a menu-bar icon,
no window, and no way to interact. It looked like a mysterious hang; the timeline gave it
away (server up at t=3s, down at t=6s, process still alive).

Startup problems now go into the menu's status line and the app stays usable. For
Accessibility specifically it calls `AXIsProcessTrustedWithOptions` to trigger *macOS's*
own prompt, then polls every 2s — so granting takes effect without a relaunch.

#### Finding 8 — launchd's PATH is not your PATH

Testing `open -a Kyanth.app` from a shell is misleading: the app inherits the shell's PATH.
At real login, launchd provides only `/usr/bin:/bin:/usr/sbin:/sbin`, so a bare
`whisper-server` resolves during testing and silently fails after a reboot.
`find_server_binary()` checks absolute Homebrew paths first. Verified under
`env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin`.

The same bug then reappeared one level down: `whisper-server --convert` shells out to
`ffmpeg`, which also wasn't on the child's PATH, and the server exited at startup with
`sh: ffmpeg: command not found`. `--convert` is now dropped entirely — we always hand it
16 kHz mono WAV — and the subprocess gets an explicit PATH anyway.

#### Finding 9 — `SIGTERM` is swallowed, so instances stack

`sys.exit(0)` from a signal handler raises `SystemExit` on the main thread, which the
NSApplication run loop absorbs — the process keeps running. Every `pkill` + relaunch during
development therefore added another live instance, each holding its own microphone stream
and event tap. **Five had accumulated** before it was noticed, and inspecting "the app"
meant inspecting whichever stale one `pgrep | head` happened to return.

Two fixes: signal handlers and the Quit item now call `os._exit(0)` after cleanup, and
`acquire_single_instance_lock()` takes an `flock` on `.kyanth.lock` at startup so a second
launch exits immediately. This matters beyond development — launchd at login plus a manual
`open -a` is exactly the same collision.

#### Finding 10 — one UI error killed dictation for the whole session

`rumps.MenuItem` creates its backing `NSMenu` lazily on first insert, so
`history_menu.clear()` raises `AttributeError: 'NoneType' has no attribute
'removeAllItems'` on an empty submenu — precisely its state during the **first**
transcription. That exception propagated out of `worker()` and killed the thread.

The symptom was perfect camouflage: the first dictation pasted correctly, then every
subsequent hold recorded, queued, and returned nothing. The hotkey, tap, mic, and model
were all fine. Nothing was logged, and the menu still read "Ready".

Three fixes:

- `worker()` wraps each job in `try/except` and reports `error` state. A UI bug must never
  be able to stop transcription.
- `_refresh_history()` checks `_menu is not None` before clearing.
- `on_result` and `set_state` now marshal to the main thread via `AppHelper.callAfter`.
  They were being called from the worker thread, and AppKit is main-thread-only — the
  crash was the visible symptom of a threading violation that could equally have corrupted
  state silently.

Paste now happens *before* the UI callback, so text reaches the field even if the menu
update fails.

#### Finding 11 — buffered stdout makes a bundled app look dead

The launcher redirects stdout to `logs/app.log`. Python block-buffers stdout to a file, so
nothing appeared until the buffer filled or the process died. Diagnostics printed at
startup and on every dictation were invisible; the Finding 10 traceback only showed up
because *stderr* is unbuffered.

This cost more debugging time than the bug it was hiding. The launcher now runs
`python -u`, and the app logs its model, permission states, input device, and every
utterance.

#### Finding 12 — a fixed VAD threshold eats quiet speech

The absolute cutoff (RMS 0.012) was tuned against loud test clips. On a real capture
peaking at 0.058 it trimmed a 4.2 s utterance to 1.0 s, and *"Testing shout end to end from
the menu bar app"* transcribed as **"Test."** — an accuracy failure that looks exactly like
a bad model.

`vad.trim()` now scales to each utterance's own peak: `max(floor, min(threshold,
peak_rms × 0.08))`. Never demand more than a fraction of the loudest frame; keep a floor so
silence isn't read as one very quiet speaker. The same clip now keeps all 4.7 s and
transcribes in full.

#### A notarized artifact stops being notarized the moment you rebuild it

The DMG was notarized and verified. Then it was rebuilt four times during unrelated work
using plain `build_release.sh` — which signs but does *not* notarize — and each result was
uploaded over the good asset with `gh release upload --clobber`. Users downloaded a
signed-but-unnotarized build and got *"Apple could not verify Kyanth is free of malware."*

Nothing objected. The build printed one quiet line when `--notarize` was omitted, and the
upload was a raw `gh` command with no idea what it was publishing.

Two guards now. `build_release.sh` ends by validating the artifact's own stapled ticket
and printing either `NOTARIZED` or a loud `*** NOT NOTARIZED ***`. And publishing goes
through `publish_release.sh`, which verifies the DMG ticket, the app ticket, and `spctl`
before uploading, and exits non-zero otherwise — it caught exactly this case on its first
real use.

The general shape is the recurring one in this project: a property that was verified once
and then silently invalidated by a later step. Checking it at the point of use, rather
than trusting that it still holds, is the only thing that works.

### Holding the microphone open is a privacy problem, not just a detail

The original Recorder opened the input device at launch and never closed it, to save ~110 ms
of open latency per press. macOS shows its orange indicator for as long as a stream is open,
so Kyanth appeared to be listening every moment it ran — and functionally it was holding the
device. A user reported exactly that, and they were right to.

Verified with screenshots: the indicator appears on `start()` and clears only on `close()`,
not on `stop()`. The device is now opened on demand and released after an idle period.

There is a neat property in the timing. Opening costs ~110 ms, and Kyanth already discarded
110 ms of lead-in to keep the start cue out of the recording. On a cold open the cue has
finished before capture begins, so the skip is applied only when the device was already warm.

### An overlay must never become key window, and must not trust mainScreen()

`NSScreen.mainScreen()` follows keyboard focus, not the menu bar. On a five-display machine
it returned a monitor the user was not looking at, and the indicator was placed at x=-1956 —
drawn correctly, on a screen nobody was watching. It now positions on the display containing
the pointer, falling back to the primary.

Two things made this slow to find: a `try/except` around the overlay swallowed every error,
and one attempt to verify it ran without a run loop, so nothing composited and the code
looked broken when it was not.

### An upgrade only takes effect if the running process cooperates

Dragging a new build over a running one leaves the OLD process running. The single-instance
lock makes the new copy exit immediately, and re-opening from Applications surfaces a
window belonging to the stale process — same PID, old code, none of the fixes, no
indication why. Reproduced before any code was written, and it silently affected several
real updates.

The first fix was in the wrong place: the new build's `main()`. But `open -a` on a running
app **never starts a second process** — macOS sends `applicationShouldHandleReopen:` to the
existing one — so that code was never reached. The check has to live in the *running*
process, which is the only one that sees the click. It compares its compiled-in version
against `CFBundleShortVersionString` of the bundle on disk, and if it has been replaced:
notifies, releases the lock, stops the server, and relaunches into the new copy.

Testing this produced three false failures worth knowing about. Ad-hoc-signed test builds
have a different code identity, so macOS treats them as new apps with no TCC grants; they
stall at the setup window and never register the reopen handler. And one run compared 1.1.0
against 1.1.0, where refusing to hand over is correct. The mechanism only proved itself once
both builds were properly signed and genuinely different versions.

One case cannot be fixed in code: upgrading *from* a build that predates the handover. The
old process has no such logic, so that upgrade requires quitting first.

### "Couldn't tell" is not "no"

`focused_is_editable()` returned three states — yes, no, and undeterminable — and the
paste skipped on anything that wasn't yes. But the code mapped an Accessibility *error* to
a hard `False`, so any app that failed to answer the query had its dictation diverted to
the clipboard while the user sat in a text field waiting for text to appear.

Plenty of apps fail that query: Electron and other non-native toolkits, anything slow to
service an AX request, and apps queried shortly after Accessibility was granted — macOS
often needs a relaunch before cross-app AX queries work reliably.

Pasting is now the default. Only a positive "this element cannot take text" suppresses it;
anything uncertain pastes *and* keeps the text on the clipboard as a net. The reason is
logged with every dictation (`focus: AXTextArea`, `focus: AX error -25204`), which was
impossible to see before.

### A setup checklist must not gate on a check that can be wrong

Input Monitoring was a hard requirement in the wizard, mirroring the same mistake made
earlier in `install_tap()`. A user reported step 3 stuck red — while steps 4, 5 and 6 were
green and the log showed the event tap firing. The app was working and the checklist said
it wasn't.

Steps now carry an `optional` flag: they are surfaced, they get a fix-it button, but they
never block. The only unskippable proof is step 7, an actual dictation.

### Opening the audio device blocks on the permission prompt

`sounddevice.InputStream()` does not raise when the microphone is ungranted — it *blocks*
while macOS displays its prompt. Startup therefore froze before the setup window could be
drawn, so a first-run user saw nothing at all. The microphone status is now checked first,
and the device is not touched until the grant is in place.

### py_compile does not catch pyobjc selector errors

On an `NSObject` subclass, pyobjc converts every method into an Objective-C selector at
class-creation time, and a bare name maps to a zero-argument selector — so a helper like
`_hint(self, step)` raises `BadPrototypeError`. `py_compile` parses without executing the
class body, so it passed cleanly and the frozen app then refused to launch. Python-only
methods are marked `@objc.python_method`, and the release build now *imports* every module
rather than merely compiling it.

### Notarization rejects on the one file you didn't sign

Three failed submissions, three separate causes, each hidden behind something that
reported success:

1. **Signing by filename misses extensionless binaries.** The loop matched `*.dylib` and
   `*.so`; the embedded `Python.framework/Versions/3.14/Python` has no extension and kept
   Homebrew's original signature. One file, whole archive rejected. Binaries are now
   enumerated by *content* (`file` → Mach-O) — 119 of them.
   `codesign --verify --deep` passed the whole time.
2. **A hardcoded path that didn't exist.** `whisper-server` was signed at
   `Contents/Resources/vendor/bin/`; PyInstaller puts it in `Contents/Frameworks/vendor/bin/`.
   A trailing `2>/dev/null || true` swallowed the error.
3. **`mapfile` is a bash 4 builtin and macOS ships bash 3.2.57.** The signing loop never
   ran — and the script still exited 0 despite `set -euo pipefail`.

Two further traps worth knowing. `notarytool submit --wait` **exits 0 even when Apple
rejects the archive**, so the status line must be grepped explicitly or the build ships an
unnotarized DMG while reporting success. And stapling the app does *not* give the disk
image a ticket: the DMG needs its own notarization pass, otherwise `stapler staple` on it
fails with "Record not found".

### Input Monitoring must be advisory, not a gate

Listening to key events wants **Input Monitoring** (`kTCCServiceListenEvent`), which is a
separate grant from Accessibility. When it's missing, `AXIsProcessTrusted()` still returns
true and `CGEventTapCreate()` still returns a valid tap — it simply never fires. So it
seemed prudent to require both before installing the tap.

That was wrong, and it broke the packaged app completely. macOS does **not** re-prompt for
Input Monitoring once it has been denied, and a freshly installed app is often not in that
list at all — so the check became a gate the app could never pass. The hotkey silently
never installed, with no error beyond a status code in the log.

Accessibility is now the hard requirement; a missing Input Monitoring grant logs a warning
and the tap is installed anyway. The original reasoning held only because, during
development, the terminal already had both grants.

### The original near-miss: Input Monitoring

Listening to key events requires **Input Monitoring** (`kTCCServiceListenEvent`), a
*separate* grant from Accessibility. When it's missing, `AXIsProcessTrusted()` still
returns `True` and `CGEventTapCreate()` still returns a valid tap — it simply never fires.
Accessibility covers *posting* events (the paste); Input Monitoring covers *receiving* them
(the hotkey).

It turned out to be already granted here, so it was not the cause of this bug —
but `install_tap()` now checks both and `request_permissions()` prompts for both, because
the failure mode is indistinguishable from a working app.

### Installing over an existing bundle needs App Management, deleting it does not

`ditto dist/Kyanth.app /Applications/Kyanth.app` over a bundle that already
exists fails on every file with `Operation not permitted`. macOS App Management
protects an installed app from being modified by another process unless the
user has granted that process App Management rights — a terminal has not.

Deleting the bundle and writing a fresh one is allowed, so the working
sequence is `rm -rf` then `ditto`. Which puts a loaded gun in the script:

```sh
MNT=$(hdiutil attach x.dmg -nobrowse -quiet | ...)   # -quiet ate the output
rm -rf /Applications/Kyanth.app                        # ran anyway
ditto "$MNT/Kyanth.app" /Applications/Kyanth.app        # source was ""
```

`-quiet` suppresses the mount table that the pipeline was parsing, so `$MNT`
came back empty, the delete ran, and the copy had nothing to copy. The app was
gone. **Verify the source before removing the destination**, and keep a copy
you can put back:

```sh
[ -d "$SRC" ] && [ "$(plist_version "$SRC")" = "$EXPECTED" ] || exit 1
ditto /Applications/Kyanth.app /tmp/kyanth-backup.app
rm -rf /Applications/Kyanth.app
ditto "$SRC" /Applications/Kyanth.app || ditto /tmp/kyanth-backup.app /Applications/Kyanth.app
```

A related trap: `ls -d /Volumes/Kyanth*` picks the wrong volume when an earlier
DMG is still attached, because the second mount becomes `/Volumes/Kyanth 1`. It
will silently install the older app. `hdiutil info` lists what is attached;
detach it first.

Permission grants survive the swap — TCC keys on the signing identity, not the
inode — but the microphone can read as undetermined for a few seconds
afterwards while TCC re-resolves.

#### Why `open -a` and not the binary directly

The LaunchAgent runs `/usr/bin/open -a Kyanth.app` rather than the inner executable.
Going through LaunchServices preserves the bundle identity that TCC keys permissions on;
exec'ing `Contents/MacOS/Kyanth` directly launches a bare process and loses the grant.

`KeepAlive` is `false` deliberately — otherwise launchd relaunches the app every time you
quit it from the menu.

---

### Phase 5 notes

#### Left and right modifiers need the device-dependent flag bits

The generic masks (`kCGEventFlagMaskAlternate` and friends) are set by *either* side of a
modifier, so they can't tell right-Option from left-Option. `hotkey.py` matches on the
`NX_DEVICE*KEYMASK` bits instead, which is what makes "Right ⌥" a distinct binding that
leaves left-Option free for normal typing.

#### fn is excluded from matching

macOS sets `kCGEventFlagMaskSecondaryFn` on F-keys and arrow keys, and whether it appears
depends on the keyboard's "use F1..F12 as function keys" setting. Requiring it would make a
binding work on one machine and silently fail on another, so `Hotkey.MATCH_MASK` covers
only ⇧⌃⌥⌘. This surfaced as an F13 binding that never fired: the event carried
`0x20800000`, the binding expected `0`.

#### Chord detection must be state-based, not trigger-keyed

The first implementation filtered events down to the binding's trigger keycode, then asked
whether the chord was satisfied. That made **press order significant**: for
`Right ⌥ + Right ⌘` (trigger ⌘), pressing ⌥ then ⌘ fired, while ⌘ then ⌥ discarded the ⌥
event and **never fired at all**. In toggle mode this reads as a shortcut that only works
if you "get it just right" — and the user unconsciously learns one specific order.

`on_event` now evaluates the chord's *state* on every `flagsChanged` event and acts on the
edges, latched by `chord_down`. Any press order works, with no timing requirement: the
chord fires the moment the last of its keys goes down, however far apart the presses are.
In hold mode, releasing *any* key of the chord ends the capture.

`rebind()` clears the latch — a stale `chord_down = True` would swallow the first press
after a settings change.

Toggle mode additionally debounces: a second press within `TOGGLE_DEBOUNCE_SEC` (0.40 s) is
treated as a finger bouncing off a key rather than an intentional stop. Without it, a
ragged chord ends the recording immediately and the audio is discarded as "too short".

#### Recording a chord means committing on release, not on press

The first recorder committed as soon as a modifier went *down*. That made multi-key
combinations impossible to enter: reaching for ⇧⌘V, the ⇧ press ended the recording and the
binding became "Left ⇧". `ChordRecorder` instead grows the chord while keys go down and
commits once they have all come back up, so the user can build it at their own pace. A
regular key still commits immediately, since nothing further can be added to it.

For a modifier-only chord the *last* key pressed becomes the trigger and the earlier ones
become required co-modifiers — "⌃ + right-⌥" fires on the right-Option edge while Control
is held. Co-modifiers are stored as device bits, so it stays distinct from "⌃ + left-⌥".

`ChordRecorder` lives in `hotkey.py` rather than the window so it can be tested without a
GUI.

#### The focused-element check needs the per-app element

`AXUIElementCreateSystemWide()` + `kAXFocusedUIElementAttribute` returns
`kAXErrorCannotComplete` (-25204) here even with Accessibility granted.
`AXUIElementCreateApplication(pid)` on the frontmost app works reliably — verified against
TextEdit (`AXTextArea`), Safari (`AXTextField`), Notes (`AXTextArea`) and the Electron-based
cmux (`AXTextArea`), all correctly settable, versus Finder (`AXOutline`, not settable).

Because a false negative would stop pasting into an app entirely, the paste is only skipped
on an explicit *not editable*; an undeterminable answer still pastes and additionally keeps
the text on the clipboard.

#### Whisper hallucinates on silence, and it gets pasted

Three consecutive **silent** test captures produced *"Decided to kill Trump."* and
*"TPSA can't get the Utah."* — fluent, confident, entirely invented from room noise, and
headed straight for whatever window had focus. This is the encoder-decoder failure mode
[PROPOSAL.md](PROPOSAL.md#33-stt-engine--the-one-real-decision) predicted, and the adaptive
VAD made it worse: scaling the threshold to the clip's own peak means a clip that is *all*
noise gets a very low threshold and passes through intact.

`vad.has_speech()` now gates the model. It requires ≥120 ms of frames above a floor of
`max(0.008, p10_rms × 3)`. Measured on this mic, a quiet room peaks at frame-RMS 0.0058
with **zero** frames above 0.008, while conversational speech holds 1820 ms above it — a
wide margin. The floor references the clip's *10th percentile*, not its median: speech
drags the median up, so a median-scaled gate would reject real dictation.

Whisper also narrates non-speech as `(dog barking)`, `(upbeat music)`, `[door closes]`.
`strip_noise()` drops any result that is entirely enclosed in brackets, while leaving a
genuine mid-sentence "(like this)" alone.

#### Auto-repeat had to be filtered

Holding a regular key produces repeated `keyDown` events. In **toggle** mode each repeat
would have flipped recording on and off many times per second. `on_event` drops events
whose `kCGKeyboardEventAutorepeat` field is set.

#### Re-opening a running app sends a delegate message, not a new process

Double-clicking Kyanth in Applications does not start a second process — LaunchServices
activates the existing one and sends `applicationShouldHandleReopen:hasVisibleWindows:`.
rumps owns the `NSApplication` delegate, so the handler is grafted on with an
`objc.Category` (whose class must be named exactly like the class it extends). The
distributed-notification path is kept as a fallback for the case where a second process
really does start.

---

