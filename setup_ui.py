"""First-run setup — Level.

Every prior install required reading a log file to discover which permission
was missing. macOS makes this genuinely hard: it will not grant Accessibility
on an app's behalf, it stops prompting for Input Monitoring once denied, and an
ungranted microphone yields *silence* rather than an error. So the app has to
check its own state, say plainly what is wrong, and re-check continuously.

The rule this window enforces has not changed: setup is not complete until a
real dictation has round-tripped. Permissions being green proves configuration,
not function — and function is what the user actually wants confirmed. Which is
also why satisfied steps are slate rather than green (DESIGN.md §4.2): seven
green ticks would claim exactly the thing this window refuses to claim.

What changed is the shape. Eight uniform rows became three grouped phases;
implicit progress became a ring and an `n/8`; four competing footer buttons
became one primary, one quiet escape, and an overflow for the diagnostics.

The eight checks and their behaviour are carried over unchanged.
"""

import subprocess
import time

import objc
from objc import python_method
from AppKit import (
    NSAlert,
    NSBackingStoreBuffered,
    NSMakePoint,
    NSMakeRect,
    NSMakeSize,
    NSScrollView,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskTitled,
    NSWindowTitleHidden,
)
from Foundation import NSObject, NSTimer

import chrome
import paths
import tokens

W = chrome.WIN_W
BOX_W = W - chrome.PAD * 2
BODY_TOP = 18.0
GROUP_GAP = tokens.GROUP_GAP
LABEL_H = 18.0

PENDING, ACTIVE, DONE, WARN = "pending", "active", "done", "warn"
MARKS = {PENDING: "todo", ACTIVE: "todo", DONE: "done", WARN: "warn"}

COUNT_WORD = {1: "One thing", 2: "Two things", 3: "Three things",
              4: "Four things", 5: "Five things", 6: "Six things",
              7: "Seven things", 8: "Eight things"}


class FlippedView(NSView):
    """Top-down coordinates, so the body reads in the order it is written."""

    def isFlipped(self):
        return True


class Step:
    """One row. `check` returns True when satisfied; `act` is the button.

    `why_ok` / `why_no` are the reason line for each state. A row that reads
    "Granted." while ungranted is precisely the confusion this window exists
    to remove, so the copy is not allowed to be state-independent.
    """

    def __init__(self, key, group, title, why_ok, why_no, check,
                 act=None, button="Open System Settings", optional=False):
        self.key = key
        self.group = group
        self.title = title
        self.why_ok = why_ok
        self.why_no = why_no
        self.check = check
        self.act = act
        self.button = button
        #  Optional steps are worth surfacing but must never block completion.
        #  Input Monitoring is the case: on some Macs the tap works without it,
        #  and gating on it strands a user whose shortcut is already firing.
        self.optional = optional
        self.state = PENDING

    @property
    def why(self):
        return self.why_ok if self.state == DONE else self.why_no


class SetupController(NSObject):

    #  Methods Cocoa calls (initWithApp_, stepAction_, tick_, …) stay as
    #  selectors. Everything else is marked @python_method: pyobjc maps a bare
    #  method name to a zero-argument selector, so a helper like _hint(step)
    #  raises BadPrototypeError at class-creation time.
    def initWithApp_(self, app):
        self = objc.super(SetupController, self).init()
        if self is None:
            return None
        self.app = app
        self.dictated = False        # set by the app when a transcription lands
        self.timer = None
        self.dupes_shown = None      # tri-state so the first layout always runs
        self._centred = False
        self.last_probe = 0.0
        self.steps = self._build_steps()
        self._build_window()
        return self

    # ------------------------------------------------------------- steps

    @python_method
    def _build_steps(self):
        app = self.app

        def mic_ok():
            from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
            return AVCaptureDevice.authorizationStatusForMediaType_(
                AVMediaTypeAudio) == 3

        def mic_act():
            from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
            status = AVCaptureDevice.authorizationStatusForMediaType_(
                AVMediaTypeAudio)
            if status == 0:
                AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    AVMediaTypeAudio, lambda granted: None)
            else:
                # Denied: macOS will not prompt again, so send them to the pane.
                self._open_pane("Privacy_Microphone")

        def ax_ok():
            from ApplicationServices import AXIsProcessTrusted
            return bool(AXIsProcessTrusted())

        def ax_act():
            from ApplicationServices import (AXIsProcessTrustedWithOptions,
                                             kAXTrustedCheckOptionPrompt)
            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
            self._open_pane("Privacy_Accessibility")

        def listen_ok():
            import shout
            return shout.input_monitoring_status() == 0

        def listen_act():
            import shout
            #  Once denied, macOS never prompts again and the app may not even
            #  appear in the list — leaving the user to hunt for the "+"
            #  button. Clearing our own TCC entry (no sudo needed) makes the
            #  system prompt fire again, which also adds us to the list.
            if shout.input_monitoring_status() == 1:
                subprocess.run(
                    ["tccutil", "reset", "ListenEvent", paths.BUNDLE_ID],
                    capture_output=True, check=False)
            shout.request_input_monitoring()
            self._open_pane("Privacy_ListenEvent")

        def audio_ok():
            #  Normally this just reads the probe done at startup: the check
            #  is polled every second, and opening the device here would flash
            #  the microphone indicator continuously.
            if app.recorder is None:
                return False
            if getattr(app, "mic_ok", False):
                return True

            #  But that probe ran before the user granted the microphone, so
            #  on every first run it failed and would stay failed forever —
            #  a row that cannot recover without a relaunch, in the one window
            #  whose promise is that it re-checks itself. Re-probe once the
            #  grant actually exists, rate-limited because each attempt does
            #  open the device.
            from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
            if AVCaptureDevice.authorizationStatusForMediaType_(
                    AVMediaTypeAudio) != 3:
                return False
            now = time.monotonic()
            if now - self.last_probe < 3.0:
                return False
            self.last_probe = now
            try:
                app.mic_ok = bool(app.recorder.probe())
            except Exception:
                app.mic_ok = False
            print(f"[setup] re-probed input device: usable={app.mic_ok}",
                  flush=True)
            return app.mic_ok

        def server_ok():
            return app.server._listening()

        def server_act():
            app.server.restart()

        def login_ok():
            import loginitem
            return loginitem.enabled()

        def login_act():
            import loginitem
            ok, msg = loginitem.set_enabled(True)
            if not ok:
                self._say(f"Open at Login: {msg}")

        def tap_ok():
            return bool(app.daemon and app.daemon.tap is not None)

        return [
            Step("mic", "Permissions", "Microphone",
                 "Granted. shout opens the stream while the shortcut is held "
                 "and closes it on release.",
                 "Not granted. Without it shout hears silence rather than an "
                 "error, so nothing will appear to happen.",
                 mic_ok, mic_act, "Grant Access"),
            Step("ax", "Permissions", "Accessibility",
                 "Granted. This is what lets shout paste into the app in "
                 "front of you.",
                 "Not granted. macOS will not enable this on shout’s behalf — "
                 "switch it on in the list that opens.",
                 ax_ok, ax_act),
            Step("listen", "Permissions", "Input Monitoring",
                 "Granted. shout sees the shortcut while another app is "
                 "frontmost.",
                 "Not granted. Usually needed for the shortcut, but optional — "
                 "if “Shortcut reaches shout” below is satisfied, ignore this.",
                 listen_ok, listen_act, optional=True),

            Step("audio", "Hardware & model", "Input device",
                 "The input device opens. shout releases it again when idle.",
                 "The input device did not open. Check the microphone selected "
                 "in Settings, then try again.",
                 audio_ok, None, ""),
            Step("server", "Hardware & model", "Model server",
                 "Running locally. No audio leaves this Mac.",
                 "Not running. The transcription model failed to load; "
                 "restarting it usually clears this.",
                 server_ok, server_act, "Restart"),
            Step("login", "Hardware & model", "Open at Login",
                 "shout starts itself after a restart.",
                 "Optional, and it never blocks. Without it shout will not "
                 "start itself after a restart.",
                 login_ok, login_act, "Turn On", optional=True),

            Step("tap", "Verification", "Shortcut reaches shout",
                 "Registered system-wide. shout sees the key combination from "
                 "any app.",
                 "Not registered. shout could not install the key tap — "
                 "granting the permissions above is what usually fixes it.",
                 tap_ok, None, ""),
            Step("test", "Verification", "Say something",
                 "Real text arrived. Setup is complete.",
                 #  Rewritten every refresh with the user's actual chord. This
                 #  placeholder is the longest form it can take, and the row
                 #  reserves its height from it — a row that grows a line when
                 #  the text changes would shove the whole list downward.
                 "Green permissions are not proof. Setup finishes when a real "
                 "dictation produces real text — Right Option + Right Command. "
                 "Press it once to start, speak, then press it again.",
                 lambda: self.dictated, None, ""),
        ]

    @python_method
    def _open_pane(self, anchor):
        subprocess.run(
            ["open",
             f"x-apple.systempreferences:com.apple.preference.security?{anchor}"],
            check=False)

    @python_method
    def _say(self, message):
        """The subtitle is the one line of prose that changes most, so it has
        to re-flow: a fixed-height label silently drops its second line."""
        chrome.set_text(self.subtitle, message, "note", tokens.BAND_MUTED)
        width = self.subtitle.frame().size.width
        height = chrome.text_height(message, "note", width)
        self.subtitle.setFrameSize_(NSMakeSize(width, height))
        self.subtitle.setFrameOrigin_(
            NSMakePoint(chrome.PAD, chrome.BAND_H - 112.0 - height))

    # ------------------------------------------------------------ window

    @python_method
    def _build_window(self):
        import version as _v

        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, 300),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            | NSWindowStyleMaskFullSizeContentView,
            NSBackingStoreBuffered, False)
        #  Traffic lights only. The window title is dropped because the lockup
        #  names the app one line below it.
        self.window.setTitlebarAppearsTransparent_(True)
        self.window.setTitleVisibility_(NSWindowTitleHidden)
        self.window.setMovableByWindowBackground_(True)
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_("shout Setup")

        # ---- band: lockup top-left, headline, ring top-right
        self.band = chrome.BandView.alloc().initWithFrame_(
            NSMakeRect(0, 0, W, chrome.BAND_H))
        self.band.setAutoresizingMask_(2 | 8)        # width + min-Y flexible
        self.band.addSubview_(chrome.lockup(chrome.PAD, chrome.BAND_H - 59.0))

        self.headline = chrome.label("Checking…", "setupTitle", tokens.BAND_FG,
                                     x=chrome.PAD, y=chrome.BAND_H - 104.0)
        self.headline.setFrameSize_(NSMakeSize(420.0, 26.0))
        self.band.addSubview_(self.headline)

        sub_w = W - chrome.PAD - chrome.RING_D - chrome.PAD * 2
        self.subtitle = chrome.label(" ", "note", tokens.BAND_MUTED,
                                     width=sub_w, x=chrome.PAD, y=0, wrap=True)
        self.band.addSubview_(self.subtitle)

        self.ring = chrome.RingView.alloc().initWithFrame_(
            NSMakeRect(W - chrome.PAD - chrome.RING_D,
                       chrome.BAND_H - 136.0, chrome.RING_D, chrome.RING_D))
        self.band.addSubview_(self.ring)

        # ---- footer: version · overflow · quiet escape · primary
        self.footer = chrome.FooterView.alloc().initWithFrame_(
            NSMakeRect(0, 0, W, chrome.FOOTER_H))
        self.footer.setAutoresizingMask_(2)
        self.footer.addSubview_(
            chrome.label(f"shout {_v.VERSION}", "version", tokens.MUTED,
                         x=chrome.PAD, y=17.0))

        self.done_btn = chrome.button("Finish", self, "finish:", primary=True,
                                      width=92)
        self.done_btn.setFrameOrigin_(
            NSMakePoint(W - chrome.PAD - self.done_btn.frame().size.width, 9.0))
        self.done_btn.setKeyEquivalent_("\r")
        self.done_btn.setEnabled_(False)
        self.footer.addSubview_(self.done_btn)

        later = chrome.button("Do this later", self, "later:", quiet=True)
        later.setFrameOrigin_(NSMakePoint(
            self.done_btn.frame().origin.x - later.frame().size.width - 4.0, 9.0))
        self.footer.addSubview_(later)

        #  A user stuck partway through setup, with the status icon hidden by a
        #  full menu bar, otherwise has no way to reach Settings or to quit at
        #  all. These stay reachable, just not as four competing buttons.
        more = chrome.popup("Options", [("Open Log", 0), ("Settings…", 1),
                                        ("Quit shout", 2)],
                            self, "more:")
        more.setFrameOrigin_(NSMakePoint(
            later.frame().origin.x - more.frame().size.width - 6.0, 9.0))
        self.footer.addSubview_(more)

        # ---- body
        self.body = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 10))
        self.scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, W, 10))
        self.scroll.setDrawsBackground_(True)
        self.scroll.setBackgroundColor_(tokens.SURFACE)
        self.scroll.setHasVerticalScroller_(True)
        self.scroll.setAutohidesScrollers_(True)
        self.scroll.setBorderType_(0)
        self.scroll.setDocumentView_(self.body)
        self.scroll.setAutoresizingMask_(2 | 16)     # width + height flexible

        content = self.window.contentView()
        content.addSubview_(self.scroll)
        content.addSubview_(self.band)
        content.addSubview_(self.footer)

        self._build_rows()
        self._layout(dupes=self._duplicates_present())

    # ---------------------------------------------------------- body rows

    @python_method
    def _duplicates_present(self):
        import version
        return bool(version.duplicate_bundles())

    @python_method
    def _build_rows(self):
        """Build every row once. Heights are computed from the LONGER of the
        two reason strings so the layout does not jump each time a check
        flips — a list that reflows once a second is unreadable."""
        self.rows = {}
        self.boxes = {}
        self.group_counts = {}

        #  A conditional box, not a ninth step: extra copies are a problem to
        #  fix, not a stage to complete, and folding them into n/8 would make
        #  the count lie on every healthy install.
        self.dupe_box = chrome.BoxView.alloc().initWithFrame_(
            NSMakeRect(chrome.PAD, 0, BOX_W, 10))
        self.dupe_row = self._make_row(
            "Extra copies of shout are installed",
            "Dragging to Applications twice is easy to do by accident, and it "
            "makes updates appear not to take effect. Only one copy should "
            "exist.", "Remove Extras", "dupesAction:")
        self.dupe_row.set_mark("warn", False)
        self.dupe_box.addSubview_(self.dupe_row)
        self.dupe_label, self.dupe_count = chrome.group_label(
            "Attention", "", 0, BOX_W)

        for i, step in enumerate(self.steps):
            box = self.boxes.get(step.group)
            if box is None:
                box = chrome.BoxView.alloc().initWithFrame_(
                    NSMakeRect(chrome.PAD, 0, BOX_W, 10))
                self.boxes[step.group] = box
                self.group_counts[step.group] = chrome.group_label(
                    step.group, "", 0, BOX_W)

            row = self._make_row(step.title, step.why_no,
                                 step.button if step.act else None,
                                 "stepAction:", tag=i)
            self.rows[step.key] = row
            box.addSubview_(row)

    @python_method
    def _make_row(self, title, why, button_title, action, tag=0):
        """Build a row. Its height is set later by `_fit_row`, from whichever
        reason string is actually showing."""
        btn = None
        text_w = BOX_W - chrome.ROW_PAD_X * 2 - chrome.MARK_COL - chrome.MARK_GAP
        if button_title:
            btn = chrome.button(button_title, self, action)
            btn.setTag_(tag)
            text_w -= btn.frame().size.width + 12.0

        row = chrome.CheckRow.alloc().initWithFrame_(NSMakeRect(0, 0, BOX_W, 40))
        row.text_x = chrome.ROW_PAD_X + chrome.MARK_COL + chrome.MARK_GAP
        row.text_w = text_w
        row.title = chrome.label(title, "rowLabel", tokens.FG, x=row.text_x)
        row.why = chrome.label(why, "note", tokens.MUTED, width=text_w,
                               x=row.text_x, wrap=True)
        row.btn = btn
        row.addSubview_(row.title)
        row.addSubview_(row.why)
        if btn is not None:
            row.addSubview_(btn)
        return row

    @python_method
    def _fit_row(self, row):
        """Size the row to the reason it is currently showing, and stack its
        contents from the top. Heights change only when a check flips, which
        is a discrete event the user caused — not once a second."""
        why = row.why.stringValue()
        why_h = chrome.text_height(why, "note", row.text_w) if why else 0.0
        height = chrome.ROW_PAD_Y * 2 + 17.0 + (2.0 + why_h if why else 0.0)

        row.setFrameSize_(NSMakeSize(BOX_W, height))
        row.title.setFrameOrigin_(
            NSMakePoint(row.text_x, height - chrome.ROW_PAD_Y - 17.0))
        row.why.setFrameSize_(NSMakeSize(row.text_w, why_h))
        row.why.setFrameOrigin_(
            NSMakePoint(row.text_x, height - chrome.ROW_PAD_Y - 19.0 - why_h))
        if row.btn is not None:
            row.btn.setFrameOrigin_(NSMakePoint(
                BOX_W - chrome.ROW_PAD_X - row.btn.frame().size.width,
                height - chrome.ROW_PAD_Y - 26.0))
        return height

    @python_method
    def _layout(self, dupes):
        """Stack the groups top-down and size the window to fit."""
        shape = (dupes, tuple(r.why.stringValue() for r in self.rows.values()),
                 tuple(bool(r.btn and not r.btn.isHidden()) for r in
                       self.rows.values()))
        if shape == self.dupes_shown:
            return
        self.dupes_shown = shape

        for v in list(self.body.subviews()):
            v.removeFromSuperview()

        y = BODY_TOP

        def place_group(box, labels, rows_):
            nonlocal y
            left, right = labels
            left.setFrameOrigin_(NSMakePoint(left.frame().origin.x, y))
            right.setFrameOrigin_(NSMakePoint(right.frame().origin.x, y))
            self.body.addSubview_(left)
            self.body.addSubview_(right)
            y += LABEL_H

            ry = 0.0
            seps = []
            for row in rows_:
                height = self._fit_row(row)
                row.setFrameOrigin_(NSMakePoint(0, ry))
                if ry:
                    seps.append(ry)
                ry += height
            box.separators = seps
            box.setFrameSize_(NSMakeSize(BOX_W, ry))
            box.setFrameOrigin_(NSMakePoint(chrome.PAD, y))
            self.body.addSubview_(box)
            y += ry + GROUP_GAP

        if dupes:
            place_group(self.dupe_box, (self.dupe_label, self.dupe_count),
                        [self.dupe_row])

        for group in ("Permissions", "Hardware & model", "Verification"):
            rows_ = [self.rows[s.key] for s in self.steps if s.group == group]
            place_group(self.boxes[group], self.group_counts[group], rows_)

        body_h = y - GROUP_GAP + BODY_TOP
        self.body.setFrameSize_(NSMakeSize(W, body_h))

        #  Size to content, but never taller than the screen it will open on.
        from AppKit import NSScreen
        screen = NSScreen.mainScreen()
        visible = screen.visibleFrame().size.height if screen else 900.0
        total = chrome.BAND_H + body_h + chrome.FOOTER_H
        height = min(total, visible - 40.0)

        frame = self.window.frame()
        self.window.setFrame_display_(
            NSMakeRect(frame.origin.x, frame.origin.y, W, height), True)
        content = self.window.contentView().bounds().size
        self.band.setFrame_(NSMakeRect(0, content.height - chrome.BAND_H,
                                       W, chrome.BAND_H))
        self.footer.setFrame_(NSMakeRect(0, 0, W, chrome.FOOTER_H))
        self.scroll.setFrame_(NSMakeRect(
            0, chrome.FOOTER_H, W,
            content.height - chrome.BAND_H - chrome.FOOTER_H))

    # ----------------------------------------------------------- actions

    def stepAction_(self, sender):
        step = self.steps[sender.tag()]
        try:
            step.act()
        except Exception as exc:
            self._say(f"{step.title}: {exc}")
        self.refresh()

    def dupesAction_(self, sender):
        import version
        copies = version.duplicate_bundles()
        if not copies:
            return
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Extra copies of shout found")
        alert.setInformativeText_(
            "These will be moved to the Trash:\n\n" + "\n".join(copies))
        alert.addButtonWithTitle_("Move to Trash")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() != 1000:
            return
        for path in copies:
            ok, msg = version.remove_bundle(path)
            if not ok:
                self._say(f"Could not remove {path}: {msg}")
        self.refresh()

    def more_(self, sender):
        tag = sender.selectedItem().tag() if hasattr(sender, "selectedItem") \
            else sender.tag()
        if tag == 0:
            subprocess.run(["open", str(paths.logs())], check=False)
        elif tag == 1:
            self.stop()
            self.window.close()
            opener = getattr(self.app, "on_settings", None)
            if opener is not None:
                opener(None)
        elif tag == 2:
            self.stop()
            self.window.close()
            quit_fn = getattr(self.app, "on_quit", None)
            if quit_fn is not None:
                quit_fn(None)

    def later_(self, sender):
        self.stop()
        self.window.close()

    def finish_(self, sender):
        self.stop()
        self.window.close()

    # ------------------------------------------------------------ polling

    @python_method
    def start(self):
        chrome.bring_to_front(self.window, center=not self._centred)
        self._centred = True
        self.refresh()
        # Re-check continuously: the user is toggling switches in another app,
        # and nothing notifies us when they do.
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "tick:", None, True)

    @python_method
    def stop(self):
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None

    def tick_(self, timer):
        self.refresh()

    @python_method
    def note_dictation(self):
        """Called by the app when a transcription completes."""
        self.dictated = True

    @python_method
    def refresh(self):
        blocking = None
        for step in self.steps:
            try:
                ok = bool(step.check())
            except Exception:
                ok = False
            if ok:
                step.state = DONE
            elif step.optional:
                # Flagged, never blocking, and it does not consume the
                # "current step" slot — the user should keep moving.
                step.state = WARN
            elif blocking is None:
                step.state = ACTIVE
                blocking = step
            else:
                step.state = PENDING

        # ---- the live verification row explains itself
        test = self.steps[-1]
        if test.state != DONE:
            hk = getattr(self.app.cfg, "hotkey", None)
            chord = hk.label() if hk else "your shortcut"
            how = ("Press it once to start, speak, then press it again."
                   if getattr(self.app.cfg, "mode", "hold") == "toggle"
                   else "Hold it, speak, then release.")
            test.why_no = (f"Green permissions are not proof. Setup finishes "
                           f"when a real dictation produces real text — "
                           f"{chord}. {how}")

        # ---- rows
        for step in self.steps:
            row = self.rows[step.key]
            row.set_mark(MARKS[step.state], step is blocking)
            chrome.set_text(row.why, step.why, "note", tokens.MUTED)
            chrome.set_text(
                row.title, step.title, "rowLabel",
                tokens.FG if step.state != PENDING else tokens.MUTED)
            if row.btn is not None:
                row.btn.setHidden_(step.state not in (ACTIVE, WARN))

        self._layout(dupes=self._duplicates_present())

        # ---- group counts, and the peak edge on the box that owns the step
        for group, box in self.boxes.items():
            members = [s for s in self.steps if s.group == group]
            done = sum(1 for s in members if s.state == DONE)
            left, right = self.group_counts[group]
            chrome.set_text(right, f"{done} of {len(members)}", "version",
                            tokens.MUTED)
            box.blocking = blocking is not None and blocking.group == group
            box.setNeedsDisplay_(True)

        # ---- band
        done_total = sum(1 for s in self.steps if s.state == DONE)
        self.ring.set_progress(done_total, len(self.steps))

        if blocking is None:
            chrome.set_text(self.headline, "shout is ready", "setupTitle",
                            tokens.BAND_FG)
            skipped = [s.title for s in self.steps if s.state == WARN]
            self._say("Every check passes and a real dictation has already "
                      "gone through."
                      + (f"  ({', '.join(skipped)} not granted — not needed "
                         f"here.)" if skipped else ""))
            self.done_btn.setEnabled_(True)
        else:
            remaining = sum(1 for s in self.steps
                            if s.state in (ACTIVE, PENDING))
            chrome.set_text(self.headline,
                            f"{COUNT_WORD.get(remaining, f'{remaining} things')} "
                            f"left", "setupTitle", tokens.BAND_FG)
            self._say(self._hint(blocking))
            self.done_btn.setEnabled_(False)

    @python_method
    def _hint(self, step):
        if step.group == "Permissions":
            return ("Permissions can only be granted by you in System "
                    "Settings — shout cannot flip those switches on its own.")
        if step.key == "test":
            return ("Everything is configured. One real dictation confirms it "
                    "actually works.")
        return ("This one shout can usually fix itself — use the button on "
                "the row below.")
