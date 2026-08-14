"""shout — push-to-talk dictation daemon.

Hold right-Option, speak, release. Text lands in the focused field.

Everything expensive is paid once at startup: Python imports, pyobjc bridges,
and the whisper model (resident in whisper-server). Per-utterance cost is
transcription + paste, ~300ms.

Run:  ./serve.sh          (terminal 1 — keeps the model resident)
      uv run shout.py     (terminal 2)
"""

import argparse
import os
import queue
import socket
import subprocess
import sys
import threading
import traceback
import time
import wave
from pathlib import Path

import numpy as np
import requests
import sounddevice as sd

import postprocess
import vad
from config import Config, load as load_config
from hotkey import MODE_HOLD, MODE_TOGGLE, Hotkey
from AppKit import NSPasteboard, NSPasteboardTypeString, NSWorkspace
from ApplicationServices import (
    AXIsProcessTrusted,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementIsAttributeSettable,
    kAXFocusedUIElementAttribute,
    kAXRoleAttribute,
    kAXValueAttribute,
)
from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
from Quartz import (
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRun,
    CGEventCreateKeyboardEvent,
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventPost,
    CGEventSetFlags,
    CGEventTapCreate,
    CGEventTapEnable,
    kCFRunLoopCommonModes,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagsChanged,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGEventTapOptionListenOnly,
    kCGHIDEventTap,
    kCGHeadInsertEventTap,
    kCGKeyboardEventAutorepeat,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
)

import paths

ROOT = paths.resources()
WAV = paths.data() / "utterance.wav"
SAMPLE_RATE = 16_000
SERVER_PORT = 8178
KEYCODE_RIGHT_OPTION = 61
KEYCODE_V = 9
CLIPBOARD_RESTORE_DELAY = 0.3
MIN_UTTERANCE_SEC = 0.25
#  Toggle mode only: a second press this soon after starting is treated as key
#  bounce rather than an intentional stop.
TOGGLE_DEBOUNCE_SEC = 0.40



# ---------------------------------------------------------------- audio

class Recorder:
    """Opens the input device on demand and releases it when idle.

    An earlier version opened the stream at launch and never closed it, to save
    ~110ms of open latency per press. That was the wrong trade: macOS shows its
    microphone-in-use indicator for as long as a stream is open, so shout
    appeared to be listening every moment it ran. A user reported exactly that,
    and they were right to.

    The device is now opened on the first press and released after
    IDLE_RELEASE_SECONDS of no use, so consecutive dictations stay instant while
    an idle shout holds nothing. The open cost is largely hidden: it overlaps
    the start cue and the user's own reaction time before speaking.
    """

    IDLE_RELEASE_SECONDS = 30.0

    def __init__(self, device=None, lead_skip_ms: int = 0):
        self._chunks: list[np.ndarray] = []
        self._active = False
        self._lock = threading.Lock()
        self._device = device
        self._stream = None
        self._idle_timer = None
        self._level = 0.0
        #  Only meaningful when the stream was ALREADY open: a freshly opened
        #  device misses the cue naturally, since opening it takes about as
        #  long as the cue lasts.
        self._lead_skip = int(SAMPLE_RATE * lead_skip_ms / 1000)
        self._skip_this_capture = 0

    # ------------------------------------------------------------ device

    def _open(self) -> bool:
        if self._stream is not None:
            return True
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=1024,
                device=self._device,
                callback=self._on_audio,
            )
            self._stream.start()
            return True
        except Exception:
            self._stream = None
            raise

    def _close(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()      # close, not just stop: only this clears
                                    # the macOS microphone indicator
            except Exception:
                pass

    def _cancel_idle_timer(self):
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _schedule_release(self):
        self._cancel_idle_timer()
        self._idle_timer = threading.Timer(self.IDLE_RELEASE_SECONDS,
                                           self._release_if_idle)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _release_if_idle(self):
        with self._lock:
            if self._active:
                return               # a capture started while we waited
            self._close()

    def probe(self) -> bool:
        """Open and immediately release, to prove the device works.

        Setup needs to verify the microphone without leaving it held open.
        """
        with self._lock:
            try:
                self._open()
            except Exception:
                return False
            self._close()
            return True

    # ----------------------------------------------------------- capture

    def _on_audio(self, indata, frames, time_info, status):
        with self._lock:
            if not self._active:
                return
            self._chunks.append(indata.copy())
            peak = float(np.abs(indata).max()) if indata.size else 0.0
            #  Smoothed so a UI reading this does not flicker.
            self._level = max(peak, self._level * 0.8)

    @property
    def level(self) -> float:
        return self._level

    def start(self):
        self._cancel_idle_timer()
        with self._lock:
            was_open = self._stream is not None
        self._open()                 # no-op when already open
        with self._lock:
            self._chunks = []
            self._level = 0.0
            #  Skip the cue only when the device was already running; a cold
            #  open has already missed it.
            self._skip_this_capture = self._lead_skip if was_open else 0
            self._active = True

    def stop(self) -> np.ndarray:
        with self._lock:
            self._active = False
            chunks = self._chunks
            self._chunks = []
            skip = self._skip_this_capture
            self._level = 0.0
        self._schedule_release()
        if not chunks:
            return np.zeros((0, 1), dtype="float32")
        audio = np.concatenate(chunks, axis=0)
        if skip and len(audio) > skip * 2:
            audio = audio[skip:]
        return audio

    def close(self):
        self._cancel_idle_timer()
        with self._lock:
            self._close()


def write_wav(audio: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(pcm.tobytes())


# ---------------------------------------------------------------- stt

def transcribe(path: Path, session: requests.Session) -> str:
    with open(path, "rb") as f:
        resp = session.post(
            f"http://127.0.0.1:{SERVER_PORT}/inference",
            files={"file": f},
            data={"response_format": "text"},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------- output

#  Roles that accept typed text. Checked before the role-agnostic
#  "is AXValue settable" fallback, which some apps answer unhelpfully.
EDITABLE_ROLES = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}


def focused_is_editable() -> tuple[bool | None, str]:
    """(verdict, why). True / False / None, where None means undeterminable.

    Only a POSITIVE answer of "not editable" may suppress the paste. An AX
    error is not that answer — it means the question could not be asked, and an
    earlier version returned False for it, so any app that failed to respond
    got its dictation diverted to the clipboard while the user sat in a text
    field waiting for text to appear.

    Plenty of apps fail to answer: Electron and other non-native toolkits,
    anything slow to service an AX request, and apps queried moments after
    Accessibility was granted.

    Uses the per-application element, not the system-wide one:
    kAXFocusedUIElementAttribute on AXUIElementCreateSystemWide returns
    kAXErrorCannotComplete (-25204) even with Accessibility granted.
    """
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None, "no frontmost app"
        element = AXUIElementCreateApplication(app.processIdentifier())
        err, focused = AXUIElementCopyAttributeValue(
            element, kAXFocusedUIElementAttribute, None)
        if err != 0:
            return None, f"AX error {err}"
        if focused is None:
            # Not proof of anything — many apps simply do not report focus.
            return None, "app reports no focused element"

        err, role = AXUIElementCopyAttributeValue(focused, kAXRoleAttribute, None)
        role_name = str(role) if err == 0 else "?"
        if err == 0 and role in EDITABLE_ROLES:
            return True, role_name

        err, settable = AXUIElementIsAttributeSettable(
            focused, kAXValueAttribute, None)
        if err != 0:
            return None, f"{role_name}, settable unknown"
        return bool(settable), f"{role_name}, settable={bool(settable)}"
    except Exception as exc:
        return None, f"exception: {exc}"


def paste(text: str) -> tuple[str, str]:
    """Returns (outcome, why). Outcome is "pasted" or "clipboard".

    Pasting is the default. Only a positive "the focused element cannot take
    text" suppresses it; anything uncertain still pastes, and additionally
    leaves the text on the clipboard as a safety net.
    """
    pb = NSPasteboard.generalPasteboard()
    saved = pb.stringForType_(NSPasteboardTypeString)

    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)

    editable, why = focused_is_editable()
    if editable is False:
        return "clipboard", why          # nothing to paste into; keep the text

    for is_down in (True, False):
        event = CGEventCreateKeyboardEvent(None, KEYCODE_V, is_down)
        CGEventSetFlags(event, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, event)
        time.sleep(0.008)

    # Reclaim the clipboard only when the target was confirmed. When it was
    # merely probable, the text stays on the clipboard too, so a paste that
    # silently went nowhere is still recoverable with Cmd-V.
    if editable is True and saved is not None:
        def restore():
            pb.clearContents()
            pb.setString_forType_(saved, NSPasteboardTypeString)

        threading.Timer(CLIPBOARD_RESTORE_DELAY, restore).start()

    return "pasted", why if editable is True else f"{why} — kept on clipboard too"


def resolve_input_device(name: str | None):
    """Device *name* -> index, or None for the system default.

    Indices shift when audio hardware is added or removed, so a stored index
    can quietly point at a different microphone. Names are stable.
    """
    if not name:
        return None
    try:
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0 and dev["name"] == name:
                return i
    except Exception:
        pass
    return None                      # fall back to the default, never fail


def input_devices() -> list[str]:
    try:
        return [d["name"] for d in sd.query_devices()
                if d["max_input_channels"] > 0]
    except Exception:
        return []


def frontmost_app() -> str:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app.localizedName() if app else "<unknown>"


# ------------------------------------------------------- input monitoring

#  Listening to key events needs Input Monitoring (kTCCServiceListenEvent),
#  which is a SEPARATE grant from Accessibility. This is the trap:
#  AXIsProcessTrusted() returns True and CGEventTapCreate() returns a valid
#  tap, so everything looks correct — but the tap never receives an event.
#  Accessibility covers posting events (the paste); Input Monitoring covers
#  receiving them (the hotkey).
_HID_LISTEN_EVENT = 1
_hid = {}


def _hid_fn(name: str):
    if name not in _hid:
        import objc
        from Foundation import NSBundle

        bundle = NSBundle.bundleWithPath_("/System/Library/Frameworks/IOKit.framework")
        ns = {}
        objc.loadBundleFunctions(bundle, ns, [(name, b"II" if "Check" in name else b"ZI")])
        _hid[name] = ns.get(name)
    return _hid[name]


def input_monitoring_status() -> int:
    """0 = granted, 1 = denied, 2 = not determined."""
    fn = _hid_fn("IOHIDCheckAccess")
    return fn(_HID_LISTEN_EVENT) if fn else 2


def request_input_monitoring() -> bool:
    """Triggers the system prompt. Only prompts once per app identity; after a
    denial the user must change it in System Settings."""
    fn = _hid_fn("IOHIDRequestAccess")
    return bool(fn(_HID_LISTEN_EVENT)) if fn else False


# ---------------------------------------------------------------- worker

def worker(jobs: "queue.Queue", cfg: Config, verbose: bool,
           on_state=None, on_result=None, cues=None) -> None:
    """Transcription runs off the event-tap thread. macOS disables a tap whose
    callback runs long, so the tap callback must never block."""
    on_state = on_state or (lambda s: None)
    on_result = on_result or (lambda text, secs, ms: None)
    session = requests.Session()
    while True:
        job = jobs.get()
        if job is None:
            return
        try:
            _handle(job, cfg, session, verbose, on_state, on_result, cues)
        except Exception:
            # A crash here used to kill the thread outright, which silently
            # disabled dictation for the rest of the session: the hotkey still
            # recorded, the queue still filled, and nothing ever came back.
            traceback.print_exc()
            if cues:
                cues.play("error")
            on_state("error")


def _handle(job, cfg: Config, session, verbose, on_state, on_result, cues=None) -> None:
    audio, app_name = job
    raw_secs = len(audio) / SAMPLE_RATE

    trimmed = 0.0
    if cfg.vad:
        audio, trimmed = vad.trim(
            audio, SAMPLE_RATE, cfg.vad_threshold, cfg.vad_pad_ms
        )
    secs = len(audio) / SAMPLE_RATE

    # Gate before the model, not after: whisper invents fluent sentences from
    # room noise, and anything it returns gets pasted.
    if not vad.has_speech(audio, SAMPLE_RATE):
        if cues:
            cues.play("ignored")
        on_state("idle")
        if verbose:
            print(f"  ○ {raw_secs:.1f}s captured, no speech detected — not transcribed")
        return

    try:
        t0 = time.perf_counter()
        write_wav(audio, WAV)
        raw = transcribe(WAV, session)
        t1 = time.perf_counter()
    except requests.RequestException as e:
        print(f"  ! transcription failed: {e}", file=sys.stderr)
        print("    is the model server running?", file=sys.stderr)
        if cues:
            cues.play("error")
        on_state("error")
        return

    text = postprocess.process(raw, cfg.vocabulary, cfg.profile_for(app_name))

    if not text:
        on_state("idle")
        if verbose:
            print(f"  ({raw_secs:.1f}s audio, no speech)")
        return

    # Paste before notifying the UI: text landing in the field is the job, and
    # it must not depend on a menu update succeeding.
    where, why = paste(text)
    if cues:
        cues.play("clipboard" if where == "clipboard" else "stop")
    on_state("idle")
    trim_note = f" -{trimmed:.1f}s" if trimmed >= 0.1 else ""
    tag = "" if where == "pasted" else "  [CLIPBOARD ONLY]"
    print(f"  [{t1 - t0:.2f}s / {secs:.1f}s{trim_note} / {app_name}]{tag} -> {text}")
    if verbose:
        print(f"      focus: {why}")
    on_result(text, secs, (t1 - t0) * 1000, where)


# ---------------------------------------------------------------- hotkey

class Daemon:
    def __init__(self, recorder: Recorder, jobs: "queue.Queue", verbose: bool,
                 on_state=None, binding: Hotkey | None = None,
                 mode: str = MODE_HOLD, cues=None):
        self.recorder = recorder
        self.jobs = jobs
        self.verbose = verbose
        self.recording = False
        self.chord_down = False     # is every key of the binding held right now
        self.tap = None
        self.t_press = 0.0
        self.enabled = True
        #  Repeated too-short presses almost always mean the user is tapping
        #  while in hold mode. Silently discarding them cost a real user an
        #  hour, with the only evidence buried in a log file.
        self.short_presses = 0
        self.on_hint = None
        self.binding = binding or Hotkey()
        self.mode = mode
        self.cues = cues
        # Optional observer so a UI can reflect idle/recording without polling.
        self.on_state = on_state or (lambda state: None)

    def rebind(self, binding: Hotkey, mode: str) -> None:
        """Apply a new binding live. If a capture is in flight, drop it —
        finishing it under the old binding would be surprising."""
        if self.recording:
            self.recorder.stop()
            self.recording = False
            self.on_state("idle")
        self.binding = binding
        self.mode = mode
        self.chord_down = False

    # ------------------------------------------------------------ capture

    def _begin(self):
        self.recording = True
        self.t_press = time.perf_counter()
        if self.cues:
            self.cues.play("start")
        self.recorder.start()
        self.on_state("recording")
        if self.verbose:
            print(f"  ● recording ({frontmost_app()})")

    def _end(self):
        self.recording = False
        audio = self.recorder.stop()
        held = time.perf_counter() - self.t_press
        if self.verbose:
            peak = float(np.abs(audio).max()) if audio.size else 0.0
            print(f"  ○ stopped after {held:.2f}s, {audio.shape[0]} frames, peak {peak:.4f}")
        if held < MIN_UTTERANCE_SEC:
            # The case that cost four days of confusion: in hold mode a tap is
            # silently discarded. Now it says so.
            if self.cues:
                self.cues.play("ignored")
            self.on_state("idle")
            if self.verbose:
                print(f"  ○ too short ({held:.2f}s), ignored")
            self.short_presses += 1
            if (self.short_presses >= 3 and self.mode == MODE_HOLD
                    and self.on_hint is not None):
                self.short_presses = 0
                self.on_hint(
                    "You are in hold mode",
                    f"Hold {self.binding.label()} while speaking, or switch to "
                    f"toggle in Settings.")
            return
        self.short_presses = 0
        self.on_state("working")
        # Resolve the target app at release, not at press: the paste lands
        # wherever focus is now.
        self.jobs.put((audio, frontmost_app()))

    # ------------------------------------------------------------- events

    def on_event(self, proxy, type_, event, refcon):
        # A timed-out tap stops delivering events until re-enabled.
        if type_ in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            CGEventTapEnable(self.tap, True)
            return event

        if not self.enabled:
            return event

        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        flags = CGEventGetFlags(event)

        if self.binding.is_modifier_only:
            if type_ != kCGEventFlagsChanged:
                return event

            # Evaluate the whole chord's *state* on every modifier event, not
            # just events for the trigger key. Filtering on the trigger made
            # press order significant: for "Right ⌥ + Right ⌘" (trigger ⌘),
            # pressing ⌥ then ⌘ worked, while ⌘ then ⌥ discarded the ⌥ event
            # and never fired at all. State-based edges are order-independent
            # and impose no timing requirement — press them in either order,
            # however far apart.
            satisfied = self.binding.is_pressed(flags)
            if satisfied == self.chord_down:
                return event                    # no edge, nothing to do
            self.chord_down = satisfied
            down = satisfied
        else:
            if type_ == kCGEventKeyDown:
                if not self.binding.matches_regular(keycode, flags):
                    return event
                # Holding a key produces repeated keyDown events. In toggle
                # mode each repeat would flip recording on and off; in hold
                # mode they're merely redundant.
                if CGEventGetIntegerValueField(event, kCGKeyboardEventAutorepeat):
                    return event
                down = True
            elif type_ == kCGEventKeyUp:
                if keycode != self.binding.keycode:
                    return event
                down = False
            else:
                return event

        if self.mode == MODE_TOGGLE:
            # Act on press only; the release of a toggle key means nothing.
            if down and not self.recording:
                self._begin()
            elif down and self.recording:
                # A ragged chord — a finger bouncing off one key and back —
                # produces two press edges in quick succession. Stopping on the
                # second would discard the recording as "too short". Treat
                # anything inside the debounce as part of the same press.
                if time.perf_counter() - self.t_press < TOGGLE_DEBOUNCE_SEC:
                    if self.verbose:
                        print("  · ignoring bounce, still recording")
                    return event
                self._end()
        else:
            if down and not self.recording:
                self._begin()
            elif not down and self.recording:
                self._end()

        return event

    def install(self) -> bool:
        """Attach the tap to the current run loop without running it, so a host
        app (rumps/NSApplication) can own the loop instead."""
        mask = (CGEventMaskBit(kCGEventFlagsChanged)
                | CGEventMaskBit(kCGEventKeyDown)
                | CGEventMaskBit(kCGEventKeyUp))
        self.tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            mask,
            self.on_event,
            None,
        )
        if self.tap is None:
            print("failed to create event tap — Accessibility not granted?", file=sys.stderr)
            return False

        source = CFMachPortCreateRunLoopSource(None, self.tap, 0)
        CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
        CGEventTapEnable(self.tap, True)
        return True

    def run(self):
        if not self.install():
            return 1
        CFRunLoopRun()
        return 0


# ---------------------------------------------------------------- main

def responsible_app() -> str | None:
    pid = os.getppid()
    for _ in range(20):
        try:
            out = subprocess.run(
                ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        except subprocess.CalledProcessError:
            return None
        if not out:
            return None
        ppid_str, _, comm = out.partition(" ")
        if ".app/Contents/MacOS/" in comm and "Python.framework" not in comm:
            return comm.split(".app/")[0] + ".app"
        try:
            pid = int(ppid_str)
        except ValueError:
            return None
        if pid <= 1:
            return None
    return None


def preflight() -> bool:
    ok = True

    if AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio) != 3:
        print("microphone: NOT GRANTED", file=sys.stderr)
        ok = False

    if not AXIsProcessTrusted():
        app = responsible_app() or "the app that owns this process"
        print(f"accessibility: NOT GRANTED — grant it to {app}", file=sys.stderr)
        ok = False

    # TCP connect, not an HTTP GET: whisper-server serves no root route and a
    # GET / hangs rather than 404ing.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        if s.connect_ex(("127.0.0.1", SERVER_PORT)) != 0:
            print(f"whisper-server: not listening on :{SERVER_PORT} — run ./serve.sh",
                  file=sys.stderr)
            ok = False

    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="only print transcriptions")
    ap.add_argument("--device", default=None, help="input device name or index")
    args = ap.parse_args()

    if not preflight():
        return 1

    verbose = not args.quiet
    cfg = load_config()
    jobs: queue.Queue = queue.Queue()
    recorder = Recorder(device=args.device)
    threading.Thread(target=worker, args=(jobs, cfg, verbose), daemon=True).start()

    print("shout ready — hold RIGHT OPTION to dictate, ctrl-C to quit")
    try:
        return Daemon(recorder, jobs, verbose,
                      binding=cfg.hotkey, mode=cfg.mode).run()
    except KeyboardInterrupt:
        print("\nbye")
        return 0
    finally:
        recorder.close()


if __name__ == "__main__":
    sys.exit(main())
