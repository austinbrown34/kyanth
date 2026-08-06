"""Text post-processing: custom vocabulary and per-app formatting.

Whisper exposes no vocabulary-injection API, so term correction happens after
transcription. In practice this fixes most jargon errors, which is the single
biggest accuracy gap for technical dictation.
"""

import re
from dataclasses import dataclass

#  whisper.cpp emits these bracket tokens for non-speech; never inject them.
NOISE_TOKENS = {"[BLANK_AUDIO]", "[SILENCE]", "(silence)", "[MUSIC]", "[NOISE]",
                "[ Silence ]", "(upbeat music)", "[sound]"}


@dataclass
class Profile:
    capitalize_first: bool = True
    strip_trailing_period: bool = False


class Vocabulary:
    """Whole-phrase, case-insensitive replacement.

    Longest phrase first, so "cube control" wins over a hypothetical "cube".
    One combined regex means a single pass and no risk of an earlier
    replacement's output being rewritten by a later rule.
    """

    def __init__(self, replacements: dict[str, str], protect: list[str] | None = None):
        self.protect = set(protect or [])
        pairs = [
            (src, dst) for src, dst in (replacements or {}).items()
            if src.lower() != dst.lower() or src != dst
        ]
        self._map = {src.lower(): dst for src, dst in pairs}
        if not pairs:
            self._re = None
            return
        ordered = sorted(self._map, key=len, reverse=True)
        self._re = re.compile(
            r"\b(" + "|".join(re.escape(p) for p in ordered) + r")\b",
            re.IGNORECASE,
        )

    def starts_with_term(self, text: str) -> bool:
        """True if `text` begins with a replacement output, meaning its casing
        was chosen deliberately and must not be overridden."""
        return any(text.startswith(dst) for dst in self._map.values())

    def apply(self, text: str) -> str:
        if not self._re or not text:
            return text

        def sub(m: re.Match) -> str:
            found = m.group(0)
            if found in self.protect:
                return found
            return self._map[found.lower()]

        return self._re.sub(sub, text)


#  Whisper narrates non-speech audio as a parenthesised description —
#  "(dog barking)", "(upbeat music)", "[door closes]". These are never dictation
#  and must not be pasted. A description occupies the whole output, so only a
#  fully-enclosed result is dropped; a genuine "(like this)" mid-sentence stays.
_SOUND_DESCRIPTION = re.compile(r"^[\(\[\*].{0,60}[\)\]\*][.!?]?$")


def strip_noise(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines()]
    kept = [ln for ln in lines if ln and ln not in NOISE_TOKENS]
    out = " ".join(kept).strip()
    # whisper sometimes inlines a bracket token mid-line
    out = re.sub(r"\[(BLANK_AUDIO|SILENCE|MUSIC|NOISE)\]", "", out, flags=re.I)
    out = re.sub(r"\s+", " ", out).strip()

    if _SOUND_DESCRIPTION.match(out):
        return ""
    return out


def apply_profile(text: str, profile: Profile, fixed_case: bool = False) -> str:
    """fixed_case: the text starts with a vocabulary term whose casing is
    authoritative (`kubectl`, `iPhone`), so leave the first letter alone."""
    if not text:
        return text
    if profile.strip_trailing_period:
        # Only a lone trailing period — leave "..." and "?"/"!" alone.
        text = re.sub(r"(?<!\.)\.$", "", text)
    if fixed_case:
        return text
    if profile.capitalize_first:
        text = text[0].upper() + text[1:]
    else:
        # Don't lowercase an acronym or a proper noun we just fixed up.
        if len(text) > 1 and text[1].islower():
            text = text[0].lower() + text[1:]
    return text


def process(raw: str, vocab: Vocabulary, profile: Profile) -> str:
    replaced = vocab.apply(strip_noise(raw))
    return apply_profile(replaced, profile, fixed_case=vocab.starts_with_term(replaced))
