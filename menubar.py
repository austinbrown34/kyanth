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
import shout
import sounds
from hotkey import MODE_HOLD
from settings_ui import SettingsController

import paths

ROOT = paths.resources()
LOGDIR = paths.logs()
LOG = LOGDIR / "server.log"
HISTORY = 8

#  A second launch of an already-running app signals the live instance over
#  this notification rather than starting a rival process.
SHOW_SETTINGS_NOTE = "local.shout.dictation.showSettings"

ASSETS = paths.resources() / "assets"

#  (image, template). Template images are recolored by macOS to match the
#  menu bar in light/dark and while a menu is open. The recording glyph opts
#  out so its red dot survives — that one is worth the inconsistency.
ICONS = {
    "idle":             ("menubar-idle@2x.png", True),
    "recording":        ("menubar-rec@2x.png",  False),
    "working":          ("menubar-idle@2x.png", True),
    "error":            ("menubar-off@2x.png",  True),
    "disabled":         ("menubar-off@2x.png",  True),
    "needs-permission": ("menubar-off@2x.png",  True),
}

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

        self.status_item = rumps.MenuItem("Starting…")
        self.toggle_item = rumps.MenuItem("Enabled", callback=self.on_toggle)
        self.toggle_item.state = True
        self.history_menu = rumps.MenuItem("Recent")
        self.sound_item = rumps.MenuItem("Sound cues", callback=self.on_toggle_sound)
        self.sound_item.state = self.cfg.sound
        # Hidden when running from source, where there is no bundle to register.
        self.login_item = None
        if loginitem.available():
            self.login_item = rumps.MenuItem("Open at Login",
                                             callback=self.on_toggle_login)
            self.login_item.state = loginitem.enabled()

        self.menu = [
            self.status_item,
            None,
            self.toggle_item,
            self.history_menu,
            None,
            self.sound_item,
            *( [self.login_item] if self.login_item else [] ),
            rumps.MenuItem("Settings & History…", callback=self.on_settings),
            rumps.MenuItem("Edit Config…", callback=self.on_edit_config),
            rumps.MenuItem("Reload Config", callback=self.on_reload),
            rumps.MenuItem("Restart Model Server", callback=self.on_restart_server),
            rumps.MenuItem("Open Log", callback=self.on_open_log),
            None,
            rumps.MenuItem("Quit shout", callback=self.on_quit),
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
            return True  # stay alive so the user can read the menu and quit

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

        try:
            self.recorder = shout.Recorder(lead_skip_ms=self.cues.lead_ms)
            print(f"[start] input device: {self.recorder._stream.device}")
        except Exception as e:
            # Almost always "microphone not yet granted". Stay alive and retry
            # rather than dying before the user has answered the prompt.
            print(f"[start] microphone unavailable: {e}")
            self.set_state("needs-permission")
            self.status_item.title = "Waiting for microphone access…"
            rumps.Timer(self.retry_start, 2).start()
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
        )
        print(f"[start] hotkey={self.cfg.hotkey.label()} mode={self.cfg.mode}")
        if not self.install_tap():
            # Ask macOS to show its own "open System Settings" prompt, then
            # poll — granting Accessibility takes effect without a relaunch.
            self.request_permissions()
            self.set_state("needs-permission")
            self.status_item.title = "Grant permissions, then wait…"
            rumps.Timer(self.retry_tap, 2).start()
            # Surface the window once the run loop is up. Without it a
            # first-run user sees nothing at all happen when they open the app.
            AppHelper.callAfter(self.on_settings)
            return True

        print("[start] event tap installed — ready")
        self.set_state("idle")
        return True

    def _observe_show_settings(self):
        """Opening shout again from the Applications folder should surface
        Settings rather than silently doing nothing."""
        global _reopen_target
        _reopen_target = self.on_settings

        # Held on self: the observer is not retained by the notification
        # centre, and a collected proxy stops delivering silently.
        self._note_proxy = _NoteProxy.alloc().initWithCallback_(
            lambda: AppHelper.callAfter(self.on_settings))
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
                self.recorder = shout.Recorder(lead_skip_ms=self.cues.lead_ms)
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
        if self.login_item is not None:
            self.login_item.state = loginitem.enabled()
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
        elif find_server_binary() is None:
            problems.append("whisper-server not found\nbrew install whisper-cpp")
        elif not self.server.start():
            problems.append(f"Model server failed\nSee {LOG}")

        return problems

    # ---------------------------------------------------------- callbacks

    def set_state(self, state: str):
        """Safe to call from any thread — the worker calls this."""
        AppHelper.callAfter(self._apply_state, state)

    def _apply_state(self, state: str):
        if self.daemon and not self.daemon.enabled:
            state = "disabled"

        name, template = ICONS.get(state, ICONS["idle"])
        path = ASSETS / name
        if path.exists():
            # template must be set first: rumps' icon setter reads the current
            # template flag when building the NSImage.
            self.template = template
            self.icon = str(path)

        label = {
            "idle": (f"Ready — {'hold' if self.cfg.mode == MODE_HOLD else 'press'} "
                     f"{self.cfg.hotkey.label()}"),
            "recording": "Recording…",
            "working": "Transcribing…",
            "error": "Transcription failed",
            "disabled": "Disabled",
        }.get(state, state)
        self.status_item.title = label

    def on_result(self, text: str, secs: float, ms: float, where: str = "pasted"):
        """Called from the worker thread. Only touches plain data here; the menu
        rebuild is pushed to the main thread, because NSMenu — like all of
        AppKit — must not be mutated from a background thread."""
        self.store.add(history_mod.Entry(text, shout.frontmost_app(),
                                         time.time(), ms, where))
        mark = " ⧉" if where == "clipboard" else ""
        preview = text if len(text) <= 60 else text[:57] + "…"
        self.history.appendleft(f"{preview}{mark}   ({ms:.0f}ms)")
        AppHelper.callAfter(self._refresh_history)
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

    def on_toggle_sound(self, sender):
        sender.state = not sender.state
        on = bool(sender.state)
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

    def on_reload(self, _):
        self.cfg = config_mod.load()
        rumps.notification("shout", "Config reloaded",
                           "Model changes need a server restart.")

    def on_settings(self, _=None):
        existing = getattr(self, "settings", None)
        if existing is not None and existing.window.isVisible():
            existing.show()          # already open: just bring it forward
            return
        # Keep a reference: an NSWindowController that goes out of scope takes
        # its window with it.
        self.settings = SettingsController.alloc().initWithHotkey_mode_history_onApply_(
            self.cfg.hotkey, self.cfg.mode, self.store, self.apply_hotkey)
        self.settings.show()

    def apply_hotkey(self, hk, mode):
        config_mod.save_settings(hk, mode, sound=self.cues.enabled)
        self.cfg = config_mod.load()
        if self.daemon:
            self.daemon.rebind(hk, mode)      # live, no restart
        self._apply_state("idle")
        print(f"[settings] hotkey={hk.label()} mode={mode}")
        rumps.notification("shout", "Shortcut updated",
                           f"{'Hold' if mode == MODE_HOLD else 'Toggle'}  {hk.label()}")

    def on_edit_config(self, _):
        subprocess.run(["open", "-t", str(paths.config_file())])

    def on_restart_server(self, _):
        self.cfg = config_mod.load()
        self.server.model = self.cfg.model
        ok = self.server.restart()
        rumps.notification("shout", "Model server",
                           "Restarted" if ok else f"Failed — see {LOG}")

    def on_open_log(self, _):
        LOGDIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(LOGDIR)])

    def on_quit(self, _):
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
        print("already running — asking the live instance to show Settings",
              file=sys.stderr)
        NSDistributedNotificationCenter.defaultCenter(
        ).postNotificationName_object_userInfo_deliverImmediately_(
            SHOW_SETTINGS_NOTE, None, None, True)
        return 0

    app = ShoutApp()

    def cleanup(*_):
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
