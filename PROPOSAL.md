# Kyanth — a local, free dictation layer for macOS

A from-scratch alternative to [Voicy](https://usevoicy.com/) ($102/yr) that runs entirely on this machine.

---

## 1. Competitive analysis: what Voicy actually is

**Product:** Push-to-talk dictation for the whole OS. Press a hotkey, talk, and the
transcribed text is injected into whatever text field currently has focus. Ships for
Mac / Windows / Linux plus a Chrome extension.

**Marketing claims:** ">99% accuracy in 50 languages", "3x faster than typing"
(~120 wpm vs ~40 wpm), "2x the accuracy of Apple/Windows Dictation".

**Pricing:** 30-min free trial → $8.49/mo, $102/yr, or $260 lifetime. Teams $6.79/user/mo.

### What's under the hood

Third-party review ([getvoibe.com](https://www.getvoibe.com/resources/voicy-review/))
finds it is **a thin client over Groq-hosted Whisper large-v3**. Specifically:

| Aspect | Reality |
|---|---|
| Model | Groq-hosted Whisper V3, exclusively. No custom training. |
| Offline | **None.** Every dictation ships audio to Groq's US servers. |
| On-device option | None at any price tier. |
| Custom vocabulary | **None.** No term injection, no domain handling. |
| LLM behind "AI commands" | **Undisclosed** — unusual; competitors name their providers. |
| Compliance | No SOC 2, no HIPAA BAA, no ISO 27001. |
| Accuracy claim | Unbacked by any published benchmark. |
| Scale | Solo developer, ~$1.6k MRR as of Aug 2025. |

The "privacy-centric" positioning means *transcripts aren't retained server-side* — not
that audio stays local. It does not.

### The actual moat

Not the model. The model is a commodity API call. The moat is roughly 200 lines of
platform glue:

1. Global hotkey capture that works while another app has focus
2. Low-latency mic buffering
3. Text injection into arbitrary, unmodified applications

All three are reproducible in a day on macOS. And the local path on this hardware is
*faster* than Voicy's network round-trip.

---

## 2. Hardware baseline

Already present on this machine — no new infrastructure needed:

```
Apple M1 Max, 64 GB unified memory, macOS 26.5.1, arm64
whisper-cpp    ✓ (brew)      llama.cpp   ✓ (brew)
portaudio      ✓ (brew)      ffmpeg      ✓ (brew)
uv             ✓             cargo       ✓        swift/xcodebuild ✓
```

64 GB of unified memory means every model under consideration fits comfortably, and
both an ASR model and a 4–8B LLM can stay resident simultaneously.

---

## 3. Architecture

Single Python daemon. Six stages:

```
  [Right-Option held]                  CGEventTap on flagsChanged
          ↓
  [mic capture]                        sounddevice, 16 kHz mono float32 ring buffer
          ↓  (on key release)
  [VAD trim]                           silero-vad or webrtcvad — strip lead/trail silence
          ↓
  [STT]                                parakeet-mlx (default) | whisper.cpp (fallback)
          ↓
  [post-process]                       custom vocab map → per-app profile → optional LLM
          ↓
  [inject]                             save clipboard → set → synth ⌘V → restore
```

### 3.1 Hotkey capture

Use a Quartz `CGEventTap` on `kCGEventFlagsChanged` **directly**, not `pynput`. Reasons:

- Distinguishes *right* Option (keycode 61) from left Option (58) — left stays free for
  normal use.
- Gives clean press **and** release events, which is what true push-to-talk needs.
  Toggle-mode hotkeys are worse for dictation: you forget you left the mic on.

```python
from Quartz import (
    CGEventTapCreate, kCGSessionEventTap, kCGHeadInsertEventTap,
    kCGEventFlagsChanged, CGEventGetIntegerValueField, kCGKeyboardEventKeycode,
    CGEventTapEnable, CFMachPortCreateRunLoopSource, CFRunLoopAddSource,
    CFRunLoopGetCurrent, kCFRunLoopCommonModes, CFRunLoopRun, CGEventMaskBit,
)

RIGHT_OPTION = 61
ALT_MASK = 0x00080000

def on_event(proxy, type_, event, refcon):
    if CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode) == RIGHT_OPTION:
        held = bool(CGEventGetFlags(event) & ALT_MASK)
        start_recording() if held else stop_and_transcribe()
    return event

tap = CGEventTapCreate(
    kCGSessionEventTap, kCGHeadInsertEventTap, 0,
    CGEventMaskBit(kCGEventFlagsChanged), on_event, None,
)
```

**Permissions required:** Accessibility, Input Monitoring, Microphone. Grant all three in
System Settings → Privacy & Security before the daemon will work. Note that during
development the permission is granted to the *interpreter binary* (e.g. the pyenv
`python3`), not to `Kyanth` — re-granting is needed if the interpreter path changes.

### 3.2 Text injection

Clipboard + synthetic ⌘V. This is what Voicy, Wispr Flow, Superwhisper, and VoiceInk all
do — there is no better universal path on macOS, because most apps don't expose
`AXTextField` write access.

```python
from AppKit import NSPasteboard, NSPasteboardTypeString
from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap, kCGEventFlagMaskCommand

def paste(text: str):
    pb = NSPasteboard.generalPasteboard()
    saved = pb.stringForType_(NSPasteboardTypeString)   # save user's clipboard
    pb.clearContents(); pb.setString_forType_(text, NSPasteboardTypeString)

    for down in (True, False):                           # V = keycode 9
        e = CGEventCreateKeyboardEvent(None, 9, down)
        CGEventSetFlags(e, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, e)

    if saved:
        threading.Timer(0.3, lambda: restore(pb, saved)).start()
```

The 300 ms delay before restore matters — restoring too fast races the target app's paste
handler and pastes the *old* clipboard contents.

### 3.3 STT engine — the one real decision

Benchmark sources **conflict** on Apple Silicon. Measure on this machine rather than
trusting published numbers.

| | Parakeet TDT 0.6B v3 (`parakeet-mlx`) | whisper-large-v3-turbo (`whisper.cpp` + CoreML) |
|---|---|---|
| English WER | ~1.9% (LibriSpeech clean) | ~3.0% |
| Languages | 25 European | 99+ |
| Silence behavior | **Transducer — emits silence during silence** | Can hallucinate text during pauses |
| Speed claims | Some sources: ~10x faster. Others: 2.6x *slower* on MLX vs CoreML. | Well-characterized, Metal-accelerated |
| Already installed | no (`uv add parakeet-mlx`) | **yes** (`brew` whisper-cpp) |

> **Superseded by measurement — see [Phase 2 results](README.md#phase-2-results).**
> Benchmarked on this machine, `base.en`, `small.en`, and `large-v3-turbo-q5_0` scored
> **identical WER (3.5%)** while `base.en` ran **6.7× faster** (71 ms vs 475 ms). The
> residual errors were jargon (fixed by the vocabulary layer) and a number-formatting
> artifact of the WER metric — neither is fixable by a bigger model. `base.en` ships as
> the default. The reasoning below was sound a priori; it just didn't survive contact
> with data. Parakeet remains untested and is now low priority.

**Original recommendation: Parakeet default, whisper.cpp behind a config flag.**

The silence behavior is the deciding factor and is underrated. Dictation is not
transcription — you stop mid-sentence to think, constantly. Whisper's encoder-decoder
architecture will invent plausible text to fill those gaps ("Thanks for watching!" is the
classic artifact). A transducer emits nothing. For this workload that is worth more than
the WER delta.

Keep whisper.cpp wired up regardless: it's already installed, it's the multilingual
escape hatch, and it's the control in your benchmark.

**Benchmark first (30 min):** record one 30-second clip with natural mid-thought pauses,
run both, compare wall-clock latency *and* whether the pauses produced phantom text.

### 3.4 Differentiators over Voicy

Cheap to build here, absent from the paid product:

**Custom vocabulary** — Voicy's most-cited gap. A YAML term list applied twice: as a
post-transcription replacement pass, and injected into the LLM cleanup prompt as context.

```yaml
# ~/.config/Kyanth/vocab.yaml
terms:
  - kubectl
  - Postgres
  - Anthropic
replacements:
  "cube control": kubectl
  "post gres":    Postgres
```

**Per-app profiles** — read the frontmost app via `NSWorkspace` and switch formatting
rules. Voicy applies one global style.

```yaml
profiles:
  Slack:    {punctuation: light, capitalize: false, llm_cleanup: false}
  Mail:     {punctuation: full,  capitalize: true,  llm_cleanup: true}
  Terminal: {punctuation: none,  capitalize: false, llm_cleanup: false}
  default:  {punctuation: full,  capitalize: true,  llm_cleanup: false}
```

**Fully local AI commands** — `llama-server` (already installed) on localhost with
Qwen3-4B or similar, kept warm. A second hotkey copies the current selection, transforms
it by voice instruction ("make this more formal", "turn this into bullets"), and pastes
the result back. Voicy does this too, but won't say what model it sends your text to.

**Latency — measured on this machine** (Phase 0 spike, `ggml-base.en`, 5.6s clip):

| Path | Latency | Notes |
|---|---|---|
| `whisper-server`, resident model | **222–245 ms** | steady state after first request |
| `whisper-cli` subprocess, warm | 500–1570 ms | reloads 141 MB model each time |
| `whisper-cli` subprocess, cold | **up to 17.9 s** | Metal shader library recompile |

The cold-start number is the finding that matters. `ggml_metal_library_init` takes
11–13 s on first compile, and the cache is not reliably warm — a spike run 60 s after a
500 ms run took 17.9 s. **The resident-model server is therefore mandatory, not an
optimization.** Subprocess-per-utterance is not viable for interactive dictation at any
percentile. `serve.sh` starts it; Phase 4 should put it under `launchd`.

Budget with the server path:

```
VAD trim            ~20 ms
STT (resident)     ~225 ms      ← measured, base.en
vocab pass           ~1 ms
clipboard + ⌘V      ~50 ms
                   --------
                    ~300 ms     vs Voicy's network round-trip to Groq
```

LLM cleanup, when enabled, adds ~300–800 ms — hence per-app profiles, so it's off for
chat and on for email.

---

## 4. Phasing

| Phase | Scope | Estimate |
|---|---|---|
| **0** | Spike: record 5 s → transcribe → paste. Proves permissions + injection path end to end. | ~1 hr |
| **1** | Hotkey daemon, push-to-talk, clipboard save/restore, config file | ~half day |
| **2** | VAD trim, custom vocab, per-app profiles, model switching + benchmark | ~1 day |
| **3** | `llama-server` cleanup + selection-rewrite hotkey | ~half day |
| **4** | `rumps` menubar, start/stop sound cues, `launchd` autostart, history log | ~1 day |

**Phases 0–1 alone replace Voicy for daily use.** Total ~3 days to exceed it.

Do Phase 0 before anything else — it's the only part with real unknowns (macOS permission
grants and synthetic-event injection are where this class of project actually stalls).
Everything after it is ordinary application code.

### Dependency set

```bash
uv init && uv add \
  sounddevice numpy pyobjc-framework-Quartz pyobjc-framework-Cocoa \
  parakeet-mlx silero-vad pyyaml rumps
```

---

## 5. Build vs. fork

Two mature open-source apps already cover phases 0–4:

- **[VoiceInk](https://github.com/beingpax/VoiceInk)** — Swift, macOS-native, GPL-3,
  whisper.cpp + Neural Engine. Requires Apple Silicon + macOS 14.4+. Polished menubar app.
- **[Handy](https://www.getvoibe.com/resources/handy-review/)** — Rust/Tauri, MIT,
  cross-platform, local Whisper.

GPL-3 on VoiceInk only constrains redistribution — personal use and private modification
are unrestricted.

**Recommendation:** run VoiceInk for a week first. It costs nothing and will tell you
precisely which parts of the UX you'd do differently — which is far better input into a
from-scratch build than starting cold. Then build `Kyanth` if you want to own the stack,
or fork if you just want to stop paying $102/yr.

---

## Sources

- <https://usevoicy.com/> — product, pricing, claims
- <https://www.getvoibe.com/resources/voicy-review/> — teardown: Groq/Whisper stack, gaps
- <https://github.com/beingpax/VoiceInk> — open-source macOS reference implementation
- <https://github.com/primaprashant/awesome-voice-typing> — landscape survey
- <https://www.parakeety.com/resources/parakeet-vs-whisper> — ASR comparison
- <https://www.arunbaby.com/speech-tech/0073-whisper-vs-parakeet-asr-decision/> — dissenting view favoring Whisper
