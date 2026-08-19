"""Does contextual prompting help more than it hurts?

Feature 01 biases Whisper's decoder toward terms read off the screen. Biasing
is not free: raising the probability of "AuroraCache" lowers everything it
competes with, so a term list can make a transcription that was already
correct become wrong. That is the failure this measures, because it is the one
that would ship silently — a name arriving correctly is visible, a common word
quietly corrupted is not.

The headline number is REGRESSIONS: words the baseline got right and the
contextual run got wrong. Improvements are the reason to ship; regressions are
the reason not to, and they are weighted accordingly.

Four conditions per clip:

    baseline   no prompt at all — what ships today
    clean      only terms genuinely present in the sentence
    noisy      clean terms plus real OCR misreads harvested from this machine
               (SEOMENTS, intelepronpter, sanple_rate ...). This is the
               adversarial case: the filters are not perfect, so the question
               is what a bad term list actually costs.
    decoy      terms that sound like ordinary words in the sentence, which is
               how "Kyanth" could eat every "client"

Caveat that limits every number here: clips come from macOS `say`, which is
unrealistically clean and has no accent, hesitation or background noise. This
harness measures the DIRECTION and relative size of an effect, not an absolute
error rate. Re-run against real recordings before treating a margin as settled.

    uv run bench_context.py
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

SERVER = "http://127.0.0.1:8178/inference"

#  Real misreads, taken verbatim from OCR of windows on this machine. Not
#  invented: inventing plausible noise would test the wrong distribution.
OCR_NOISE = ["SEOMENTS", "SUNU", "intelepronpter", "fron", "apil", "cursar",
             "vords", "sanple_rate", "tenpo_factor", "dowserver", "Lapil"]

#  (sentence, terms genuinely in it, decoys that sound like words in it)
#  Sentences carrying terms the feature is meant to fix.
TARGETED = [
    ("Elena Marquez confirmed that AuroraCache is blocking the ZephyrSync rollout",
     ["Elena", "Marquez", "AuroraCache", "ZephyrSync"]),
    ("Kyanth pastes the text into the focused field of whatever app you are using",
     ["Kyanth"]),
    ("The ZephyrSync migration needs review before we touch AuroraCache",
     ["ZephyrSync", "AuroraCache"]),
    ("Ask Marquez whether Project Atlas depends on that service",
     ["Marquez", "Atlas"]),
]

#  Ordinary sentences containing NO term the prompt could legitimately fix.
#  These are the regression probe: with a contaminated term list, anything that
#  changes here is pure damage. Weighted heavily because this is the case the
#  user is in almost all of the time.
NEUTRAL = [
    "Move the launch to Thursday so QA gets a full day with the signed build",
    "The client asked for a refund on Tuesday afternoon",
    "Please review the migration script before I run it against staging",
    "Add an index on the created column because the dashboard does a full scan",
    "We should call the client back before the meeting starts",
    "The parser should fail loudly on a malformed header instead of skipping",
    "Let me know if the deploy finished or if it is still waiting on approval",
    "I think the retry logic needs jitter otherwise every client wakes at once",
    "Can you take a look at the failing test in the payments module",
    "The design review is on Wednesday and the mockups are already shared",
    "Send me the summary once you have finished reading the report",
    "There is a rounding error in the invoice total for annual plans",
    "We agreed to postpone the rewrite until the metrics look stable",
    "The cache is warming slowly which makes the first request expensive",
    "Remind me to rotate the credentials before the end of the quarter",
    "Nothing in the logs explains why the worker stopped consuming",
    "It would help to see the request headers for the failing calls",
    "The onboarding flow drops people at the permissions step",
]

CORPUS = ([(s, terms, []) for s, terms in TARGETED] +
          [(s, [], []) for s in NEUTRAL])

_TOK = re.compile(r"[a-z0-9']+")


def tokens(text):
    return _TOK.findall((text or "").lower())


def say(text, path):
    subprocess.run(["say", "-o", str(path.with_suffix(".aiff")), text],
                   check=True, capture_output=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1",
                    str(path.with_suffix(".aiff")), str(path)],
                   check=True, capture_output=True)


def transcribe(path, prompt, session):
    data = {"response_format": "text"}
    if prompt:
        data["prompt"] = prompt
    with open(path, "rb") as f:
        r = session.post(SERVER, files={"file": f}, data=data, timeout=60)
    r.raise_for_status()
    return r.text.strip()


def align(truth, got):
    """Which reference words survived, by real alignment rather than position.

    Positional comparison is wrong here and wrong in a way that flatters the
    result: "Aurora Cash" is two tokens where "AuroraCache" is one, so a single
    correct merge shifts every later word and scores as a wall of errors and
    improvements at once. SequenceMatcher aligns properly, so only words that
    actually changed are counted.
    """
    from difflib import SequenceMatcher

    t, g = tokens(truth), tokens(got)
    correct = [False] * len(t)
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, t, g, autojunk=False).get_opcodes():
        if tag == "equal":
            for i in range(i1, i2):
                correct[i] = True
    return t, correct


def main():
    session = requests.Session()
    try:
        session.post(SERVER, files={"file": ("x", b"")}, timeout=3)
    except Exception:
        print("model server not reachable on 127.0.0.1:8178", file=sys.stderr)
        return 1

    tmp = Path(tempfile.mkdtemp())
    totals = {}
    print(f"{'condition':10} {'target hits':>12} {'regressions':>12} "
          f"{'improvements':>13} {'net':>6} {'on neutral':>12}")
    print("-" * 72)

    per_clip = []
    for idx, (sentence, real, decoys) in enumerate(CORPUS):
        wav = tmp / f"c{idx}.wav"
        say(sentence, wav)
        conditions = {
            "baseline": "",
            "clean": ", ".join(real) if real else "",
            "noisy": ", ".join(real + OCR_NOISE),
            "decoy": ", ".join(real + decoys) if (real or decoys) else "",
        }
        got = {}
        for name, terms in conditions.items():
            prompt = f"Vocabulary: {terms}." if terms else ""
            got[name] = transcribe(wav, prompt, session)
        per_clip.append((sentence, real, got))

    for cond in ("clean", "noisy", "decoy"):
        reg = imp = hits = base_hits = 0
        neutral_reg = 0
        for sentence, real, got in per_clip:
            _t, base_ok = align(sentence, got["baseline"])
            _t2, cond_ok = align(sentence, got[cond])
            for b, c in zip(base_ok, cond_ok):
                if b and not c:
                    reg += 1
                    if not real:
                        neutral_reg += 1
                elif c and not b:
                    imp += 1
            for term in real:
                base_hits += term.lower() in got["baseline"].lower()
                hits += term.lower() in got[cond].lower()
        totals[cond] = (hits, reg, imp, neutral_reg)
        print(f"{cond:10} {hits:>6} / {base_hits:<3} {reg:>12} {imp:>13} "
              f"{imp - reg:>+6} {neutral_reg:>12}")

    print("\n  per-clip detail where the contextual run differed from baseline:")
    for sentence, real, got in per_clip:
        for cond in ("clean", "noisy", "decoy"):
            if got[cond] != got["baseline"]:
                print(f"\n    said : {sentence}")
                print(f"    base : {got['baseline']}")
                print(f"    {cond:5}: {got[cond]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
