"""Where things live, in both the development tree and a frozen .app bundle.

A signed application bundle is read-only — writing inside it breaks the code
signature, which macOS enforces by refusing to launch. So the two kinds of file
must be kept apart:

  resources   code, model, vendored whisper binaries, default config, icons
              -> inside the bundle when frozen, the repo when not
  user data   config the user edits, settings, history, logs, generated cues
              -> always ~/Library/Application Support/Kyanth

In development both happen to live in the repo, which is why this distinction
did not exist until packaging forced it.
"""

import os
import sys
from pathlib import Path

#  PyInstaller sets both; _MEIPASS is where bundled data was unpacked.
FROZEN = getattr(sys, "frozen", False)

APP_NAME = "Kyanth"
BUNDLE_ID = "com.austinbrown.kyanth"


def resources() -> Path:
    """Read-only files shipped with the app."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


LEGACY_APP_NAME = "shout"


def data() -> Path:
    """Writable per-user state. Created on demand."""
    d = Path.home() / "Library" / "Application Support" / APP_NAME
    if not d.exists():
        _migrate_legacy(d)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _migrate_legacy(new: Path) -> None:
    """Carry a pre-rename install's history, settings and config across.

    The rename changed the bundle identifier, so macOS treats this as an
    entirely new app — permissions reset, and the old state would otherwise sit
    orphaned under the old name with the user seeing an empty history and their
    shortcut reverted to the default.

    Moved rather than copied: two live copies would diverge silently, and the
    old app is being replaced, not run alongside.
    """
    old = Path.home() / "Library" / "Application Support" / LEGACY_APP_NAME
    if not old.is_dir():
        return
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        old.rename(new)
        #  Lock and liveness files name the old process; they mean nothing now
        #  and a stale lock would look like an instance that is already running.
        for stale in (".shout.lock", ".shout.running.json"):
            (new / stale).unlink(missing_ok=True)
        print(f"[migrate] carried over {old.name} -> {new.name}", flush=True)
    except OSError as exc:
        #  Never fatal: a fresh install is a working install, just an empty one.
        print(f"[migrate] could not move {old}: {exc}", flush=True)


def logs() -> Path:
    d = data() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cues() -> Path:
    d = data() / "cues"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_file() -> Path:
    """User-editable config, seeded from the bundled default on first run."""
    user = data() / "config.yaml"
    if not user.exists():
        default = resources() / "config.yaml"
        if default.exists():
            user.write_text(default.read_text())
    return user


def settings_file() -> Path:
    return data() / "settings.json"


def history_file() -> Path:
    return data() / "history.jsonl"


def model_path(rel: str) -> Path:
    """Models ship inside the bundle, but a user-supplied one wins so people
    can drop in a larger model without rebuilding."""
    override = data() / rel
    if override.exists():
        return override
    return resources() / rel


def whisper_server() -> str | None:
    """Vendored binary first, so a packaged install needs no Homebrew."""
    vendored = resources() / "vendor" / "bin" / "whisper-server"
    if vendored.is_file():
        return str(vendored)
    for p in ("/opt/homebrew/bin/whisper-server", "/usr/local/bin/whisper-server"):
        if Path(p).is_file():
            return p
    from shutil import which
    return which("whisper-server")


def whisper_env() -> dict:
    """Environment for the vendored server: ggml resolves its backends relative
    to the executable, and a login-time PATH has no Homebrew on it."""
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "/usr/bin:/bin")
    backends = resources() / "vendor" / "bin"
    if backends.is_dir():
        env["GGML_BACKEND_PATH"] = str(backends)
    return env
