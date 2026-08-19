"""Reading the screen the user is talking about.

Feature 01. The point is to resolve names Whisper has never heard — a
colleague in a thread, a service in a dashboard — by feeding them to the
decoder as prompt terms *before* it commits. `prompting` already does this
from history; history can only know words you have already said, so it cannot
help the first time you say "Elena Marquez".

Why OCR rather than Accessibility, which would be cheaper and needs no extra
permission: measured across the running apps on this machine, AX returns
nothing for cmux, one string for Notes, one for reticula, and is unreadable
for VS Code, iTerm2, Messages and TextEdit. Those are the top paste
destinations in the real history. Electron and terminal apps simply do not
expose their content tree, and they are most of the work. AX is kept as a
free supplement where it is rich (Finder, Preview, Xcode), not as the source.

Timing is the whole trick. Capture is 73 ms and OCR of a downscaled window is
about 685 ms, which would be ruinous on the 200 ms paste path — so none of it
happens there. It runs on a worker thread from the moment the key goes DOWN,
while the user is still speaking, and the result is collected at key-up. An
utterance long enough to be worth dictating is long enough to hide this
entirely.

Measured scaling, 3456x2168 retina window, fast recognition:

    3456 px   867 ms   234 lines
    1600 px   784 ms   205 lines
    1100 px   685 ms   165 lines     <- chosen
     800 px   497 ms    87 lines     <- loses half the text

Greyscale costs 6 ms and removes two thirds of the bytes; text recognition has
no use for colour.
"""

import re
import threading
import time

#  Never read these, whatever the user has enabled. Password managers and the
#  keychain are the obvious case; a browser in private mode is the ambiguous
#  one and is left to the user's own exclusions.
NEVER_READ = {
    "1Password", "1Password 7", "1Password 8", "Keychain Access", "Bitwarden",
    "LastPass", "Dashlane", "Enpass", "KeePassXC", "Proton Pass", "Secretive",
    "System Settings", "Keychain", "Passwords",
}

#  Below this the OCR starts dropping half the lines; above it, latency grows
#  with no more text recovered. See the table above.
OCR_WIDTH = 1100

#  Recognition levels: 0 fast, 1 accurate. Accurate costs roughly 2.5x for
#  marginally better glyphs, and a term list tolerates the odd bad character
#  far better than it tolerates arriving after the user has stopped talking.
FAST = 0

MAX_TERMS = 40

#  Below this, Vision is guessing. Measured: the sub-0.9 band is where the
#  unreadable glyph runs live.
MIN_CONFIDENCE = 0.9


def screen_capture_permitted():
    """True when this process may read window pixels.

    Never triggers the system prompt — asking is the setup window's job, not
    something to do behind a dictation.
    """
    try:
        from Quartz import CGPreflightScreenCaptureAccess
        return bool(CGPreflightScreenCaptureAccess())
    except Exception:
        return False


def request_screen_capture():
    """Ask macOS for the grant. Returns immediately; the user answers a dialog."""
    try:
        from Quartz import CGRequestScreenCaptureAccess
        return bool(CGRequestScreenCaptureAccess())
    except Exception:
        return False


def _frontmost_window():
    """(window_id, app_name) for the focused app's largest on-screen window."""
    from AppKit import NSWorkspace
    from Quartz import (CGWindowListCopyWindowInfo, kCGNullWindowID,
                        kCGWindowListOptionOnScreenOnly)

    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return None, ""
    name = app.localizedName() or ""
    pid = app.processIdentifier()
    best, area = None, 0
    for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly,
                                        kCGNullWindowID) or ():
        if w.get("kCGWindowOwnerPID") != pid:
            continue
        b = w.get("kCGWindowBounds") or {}
        a = b.get("Width", 0) * b.get("Height", 0)
        #  Skip the overlay and other chrome-sized panels.
        if a > area and b.get("Width", 0) > 240 and b.get("Height", 0) > 160:
            best, area = w.get("kCGWindowNumber"), a
    return best, name


def _downscale_grey(src, target_w):
    import Quartz
    from Quartz import (CGBitmapContextCreate, CGBitmapContextCreateImage,
                        CGColorSpaceCreateDeviceGray, CGContextDrawImage, CGRectMake)
    w0 = Quartz.CGImageGetWidth(src)
    h0 = Quartz.CGImageGetHeight(src)
    if w0 <= target_w or not w0 or not h0:
        return src
    scale = target_w / float(w0)
    w, h = int(w0 * scale), int(h0 * scale)
    ctx = CGBitmapContextCreate(None, w, h, 8, 0, CGColorSpaceCreateDeviceGray(), 0)
    if ctx is None:
        return src
    CGContextDrawImage(ctx, CGRectMake(0, 0, w, h), src)
    return CGBitmapContextCreateImage(ctx) or src


def read_window_text(deadline=None):
    """OCR the focused window. Returns ([(confidence, line)], app_name, window_id).

    Confidence is carried out rather than discarded because it is the only
    thing separating a real word from a glyph run. The window id comes out so
    the caller can prove the terms belong to the place the text will land.
    Never raises."""
    try:
        import Vision
        from Quartz import (CGRectNull, CGWindowListCreateImage,
                            kCGWindowImageBoundsIgnoreFraming,
                            kCGWindowListOptionIncludingWindow)
    except Exception:
        return [], "", None

    wid, app_name = _frontmost_window()
    if wid is None or app_name in NEVER_READ:
        return [], app_name, None
    if deadline and time.monotonic() > deadline:
        return [], app_name, wid

    img = CGWindowListCreateImage(CGRectNull, kCGWindowListOptionIncludingWindow,
                                  wid, kCGWindowImageBoundsIgnoreFraming)
    if img is None:                       # permission revoked, or window gone
        return [], app_name, wid

    small = _downscale_grey(img, OCR_WIDTH)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(small, {})
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(FAST)
    #  Language correction "fixes" unusual names into common words, which is
    #  the exact opposite of what this is for.
    req.setUsesLanguageCorrection_(False)
    ok, _err = handler.performRequests_error_([req], None)
    if not ok:
        return [], app_name, wid
    lines = []
    for r in req.results() or ():
        cands = r.topCandidates_(1)
        if cands:
            lines.append((cands[0].confidence(), cands[0].string()))
    return lines, app_name, wid


_WORD = re.compile(r"\b[A-Za-z][A-Za-z0-9._+#'-]{2,}\b")

#  macOS ships a 235k-word list. It is used as a REJECT list: an ordinary
#  English word is exactly what Whisper already gets right, and spending the
#  224-token prompt budget on "target", "help" and "with" pushes out the
#  project names that are the entire point.
_DICT_PATH = "/usr/share/dict/words"
_dictionary = None


def _words():
    global _dictionary
    if _dictionary is None:
        try:
            with open(_DICT_PATH) as f:
                _dictionary = {w.strip().lower() for w in f if w.strip()}
        except OSError:
            _dictionary = set()          # filter degrades, never fails
    return _dictionary


def _ordinary(word):
    """True for words the model already handles, including the inflections the
    system dictionary happens not to list.

    Without the stem checks a browser window yields "it's", "wasn't", "weeks"
    and "runs" — all common, all absent from /usr/share/dict/words, all noise.
    """
    d = _words()
    lw = word.lower().strip("._-'")
    if not lw:
        return True
    if lw in d:
        return True
    for suffix in ("'s", "s'", "n't", "'re", "'ve", "'ll", "'d", "'m"):
        if lw.endswith(suffix) and lw[: -len(suffix)] in d:
            return True
    for suffix in ("s", "es", "ed", "ing", "'"):
        if lw.endswith(suffix) and lw[: -len(suffix)] in d:
            return True
    return False


def _plausible(word):
    """Reject OCR mush.

    The hard case is a misread that repeats: the same wrong glyphs appear all
    over a screen, so confidence and repetition both pass it. Measured on a
    dense terminal that yielded "intelepronpter", "fron", "apil", "cursar"
    and "vords" — all of which would have been handed to the decoder as
    vocabulary, where they could pull a real word toward nonsense.

    What separates a name from a misread is shape. Identifiers carry a dot,
    underscore, hyphen or digit; names carry a capital. An all-lowercase
    unfamiliar run of letters is overwhelmingly a misread, and rejecting that
    class costs almost nothing: the terms this feature exists for are
    ZephyrSync, AuroraCache, dancify_app, run.sh, Elena Marquez.
    """
    lw = word.lower().strip("._-'")
    if len(lw) < 4:
        return False
    if not any(v in lw for v in "aeiouy"):
        return False
    if sum(c.isdigit() for c in lw) > len(lw) // 2:
        return False
    return True


def _shapely(word):
    """True when a token's shape alone marks it as an identifier or a name."""
    return (any(c in word for c in "._-+#") or any(c.isdigit() for c in word)
            or word[0].isupper() or word[1:] != word[1:].lower())


def terms_from(lines, limit=MAX_TERMS, min_hits=2):
    """Candidate names and identifiers from OCR'd screen text.

    `lines` is [(confidence, text)]. Three filters, each earned by measurement
    on a real screen:

      confidence  low-confidence lines are where "BARNL" and "EN201H ANZAND"
                  come from — pure noise that would bias the decoder at random.
      repetition  a name that matters appears more than once on a screen; OCR
                  errors are usually unique. This is the strongest single
                  signal and it costs nothing.
      dictionary  ordinary English is what the model is already good at.

    What survives on a working screen: dancify, run.sh, imgui, dancify_app,
    kyanth, magicaudioplayer, cmux, getmehitched.
    """
    import collections

    hits = collections.Counter()
    for confidence, line in lines:
        if confidence < MIN_CONFIDENCE:
            continue
        for word in _WORD.findall(line):
            if _plausible(word):
                hits[word] += 1
    #  An all-lowercase unfamiliar token is usually a misread, but sometimes
    #  it is imgui or kubectl. Rather than choose, make it pay for entry: a
    #  real project name recurs across a screen, a glyph error rarely gets
    #  past twice.
    ranked = []
    for word, n in hits.most_common(400):
        if _ordinary(word):
            continue
        if n >= min_hits if _shapely(word) else n >= min_hits + 2:
            ranked.append(word)
    return ranked[:limit]


class Harvester:
    """Runs the read on a worker thread for the duration of an utterance.

    `begin` is called when the key goes down and must return instantly — the
    event tap callback is on the critical path and macOS disables a tap whose
    callback runs long. `collect` is called when the audio is ready and waits
    only for whatever time is left.

    Two things make the result untrustworthy unless guarded, and both were
    observed rather than theorised:

    *The destination can change mid-utterance.* Context is harvested at
    key-down from whatever is frontmost; the paste target is resolved at
    key-up. Start speaking in Slack, alt-tab to a terminal, and the terms
    describe a window the text will never reach. During testing this produced
    a read of "Universal Control" when the intended target was cmux. Terms
    from the wrong window are worse than none: they are plausible, so nothing
    downstream can tell they are wrong.

    *A slow read can outlive its own dictation.* A second `begin` while the
    first is still in Vision would otherwise let the older thread write its
    terms over the newer ones. Each read carries the generation it belongs to
    and drops its result if that has moved on.
    """

    def __init__(self, enabled=lambda: False, budget=2.5):
        self.enabled = enabled
        self.budget = budget
        self._gen = 0
        self._terms = []
        self._app = ""
        self._window = None
        self._done = threading.Event()
        self._lock = threading.Lock()

    def begin(self):
        #  Bump unconditionally, before the enabled check: a read started while
        #  the feature was on must not land after it has been switched off.
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._terms, self._app, self._window = [], "", None
            self._done = threading.Event()
            done = self._done
        if not self.enabled():
            done.set()
            return
        deadline = time.monotonic() + self.budget

        def run():
            t0 = time.perf_counter()
            try:
                #  The permission check is a TCC query and measured 430 ms on
                #  its first call. It belongs here and not in begin(), which
                #  runs inside the event-tap callback — macOS disables a tap
                #  whose callback is slow, which would take dictation down
                #  with it. Nothing above this line may touch a framework.
                if not screen_capture_permitted():
                    done.set()
                    return
                lines, app, window = read_window_text(deadline)
                terms = terms_from(lines) if lines else []
            except Exception as exc:
                print(f"[context] read failed: {exc}", flush=True)
                app, window, terms = "", None, []
            ms = (time.perf_counter() - t0) * 1000
            with self._lock:
                if gen != self._gen:
                    print(f"[context] dropped stale read ({ms:.0f}ms, "
                          f"generation {gen} of {self._gen})", flush=True)
                    return
                self._terms, self._app, self._window = terms, app, window
            if terms:
                print(f"[context] {app}: {len(terms)} terms in {ms:.0f}ms", flush=True)
            done.set()

        threading.Thread(target=run, daemon=True).start()

    def collect(self, destination="", timeout=0.35):
        """Terms for this utterance, or nothing if they describe somewhere else.

        `destination` is the app the text is about to be pasted into, resolved
        at key-up. Matching is by app rather than window: a different window of
        the same app is a sibling context and still plausibly relevant, while a
        different app is simply the wrong screen.
        """
        with self._lock:
            done = self._done
        done.wait(timeout)
        with self._lock:
            if not self._terms:
                return []
            if destination and self._app and destination != self._app:
                print(f"[context] discarded {len(self._terms)} terms: harvested "
                      f"from {self._app!r}, pasting into {destination!r}", flush=True)
                return []
            return list(self._terms)
