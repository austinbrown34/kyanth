"""Open-at-login, via SMAppService.

macOS 13 replaced the old approach — hand-writing a plist into
~/Library/LaunchAgents — with SMAppService. It is better here for three reasons:

  * the app registers *itself*, so there is no second file to keep in sync with
    the bundle's location, and moving or deleting the app cannot orphan an
    agent that then fails to launch on every boot
  * the entry appears in System Settings > General > Login Items under the
    app's own name and icon, where users expect to find and remove it
  * the user's choice there is authoritative; a plist could be silently
    re-created behind their back, which SMAppService will not allow

Only meaningful in a bundled app. Running from source reports NOT_FOUND,
because there is no bundle for macOS to register.
"""

from ServiceManagement import SMAppService

NOT_REGISTERED = 0
ENABLED = 1
REQUIRES_APPROVAL = 2
NOT_FOUND = 3

_LABELS = {
    NOT_REGISTERED: "not registered",
    ENABLED: "enabled",
    REQUIRES_APPROVAL: "needs approval in System Settings",
    NOT_FOUND: "not registered yet",
}


def status() -> int:
    try:
        return int(SMAppService.mainAppService().status())
    except Exception:
        return NOT_FOUND


def status_label() -> str:
    return _LABELS.get(status(), "unknown")


def available() -> bool:
    """Whether open-at-login can work at all.

    Deliberately keyed on being inside a bundle, NOT on status(): for
    mainAppService, macOS reports NOT_FOUND until the app has actually been
    registered once. Gating on that meant never attempting registration, so the
    feature could never turn itself on.
    """
    import paths
    return paths.FROZEN


def enabled() -> bool:
    return status() == ENABLED


def set_enabled(on: bool) -> tuple[bool, str]:
    """Returns (succeeded, message). Never raises: a login-item failure must
    not take down dictation."""
    service = SMAppService.mainAppService()
    try:
        if on:
            ok, err = service.registerAndReturnError_(None)
        else:
            ok, err = service.unregisterAndReturnError_(None)
    except Exception as exc:
        return False, str(exc)

    if ok:
        return True, "enabled" if on else "disabled"

    # The usual cause is the user having switched it off in System Settings,
    # which macOS treats as final until they switch it back on there.
    detail = ""
    if err is not None:
        try:
            detail = str(err.localizedDescription())
        except Exception:
            detail = str(err)
    if status() == REQUIRES_APPROVAL:
        detail = "approve it in System Settings > General > Login Items"
    return False, detail or "failed"
