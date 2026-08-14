"""Short audio cues.

The menu-bar icon is the only state indicator Kyanth has, and on a full menu bar
macOS hides it with no warning — leaving no way to tell "recording" from
"ignored your tap" from "broken". These cues make state audible instead.

macOS system sounds are unusable here: the shortest (Tink) is 0.56s, which
bleeds well into the recording. These are ~70ms with a fade, generated once
into the runtime directory and cached.

Pitch carries the meaning, so the cues are distinguishable without looking:
  start     rising     — we are listening
  stop      falling    — pasted into the focused field
  clipboard two rising — nothing to paste into; text is on the clipboard
  ignored low blip  — that press did not count
  error   two lows  — something failed
"""

import math
import struct
import wave
from pathlib import Path

from AppKit import NSSound

RATE = 44_100

#  name -> (start_hz, end_hz, seconds, repeats)
CUES = {
    "start":   (660.0, 990.0, 0.070, 1),
    "stop":    (880.0, 620.0, 0.070, 1),
    "ignored": (320.0, 300.0, 0.055, 1),
    "error":   (300.0, 240.0, 0.090, 2),
    #  distinct from "stop": the text is waiting on the clipboard,
    #  not already in a document
    "clipboard": (740.0, 1040.0, 0.055, 2),
}


def _render(path: Path, f0: float, f1: float, secs: float, repeats: int) -> None:
    n = int(RATE * secs)
    gap = int(RATE * 0.045)
    frames = []
    for r in range(repeats):
        phase = 0.0
        for i in range(n):
            t = i / n
            freq = f0 + (f1 - f0) * t
            phase += 2.0 * math.pi * freq / RATE
            # Raised-cosine envelope: no click at either edge.
            env = 0.5 - 0.5 * math.cos(2.0 * math.pi * min(t, 1.0))
            frames.append(int(math.sin(phase) * env * 26000))
        if r != repeats - 1:
            frames.extend([0] * gap)

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", s) for s in frames))


class Cues:
    """Preloaded NSSounds. Loading on demand would add file I/O to the hotkey
    path, which must stay fast — a slow event-tap callback gets disabled."""

    def __init__(self, directory: Path, enabled: bool = True, volume: float = 0.35):
        self.enabled = enabled
        self.sounds = {}
        for name, (f0, f1, secs, repeats) in CUES.items():
            path = directory / f"cue-{name}.wav"
            if not path.exists():
                _render(path, f0, f1, secs, repeats)
            sound = NSSound.alloc().initWithContentsOfFile_byReference_(str(path), True)
            if sound is not None:
                sound.setVolume_(volume)
                self.sounds[name] = sound

    @property
    def lead_ms(self) -> int:
        """How much audio to discard after the start cue, so the cue itself
        isn't transcribed. Zero when cues are off."""
        return 110 if self.enabled else 0

    def play(self, name: str) -> None:
        if not self.enabled:
            return
        sound = self.sounds.get(name)
        if sound is None:
            return
        # stop() first so rapid presses retrigger instead of being dropped
        # while the previous copy is still playing.
        sound.stop()
        sound.play()

    def set_volume(self, volume: float) -> None:
        for sound in self.sounds.values():
            sound.setVolume_(volume)
