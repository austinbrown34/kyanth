"""Benchmark whisper models on accuracy (WER) and latency.

Uses macOS `say` to synthesize reference clips. Synthetic speech is cleaner
than real dictation, so absolute WER here is optimistic — but the *ranking*
between models holds, which is what the choice depends on.

Run:  uv run bench.py
"""

import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent
SCRATCH = ROOT / ".scratch" / "bench"
PORT = 8179  # separate from the live daemon's server

MODELS = [
    "models/ggml-base.en.bin",
    "models/ggml-small.en.bin",
    "models/ggml-large-v3-turbo-q5_0.bin",
]

# Mix of plain prose and the technical jargon that actually breaks dictation.
CASES = [
    "The quick brown fox jumps over the lazy dog near the river bank.",
    "Let's refactor the authentication middleware before the deploy on Friday.",
    "Run kubectl get pods and check whether the Postgres replica is healthy.",
    "I pushed the TypeScript changes to GitHub but the CI pipeline is failing.",
    "Can you review the pull request and leave comments on the API schema.",
    "We need to migrate from Redis to Postgres for the session store.",
    "The latency budget is three hundred milliseconds end to end.",
    "Anthropic released a new model and the tokenizer changed slightly.",
]


def normalize(s: str) -> list[str]:
    keep = "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in s)
    return keep.split()


def wer(ref: str, hyp: str) -> float:
    """Levenshtein distance over words / reference length."""
    r, h = normalize(ref), normalize(hyp)
    if not r:
        return 0.0
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1] / len(r)


def synth(text: str, path: Path) -> None:
    aiff = path.with_suffix(".aiff")
    subprocess.run(["say", "-o", str(aiff), text], check=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
         "-ar", "16000", "-ac", "1", str(path)],
        check=True,
    )
    aiff.unlink()


def start_server(model: str):
    proc = subprocess.Popen(
        ["whisper-server", "-m", model, "--host", "127.0.0.1", "--port", str(PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    import socket
    for _ in range(240):
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", PORT)) == 0:
                return proc
        time.sleep(0.25)
    proc.kill()
    raise RuntimeError(f"server for {model} never came up")


def main() -> int:
    SCRATCH.mkdir(parents=True, exist_ok=True)

    print("synthesizing reference clips...")
    clips = []
    for i, text in enumerate(CASES):
        p = SCRATCH / f"case{i}.wav"
        if not p.exists():
            synth(text, p)
        clips.append((text, p))

    results = {}
    for model in MODELS:
        if not (ROOT / model).exists():
            print(f"skip {model} (not downloaded)")
            continue
        name = Path(model).stem.replace("ggml-", "")
        print(f"\n=== {name} ===")
        proc = start_server(model)
        session = requests.Session()
        try:
            # discard first request: warms caches
            with open(clips[0][1], "rb") as f:
                session.post(f"http://127.0.0.1:{PORT}/inference",
                             files={"file": f}, data={"response_format": "text"},
                             timeout=120)

            errs, lats = [], []
            for ref, path in clips:
                t0 = time.perf_counter()
                with open(path, "rb") as f:
                    r = session.post(f"http://127.0.0.1:{PORT}/inference",
                                     files={"file": f},
                                     data={"response_format": "text"}, timeout=120)
                lat = (time.perf_counter() - t0) * 1000
                hyp = r.text.strip()
                e = wer(ref, hyp)
                errs.append(e)
                lats.append(lat)
                flag = "" if e == 0 else f"   <-- {hyp}"
                print(f"  wer {e:5.1%}  {lat:6.0f}ms{flag}")

            results[name] = (sum(errs) / len(errs), sum(lats) / len(lats))
        finally:
            proc.kill()
            proc.wait()

    print("\n" + "=" * 58)
    print(f"{'model':<28} {'mean WER':>10} {'mean latency':>16}")
    print("-" * 58)
    for name, (e, lat) in sorted(results.items(), key=lambda kv: kv[1][0]):
        print(f"{name:<28} {e:>9.1%} {lat:>13.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
