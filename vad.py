"""Energy-based silence trimming.

Not a full VAD — it only trims leading and trailing silence, which is what
push-to-talk actually needs (you press slightly early and release slightly
late). Two wins: less audio to transcribe, and no trailing silence for whisper
to hallucinate into.

Deliberately not silero-vad: that's a torch dependency and ~30ms of inference
to save ~20ms of transcription. Energy thresholding is free.
"""

import numpy as np

FRAME_MS = 20

#  Speech frames sit well above this fraction of the utterance's own peak, so
#  scaling to the peak keeps quiet recordings intact. The floor stops a
#  silent capture from being read as one very quiet speaker.
PEAK_FRACTION = 0.08
ABSOLUTE_FLOOR = 0.0025


def trim(
    audio: np.ndarray,
    sample_rate: int,
    threshold: float = 0.012,
    pad_ms: int = 150,
) -> tuple[np.ndarray, float]:
    """Returns (trimmed, seconds_removed). Returns input unchanged if no speech
    is found — better to send questionable audio than to send nothing."""
    if audio.size == 0:
        return audio, 0.0

    mono = audio.reshape(-1) if audio.ndim == 1 else audio[:, 0]
    frame = max(1, int(sample_rate * FRAME_MS / 1000))
    n_frames = len(mono) // frame
    if n_frames < 2:
        return audio, 0.0

    frames = mono[: n_frames * frame].reshape(n_frames, frame)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))

    # Adaptive threshold. A fixed absolute cutoff silently eats speech from a
    # quiet source: a 4.2s capture peaking at 0.058 got trimmed to 1.0s and
    # "Testing shout end to end from the menu bar app" transcribed as "Test."
    # Never demand more than a fraction of this utterance's own loudest frame,
    # and keep a floor so pure silence isn't treated as speech.
    peak_rms = float(rms.max())
    effective = max(ABSOLUTE_FLOOR, min(threshold, peak_rms * PEAK_FRACTION))

    voiced = np.flatnonzero(rms >= effective)
    if voiced.size == 0:
        return audio, 0.0

    pad = int(sample_rate * pad_ms / 1000)
    start = max(0, voiced[0] * frame - pad)
    end = min(len(mono), (voiced[-1] + 1) * frame + pad)

    removed = (len(mono) - (end - start)) / sample_rate
    return audio[start:end], removed


#  Whisper hallucinates confidently on near-silence — three silent captures in
#  testing produced "Decided to kill Trump." and "TPSA can't get the Utah."
#  which would have been pasted into whatever had focus. An energy gate is the
#  cheap, reliable defence: if there is no sustained speech-level audio, never
#  send it to the model at all.
#
#  Measured on this mic: a quiet room peaks at frame-RMS 0.0058 with ZERO
#  frames above 0.008, while conversational speech holds 1820ms above it.
SPEECH_FLOOR = 0.008
MIN_SPEECH_MS = 120
NOISE_PERCENTILE = 10
NOISE_MULTIPLE = 3.0


def has_speech(audio: np.ndarray, sample_rate: int) -> bool:
    """True if the clip contains enough speech-level audio to be worth sending.

    The floor adapts upward in a noisy room by referencing the clip's own quiet
    frames (10th percentile), which stay low even during speech because of the
    pauses between words. Scaling off the *median* would fail — speech drags the
    median up and the gate would reject real dictation.
    """
    if audio.size == 0:
        return False

    mono = audio.reshape(-1) if audio.ndim == 1 else audio[:, 0]
    frame = max(1, int(sample_rate * FRAME_MS / 1000))
    n_frames = len(mono) // frame
    if n_frames < 2:
        return False

    frames = mono[: n_frames * frame].reshape(n_frames, frame)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))

    noise = float(np.percentile(rms, NOISE_PERCENTILE))
    floor = max(SPEECH_FLOOR, noise * NOISE_MULTIPLE)
    speech_ms = int((rms >= floor).sum() * FRAME_MS)
    return speech_ms >= MIN_SPEECH_MS
