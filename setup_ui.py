"""First-run setup wizard.

Every prior install required reading a log file to discover which permission was
missing. macOS makes this genuinely hard: it will not grant Accessibility on an
app's behalf, it stops prompting for Input Monitoring once denied, and an
ungranted microphone yields *silence* rather than an error. So the app has to
check its own state, say plainly what is wrong, and re-check continuously.

The rule this window enforces: setup is not "complete" until a real dictation
has round-tripped. Permissions being green proves configuration, not function —
and function is what the user actually wants confirmed.
"""

import subprocess

import objc
from objc import python_method
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSButton,
    NSColor,
    NSFont,
    NSMakeRect,
    NSTextField,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject, NSTimer

#  Sized so all seven rows fit with room to spare. The first version used
#  H=520 with ROW_H=74, which put row 7 at y=-36 — off-window — and overlapped
#  every title with its own detail line.
W, H = 580, 700
ROW_H = 66
ROWS_TOP = H - 124

PENDING, ACTIVE, DONE, WARN = "pending", "active", "done", "warn"

DOT = {PENDING: "○", ACTIVE: "◉", DONE: "✔", WARN: "!"}


def _text(s, x, y, w, h, size=13, bold=False, color=None, mono=False):
    f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    f.setStringValue_(s)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    if mono:
        f.setFont_(NSFont.monospacedSystemFontOfSize_weight_(size, 0))
    else:
        f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold
                   else NSFont.systemFontOfSize_(size))
    if color is not None:
        f.setTextColor_(color)
    return f


class Step:
    """One row. `check` returns True when satisfied; `act` is the button."""

    def __init__(self, key, title, detail, check, act=None,
                 button="Open Settings", optional=False):
        self.key = key
        self.title = title
        self.detail = detail
        self.check = check
        self.act = act
        self.button = button
        #  Optional steps are worth surfacing but must never block completion.
        #  Input Monitoring is the case: on some Macs the tap works without it,
        #  and gating on it strands a user whose shortcut is already firing.
        self.optional = optional
        self.state = PENDING


class SetupController(NSObject):

    #  Methods that Cocoa calls (initWithApp_, stepAction_, tick_, …) stay as
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
            shout.request_input_monitoring()
            self._open_pane("Privacy_ListenEvent")

        def server_ok():
            return app.server._listening()

        def server_act():
            app.server.restart()

        def tap_ok():
            return bool(app.daemon and app.daemon.tap is not None)

        def audio_ok():
            return app.recorder is not None

        return [
            Step("mic", "Microphone",
                 "So shout can hear you. Audio never leaves this Mac.",
                 mic_ok, mic_act, "Grant Access"),
            Step("ax", "Accessibility",
                 "So shout can type the text into whatever app you are using.",
                 ax_ok, ax_act),
            Step("listen", "Input Monitoring",
                 "Usually needed for the shortcut. Skip if step 7 already works.",
                 listen_ok, listen_act, optional=True),
            Step("audio", "Microphone connected",
                 "Opens the input device and starts listening for your shortcut.",
                 audio_ok, None, ""),
            Step("server", "Speech engine",
                 "Loads the transcription model. Runs locally on this Mac.",
                 server_ok, server_act, "Restart"),
            Step("tap", "Shortcut active",
                 "Registers your key combination system-wide.",
                 tap_ok, None, ""),
            Step("test", "Try it",
                 "Setup completes only once real text has appeared.",
                 lambda: self.dictated, None, ""),
        ]

    @python_method
    def _open_pane(self, anchor):
        subprocess.run(
            ["open",
             f"x-apple.systempreferences:com.apple.preference.security?{anchor}"],
            check=False)

    # ------------------------------------------------------------ window

    @python_method
    def _build_window(self):
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered, False)
        self.window.setTitle_("shout Setup")
        self.window.setReleasedWhenClosed_(False)
        view = self.window.contentView()

        view.addSubview_(_text("Setting up shout", 28, H - 56, 400, 26, 19, bold=True))
        self.subtitle = _text("Checking…", 28, H - 80, W - 56, 18, 12,
                              color=NSColor.secondaryLabelColor())
        view.addSubview_(self.subtitle)

        self.rows = {}
        for i, step in enumerate(self.steps):
            y = ROWS_TOP - i * ROW_H
            dot = _text(DOT[PENDING], 28, y - 18, 24, 22, 16)
            title = _text(f"{i + 1}. {step.title}", 56, y - 18, 320, 20, 13, bold=True)
            wide = step.act is None          # no button, so use the full width
            detail = _text(step.detail, 56, y - 40, (W - 84) if wide else (W - 200),
                           17, 11, color=NSColor.secondaryLabelColor())
            view.addSubview_(dot)
            view.addSubview_(title)
            view.addSubview_(detail)

            btn = None
            if step.act is not None:
                btn = NSButton.alloc().initWithFrame_(
                    NSMakeRect(W - 160, y - 24, 132, 30))
                btn.setTitle_(step.button)
                btn.setBezelStyle_(NSBezelStyleRounded)
                btn.setTarget_(self)
                btn.setAction_("stepAction:")
                btn.setTag_(i)
                btn.setHidden_(True)
                view.addSubview_(btn)

            self.rows[step.key] = (dot, title, detail, btn)

        self.status = _text("", 28, 74, W - 56, 38, 11,
                            color=NSColor.secondaryLabelColor())
        self.status.setUsesSingleLineMode_(False)
        view.addSubview_(self.status)

        self.done_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(W - 160, 24, 132, 32))
        self.done_btn.setTitle_("Done")
        self.done_btn.setBezelStyle_(NSBezelStyleRounded)
        self.done_btn.setKeyEquivalent_("\r")
        self.done_btn.setTarget_(self)
        self.done_btn.setAction_("finish:")
        self.done_btn.setEnabled_(False)
        view.addSubview_(self.done_btn)

        log_btn = NSButton.alloc().initWithFrame_(NSMakeRect(28, 24, 112, 32))
        log_btn.setTitle_("Open Log")
        log_btn.setBezelStyle_(NSBezelStyleRounded)
        log_btn.setTarget_(self)
        log_btn.setAction_("openLog:")
        view.addSubview_(log_btn)

        #  A user stuck partway through setup, with the status icon hidden by a
        #  full menu bar, otherwise has no way to quit the app at all.
        settings_btn = NSButton.alloc().initWithFrame_(NSMakeRect(148, 24, 112, 32))
        settings_btn.setTitle_("Settings…")
        settings_btn.setBezelStyle_(NSBezelStyleRounded)
        settings_btn.setTarget_(self)
        settings_btn.setAction_("openSettings:")
        view.addSubview_(settings_btn)

        import version as _v
        view.addSubview_(_text(f"v{_v.VERSION}", W - 210, 30, 60, 18, 11,
                               color=NSColor.tertiaryLabelColor()))

        quit_btn = NSButton.alloc().initWithFrame_(NSMakeRect(268, 24, 112, 32))
        quit_btn.setTitle_("Quit shout")
        quit_btn.setBezelStyle_(NSBezelStyleRounded)
        quit_btn.setTarget_(self)
        quit_btn.setAction_("quitApp:")
        view.addSubview_(quit_btn)

    # ----------------------------------------------------------- actions

    def stepAction_(self, sender):
        step = self.steps[sender.tag()]
        try:
            step.act()
        except Exception as exc:
            self.status.setStringValue_(f"{step.title}: {exc}")
        self.refresh()

    def openSettings_(self, sender):
        """Reachable from setup: changing the shortcut or the microphone is
        often what step 7 needs, and there was no route to it from here."""
        self.stop()
        self.window.close()
        opener = getattr(self.app, "on_settings", None)
        if opener is not None:
            opener(None)

    def quitApp_(self, sender):
        self.stop()
        self.window.close()
        quit_fn = getattr(self.app, "on_quit", None)
        if quit_fn is not None:
            quit_fn(None)

    def openLog_(self, sender):
        import paths
        subprocess.run(["open", str(paths.logs())], check=False)

    def finish_(self, sender):
        self.stop()
        self.window.close()

    # ------------------------------------------------------------ polling

    @python_method
    def start(self):
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
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
        first_incomplete = None
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
            elif first_incomplete is None:
                step.state = ACTIVE
                first_incomplete = step
            else:
                step.state = PENDING

        for i, step in enumerate(self.steps):
            dot, title, detail, btn = self.rows[step.key]
            dot.setStringValue_(DOT[step.state])
            dot.setTextColor_(
                NSColor.systemGreenColor() if step.state == DONE
                else NSColor.systemOrangeColor() if step.state == WARN
                else NSColor.controlAccentColor() if step.state == ACTIVE
                else NSColor.tertiaryLabelColor())
            title.setTextColor_(
                NSColor.labelColor() if step.state in (DONE, ACTIVE, WARN)
                else NSColor.tertiaryLabelColor())
            if btn is not None:
                btn.setHidden_(step.state not in (ACTIVE, WARN))

        if first_incomplete is None:
            self.subtitle.setStringValue_("Everything is working.")
            skipped = [s.title for s in self.steps if s.state == WARN]
            self.status.setStringValue_(
                "shout is running and will start automatically at login."
                + (f"  ({', '.join(skipped)} not granted, but not needed here.)"
                   if skipped else ""))
            self.status.setTextColor_(NSColor.systemGreenColor())
            self.done_btn.setEnabled_(True)
            self.done_btn.setTitle_("Finish")
        else:
            n = self.steps.index(first_incomplete) + 1
            self.subtitle.setStringValue_(
                f"Step {n} of {len(self.steps)} — {first_incomplete.title}")
            self.status.setStringValue_(self._hint(first_incomplete))
            self.status.setTextColor_(NSColor.secondaryLabelColor())
            self.done_btn.setEnabled_(False)

    @python_method
    def _hint(self, step):
        if step.key == "ax":
            return ("macOS cannot enable this for you. Click the button, then "
                    "switch “shout” ON in the list that opens. "
                    "This window updates by itself.")
        if step.key == "listen":
            return ("Click the button, then switch “shout” ON. If it is not "
                    "listed, click + and choose /Applications/shout.app. "
                    "Optional — if step 7 works, you can ignore this.")
        if step.key == "test":
            hk = getattr(self.app.cfg, "hotkey", None)
            label = hk.label() if hk else "your shortcut"
            mode = getattr(self.app.cfg, "mode", "hold")
            how = ("Press once to start, speak, press again to stop."
                   if mode == "toggle" else "Hold it, speak, then release.")
            return f"{label} — {how}"
        return ""
