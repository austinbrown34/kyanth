"""The initial prompt handed to Whisper before it decodes.

Whisper accepts a short piece of "previous context" and conditions its decoder
on it. That is the only place term knowledge can be injected *while the audio
is still available* — which is the whole reason this exists.

The vocabulary layer in `postprocess` runs after decoding, on a lossy artifact.
By then the model has already chosen "client" and the acoustics that would have
distinguished it from "Kyanth" are gone, so the only repair available is exact
string replacement — and replacing every "client" would wreck the sentences
where the user genuinely said client. Measured on base.en:

    no prompt   "I am testing Kianthen to end from the menu bar app."
    prompted    "I am testing Kyanth then to end from the menu bar app."

and, importantly, with the same prompt active:

    "The client asked for a refund"  ->  "The client asked for a refund"

Biasing raises a term's likelihood; it does not force it. That asymmetry is
what makes this safe where blanket replacement is not. The measured cost is
about 10 ms.

Whisper's context window for this is 224 tokens and it is a hard limit — the
model silently keeps only the tail, so an over-long prompt does not fail, it
just quietly drops whatever mattered most. Everything here is budgeted.
"""

import re
from collections import Counter

#  Conservative: ~4 characters per token, against a 224-token window, leaving
#  room for the model's own bookkeeping. Overshooting is silent, so under-fill.
MAX_CHARS = 700

#  Terms are emitted as a bare comma list rather than an instruction. Whisper
#  is not instruction-following — it continues text. A list of proper nouns
#  reads to it as "the previous sentence contained these", which is exactly
#  the conditioning we want. Telling it to "please spell Kyanth correctly"
#  would just make it likely to transcribe that sentence.
LEAD = "Vocabulary: "

#  The app's own name, always. It is the one term guaranteed to be said to a
#  dictation tool and guaranteed to be absent from the model's training data,
#  and it is not something a user should have to discover and configure. It
#  also cannot be fixed after the fact: base.en hears "client".
BASE_TERMS = ("Kyanth",)

#  A learned term has to clear this bar before it earns a place in the budget.
MIN_OCCURRENCES = 3
MIN_LENGTH = 4

#  Common words that survive the proper-noun filter but carry no information.
STOP = {
    "The", "This", "That", "There", "These", "Those", "Then", "They", "Their",
    "What", "When", "Where", "Which", "While", "Would", "Could", "Should",
    "And", "But", "For", "Not", "You", "Your", "It's", "I'm", "We're",
    "Just", "Like", "Have", "Here", "Been", "Because", "About", "After",
    "Also", "Only", "Some", "Same", "Something", "Someone", "Still", "Sure",
    "Okay", "Yeah", "Yes", "One", "Two", "Now", "Can", "Let", "Make", "Need",
    "Want", "Know", "Think", "Going", "Get", "Got", "Give", "Take", "Look",
}

_WORD = re.compile(r"\b[A-Za-z][A-Za-z0-9._+#-]{2,}\b")
#  Sentence starts, so the first word of each can be excluded from the
#  "is it capitalised?" test.
_SENTENCE = re.compile(r"(?:^|[.!?]\s+|\n+)\s*")


def _distinctive(word):
    """True for tokens that are informative regardless of position: dotted or
    hyphenated names, anything with a digit, camelCase, ALLCAPS."""
    return (any(c in word for c in "._+#-")
            or any(c.isdigit() for c in word)
            or word[1:] != word[1:].lower())


def learned_terms(entries, limit=40):
    """Terms the user demonstrably says, mined from their own history.

    This is the honest version of "pick up context clues": rather than asking
    the user to predict what the model will mishear, it watches what they
    actually dictate. History holds *post-correction* text, so anything the
    vocabulary already fixed appears here spelled correctly — the two layers
    feed each other.

    Capitalisation only counts MID-SENTENCE. Every sentence starts with a
    capital, so a naive uppercase test learns "However", "Currently" and
    "Show" — ordinary words that burn budget and bias the decoder toward
    nothing useful.
    """
    counts = Counter()
    for e in entries:
        text = getattr(e, "text", "") or ""
        for sentence in _SENTENCE.split(text):
            first = True
            for word in _WORD.findall(sentence):
                lead, first = first, False
                if word in STOP or len(word) < MIN_LENGTH:
                    continue
                if _distinctive(word):
                    counts[word] += 1
                elif word[0].isupper() and not lead:
                    counts[word] += 1
    return [w for w, n in counts.most_common(limit) if n >= MIN_OCCURRENCES]


def configured_terms(vocab):
    """The right-hand side of the user's replacement rules.

    Those are the spellings they have already told us are correct, which makes
    them the highest-confidence terms available — worth spending budget on
    before anything mined from history.
    """
    terms = []
    for dst in getattr(vocab, "_map", {}).values():
        if dst not in terms:
            terms.append(dst)
    for word in getattr(vocab, "protect", ()) or ():
        if word not in terms:
            terms.append(word)
    return terms


def build(vocab=None, entries=(), app_name="", extra=(), screen=()):
    """Assemble the prompt, highest-confidence terms first.

    Ordering matters because truncation happens at the tail: the app name and
    what is on screen survive, and configured then mined terms fill whatever
    budget is left.
    """
    seen, terms = set(), []

    def add(items):
        for t in items:
            key = t.lower()
            if t and key not in seen:
                seen.add(key)
                terms.append(t)

    add(BASE_TERMS)                             # always, unconfigured
    #  What is on screen right now outranks both config and history: it is the
    #  only source that can know a name the user has never dictated before,
    #  which is the case the other two structurally cannot cover.
    add(screen)
    add(extra)                                  # per-app, from config
    add(configured_terms(vocab) if vocab else ())
    add(learned_terms(entries))

    if not terms:
        return ""

    out = LEAD
    for i, term in enumerate(terms):
        piece = term if i == 0 else ", " + term
        if len(out) + len(piece) + 1 > MAX_CHARS:
            break
        out += piece
    return out + "."


def merge(base, screen):
    """Splice this utterance's screen terms into an already-built prompt.

    Screen terms go directly after the app's own name, because truncation
    happens at the tail and a name that is on screen right now is the most
    likely thing about to be said. Rebuilding the whole prompt per dictation
    would mean re-mining hundreds of history entries on the paste path.
    """
    if not screen:
        return base
    body = base[len(LEAD):].rstrip(".") if base.startswith(LEAD) else ""
    existing = [t.strip() for t in body.split(",") if t.strip()]
    seen = {t.lower() for t in existing}
    head = [t for t in BASE_TERMS if t.lower() in seen]
    fresh = [t for t in screen if t.lower() not in seen]
    rest = [t for t in existing if t not in head]

    out = LEAD
    for i, term in enumerate(head + fresh + rest):
        piece = term if i == 0 else ", " + term
        if len(out) + len(piece) + 1 > MAX_CHARS:
            break
        out += piece
    return out + "." if len(out) > len(LEAD) else ""
