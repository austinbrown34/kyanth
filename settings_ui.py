"""Settings window.

rumps only offers a single-line text prompt, which can't record a key
combination — so this is a plain Cocoa window built with pyobjc.

The recorder captures both kinds of binding:
  * a modifier-only key (right-Option, fn) via `flagsChanged`
  * a regular key, with modifiers, via `keyDown`

A *local* NSEvent monitor is used rather than a global one: it only sees events
while this window is key, so recording can't swallow keystrokes meant for other
apps, and it needs no extra permission.
"""

import time

import objc
from AppKit import (
    NSAlert,
    NSApp,
    NSApplication,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSButton,
    NSColor,
    NSEvent,
    NSEventMaskFlagsChanged,
    NSEventMaskKeyDown,
    NSEventTypeFlagsChanged,
    NSEventTypeKeyDown,
    NSFont,
    NSMakeRect,
    NSPasteboard,
    NSPasteboardTypeString,
    NSScrollView,
    NSSegmentedControl,
    NSTableColumn,
    NSTableView,
    NSTabView,
    NSTabViewItem,
    NSTextField,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject

from hotkey import MODE_HOLD, MODE_TOGGLE, ChordRecorder, Hotkey

W, H = 500, 452
FOOTER = 52          # persistent strip below the tabs, visible on every tab
TAB_H = H - 24 - FOOTER

MODE_HELP = {
    MODE_HOLD: "Hold the key while you speak. Release to transcribe.",
    MODE_TOGGLE: "Press once to start, press again to stop and transcribe.",
}


def _label(text, x, y, w, h, size=13, bold=False, color=None):
    f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    f.setStringValue_(text)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold
               else NSFont.systemFontOfSize_(size))
    if color is not None:
        f.setTextColor_(color)
    return f


class SettingsController(NSObject):
    """Owns the window. `on_apply(hotkey, mode)` is called when the user saves."""

    def initWithHotkey_mode_history_onApply_onQuit_(self, hk, mode, hist,
                                                    on_apply, on_quit):
        self = objc.super(SettingsController, self).init()
        if self is None:
            return None
        self.hotkey = hk
        self.mode = mode if mode in (MODE_HOLD, MODE_TOGGLE) else MODE_HOLD
        self.history = hist
        self.rows = []
        self.on_apply = on_apply
        self.on_quit = on_quit
        self.monitor = None
        self.recording = False
        self.recorder = ChordRecorder()
        self._build()
        return self

    # ---------------------------------------------------------------- ui

    def _build(self):
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered, False,
        )
        self.window.setTitle_("shout")
        self.window.setReleasedWhenClosed_(False)

        tabs = NSTabView.alloc().initWithFrame_(
            NSMakeRect(12, FOOTER, W - 24, TAB_H))
        self.window.contentView().addSubview_(tabs)

        #  Quitting lives outside the tab view so it is reachable from either
        #  tab. It matters more than it looks: when the menu bar is full macOS
        #  hides the status icon, and this window is then the only way to quit.
        quit_btn = NSButton.alloc().initWithFrame_(NSMakeRect(16, 12, 132, 30))
        quit_btn.setTitle_("Quit shout")
        quit_btn.setBezelStyle_(NSBezelStyleRounded)
        quit_btn.setTarget_(self)
        quit_btn.setAction_("quitApp:")
        self.window.contentView().addSubview_(quit_btn)

        self.window.contentView().addSubview_(
            _label("Dictation stops until you open shout again.",
                   158, 17, W - 174, 18, 11,
                   color=NSColor.secondaryLabelColor()))

        shortcut = NSTabViewItem.alloc().initWithIdentifier_("shortcut")
        shortcut.setLabel_("Shortcut")
        shortcut.setView_(self._shortcut_view())
        tabs.addTabViewItem_(shortcut)

        hist = NSTabViewItem.alloc().initWithIdentifier_("history")
        hist.setLabel_("History")
        hist.setView_(self._history_view())
        tabs.addTabViewItem_(hist)

        self._refresh()

    def _shortcut_view(self):
        from AppKit import NSView
        h = TAB_H - 36
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W - 24, h))

        v.addSubview_(_label("Activation", 20, h - 44, 200, 20, 15, bold=True))

        self.seg = NSSegmentedControl.alloc().initWithFrame_(
            NSMakeRect(20, h - 84, W - 64, 28))
        self.seg.setSegmentCount_(2)
        self.seg.setLabel_forSegment_("Hold to talk", 0)
        self.seg.setLabel_forSegment_("Toggle on / off", 1)
        self.seg.setWidth_forSegment_((W - 64) / 2, 0)
        self.seg.setWidth_forSegment_((W - 64) / 2, 1)
        self.seg.setSelectedSegment_(0 if self.mode == MODE_HOLD else 1)
        self.seg.setTarget_(self)
        self.seg.setAction_("modeChanged:")
        v.addSubview_(self.seg)

        self.mode_help = _label(MODE_HELP[self.mode], 20, h - 110, W - 64, 18, 11,
                                color=NSColor.secondaryLabelColor())
        v.addSubview_(self.mode_help)

        v.addSubview_(_label("Shortcut", 20, h - 158, 200, 20, 15, bold=True))

        self.record_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(20, h - 200, W - 64, 32))
        self.record_btn.setBezelStyle_(NSBezelStyleRounded)
        self.record_btn.setTarget_(self)
        self.record_btn.setAction_("toggleRecording:")
        v.addSubview_(self.record_btn)

        self.hint = _label("", 20, h - 226, W - 64, 18, 11,
                           color=NSColor.secondaryLabelColor())
        v.addSubview_(self.hint)

        cancel = NSButton.alloc().initWithFrame_(NSMakeRect(W - 214, 14, 84, 32))
        cancel.setTitle_("Cancel")
        cancel.setBezelStyle_(NSBezelStyleRounded)
        cancel.setTarget_(self); cancel.setAction_("cancel:")
        v.addSubview_(cancel)

        save = NSButton.alloc().initWithFrame_(NSMakeRect(W - 124, 14, 84, 32))
        save.setTitle_("Save")
        save.setBezelStyle_(NSBezelStyleRounded)
        save.setKeyEquivalent_("\r")
        save.setTarget_(self); save.setAction_("save:")
        v.addSubview_(save)
        return v

    def _history_view(self):
        from AppKit import NSView
        h = TAB_H - 36
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, W - 24, h))

        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(16, 62, W - 56, h - 82))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(2)          # NSBezelBorder

        self.table = NSTableView.alloc().initWithFrame_(scroll.bounds())
        col = NSTableColumn.alloc().initWithIdentifier_("text")
        col.setWidth_(W - 90)
        col.headerCell().setStringValue_("Recent transcriptions")
        self.table.addTableColumn_(col)
        self.table.setDataSource_(self)
        self.table.setDelegate_(self)
        self.table.setRowHeight_(20.0)
        self.table.setTarget_(self)
        self.table.setDoubleAction_("copySelected:")
        scroll.setDocumentView_(self.table)
        v.addSubview_(scroll)

        self.hist_hint = _label("Double-click a line, or select and press Copy.",
                                16, 40, W - 56, 18, 11,
                                color=NSColor.secondaryLabelColor())
        v.addSubview_(self.hist_hint)

        copy = NSButton.alloc().initWithFrame_(NSMakeRect(16, 4, 110, 32))
        copy.setTitle_("Copy")
        copy.setBezelStyle_(NSBezelStyleRounded)
        copy.setTarget_(self); copy.setAction_("copySelected:")
        v.addSubview_(copy)

        clear = NSButton.alloc().initWithFrame_(NSMakeRect(W - 140, 4, 110, 32))
        clear.setTitle_("Clear All")
        clear.setBezelStyle_(NSBezelStyleRounded)
        clear.setTarget_(self); clear.setAction_("clearHistory:")
        v.addSubview_(clear)

        self.reload_history()
        return v

    def _refresh(self):
        if self.recording:
            self.record_btn.setTitle_("Press a key or combination…")
            self.hint.setStringValue_(
                "Hold several keys to build a chord. Esc to cancel.")
        else:
            self.record_btn.setTitle_(f"{self.hotkey.label()}    (click to change)")
            if self.hotkey.is_modifier_only:
                self.hint.setStringValue_(
                    "Modifier-only keys can't be typed, so nothing is stolen.")
            else:
                self.hint.setStringValue_(
                    "Intercepted system-wide — pick something unused.")
        self.mode_help.setStringValue_(MODE_HELP[self.mode])

    # ------------------------------------------------------------ history

    def reload_history(self):
        self.rows = self.history.recent() if self.history else []
        if getattr(self, "table", None) is not None:
            self.table.reloadData()

    #  NSTableView data source. Selectors must match Objective-C exactly.
    def numberOfRowsInTableView_(self, table):
        return len(self.rows)

    def tableView_objectValueForTableColumn_row_(self, table, column, row):
        if row >= len(self.rows):
            return ""
        e = self.rows[row]
        stamp = time.strftime("%b %-d  %-I:%M %p", time.localtime(e.when)) if e.when else ""
        flag = "  ⧉" if e.where == "clipboard" else ""
        text = e.text if len(e.text) <= 96 else e.text[:93] + "…"
        return f"{stamp}{flag}   {text}"

    def copySelected_(self, sender):
        row = self.table.selectedRow()
        if row < 0 or row >= len(self.rows):
            return
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(self.rows[row].text, NSPasteboardTypeString)
        self.hist_hint.setStringValue_("Copied to clipboard — paste with ⌘V.")

    def clearHistory_(self, sender):
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Clear all history?")
        alert.setInformativeText_(
            f"{len(self.rows)} transcriptions will be deleted from this Mac.")
        alert.addButtonWithTitle_("Clear")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() == 1000:      # first button
            if self.history:
                self.history.clear()
            self.reload_history()
            self.hist_hint.setStringValue_("History cleared.")

    # ----------------------------------------------------------- actions

    def modeChanged_(self, sender):
        self.mode = MODE_HOLD if sender.selectedSegment() == 0 else MODE_TOGGLE
        self._refresh()

    def toggleRecording_(self, sender):
        self._stop_recording() if self.recording else self._start_recording()

    def _start_recording(self):
        self.recording = True
        self.recorder.reset()
        self._refresh()

        def handler(event):
            kind = event.type()
            flags = int(event.modifierFlags())

            if kind == NSEventTypeKeyDown:
                code = event.keyCode()
                print(f"[record] keyDown code={code} flags=0x{flags:08x}", flush=True)
                if code == 53:                       # Escape cancels
                    self._stop_recording()
                    return None
                self.hotkey = self.recorder.on_key(code, flags)
                self._stop_recording()
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
                    self.record_btn.setTitle_(f"{hk.label()}    (release to set)")
                else:
                    self.hotkey = hk
                    self._stop_recording()
                return None

            return event

        self.monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown | NSEventMaskFlagsChanged, handler)

    def _stop_recording(self):
        if self.monitor is not None:
            NSEvent.removeMonitor_(self.monitor)
            self.monitor = None
        self.recording = False
        self._refresh()

    def quitApp_(self, sender):
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Quit shout?")
        alert.setInformativeText_(
            "Dictation will stop working until you open shout again.")
        alert.addButtonWithTitle_("Quit")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() == 1000:          # first button
            self.window.close()
            if self.on_quit:
                self.on_quit()

    def cancel_(self, sender):
        self._stop_recording()
        self.window.close()

    def save_(self, sender):
        self._stop_recording()
        self.on_apply(self.hotkey, self.mode)
        self.window.close()

    # ------------------------------------------------------------- show

    def show(self):
        self.reload_history()
        # LSUIElement apps start non-activating, so without this the window
        # opens behind everything and never becomes key — which means the
        # local event monitor would never fire.
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
