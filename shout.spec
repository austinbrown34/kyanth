# PyInstaller spec — builds a self-contained, properly branded shout.app.
#
# The point of freezing rather than shipping a launcher script: the bundle's
# executable becomes a real Mach-O binary named `shout`, so macOS attributes
# TCC permissions to *shout* and shows its icon in System Settings. A script
# that exec's Python makes the process literally be Python, which is why
# permissions used to read "Python 3.14".
#
# Build with ./build_release.sh — it vendors whisper first, which this needs.

import plistlib
from pathlib import Path

ROOT = Path(SPECPATH)
VERSION = "2.0.2"

datas = [
    (str(ROOT / "assets" / "shout.icns"), "assets"),
    (str(ROOT / "config.yaml"), "."),
]
for png in sorted((ROOT / "assets").glob("menubar-*.png")):
    datas.append((str(png), "assets"))

# Vendored whisper-server, its dylibs and ggml's runtime backends.
for sub in ("bin", "lib"):
    for f in sorted((ROOT / "vendor" / sub).glob("*")):
        if f.is_file():
            datas.append((str(f), f"vendor/{sub}"))

# Only the configured model ships — globbing models/ would add ~1.1GB of
# alternates that nothing references.
import yaml
_cfg = yaml.safe_load((ROOT / "config.yaml").read_text()) or {}
_model = ROOT / _cfg.get("model", "models/ggml-base.en.bin")
if not _model.exists():
    raise SystemExit(f"model missing: {_model} (run ./install.sh or download it)")
datas.append((str(_model), "models"))

a = Analysis(
    ["menubar.py"],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=[
        "config", "history", "hotkey", "loginitem", "paths", "postprocess",
        "tokens",
        "overlay", "settings_ui", "setup_ui", "shout", "sounds", "vad", "version",
    ],
    excludes=["tkinter", "matplotlib", "PIL", "pytest", "setuptools"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="shout",                 # -> Contents/MacOS/shout, the TCC identity
    console=False,
    target_arch="arm64",
    codesign_identity=None,       # build_release.sh signs the whole bundle
    entitlements_file=str(ROOT / "entitlements.plist"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="shout")

app = BUNDLE(
    coll,
    name="shout.app",
    icon=str(ROOT / "assets" / "shout.icns"),
    bundle_identifier="com.austinbrown.shout",
    version=VERSION,
    info_plist={
        "CFBundleName": "shout",
        "CFBundleDisplayName": "shout",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "13.0",
        # menu-bar only: no Dock icon, no app-switcher entry
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        # These strings are what the permission prompts actually say.
        "NSMicrophoneUsageDescription":
            "shout transcribes your speech on this Mac to type it into the app "
            "you are using. Audio never leaves your computer.",
        "NSAppleEventsUsageDescription":
            "shout pastes transcribed text into the app you are using.",
    },
)
