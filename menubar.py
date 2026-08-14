"""shout menubar app.

Owns the whisper-server subprocess and the dictation daemon, and shows state
in the menu bar. rumps runs an NSApplication, whose run loop the event tap
attaches to — hence Daemon.install() rather than Daemon.run().
"""

import fcntl
import os
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from pathlib import Path

import objc
import rumps
from Foundation import NSDistributedNotificationCenter, NSObject
from PyObjCTools import AppHelper

import config as config_mod
import history as history_mod
import loginitem
import menuheader
import overlay as overlay_mod
import shout
import sounds
import version
from hotkey import MODE_HOLD
from settings_ui import SettingsController
from setup_ui import SetupController

import paths

ROOT = paths.resources()
LOGDIR = paths.logs()
LOG = LOGDIR / "server.log"
HISTORY = 8

#  A second launch of an already-running app signals the live instance over
#  this notification rather than starting a rival process.
SHOW_SETTINGS_NOTE = "local.shout.dictation.showSettings"

ASSETS = paths.resources() / "assets"

#  Six states, six SHAPES — not three glyphs doing six jobs. `idle` and
#  `working` were previously identical, which was the single most-cited gap in
#  the v1.2.0 reference. Template images are recoloured by macOS for light and
#  dark menu bars; `recording` opts out so its red dot survives, which is the
#  one deliberate inconsistency the app already shipped. Opting out also means
#  macOS will not invert its bars, so recording ships in two tones and
#  `_icon_for` picks by appearance — otherwise a dark menu bar shows a lone
#  red dot with the mark missing.
ICONS = {
    "idle":             ("menubar-idle@2x.png",             True),
    "recording":        ("menubar-recording@2x.png",        False),
    "working":          ("menubar-transcribing-0@2x.png",   True),
    "disabled":         ("menubar-disabled@2x.png",         True),
    "needs-permission": ("menubar-needs-permission@2x.png", True),
    "error":            ("menubar-error@2x.png",            True),
}

#  `transcribing` animates: the taller stub walks left → centre → right on a
#  ~180 ms timer. The timer stops the moment the state leaves `working` — a
#  status item that keeps ticking is a battery complaint.
TRANSCRIBE_FRAMES = [f"menubar-transcribing-{i}@2x.png" for i in range(3)]
TRANSCRIBE_INTERVAL = 0.18

#  Resolution order lives in paths.whisper_server(): the vendored copy inside
#  the bundle first, then absolute Homebrew locations. launchd gives a
#  login-time process a minimal PATH, so a bare name would resolve during
#  testing and silently fail after a reboot.


#  Re-opening a running app (double-click in Applications, `open -a`) does NOT
#  start a second process — LaunchServices activates the existing one and sends
#  this delegate message. rumps owns the NSApplication delegate, so the handler
#  is grafted on as an Objective-C category. The category class must be named
#  exactly like the class it extends.
_reopen_target = None


class NSApp(objc.Category(rumps.rumps.NSApp)):
    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, flag):
        if _reopen_target is not None:
            AppHelper.callAfter(_reopen_target)
        return True


class _LaunchProbe(NSObject):
    """Records how this process was launched.

    A menu-bar app with no Dock icon has one discoverable way to reach its UI —
    clicking it in Applications — and when it is not already running that did
    nothing visible at all. Opening the window on every cold start is wrong the
    other way: the login item cold-starts too, and nobody wants Settings in
    their face at every login.

    LaunchServices distinguishes the two in the didFinishLaunching userInfo.
    Both signals are logged because XPC_SERVICE_NAME looks like it should work
    and does not — launchd names the service identically either way.
    """

    def initWithCallback_(self, cb):
        self = objc.super(_LaunchProbe, self).init()
        if self is None:
            return None
        self.cb = cb
        return self

    def handle_(self, note):
        info = note.userInfo() or {}
        flag = info.objectForKey_("NSApplicationLaunchIsDefaultLaunchKey")
        print(f"[start] launch: default={flag!r} "
              f"xpc={os.environ.get('XPC_SERVICE_NAME', '')!r}", flush=True)
        self.cb(None if flag is None else bool(flag))


class _NoteProxy(NSObject):
    """rumps.App is a plain Python class, so it cannot itself be an
    Objective-C notification observer. This forwards to a callable."""

    def initWithCallback_(self, cb):
        self = objc.super(_NoteProxy, self).init()
        if self is None:
            return None
        self.cb = cb
        return self

    def handle_(self, note):
        self.cb()


def find_server_binary() -> str | None:
    return paths.whisper_server()


class ServerManager:
    """whisper-server lifecycle. Owned by the app so quitting cleans it up
    rather than orphaning a 141MB resident model."""

    def __init__(self, model: str, port: int):
        self.model = model
        self.port = port
        self.proc: subprocess.Popen | None = None
        self.adopted = False

    def _listening(self) -> bool:
        with socket.socket() as s:
            s.settimeout(0.4)
            return s.connect_ex(("127.0.0.1", self.port)) == 0

    def start(self, timeout: float = 60.0) -> bool:
        if self._listening():
            # Someone already runs one (e.g. ./serve.sh). Don't start a second
            # on the same port, and don't kill it on quit.
            self.adopted = True
            return True

        binary = find_server_binary()
        if binary is None:
            return False

        LOG.parent.mkdir(parents=True, exist_ok=True)

        # No --convert: we always hand it 16 kHz mono WAV, and --convert makes
        # whisper-server shell out to ffmpeg, which is not on a login-time PATH.
        model = paths.model_path(self.model)
        self.proc = subprocess.Popen(
            [binary, "-m", str(model),
             "--host", "127.0.0.1", "--port", str(self.port)],
            stdout=open(LOG, "a"), stderr=subprocess.STDOUT,
            cwd=str(Path(binary).parent), env=paths.whisper_env(),
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._listening():
                return True
            if self.proc.poll() is not None:
                return False
            time.sleep(0.25)
        return False

    def stop(self):
        if self.proc and not self.adopted:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def restart(self) -> bool:
        self.stop()
        self.proc, self.adopted = None, False
        return self.start()


class ShoutApp(rumps.App):
    def __init__(self):
        icon = ASSETS / ICONS["idle"][0]
        super().__init__("shout", icon=str(icon) if icon.exists() else None,
                         template=True, title=None, quit_button=None)

        self.cfg = config_mod.load()
        self.store = history_mod.History(paths.history_file())
        self.history: deque[str] = deque(maxlen=HISTORY)
        self.jobs: queue.Queue = queue.Queue()
        self.server = ServerManager(self.cfg.model, shout.SERVER_PORT)
        self.recorder = None
        self.daemon = None
        self._warned_listen = False
        self._icon_state = None
        self._icon_dark = None       # skip redundant NSImage rebuilds
        #  None until didFinishLaunching tells us. Unknown is treated as "not
        #  a user launch": a Settings window nobody asked for at every login is
        #  worse than one missing click.
        self.user_launched = None
        self._watch_launch()
        self._transcribe_timer = None
        self._transcribe_frame = 0
        self.mic_ok = False
        self._level_timer = None
        self.overlay = overlay_mod.Overlay.alloc().init()

        #  Six rows in three groups. The status line became a header view, so
        #  it no longer truncates to the menu width and can carry the live
        #  meter and the chord in key caps. The five diagnostics moved behind
        #  Advanced; Sound cues and Open at Login moved to Settings, where
        #  preferences belong.
        self.status_item = rumps.MenuItem("")
        self.header = menuheader.make(self._chord_labels(), self._mode_hint())
        self.status_item._menuitem.setView_(self.header)

        self.toggle_item = rumps.MenuItem("Enabled", callback=self.on_toggle)
        self.toggle_item.state = True
        self.history_menu = rumps.MenuItem("Recent transcriptions")

        advanced = rumps.MenuItem("Advanced")
        for title, cb in (("Edit Config…", self.on_edit_config),
                          ("Reload Config", self.on_reload),
                          ("Restart Model Server", self.on_restart_server),
                          ("Check for Updates…", self.on_check_updates),
                          ("Open Log", self.on_open_log)):
            advanced.add(rumps.MenuItem(title, callback=cb))

        settings_item = rumps.MenuItem("Settings & History…",
                                       callback=self.on_settings, key=",")
        quit_item = rumps.MenuItem("Quit shout", callback=self.on_quit, key="q")

        self.menu = [
            self.status_item,
            None,
            self.toggle_item,
            self.history_menu,
            None,
            settings_item,
            rumps.MenuItem("Re-run Setup Check…", callback=self.show_setup),
            None,
            advanced,
            None,
            quit_item,
        ]

    # ---------------------------------------------------------- lifecycle

    def start(self) -> bool:
        """Never show a modal here: rumps.alert() before app.run() has no
        running NSApplication behind it, so the alert is invisible AND modal —
        the process hangs with a menu-bar icon and no way to interact. Problems
        are surfaced in the menu instead, and the app stays up."""
        problems = self.preflight()
        if problems:
            self.status_item.title = problems[0].splitlines()[0]
            self.set_state("error")
            print("preflight problems:", problems, file=sys.stderr)
            # Guidance matters most when the app cannot start at all.
            self._observe_show_settings()
            AppHelper.callAfter(self.show_setup)
            return True

        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        mic = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
        print(f"[start] model={self.cfg.model} mic_auth={mic} "
              f"(0=undetermined 2=denied 3=granted)")

        # On a fresh install the app is a new TCC identity with no grants.
        # Opening an input stream before asking raises and kills startup, so
        # request first and let the retry timer pick it up once granted.
        if mic == 0:
            AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AVMediaTypeAudio, lambda granted: None)
        from ApplicationServices import AXIsProcessTrusted
        print(f"[start] accessibility={AXIsProcessTrusted()} "
              f"input_monitoring={shout.input_monitoring_status()} "
              f"(0=granted 1=denied 2=undetermined)")

        self.cues = sounds.Cues(paths.cues(), enabled=self.cfg.sound,
                                volume=self.cfg.volume)
        print(f"[start] frozen={paths.FROZEN} open at login: {loginitem.status_label()}")
        print(f"[start] sound cues: {'on' if self.cfg.sound else 'off'} "
              f"(volume {self.cfg.volume})")

        # Register these BEFORE anything that can fail. They are how the user
        # reaches the app at all: with a full menu bar the icon is hidden, and
        # a menu-bar app has no window, so re-opening from Applications is the
        # only remaining route to Settings. Gating them behind a successful
        # start made the app unreachable in exactly the situation — missing
        # permissions — where it most needs to be reached.
        self._observe_show_settings()
        self._offer_login_item()

        # Do NOT touch the audio device before the microphone is granted:
        # opening an input stream *blocks* while macOS shows its prompt, which
        # froze startup before the setup window could ever be drawn. Show the
        # guide instead and let the retry timer open the device afterwards.
        if mic != 3:
            print("[start] microphone not granted yet — showing setup")
            self.set_state("needs-permission")
            self.status_item.title = "Waiting for microphone access…"
            rumps.Timer(self.retry_start, 2).start()
            AppHelper.callAfter(self.show_setup)
            return True

        try:
            self.recorder = shout.Recorder(
                device=shout.resolve_input_device(self.cfg.input_device),
                lead_skip_ms=self.cues.lead_ms)
            #  The device is opened lazily now, so constructing the Recorder no
            #  longer proves the microphone works. Probe once — open and
            #  immediately release — so setup can report a real answer without
            #  holding the device or flashing the indicator on every poll.
            self.mic_ok = self.recorder.probe()
            print(f"[start] input device: "
                  f"{self.cfg.input_device or 'system default'} "
                  f"(usable={self.mic_ok})")
        except Exception as e:
            print(f"[start] microphone unavailable: {e}")
            self.set_state("needs-permission")
            self.status_item.title = "Waiting for microphone access…"
            rumps.Timer(self.retry_start, 2).start()
            AppHelper.callAfter(self.show_setup)
            return True
        threading.Thread(
            target=shout.worker,
            args=(self.jobs, self.cfg, True, self.set_state, self.on_result,
                  self.cues),
            daemon=True,
        ).start()

        self.daemon = shout.Daemon(
            self.recorder, self.jobs, verbose=True, on_state=self.set_state,
            binding=self.cfg.hotkey, mode=self.cfg.mode, cues=self.cues,
            min_press_ms=self.cfg.min_press_ms,
        )
        self.daemon.on_hint = lambda title, msg: AppHelper.callAfter(
            rumps.notification, "shout", title, msg)
        print(f"[start] hotkey={self.cfg.hotkey.label()} mode={self.cfg.mode}")
        if not self.install_tap():
            # Ask macOS to show its own "open System Settings" prompt, then
            # poll — granting Accessibility takes effect without a relaunch.
            self.request_permissions()
            self.set_state("needs-permission")
            self.status_item.title = "Grant permissions, then wait…"
            rumps.Timer(self.retry_tap, 2).start()
            # Show the guided setup rather than the settings window: the user
            # needs to be told which switch to flip, and told when it worked.
            AppHelper.callAfter(self.show_setup)
            return True

        print("[start] event tap installed — ready")
        self.set_state("idle")
        self._surface_on_user_launch()
        return True

    def _watch_launch(self):
        from Foundation import NSNotificationCenter

        def note(is_default):
            self.user_launched = is_default

        #  Held on self: the notification centre does not retain observers, and
        #  a collected proxy stops delivering without saying so.
        self._launch_probe = _LaunchProbe.alloc().initWithCallback_(note)
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self._launch_probe, "handle:",
            "NSApplicationDidFinishLaunchingNotification", None)

    def _surface_on_user_launch(self):
        """A cold start the user asked for should land somewhere visible."""
        if not self.user_launched:
            return
        print("[start] user launch — opening Settings", flush=True)
        AppHelper.callAfter(self.on_settings)

    def _observe_show_settings(self):
        """Opening shout again from the Applications folder should surface
        Settings rather than silently doing nothing."""
        global _reopen_target
        _reopen_target = self.on_reopen

        # Held on self: the observer is not retained by the notification
        # centre, and a collected proxy stops delivering silently.
        self._note_proxy = _NoteProxy.alloc().initWithCallback_(
            lambda: AppHelper.callAfter(self.on_reopen))
        NSDistributedNotificationCenter.defaultCenter(
        ).addObserver_selector_name_object_(
            self._note_proxy, "handle:", SHOW_SETTINGS_NOTE, None)

    def retry_start(self, timer):
        """Poll until every grant is in place, then finish starting. Lets a
        first-run user grant permissions without relaunching the app."""
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio

        if AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio) != 3:
            return
        if self.recorder is None:
            try:
                self.recorder = shout.Recorder(
                    device=shout.resolve_input_device(self.cfg.input_device),
                    lead_skip_ms=self.cues.lead_ms)
            except Exception:
                return
            threading.Thread(
                target=shout.worker,
                args=(self.jobs, self.cfg, True, self.set_state, self.on_result,
                      self.cues),
                daemon=True,
            ).start()
            self.daemon = shout.Daemon(
                self.recorder, self.jobs, verbose=True, on_state=self.set_state,
                binding=self.cfg.hotkey, mode=self.cfg.mode, cues=self.cues,
                min_press_ms=self.cfg.min_press_ms,
            )
        if self.install_tap():
            timer.stop()
            self.set_state("idle")
            print("[start] permissions granted — ready")
            rumps.notification("shout", "Ready", "Hold your shortcut to dictate.")
        else:
            self.request_permissions()

    def _offer_login_item(self):
        """Register at login once, on first successful start. A menu-bar
        dictation tool is useless if it isn't running, so the default is on —
        but only offered once, so turning it off sticks."""
        if not loginitem.available():
            return
        if config_mod.load_settings().get("login_offered"):
            return
        ok, msg = loginitem.set_enabled(True)
        config_mod.mark_login_offered()
        print(f"[login] first run, registered at login: {ok} ({msg})")

    def install_tap(self) -> bool:
        """Accessibility is the hard requirement; Input Monitoring is advisory.

        Treating Input Monitoring as mandatory was wrong: macOS does not
        re-prompt for it once denied, and a freshly installed app is often not
        in that list at all — so the check became a gate the app could never
        pass, and the hotkey silently never installed. Attempt the tap on
        Accessibility alone and warn if the other grant is missing.
        """
        from ApplicationServices import AXIsProcessTrusted

        if not AXIsProcessTrusted():
            return False
        if shout.input_monitoring_status() != 0 and not self._warned_listen:
            self._warned_listen = True
            print("[perm] Input Monitoring not granted — installing the tap "
                  "anyway; if the hotkey does nothing, add shout under "
                  "System Settings > Privacy & Security > Input Monitoring")
        return bool(self.daemon and self.daemon.install())

    def request_permissions(self):
        from ApplicationServices import (
            AXIsProcessTrusted,
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
        missing = []
        if not AXIsProcessTrusted():
            AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
            missing.append("Accessibility")
        if shout.input_monitoring_status() != 0:
            shout.request_input_monitoring()
            missing.append("Input Monitoring")
        print(f"[perm] requesting: {', '.join(missing) or 'nothing'}")

    def retry_tap(self, timer):
        if self.install_tap():
            timer.stop()
            self.set_state("idle")
            rumps.notification("shout", "Ready",
                               f"Hold {self.cfg.hotkey.label()} to dictate.")

    def preflight(self) -> list[str]:
        problems = []
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio

        if AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio) == 2:
            problems.append("Microphone denied\n"
                            "System Settings > Privacy & Security > Microphone")

        model_path = paths.model_path(self.cfg.model)
        if not model_path.exists():
            problems.append(f"Model not found\n{model_path}")
        elif model_path.stat().st_size < 10_000_000:
            #  A truncated download otherwise fails at the first dictation,
            #  where it looks like a transcription bug rather than a bad file.
            problems.append(
                f"Model file looks truncated "
                f"({model_path.stat().st_size // 1_000_000} MB)\n{model_path}")
        elif find_server_binary() is None:
            problems.append("whisper-server not found\nbrew install whisper-cpp")
        elif not self.server.start():
            problems.append(f"Model server failed\nSee {LOG}")

        return problems

    # ---------------------------------------------------------- callbacks

    def set_state(self, state: str):
        """Safe to call from any thread — the worker calls this."""
        AppHelper.callAfter(self._apply_state, state)

    def _menu_bar_is_dark(self):
        from AppKit import NSApplication
        return NSApplication.sharedApplication().effectiveAppearance() \
            .bestMatchFromAppearancesWithNames_(
                ["NSAppearanceNameAqua", "NSAppearanceNameDarkAqua"]) \
            == "NSAppearanceNameDarkAqua"

    def _set_icon(self, state: str):
        name, template = ICONS.get(state, ICONS["idle"])
        dark = self._menu_bar_is_dark()
        if state == "recording" and dark:
            name = "menubar-recording-dark@2x.png"
        path = ASSETS / name
        if path.exists():
            self.template = template
            self.icon = str(path)
        self._icon_dark = dark

    def _apply_state(self, state: str):
        if state == "ignored":
            #  An outcome, not a status: the pill says "Nothing heard" and
            #  dismisses itself; the menu-bar icon stays idle.
            try:
                self.overlay.set_state(overlay_mod.IGNORED)
            except Exception:
                pass
            self._stop_level_feed()
            state = "idle"

        if self.daemon and not self.daemon.enabled:
            state = "disabled"

        #  The Shortcut pane's "Keys arriving" pill lights from this. It is
        #  the only way to tell a wrong chord apart from one another app
        #  swallowed, so it has to reflect the daemon and not the recorder.
        settings = getattr(self, "settings", None)
        if settings is not None and settings.window.isVisible():
            settings.push_state(state)

        #  Rebuild the status image only on a real change. rumps re-assigns
        #  .icon from inside its template setter, so a naive update allocated
        #  two NSImages per call — six per dictation — and the status item was
        #  reported vanishing after prolonged use.
        #  The appearance check rides along with the state change rather than
        #  an observer: `recording` is the only glyph that cares, it lasts
        #  seconds, and the next state change repaints it correctly anyway.
        if state != self._icon_state or self._icon_dark != self._menu_bar_is_dark():
            self._set_icon(state)
            self._icon_state = state
            self._set_transcribe_animation(state == "working")
            self._update_overlay(state)

        try:
            self.header.state = state
            self.header.chord = self._chord_labels()
            self.header.mode_hint = self._mode_hint()
            self.header.setNeedsDisplay_(True)
        except Exception:
            pass

        label = {
            "idle": (f"Ready — {'hold' if self.cfg.mode == MODE_HOLD else 'press'} "
                     f"{self.cfg.hotkey.label()}"),
            "recording": "Recording…",
            "working": "Transcribing…",
            "error": "Transcription failed",
            "disabled": "Disabled",
        }.get(state, state)
        self.status_item.title = label

    def _chord_labels(self):
        """The bound chord as separate key caps."""
        try:
            return [p.strip() for p in self.cfg.hotkey.label().split("+")]
        except Exception:
            return ["Right ⌥"]

    def _mode_hint(self):
        return "Hold" if self.cfg.mode == MODE_HOLD else "Press"

    def _set_transcribe_animation(self, running: bool):
        if running and self._transcribe_timer is None:
            self._transcribe_frame = 0
            self._transcribe_timer = rumps.Timer(self._tick_transcribe,
                                                 TRANSCRIBE_INTERVAL)
            self._transcribe_timer.start()
        elif not running and self._transcribe_timer is not None:
            self._transcribe_timer.stop()
            self._transcribe_timer = None

    def _tick_transcribe(self, _timer):
        self._transcribe_frame = (self._transcribe_frame + 1) % len(TRANSCRIBE_FRAMES)
        path = ASSETS / TRANSCRIBE_FRAMES[self._transcribe_frame]
        if path.exists():
            self.template = True
            self.icon = str(path)

    def _update_overlay(self, state: str):
        """Mirror the state onto the floating indicator.

        This is the only signal that survives a full menu bar and muted
        speakers, so it carries more weight than it looks.
        """
        try:
            if state == "recording":
                self.overlay.show(overlay_mod.LISTENING)
                self._start_level_feed()
            elif state == "working":
                self.overlay.set_state(overlay_mod.TRANSCRIBING)
                self._stop_level_feed()
            elif state == "error":
                self._stop_level_feed()
                self.overlay.set_state(overlay_mod.ERROR,
                                       "Model server not responding")
            else:
                self._stop_level_feed()
                #  An outcome pill dismisses itself; only clear the overlay
                #  here if nothing is showing an outcome.
                if not self.overlay.dismiss_timer:
                    self.overlay.hide()
        except Exception as exc:
            #  Logged, never raised: the indicator must not break dictation.
            print(f"[overlay] {state} failed: {exc}", flush=True)

    def _start_level_feed(self):
        if self._level_timer is not None:
            return
        self._level_timer = (
            rumps.Timer(self._push_level, 1.0 / 60.0))
        self._level_timer.start()

    def _stop_level_feed(self):
        if self._level_timer is not None:
            self._level_timer.stop()
            self._level_timer = None

    def _push_level(self, _timer):
        #  Fed from the existing Recorder rather than a second AVAudioEngine
        #  tap: opening another audio path would re-introduce the permanent
        #  microphone indicator that on-demand capture was built to fix.
        try:
            if self.recorder is not None:
                level = min(self.recorder.level * 6.0, 1.0)
                self.overlay.push_level(level)
                self.header.level = level
                self.header.setNeedsDisplay_(True)
                settings = getattr(self, "settings", None)
                if settings is not None and settings.window.isVisible():
                    settings.push_level(level)
        except Exception:
            pass

    def on_result(self, text: str, secs: float, ms: float, where: str = "pasted"):
        """Called from the worker thread. Plain data only.

        Nothing here may reach AppKit. That was survivable when the overlay was
        a fixed-size ripple, but the pill sizes itself to its message, so
        setting its state moves a window — and AppKit traps on a window moved
        off the main thread. It crashed the app after a dictation, which looks
        exactly like "shout stopped working".
        """
        app_name = shout.frontmost_app()
        self.store.add(history_mod.Entry(text, app_name,
                                         time.time(), ms, where, secs))
        mark = " ⧉" if where == "clipboard" else ""
        preview = text if len(text) <= 60 else text[:57] + "…"
        self.history.appendleft(f"{preview}{mark}   ({ms:.0f}ms)")
        setup = getattr(self, "setup", None)
        if setup is not None:
            setup.note_dictation()
        AppHelper.callAfter(self._present_result, where, app_name)

    def _present_result(self, where: str, app_name: str):
        """Everything on_result deferred, on the main thread."""
        try:
            if where == "clipboard":
                self.overlay.set_state(overlay_mod.CLIPBOARD)
            else:
                self.overlay.set_state(overlay_mod.PASTED,
                                       f"Pasted into {app_name}")
        except Exception as exc:
            print(f"[overlay] outcome failed: {exc}", flush=True)
        self._refresh_history()
        if where == "clipboard":
            rumps.notification("shout", "Copied to clipboard",
                               "No text field was focused — press ⌘V to paste.")

    def _refresh_history(self):
        # Not history_menu.clear(): rumps creates the backing NSMenu lazily on
        # first insert, so clear() raises AttributeError on an empty submenu —
        # which is exactly the state it is in for the very first transcription.
        if self.history_menu._menu is not None:
            self.history_menu.clear()
        for entry in self.history:
            self.history_menu.add(rumps.MenuItem(entry, callback=self.on_copy_history))

    def on_copy_history(self, sender):
        from AppKit import NSPasteboard, NSPasteboardTypeString

        text = sender.title.rsplit("   (", 1)[0]
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, NSPasteboardTypeString)

    def on_toggle(self, sender):
        sender.state = not sender.state
        if self.daemon:
            self.daemon.enabled = bool(sender.state)
        self.set_state("idle" if sender.state else "disabled")

    def on_toggle_sound(self, sender=None, on=None):
        """Kept as a method for Settings to call; no longer a menu row."""
        if on is None:
            on = not self.cues.enabled
        if sender is not None and hasattr(sender, "state"):
            sender.state = on
        self.cues.enabled = on
        config_mod.save_settings(self.cfg.hotkey, self.cfg.mode, sound=on)
        self.cfg = config_mod.load()
        if on:
            self.cues.play("start")     # confirm audibly
        print(f"[settings] sound cues {'on' if on else 'off'}")

    def on_toggle_login(self, sender):
        want = not sender.state
        ok, msg = loginitem.set_enabled(want)
        # Reflect the real state, not the intent: macOS can refuse, and a
        # checkbox that lies about it is worse than one that does nothing.
        sender.state = loginitem.enabled()
        print(f"[login] open-at-login -> {loginitem.status_label()} ({msg})")
        if not ok:
            rumps.notification("shout", "Could not change Open at Login", msg)

    def _reopen_input_device(self):
        """Switch microphones without a restart."""
        try:
            if self.recorder is not None:
                self.recorder.close()
            index = shout.resolve_input_device(self.cfg.input_device)
            self.recorder = shout.Recorder(device=index,
                                           lead_skip_ms=self.cues.lead_ms)
            if self.daemon is not None:
                self.daemon.recorder = self.recorder
            print(f"[audio] input device -> "
                  f"{self.cfg.input_device or 'system default'} (index {index})")
        except Exception as exc:
            print(f"[audio] could not open {self.cfg.input_device}: {exc}")
            rumps.notification("shout", "Microphone unavailable",
                               f"Could not open {self.cfg.input_device}.")

    def on_reload(self, _):
        self.cfg = config_mod.load()
        rumps.notification("shout", "Config reloaded",
                           "Model changes need a server restart.")

    def on_reopen(self, _=None):
        """Re-opening from Applications must land on whatever the user needs.

        It previously always showed Settings — so a user who closed the setup
        window with permissions still missing had no way back to the guide,
        and a hidden menu-bar icon left them with no route at all.
        """
        # Upgrade check belongs HERE, not in main(): `open -a` on a running app
        # sends a reopen event and never starts a second process, so the new
        # bundle's startup code is never reached. The running (old) instance is
        # the only one that sees the click, so it has to notice it has been
        # replaced and hand over.
        if self._relaunch_if_replaced():
            return
        if self.daemon is None or self.daemon.tap is None:
            self.show_setup()
        else:
            self.on_settings()

    def _relaunch_if_replaced(self) -> bool:
        """True if a newer build is installed and we relaunched into it."""
        try:
            installed = version.installed_version()
        except Exception:
            return False
        if not installed or not version.is_newer(installed, version.VERSION):
            return False

        print(f"[upgrade] {installed} is installed, running {version.VERSION} "
              f"— handing over")
        rumps.notification("shout", f"Updating to {installed}",
                           "shout will restart in a moment.")
        bundle = version.installed_bundle()
        version.clear_running()
        self.server.stop()
        if self.recorder:
            try:
                self.recorder.close()
            except Exception:
                pass
        # Detach the relaunch so it survives this process exiting, and give
        # the lock time to be released before the new copy grabs it.
        subprocess.Popen(
            ["/bin/sh", "-c",
             f'sleep 1.5; open -a "{bundle}"'],
            start_new_session=True)
        AppHelper.callAfter(os._exit, 0)
        return True

    def show_setup(self, _=None):
        existing = getattr(self, "setup", None)
        if existing is not None and existing.window.isVisible():
            existing.start()
            return
        self.setup = SetupController.alloc().initWithApp_(self)
        self.setup.start()

    def on_settings(self, _=None):
        existing = getattr(self, "settings", None)
        if existing is not None and existing.window.isVisible():
            existing.show()          # already open: just bring it forward
            return
        # Keep a reference: an NSWindowController that goes out of scope takes
        # its window with it.
        self.settings = SettingsController.alloc().initWithApp_(self)
        self.settings.show()

    def apply_hotkey(self, hk, mode, device=...):
        config_mod.save_settings(hk, mode, sound=self.cues.enabled,
                                 input_device=device)
        previous_device = self.cfg.input_device
        self.cfg = config_mod.load()
        if self.cfg.input_device != previous_device:
            self._reopen_input_device()
        if self.daemon:
            self.daemon.rebind(hk, mode)      # live, no restart
        self._apply_state("idle")
        print(f"[settings] hotkey={hk.label()} mode={mode}")
        rumps.notification("shout", "Shortcut updated",
                           f"{'Hold' if mode == MODE_HOLD else 'Toggle'}  {hk.label()}")

    def apply_min_press(self, ms: int):
        config_mod.save_settings(self.cfg.hotkey, self.cfg.mode,
                                 sound=self.cues.enabled, min_press_ms=ms)
        self.cfg = config_mod.load()
        if self.daemon:
            self.daemon.min_press_sec = max(0.0, ms / 1000.0)
        print(f"[settings] min_press={ms}ms")

    def apply_sound(self, on: bool):
        self.cues.enabled = bool(on)
        config_mod.save_settings(self.cfg.hotkey, self.cfg.mode, sound=bool(on))
        self.cfg = config_mod.load()
        print(f"[settings] sound={on}")

    def apply_volume(self, level: float):
        self.cues.volume = float(level)
        config_mod.save_settings(self.cfg.hotkey, self.cfg.mode,
                                 sound=self.cues.enabled, volume=float(level))
        self.cfg = config_mod.load()

    def on_edit_config(self, _):
        subprocess.run(["open", "-t", str(paths.config_file())])

    def on_restart_server(self, _):
        self.cfg = config_mod.load()
        self.server.model = self.cfg.model
        ok = self.server.restart()
        rumps.notification("shout", "Model server",
                           "Restarted" if ok else f"Failed — see {LOG}")

    def on_check_updates(self, _=None):
        def work():
            tag, msg = version.latest_release()
            if tag is None:
                body = msg
            elif version.is_newer(tag, version.VERSION):
                body = f"Version {tag} is available (you have {version.VERSION})."
                AppHelper.callAfter(subprocess.run,
                                    ["open", version.RELEASE_PAGE])
            else:
                body = f"shout {version.VERSION} is up to date."
            AppHelper.callAfter(rumps.notification, "shout", "Updates", body)
            print(f"[update] {body}")
        threading.Thread(target=work, daemon=True).start()

    def on_open_log(self, _):
        LOGDIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(LOGDIR)])

    def on_quit(self, _):
        version.clear_running()
        self.server.stop()
        if self.recorder:
            self.recorder.close()
        rumps.quit_application()
        os._exit(0)


def acquire_single_instance_lock():
    """Return the held lock file, or None if another instance owns it.

    Without this, every launch stacks another instance — launchd at login plus
    any manual `open -a` — each holding its own microphone stream and event tap.
    Five had accumulated during development before this was noticed.
    """
    LOGDIR.mkdir(parents=True, exist_ok=True)
    lock = open(paths.data() / ".shout.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    lock.write(str(os.getpid()))
    lock.flush()
    return lock


def _redirect_output() -> None:
    """A frozen bundle has no terminal, so an unredirected traceback vanishes
    and a crash looks like "it just doesn't start". Line-buffered because
    block-buffered output to a file stays invisible until the buffer fills."""
    if not paths.FROZEN:
        return
    log = paths.logs() / "app.log"
    stream = open(log, "a", buffering=1)
    os.dup2(stream.fileno(), sys.stdout.fileno())
    os.dup2(stream.fileno(), sys.stderr.fileno())
    sys.stdout = sys.stderr = stream


def main() -> int:
    _redirect_output()
    lock = acquire_single_instance_lock()
    if lock is None:
        # An upgrade must actually take effect. Without this the newly
        # installed build exits here and the OLD process keeps running, so the
        # user gets none of the fixes and no hint as to why.
        may_take_over, why = version.supersede_older()
        print(f"[upgrade] {why}", file=sys.stderr)
        if may_take_over:
            for _ in range(20):
                lock = acquire_single_instance_lock()
                if lock is not None:
                    break
                time.sleep(0.25)
        if lock is None:
            print("already running — asking the live instance to show Settings",
                  file=sys.stderr)
            NSDistributedNotificationCenter.defaultCenter(
            ).postNotificationName_object_userInfo_deliverImmediately_(
                SHOW_SETTINGS_NOTE, None, None, True)
            return 0

    version.record_running()
    print(f"[start] shout {version.VERSION}")

    app = ShoutApp()

    def cleanup(*_):
        version.clear_running()
        app.server.stop()
        # os._exit, not sys.exit: SystemExit raised in a signal handler is
        # swallowed by the NSApplication run loop and the process survives.
        os._exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    try:
        app.start()
    except Exception:
        # A bug in startup must not take the app down: without this, a
        # NameError on a rarely-taken permission path killed the whole app on
        # first run, with the failure visible only in the log file.
        traceback.print_exc()
        app.status_item.title = "Startup failed — see Open Log"
        try:
            app._apply_state("error")
        except Exception:
            pass
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
