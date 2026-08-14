"""Build version, and the handover that makes upgrades actually take effect.

The problem this solves is real and was reproduced: dragging a new build over a
running one leaves the OLD process running. The single-instance lock makes the
new build exit immediately, and re-opening from Applications just surfaces a
window belonging to the stale process. The user gets none of the fixes and no
indication why.

So the lock file records the version and bundle path of whoever holds it. A new
build that finds an older holder asks it to quit, waits, and takes over.
"""

import json
import os
import sys
import signal
import time
from pathlib import Path

import paths
from paths import BUNDLE_ID

VERSION = "2.0.2"


def _parse(v: str) -> tuple:
    """Compare versions numerically: "1.10.0" must sort above "1.9.0"."""
    parts = []
    for chunk in str(v).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts + [0] * (3 - len(parts)))[:3]


def is_newer(a: str, b: str) -> bool:
    return _parse(a) > _parse(b)


def lock_path() -> Path:
    return paths.data() / ".shout.lock"


def _meta_path() -> Path:
    #  Kept beside the lock rather than inside it: the lock is held open by
    #  flock for the process lifetime, and rewriting it in place races.
    return paths.data() / ".shout.running.json"


def record_running() -> None:
    try:
        _meta_path().write_text(json.dumps({
            "version": VERSION,
            "pid": os.getpid(),
            "bundle": str(paths.resources()),
        }))
    except OSError:
        pass


def clear_running() -> None:
    try:
        _meta_path().unlink(missing_ok=True)
    except OSError:
        pass


def running_info() -> dict:
    try:
        return json.loads(_meta_path().read_text())
    except (OSError, ValueError):
        return {}


def _other_instance_pid() -> int | None:
    """PID of another shout app binary, excluding ourselves.

    Matches on "/shout.app/Contents/MacOS/" rather than a bare name so a
    developer running from source, or an unrelated process, is never targeted.
    """
    import subprocess
    me = os.getpid()
    try:
        out = subprocess.run(["ps", "-ax", "-o", "pid=,command="],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    for line in out.splitlines():
        line = line.strip()
        if "/shout.app/Contents/MacOS/" not in line:
            continue
        head = line.split(None, 1)[0]
        if not head.isdigit():
            continue
        pid = int(head)
        if pid != me:
            return pid
    return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def supersede_older(timeout: float = 8.0) -> tuple[bool, str]:
    """If an older build holds the lock, ask it to quit and wait.

    Returns (may_proceed, message). Only supersedes a *strictly older* version,
    so two copies of the same build still respect the single-instance rule and
    the second one surfaces the first's window as before.
    """
    info = running_info()
    if not info:
        # A build older than version tracking leaves no record. That is exactly
        # the upgrade this feature exists for, so fall back to identifying the
        # holder by process: any other shout binary running from our own bundle
        # path is by definition the copy we have just replaced.
        pid = _other_instance_pid()
        if pid is None:
            return True, "no running instance found"
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            return False, f"could not signal legacy instance {pid}: {exc}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not _alive(pid):
                return True, f"replaced untracked instance (pid {pid})"
            time.sleep(0.2)
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
        except OSError:
            pass
        return ((True, f"force-replaced untracked instance (pid {pid})")
                if not _alive(pid)
                else (False, f"untracked instance {pid} would not exit"))

    other_version = str(info.get("version", "0.0.0"))
    pid = int(info.get("pid", 0) or 0)

    if not pid or not _alive(pid):
        clear_running()
        return True, "stale record cleaned up"

    if not is_newer(VERSION, other_version):
        return False, f"running {other_version} is not older than {VERSION}"

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        return False, f"could not signal {pid}: {exc}"

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _alive(pid):
            clear_running()
            return True, f"replaced running {other_version}"
        time.sleep(0.2)

    # It ignored SIGTERM. Escalate rather than leave the user on old code.
    try:
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
    except OSError:
        pass
    if not _alive(pid):
        clear_running()
        return True, f"force-replaced unresponsive {other_version}"
    return False, f"{other_version} would not exit"


# ------------------------------------------------------------- updates

RELEASE_API = "https://api.github.com/repos/austinbrown34/shout/releases/latest"
RELEASE_PAGE = "https://github.com/austinbrown34/shout/releases/latest"


def latest_release(timeout: float = 6.0) -> tuple[str | None, str]:
    """(latest_tag, message). Never raises — an update check must not be able
    to break a working app, and the repo may be private or unreachable."""
    try:
        import requests
        resp = requests.get(RELEASE_API, timeout=timeout,
                            headers={"Accept": "application/vnd.github+json"})
        if resp.status_code == 404:
            return None, "no public release found"
        resp.raise_for_status()
        tag = str(resp.json().get("tag_name", "")).lstrip("v")
        if not tag:
            return None, "release has no tag"
        return tag, tag
    except Exception as exc:
        return None, f"could not check: {exc}"


def installed_bundle() -> str:
    """Path of the installed app, which may differ from the running one after
    an upgrade has been dragged into place."""
    for candidate in ("/Applications/shout.app",
                      str(Path.home() / "Applications" / "shout.app")):
        if Path(candidate).is_dir():
            return candidate
    return "/Applications/shout.app"


def installed_version() -> str | None:
    """Version of the app currently on disk, read from its Info.plist.

    A running instance uses this to notice it has been replaced: the bundle it
    was launched from has been overwritten, but its own VERSION constant is
    whatever was compiled in.
    """
    plist = Path(installed_bundle()) / "Contents" / "Info.plist"
    if not plist.is_file():
        return None
    try:
        import plistlib
        with open(plist, "rb") as fh:
            data = plistlib.load(fh)
        return str(data.get("CFBundleShortVersionString") or "") or None
    except Exception:
        return None


# ---------------------------------------------------------- duplicates

def duplicate_bundles() -> list[str]:
    """Other copies of shout.app besides the one we are running from.

    Dragging the app to Applications twice is easy to do by accident — the
    drop gives no feedback, so people repeat it — and leaves "shout 2.app"
    alongside "shout.app". Both carry the same bundle identifier, so only one
    can run (the file lock sees to that), but the update handover then compares
    against whichever copy was launched, and an update can appear not to take.
    """
    import subprocess

    #  Only meaningful for an installed app. Running from source there is no
    #  bundle to be duplicated, and every installed copy would be reported.
    if not paths.FROZEN:
        return []

    #  sys.executable is .../shout.app/Contents/MacOS/shout when frozen, which
    #  identifies our own bundle exactly. paths.resources() points at the
    #  unpacked resource dir and does not.
    running = str(Path(sys.executable).resolve())
    if ".app/" in running:
        running = running.split(".app/")[0] + ".app"

    found = []
    for directory in ("/Applications", str(Path.home() / "Applications")):
        d = Path(directory)
        if not d.is_dir():
            continue
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.name.endswith(".app"):
                continue
            plist = entry / "Contents" / "Info.plist"
            if not plist.is_file():
                continue
            try:
                import plistlib
                with open(plist, "rb") as fh:
                    bundle_id = plistlib.load(fh).get("CFBundleIdentifier")
            except Exception:
                continue
            if bundle_id != BUNDLE_ID:
                continue
            if str(entry) == running:
                continue
            found.append(str(entry))
    return sorted(found)


def remove_bundle(path: str) -> tuple[bool, str]:
    """Move a duplicate to the Trash rather than deleting it outright."""
    try:
        import subprocess
        script = (f'tell application "Finder" to delete POSIX file "{path}"')
        result = subprocess.run(["osascript", "-e", script],
                                capture_output=True, text=True, timeout=20)
        if result.returncode == 0:
            return True, "moved to Trash"
        return False, result.stderr.strip() or "Finder refused"
    except Exception as exc:
        return False, str(exc)
