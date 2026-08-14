"""Settings — Level.

rumps offers a single-line text prompt, which cannot record a key combination,
so this is a plain Cocoa window built with pyobjc.

The chord recorder is unchanged and stays the centre of the Shortcut pane: it
builds as keys go down and commits on release, so `⌃ + Right ⌥` is recordable
rather than just single keys, and modifiers are side-aware — `Right ⌥` is not
`Left ⌥`. A *local* NSEvent monitor is used rather than a global one: it only
sees events while this window is key, so recording cannot swallow keystrokes
meant for other apps, and it needs no extra permission.

What changed is the shell. The tab strip became a source list, because three
tabs do not scale and the diagnostics had nowhere to go. Save/Cancel is gone:
mode and device changes already applied live, so those buttons were describing
a modal commit that never existed. The footer now says what is true.
"""

import subprocess

import objc
from objc import python_method
from AppKit import (
    NSAlert,
    NSApp,
    NSBackingStoreBuffered,
    NSEvent,
    NSEventMaskFlagsChanged,
    NSEventMaskKeyDown,
    NSEventTypeFlagsChanged,
    NSEventTypeKeyDown,
    NSMakePoint,
    NSMakeRect,
    NSMakeSize,
    NSPopUpButton,
    NSScrollView,
    NSSearchField,
    NSSegmentedControl,
    NSSegmentStyleRounded,
    NSSlider,
    NSSwitch,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskTitled,
    NSWindowTitleHidden,
)
from Foundation import NSObject, NSTimer

import chrome
import history_view
import paths
import tokens
from hotkey import MODE_HOLD, MODE_TOGGLE, ChordRecorder

SIDEBAR_W = chrome.SIDEBAR_W
PANE_X = tokens.PANE_X
FOOTER_H = chrome.FOOTER_H

#  The design gives History more room because it is a table; every other pane
#  is a form and 800 is generous for one. Resizing on selection is what the
#  system's own Settings does.
WIDTH = {"history": 940.0}
DEFAULT_W = 800.0
HEIGHT = 620.0

MODE_HELP = {
    MODE_HOLD: "Recording runs for exactly as long as the keys are down. "
               "Release to transcribe.",
    MODE_TOGGLE: "Press once to start, speak, then press again to stop and "
                 "transcribe.",
}

SOURCES = [
    ("Capture", [("shortcut", "Shortcut", "keyboard"),
                 ("audio", "Audio", "waveform")]),
    ("Text", [("history", "History", "clock"),
              ("behaviour", "Behaviour", "slider.horizontal.3")]),
    ("System", [("permissions", "Permissions", "lock")]),
]

PANE_HEAD = {
    "shortcut": ("Shortcut",
                 "What shout listens for, and proof that it is hearing it."),
    "audio": ("Audio",
              "Which microphone shout opens, and what it plays back to you."),
    "history": ("History",
                "Everything you have dictated, newest first. Kept on this "
                "Mac, capped at 500."),
    "behaviour": ("Behaviour",
                  "What shout does with the text once it has it."),
    "permissions": ("Permissions",
                    "What macOS has granted. shout cannot flip these itself."),
}


class Flipped(NSView):
    def isFlipped(self):
        return True


class SettingsController(NSObject):
    """Owns the window. `on_apply(hotkey, mode, device)` saves and rebinds."""

    def initWithApp_(self, app):
        self = objc.super(SettingsController, self).init()
        if self is None:
            return None
        self.app = app
        self.hotkey = app.cfg.hotkey
        self.mode = app.cfg.mode if app.cfg.mode in (MODE_HOLD, MODE_TOGGLE) \
            else MODE_HOLD
        self.history = app.store
        self.input_device = app.cfg.input_device
        self.pane = "shortcut"
        self.monitor = None
        self.recording = False
        self.recorder = ChordRecorder()
        self.level_timer = None
        self.panes = {}
        self._build()
        return self

    # ------------------------------------------------------------- shell

    @python_method
    def _build(self):
        import version as _v

        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, DEFAULT_W, HEIGHT),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            | NSWindowStyleMaskFullSizeContentView,
            NSBackingStoreBuffered, False)
        self.window.setTitlebarAppearsTransparent_(True)
        self.window.setTitleVisibility_(NSWindowTitleHidden)
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_("shout")
        content = self.window.contentView()

        # ---- sidebar: the band, full height, lockup at the top
        self.sidebar = chrome.SidebarView.alloc().initWithFrame_(
            NSMakeRect(0, 0, SIDEBAR_W, HEIGHT))
        self.sidebar.setAutoresizingMask_(16)          # height flexible
        self.sidebar.addSubview_(chrome.lockup(18.0, HEIGHT - 59.0))
        content.addSubview_(self.sidebar)

        self.source_rows = {}
        y = HEIGHT - 92.0
        for group, items in SOURCES:
            head = chrome.label(group.upper(), "groupLabel", tokens.BAND_DIM,
                                x=20.0, y=y - 14.0)
            head.setAutoresizingMask_(8)               # pinned to the top
            self.sidebar.addSubview_(head)
            y -= 24.0
            for key, title, symbol in items:
                row = chrome.SourceRow.alloc().initWithFrame_(
                    NSMakeRect(0, y - chrome.SOURCE_H, SIDEBAR_W,
                               chrome.SOURCE_H))
                row.setAutoresizingMask_(8)
                row.title, row.symbol = title, symbol
                self.source_rows[key] = row
                self.sidebar.addSubview_(row)
                y -= chrome.SOURCE_H + 2.0
            y -= 14.0

        self.sidebar.addSubview_(
            chrome.label(f"Version {_v.VERSION}", "version", tokens.BAND_DIM,
                         x=20.0, y=18.0))

        #  Clicks on the source list. A row is a plain view, so selection is
        #  hit-testing on mouse-down rather than an NSTableView delegate — 5
        #  static rows do not justify a data source.
        click = ClickCatcher.alloc().initWithFrame_(
            NSMakeRect(0, 0, SIDEBAR_W, HEIGHT))
        click.setAutoresizingMask_(16)
        click.controller = self
        self.sidebar.addSubview_(click)

        # ---- pane head
        self.head_title = chrome.label("", "paneTitle", tokens.FG,
                                       x=SIDEBAR_W + PANE_X, y=0)
        self.head_title.setFrameSize_(NSMakeSize(420.0, 24.0))
        self.head_sub = chrome.label("", "note", tokens.MUTED, width=420.0,
                                     x=SIDEBAR_W + PANE_X, y=0, wrap=True)
        content.addSubview_(self.head_title)
        content.addSubview_(self.head_sub)

        self.head_rule = Hairline.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 1))
        content.addSubview_(self.head_rule)

        self.search = NSSearchField.alloc().initWithFrame_(
            NSMakeRect(0, 0, 220.0, 26.0))
        self.search.setFont_(tokens.font(12.5))
        self.search.setTarget_(self)
        self.search.setAction_("searchChanged:")
        self.search.setPlaceholderString_("Search")
        #  Filter as they type rather than on Return: the whole point is to
        #  narrow a list they are looking at.
        self.search.setSendsWholeSearchString_(False)
        self.search.setSendsSearchStringImmediately_(True)
        self.search.setHidden_(True)
        content.addSubview_(self.search)

        # ---- body
        self.body = Flipped.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.scroll.setDrawsBackground_(True)
        self.scroll.setBackgroundColor_(tokens.SURFACE)
        self.scroll.setHasVerticalScroller_(True)
        self.scroll.setAutohidesScrollers_(True)
        self.scroll.setBorderType_(0)
        self.scroll.setDocumentView_(self.body)
        content.addSubview_(self.scroll)

        # ---- footer
        self.footer = chrome.FooterView.alloc().initWithFrame_(
            NSMakeRect(0, 0, 10, FOOTER_H))
        content.addSubview_(self.footer)

        self.foot_note = chrome.label("Changes apply immediately", "note",
                                      tokens.MUTED, x=0, y=17.0)
        self.footer.addSubview_(self.foot_note)

        #  Quitting lives here because when the menu bar is full macOS hides
        #  the status icon, and this window is then the only way out.
        self.quit_btn = chrome.button("Quit shout", self, "quitApp:")
        self.quit_btn.setContentTintColor_(tokens.RECORD)
        self.footer.addSubview_(self.quit_btn)

        self.setup_btn = chrome.button("Re-run Setup…", self, "runSetup:")
        self.footer.addSubview_(self.setup_btn)

        self.foot_extra = []          # pane-specific footer buttons

        self.select_("shortcut")

    @python_method
    def _layout_shell(self):
        content = self.window.contentView().bounds().size
        w, h = content.width, content.height
        pane_w = w - SIDEBAR_W

        self.head_title.setFrameOrigin_(
            NSMakePoint(SIDEBAR_W + PANE_X, h - 52.0))
        sub_w = pane_w - PANE_X * 2 - (240.0 if self.pane == "history" else 0.0)
        self.head_sub.setFrameSize_(NSMakeSize(
            sub_w, chrome.text_height(self.head_sub.stringValue(), "note", sub_w)))
        self.head_sub.setFrameOrigin_(NSMakePoint(
            SIDEBAR_W + PANE_X,
            h - 56.0 - self.head_sub.frame().size.height))

        head_h = h - (self.head_sub.frame().origin.y - 16.0)
        self.head_rule.setFrame_(
            NSMakeRect(SIDEBAR_W, h - head_h, pane_w, 1.0))
        self.search.setFrameOrigin_(
            NSMakePoint(w - PANE_X - 220.0, h - 58.0))

        self.scroll.setFrame_(NSMakeRect(
            SIDEBAR_W, FOOTER_H, pane_w, h - head_h - FOOTER_H))
        self.footer.setFrame_(NSMakeRect(SIDEBAR_W, 0, pane_w, FOOTER_H))
        self.foot_note.setFrameOrigin_(NSMakePoint(PANE_X, 17.0))

        x = pane_w - PANE_X
        for btn in [self.quit_btn, self.setup_btn] + self.foot_extra:
            if btn.isHidden():
                continue
            x -= btn.frame().size.width
            btn.setFrameOrigin_(NSMakePoint(x, 9.0))
            x -= 8.0

    # -------------------------------------------------------------- panes

    def select_(self, pane):
        self.pane = pane
        for k, row in self.source_rows.items():
            row.set_selected(k == pane)

        title, sub = PANE_HEAD[pane]
        chrome.set_text(self.head_title, title, "paneTitle", tokens.FG)
        chrome.set_text(self.head_sub, sub, "note", tokens.MUTED)
        self.search.setHidden_(pane != "history")

        for v in list(self.body.subviews()):
            v.removeFromSuperview()
        for btn in self.foot_extra:
            btn.removeFromSuperview()
        self.foot_extra = []

        #  Resize before laying out, and without animation: the History pane
        #  sizes itself and its columns to the visible area, so it has to see
        #  the final width. An animated resize is still mid-flight here and
        #  would hand it the old one.
        target_w = WIDTH.get(pane, DEFAULT_W)
        frame = self.window.frame()
        if abs(frame.size.width - target_w) > 1.0:
            self.window.setFrame_display_(
                NSMakeRect(frame.origin.x + (frame.size.width - target_w) / 2.0,
                           frame.origin.y, target_w, frame.size.height), True)

        self._layout_shell()
        builder = {"shortcut": self._pane_shortcut, "audio": self._pane_audio,
                   "history": self._pane_history,
                   "behaviour": self._pane_behaviour,
                   "permissions": self._pane_permissions}[pane]
        chrome.set_text(self.foot_note, builder(), "note", tokens.MUTED)
        self.foot_note.sizeToFit()
        self._layout_shell()
        self._sync()

    @python_method
    def _pane_width(self):
        return self.window.contentView().bounds().size.width - SIDEBAR_W

    @python_method
    def _stack(self, groups):
        """Lay out [(label, [rows])] down the body and size it."""
        width = self._pane_width() - PANE_X * 2
        y = 18.0
        for name, rows in groups:
            head = chrome.label(name.upper(), "groupLabel", tokens.MUTED,
                                x=PANE_X + 13.0, y=y)
            self.body.addSubview_(head)
            y += 18.0
            box = chrome.stack_box(width, rows)
            box.setFrameOrigin_(NSMakePoint(PANE_X, y))
            self.body.addSubview_(box)
            y += box.frame().size.height + tokens.GROUP_GAP
        self.body.setFrameSize_(NSMakeSize(self._pane_width(), y))

    # ---- Shortcut

    @python_method
    def _pane_shortcut(self):
        width = self._pane_width() - PANE_X * 2

        self.seg = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(0, 0, 210.0, 26.0))
        self.seg.setSegmentStyle_(NSSegmentStyleRounded)
        self.seg.setSegmentCount_(2)
        self.seg.setLabel_forSegment_("Hold to talk", 0)
        self.seg.setLabel_forSegment_("Toggle", 1)
        self.seg.setWidth_forSegment_(112.0, 0)
        self.seg.setWidth_forSegment_(98.0, 1)
        self.seg.setSelectedSegment_(0 if self.mode == MODE_HOLD else 1)
        self.seg.setTarget_(self)
        self.seg.setAction_("modeChanged:")
        mode_row, _ = chrome.form_row(width, "Mode", [self.seg],
                                      MODE_HELP[self.mode])
        self.mode_row = mode_row

        self.min_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(0, 0, 76.0, 24.0))
        self.min_field.setFont_(tokens.tabular(12.5))
        self.min_field.setStringValue_(f"{int(self._min_press_ms())} ms")
        self.min_field.setTarget_(self)
        self.min_field.setAction_("minPressChanged:")
        min_row, _ = chrome.form_row(
            width, "Ignore presses under", [self.min_field],
            "Anything shorter returns the low blip instead of an empty "
            "transcription.", note_indent=True)

        self.chord_field = chrome.label("", "rowLabel", tokens.FG, x=0, y=0)
        self.chord_field.setFrameSize_(NSMakeSize(230.0, 22.0))
        self.record_btn = chrome.button("Change…", self, "toggleRecording:")
        keys_row, _ = chrome.form_row(
            width, "Shortcut", [self.chord_field], trailing=self.record_btn,
            note=
            "Modifiers are side-aware, so Right ⌥ is not Left ⌥. The chord "
            "builds as keys go down and commits when you let go, which is how "
            "⌃ + Right ⌥ stays recordable.")

        self.keys_pill = chrome.StatusPill.alloc().initWithFrame_(
            NSMakeRect(0, 0, 160.0, 24.0))
        self.keys_pill.set_state("Not being pressed", False)
        pill_row, _ = chrome.form_row(width, "Keys arriving", [self.keys_pill])

        self.meter = chrome.MeterView.alloc().initWithFrame_(
            NSMakeRect(0, 0, chrome.MeterView.width(), 14.0))
        self.device_note = chrome.label(self._device_label(), "note",
                                        tokens.MUTED, x=0, y=0)
        audio_row, _ = chrome.form_row(width, "Audio arriving",
                                       [self.meter, self.device_note])

        self._stack([("Activation", [mode_row, min_row]),
                     ("Keys", [keys_row]),
                     ("Reception", [pill_row, audio_row])])
        return "Changes apply immediately"

    # ---- Audio

    @python_method
    def _pane_audio(self):
        width = self._pane_width() - PANE_X * 2
        import shout as _shout

        self.device_menu = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(0, 0, 260.0, 26.0), False)
        self.device_menu.setFont_(tokens.font(12.5))
        #  Listed by name. A saved index would silently point at a different
        #  microphone as soon as any audio device is added or removed.
        self.device_menu.addItemWithTitle_("System default")
        for name in _shout.input_devices():
            self.device_menu.addItemWithTitle_(name)
        if self.input_device:
            idx = self.device_menu.indexOfItemWithTitle_(self.input_device)
            if idx >= 0:
                self.device_menu.selectItemAtIndex_(idx)
        self.device_menu.setTarget_(self)
        self.device_menu.setAction_("deviceChanged:")
        device_row, _ = chrome.form_row(
            width, "Input", [self.device_menu],
            "Pick a specific microphone if the default is a virtual device.",
            note_indent=True)

        self.meter2 = chrome.MeterView.alloc().initWithFrame_(
            NSMakeRect(0, 0, chrome.MeterView.width(), 14.0))
        level_row, _ = chrome.form_row(
            width, "Level", [self.meter2],
            "Live while this window is open. shout opens the device only "
            "while the shortcut is held, so the microphone indicator is not "
            "on the rest of the time.", note_indent=True)

        self.sound_switch = NSSwitch.alloc().initWithFrame_(
            NSMakeRect(0, 0, 38.0, 22.0))
        self.sound_switch.setState_(1 if self.app.cues.enabled else 0)
        self.sound_switch.setTarget_(self)
        self.sound_switch.setAction_("soundChanged:")
        cue_row, _ = chrome.form_row(
            width, "Sound cues", [self.sound_switch],
            "A short blip when recording starts, ends, or is ignored.",
            note_indent=True)

        self.volume = NSSlider.alloc().initWithFrame_(
            NSMakeRect(0, 0, 180.0, 22.0))
        self.volume.setMinValue_(0.0)
        self.volume.setMaxValue_(1.0)
        self.volume.setDoubleValue_(float(getattr(self.app.cues, "volume", 0.35)))
        self.volume.setTarget_(self)
        self.volume.setAction_("volumeChanged:")
        vol_row, _ = chrome.form_row(width, "Volume", [self.volume])

        self._stack([("Input", [device_row, level_row]),
                     ("Cues", [cue_row, vol_row])])
        return "Changes apply immediately"

    # ---- Behaviour

    @python_method
    def _pane_behaviour(self):
        width = self._pane_width() - PANE_X * 2
        import loginitem

        self.login_switch = NSSwitch.alloc().initWithFrame_(
            NSMakeRect(0, 0, 38.0, 22.0))
        self.login_switch.setState_(1 if loginitem.enabled() else 0)
        self.login_switch.setTarget_(self)
        self.login_switch.setAction_("loginChanged:")
        login_row, _ = chrome.form_row(
            width, "Open at Login", [self.login_switch],
            "shout is a menu-bar app with no Dock icon, so without this it "
            "will not come back after a restart.", note_indent=True)

        paste_row, _ = chrome.form_row(
            width, "Where text goes",
            [chrome.label("The app in front of you", "rowLabel", tokens.FG)],
            "shout pastes unless it can positively tell the focused field is "
            "not editable, in which case the text is left on the clipboard "
            "and the overlay says so. Guessing wrong in the other direction "
            "loses the dictation entirely.")

        vocab_btn = chrome.button("Edit config.yaml…", self, "editConfig:")
        vocab_row, _ = chrome.form_row(
            width, "Vocabulary", [], trailing=vocab_btn, note=
            "Replacement rules and per-app profiles live in config.yaml, "
            "which is hand-edited so its comments survive.", note_indent=True)

        self._stack([("Startup", [login_row]),
                     ("Text", [paste_row, vocab_row])])
        return "Changes apply immediately"

    # ---- Permissions

    @python_method
    def _pane_permissions(self):
        width = self._pane_width() - PANE_X * 2
        self.perm_rows = []

        def make(title, anchor, note):
            pill = chrome.StatusPill.alloc().initWithFrame_(
                NSMakeRect(0, 0, 120.0, 24.0))
            btn = chrome.button("Open System Settings", self, "openPane:")
            btn.setTag_(len(self.perm_rows))
            row, _ = chrome.form_row(width, title, [pill], note=note,
                                     trailing=btn)
            self.perm_rows.append((anchor, pill, btn))
            return row

        rows = [
            make("Microphone", "Privacy_Microphone",
                 "So shout can hear you. Audio never leaves this Mac."),
            make("Accessibility", "Privacy_Accessibility",
                 "So shout can type the text into whatever app you are using."),
            make("Input Monitoring", "Privacy_ListenEvent",
                 "Usually needed for the shortcut. If “Keys arriving” lights "
                 "up on the Shortcut pane, you do not need it."),
        ]
        self._stack([("Granted by you", rows)])
        return "macOS re-checks these every second"

    # ---- History

    @python_method
    def _pane_history(self):
        #  The table manages its own scrolling, so the pane is sized to the
        #  visible area and the outer scroll view has nothing to scroll.
        visible = self.scroll.contentView().bounds().size
        #  Resize the document view BEFORE adding the pane. The pane tracks
        #  its container's width, so adding it first makes it absorb the very
        #  resize that is meant to fit it — and its right-hand column falls
        #  off the edge.
        self.body.setFrameSize_(visible)
        self.history_view = history_view.HistoryPane.alloc().initWithFrame_store_(
            NSMakeRect(0, 0, visible.width, visible.height), self.history)
        self.history_view.setAutoresizingMask_(2 | 16)
        self.body.addSubview_(self.history_view)

        reveal = chrome.button("Reveal in Finder", self, "revealHistory:")
        clear = chrome.button("Clear all…", self, "clearHistory:")
        clear.setContentTintColor_(tokens.RECORD)
        self.foot_extra = [clear, reveal]
        for btn in self.foot_extra:
            self.footer.addSubview_(btn)
        self.quit_btn.setHidden_(True)
        self.setup_btn.setHidden_(True)
        return "history.jsonl · on this Mac"

    # ------------------------------------------------------------ syncing

    @python_method
    def _min_press_ms(self):
        import shout
        return getattr(self.app.cfg, "min_press_ms", shout.MIN_UTTERANCE_SEC * 1000)

    @python_method
    def _device_label(self):
        name = self.input_device or "System default"
        return f"{name} · 16 kHz"

    @python_method
    def _sync(self):
        """Refresh whatever the current pane shows. Cheap enough to run on
        every tick, because everything here is a label or a small view."""
        self.quit_btn.setHidden_(self.pane == "history")
        self.setup_btn.setHidden_(self.pane == "history")

        count = len(self.history.entries) if self.history else 0
        self.source_rows["history"].set_badge(str(count) if count else "")

        if self.pane == "shortcut":
            if self.recording:
                chrome.set_text(self.chord_field, "Press a combination…",
                                "rowLabel", tokens.ACCENT)
                self.record_btn.setTitle_("Cancel")
            else:
                chrome.set_text(self.chord_field, self.hotkey.label(),
                                "rowLabel", tokens.FG)
                self.record_btn.setTitle_("Change…")
            if getattr(self, "mode_row", None) is not None:
                chrome.set_text(self.mode_row.note, MODE_HELP[self.mode],
                                "note", tokens.MUTED)

        if self.pane == "permissions":
            self._sync_permissions()

    @python_method
    def _sync_permissions(self):
        from ApplicationServices import AXIsProcessTrusted
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        import shout

        states = [
            AVCaptureDevice.authorizationStatusForMediaType_(
                AVMediaTypeAudio) == 3,
            bool(AXIsProcessTrusted()),
            shout.input_monitoring_status() == 0,
        ]
        for (anchor, pill, btn), ok in zip(self.perm_rows, states):
            pill.set_state("Granted" if ok else "Not granted", ok)
            btn.setHidden_(bool(ok))

    # ----------------------------------------------------------- feeding

    @python_method
    def push_level(self, level):
        for name in ("meter", "meter2"):
            meter = getattr(self, name, None)
            if meter is not None and meter.window() is not None:
                meter.set_level(level)

    @python_method
    def push_state(self, state):
        """The app pushes its state here so "Keys arriving" can light the
        moment shout receives exactly the bound chord — which is the only way
        to tell a wrong chord apart from one another app swallowed."""
        pill = getattr(self, "keys_pill", None)
        if pill is None or pill.window() is None:
            return
        down = state == "recording"
        pill.set_state("Being pressed now" if down else "Not being pressed", down)

    # ----------------------------------------------------------- actions

    def modeChanged_(self, sender):
        self.mode = MODE_HOLD if sender.selectedSegment() == 0 else MODE_TOGGLE
        self._apply()
        self._sync()

    def minPressChanged_(self, sender):
        digits = "".join(c for c in sender.stringValue() if c.isdigit())
        ms = max(0, min(2000, int(digits or 0)))
        sender.setStringValue_(f"{ms} ms")
        self.app.apply_min_press(ms)

    def deviceChanged_(self, sender):
        title = str(sender.titleOfSelectedItem() or "")
        self.input_device = None if title == "System default" else title
        self._apply()

    def soundChanged_(self, sender):
        self.app.apply_sound(bool(sender.state()))

    def volumeChanged_(self, sender):
        self.app.apply_volume(float(sender.doubleValue()))

    def loginChanged_(self, sender):
        import loginitem
        ok, msg = loginitem.set_enabled(bool(sender.state()))
        if not ok:
            sender.setState_(0 if sender.state() else 1)
            chrome.set_text(self.foot_note, msg, "note", tokens.RECORD)
            self.foot_note.sizeToFit()

    def editConfig_(self, sender):
        subprocess.run(["open", "-t", str(paths.config_file())], check=False)

    def openPane_(self, sender):
        anchor = self.perm_rows[sender.tag()][0]
        subprocess.run(
            ["open",
             f"x-apple.systempreferences:com.apple.preference.security?{anchor}"],
            check=False)

    def searchChanged_(self, sender):
        view = getattr(self, "history_view", None)
        if view is not None:
            view.set_query(str(sender.stringValue()))

    def revealHistory_(self, sender):
        subprocess.run(["open", "-R", str(self.history.path)], check=False)

    def clearHistory_(self, sender):
        count = len(self.history.entries) if self.history else 0
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Clear all history?")
        alert.setInformativeText_(
            f"{count} transcriptions will be deleted from this Mac. "
            f"This cannot be undone.")
        alert.addButtonWithTitle_("Clear")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() == 1000:
            if self.history:
                self.history.clear()
            self.history_view.reload()
            self._sync()

    def runSetup_(self, sender):
        self.window.close()
        self.app.show_setup()

    def quitApp_(self, sender):
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Quit shout?")
        alert.setInformativeText_(
            "Dictation will stop working until you open shout again.")
        alert.addButtonWithTitle_("Quit")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() == 1000:
            self.window.close()
            self.app.on_quit(None)

    # ------------------------------------------------------ chord capture

    def toggleRecording_(self, sender):
        self._stop_recording() if self.recording else self._start_recording()

    @python_method
    def _start_recording(self):
        self.recording = True
        self.recorder.reset()
        self._sync()

        def handler(event):
            kind = event.type()
            flags = int(event.modifierFlags())

            if kind == NSEventTypeKeyDown:
                code = event.keyCode()
                print(f"[record] keyDown code={code} flags=0x{flags:08x}",
                      flush=True)
                if code == 53:                       # Escape cancels
                    self._stop_recording()
                    return None
                self.hotkey = self.recorder.on_key(code, flags)
                self._stop_recording()
                self._apply()
                return None

            if kind == NSEventTypeFlagsChanged:
                result = self.recorder.on_flags(flags)
                #  Logged because chord capture depends on the device-dependent
                #  modifier bits, and whether a given keyboard supplies them is
                #  not otherwise observable.
                from hotkey import keys_down
                print(f"[record] flags=0x{flags:08x} down={keys_down(flags)} "
                      f"-> {result[0] if result else None}"
                      f"{' ' + result[1].label() if result else ''}", flush=True)
                if result is None:
                    return None
                what, hk = result
                if what == "preview":
                    chrome.set_text(self.chord_field, hk.label(), "rowLabel",
                                    tokens.ACCENT)
                else:
                    self.hotkey = hk
                    self._stop_recording()
                    self._apply()
                return None

            return event

        self.monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown | NSEventMaskFlagsChanged, handler)

    @python_method
    def _stop_recording(self):
        if self.monitor is not None:
            NSEvent.removeMonitor_(self.monitor)
            self.monitor = None
        self.recording = False
        self._sync()

    @python_method
    def _apply(self):
        self.app.apply_hotkey(self.hotkey, self.mode, self.input_device)

    # -------------------------------------------------------------- show

    def tick_(self, timer):
        self._sync()

    @python_method
    def show(self):
        view = getattr(self, "history_view", None)
        if view is not None and self.pane == "history":
            view.reload()
        # LSUIElement apps start non-activating, so without this the window
        # opens behind everything and never becomes key — which means the
        # local event monitor would never fire.
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        if self.level_timer is None:
            self.level_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0, self, "tick:", None, True)


class Hairline(NSView):
    def drawRect_(self, rect):
        tokens.BORDER.set()
        from AppKit import NSBezierPath
        NSBezierPath.fillRect_(self.bounds())


class ClickCatcher(NSView):
    """Transparent overlay on the sidebar that routes clicks to source rows."""

    def initWithFrame_(self, frame):
        self = objc.super(ClickCatcher, self).initWithFrame_(frame)
        if self is None:
            return None
        self.controller = None
        return self

    def mouseDown_(self, event):
        where = self.convertPoint_fromView_(event.locationInWindow(), None)
        for key, row in self.controller.source_rows.items():
            if row.hitTest_(self.convertPoint_toView_(where, row.superview())):
                self.controller.select_(key)
                return
