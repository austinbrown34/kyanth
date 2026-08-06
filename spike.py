"""Phase 0 spike: record -> transcribe -> paste.

Proves the three things that can actually block this project on macOS:
  1. Microphone permission + capture works
  2. Local whisper.cpp transcription works
  3. Synthetic Cmd+V injection into another app works (Accessibility permission)

Run:  uv run spike.py
"""

import argparse
import os
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import requests
import sounddevice as sd
from AppKit import NSPasteboard, NSPasteboardTypeString, NSWorkspace
from ApplicationServices import (
    AXIsProcessTrusted,
    AXIsProcessTrustedWithOptions,
    kAXTrustedCheckOptionPrompt,
)
from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

ROOT = Path(__file__).parent
MODEL = ROOT / "models" / "ggml-base.en.bin"
WAV = ROOT / ".scratch" / "spike.wav"
SAMPLE_RATE = 16_000
SERVER_PORT = 8178
KEYCODE_V = 9
CLIPBOARD_RESTORE_DELAY = 0.3


def record(seconds: float) -> np.ndarray:
    print(f"  recording {seconds:.0f}s — speak now...", flush=True)
    audio = sd.rec(
        int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32"
    )
    sd.wait()
    peak = float(np.abs(audio).max())
    print(f"  captured {audio.shape[0]} frames, peak amplitude {peak:.3f}")
    if peak < 0.01:
        print("  WARNING: near-silent input. Check mic permission / input device.")
    return audio


def write_wav(audio: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(pcm.tobytes())


def transcribe_via_server(path: Path) -> str | None:
    """Warm resident model. ~225ms vs ~500ms for a fresh subprocess."""
    try:
        with open(path, "rb") as f:
            resp = requests.post(
                f"http://127.0.0.1:{SERVER_PORT}/inference",
                files={"file": f},
                data={"response_format": "text"},
                timeout=30,
            )
        resp.raise_for_status()
        return resp.text.strip()
    except requests.RequestException:
        return None


def transcribe_via_cli(path: Path) -> str:
    proc = subprocess.run(
        ["whisper-cli", "-m", str(MODEL), "-f", str(path), "-nt", "--no-prints"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"whisper-cli failed:\n{proc.stderr}")
    return proc.stdout.strip()


#  whisper.cpp emits these bracket tokens for non-speech; never inject them.
NOISE_TOKENS = {"[BLANK_AUDIO]", "[SILENCE]", "(silence)", "[MUSIC]", "[NOISE]"}


def clean(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines()]
    kept = [ln for ln in lines if ln and ln not in NOISE_TOKENS]
    return " ".join(kept).strip()


def transcribe(path: Path) -> tuple[str, str]:
    """Returns (text, which_path_was_used)."""
    text = transcribe_via_server(path)
    if text is not None:
        return clean(text), "server"
    return clean(transcribe_via_cli(path)), "cli"


def paste(text: str) -> None:
    """Clipboard + synthetic Cmd+V. Same path Voicy/Wispr/VoiceInk use."""
    pb = NSPasteboard.generalPasteboard()
    saved = pb.stringForType_(NSPasteboardTypeString)

    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)

    for is_down in (True, False):
        event = CGEventCreateKeyboardEvent(None, KEYCODE_V, is_down)
        CGEventSetFlags(event, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, event)
        time.sleep(0.01)

    # Restoring too early races the target app's paste handler.
    if saved is not None:
        def restore():
            pb.clearContents()
            pb.setString_forType_(saved, NSPasteboardTypeString)

        threading.Timer(CLIPBOARD_RESTORE_DELAY, restore).start()


def responsible_app() -> str | None:
    """Walk up the process tree to the owning .app bundle.

    macOS attributes TCC grants to the responsible process — the ancestor .app,
    not the python binary. Guessing this wrong is the single most common reason
    the grant "doesn't take".
    """
    # Start at the parent: our own process resolves to the interpreter's
    # Python.framework/Resources/Python.app shim, which is never the grantee.
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


def preflight(prompt_for_access: bool = False) -> bool:
    """Check the two permissions that silently break this pipeline.

    Failure mode without Accessibility: CGEventPost returns success and simply
    does nothing. No error, no exception. Worth checking explicitly.
    """
    mic_status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
    mic_ok = mic_status == 3
    print(f"  microphone:    {'OK' if mic_ok else f'NOT GRANTED (status {mic_status})'}")

    if prompt_for_access:
        opts = {kAXTrustedCheckOptionPrompt: True}
        ax_ok = AXIsProcessTrustedWithOptions(opts)
    else:
        ax_ok = AXIsProcessTrusted()
    print(f"  accessibility: {'OK' if ax_ok else 'NOT GRANTED'}")

    if not ax_ok:
        app = responsible_app()
        print()
        print("  Accessibility controls synthetic keystrokes. Without it, paste")
        print("  silently does nothing — no error, no exception.")
        print()
        if app:
            print(f"  Grant it to:  {app}")
            print("  (the app that owns this process — NOT python, and not whatever")
            print("   window happens to be frontmost)")
        else:
            print("  Grant it to the app that owns this process.")
        print()
        print("    System Settings > Privacy & Security > Accessibility")
        print()
        print("  Then FULLY QUIT and reopen that app — the grant is read at launch.")

    return mic_ok and ax_ok


def frontmost_app() -> str:
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app.localizedName() if app else "<unknown>"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--countdown", type=int, default=5,
                    help="seconds to switch focus to a text field before pasting")
    ap.add_argument("--no-paste", action="store_true",
                    help="stop after transcription; skip the injection test")
    ap.add_argument("--check", action="store_true",
                    help="check permissions and exit")
    ap.add_argument("--request-access", action="store_true",
                    help="trigger the macOS Accessibility permission dialog")
    args = ap.parse_args()

    if args.check or args.request_access:
        print("[preflight]")
        return 0 if preflight(prompt_for_access=args.request_access) else 1

    if not MODEL.exists():
        print(f"model not found: {MODEL}", file=sys.stderr)
        return 1

    print("[preflight]")
    ready = preflight()
    if not ready and not args.no_paste:
        print("\nRun with --no-paste to test capture+transcription anyway.")
        return 1

    print("[1/3] capture")
    t0 = time.perf_counter()
    audio = record(args.seconds)
    write_wav(audio, WAV)

    print("[2/3] transcribe")
    t1 = time.perf_counter()
    text, via = transcribe(WAV)
    t2 = time.perf_counter()
    print(f"  {t2 - t1:.2f}s via {via} for {args.seconds:.0f}s audio "
          f"({args.seconds / (t2 - t1):.1f}x realtime)")
    if via == "cli":
        print("  (whisper-server not running — start it for ~2x lower latency)")
    print(f"  -> {text!r}")

    if not text:
        print("  no text produced; stopping before paste test.")
        return 1

    if args.no_paste:
        return 0

    print("[3/3] inject")
    for remaining in range(args.countdown, 0, -1):
        print(f"  focus a text field... {remaining}", end="\r", flush=True)
        time.sleep(1)
    print(f"  pasting into: {frontmost_app()}          ")
    paste(text)
    time.sleep(CLIPBOARD_RESTORE_DELAY + 0.2)

    print(f"\ndone in {time.perf_counter() - t0:.2f}s total")
    print("If the text appeared in the focused field, the whole path works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
