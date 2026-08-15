"""Config loading.

Two layers:

  config.yaml    hand-edited: model, VAD, vocabulary, per-app profiles.
  settings.json  GUI-managed: hotkey binding and mode.

They're separate so the settings window can write without reformatting
config.yaml and destroying its comments.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from hotkey import MODE_HOLD, MODE_TOGGLE, Hotkey
from postprocess import Profile, Vocabulary

import paths

ROOT = paths.resources()
SETTINGS_PATH = paths.settings_file()

#  Bumped when the shape of settings.json changes. Unknown keys from a NEWER
#  build are preserved on save rather than dropped, so downgrading and
#  upgrading again does not silently discard the user's choices.
SCHEMA_VERSION = 2


def mark_login_offered() -> None:
    """Remember that open-at-login was registered once, so a user who turns it
    off is not overridden on the next launch."""
    data = load_settings()
    data["login_offered"] = True
    SETTINGS_PATH.write_text(json.dumps(data, indent=2) + "\n")


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(hotkey: Hotkey, mode: str, sound: bool | None = None,
                  volume: float | None = None,
                  input_device: str | None = ...,
                  min_press_ms: int | None = None) -> None:
    current = load_settings()
    #  Start from what is already on disk so keys written by a newer build
    #  survive a save from an older one.
    data = dict(current)
    data.update({
        "hotkey": hotkey.to_dict(),
        "mode": mode,
        "sound": current.get("sound", True) if sound is None else bool(sound),
        "volume": current.get("volume", 0.35) if volume is None else float(volume),
        "login_offered": current.get("login_offered", False),
        #  Stored by name, not index: indices are reassigned whenever devices
        #  are plugged in or removed, so a saved index silently becomes a
        #  different microphone.
        "input_device": (current.get("input_device")
                         if input_device is ... else input_device),
        #  The outcome model already has an `ignored` result for a press too
        #  short to contain speech; the user should be able to move that line.
        "min_press_ms": (current.get("min_press_ms", 250)
                         if min_press_ms is None else int(min_press_ms)),
        "schema": SCHEMA_VERSION,
    })
    SETTINGS_PATH.write_text(json.dumps(data, indent=2) + "\n")


@dataclass
class Config:
    model: str = "models/ggml-base.en.bin"
    vad: bool = True
    vad_threshold: float = 0.012
    vad_pad_ms: int = 150
    vocabulary: Vocabulary = field(default_factory=lambda: Vocabulary({}))
    profiles: dict[str, Profile] = field(default_factory=dict)
    hotkey: Hotkey = field(default_factory=Hotkey)
    mode: str = MODE_HOLD
    sound: bool = True
    volume: float = 0.35
    input_device: str | None = None
    min_press_ms: int = 250
    #  Terms fed to Whisper BEFORE it decodes. Unlike `vocabulary`,
    #  which repairs the output, these bias the decision itself.
    prompt_terms: tuple[str, ...] = ()

    def profile_for(self, app_name: str) -> Profile:
        return self.profiles.get(app_name) or self.profiles.get("default") or Profile()


def load(path: Path | None = None) -> Config:
    path = path or paths.config_file()
    if not path.exists():
        return Config()

    raw = yaml.safe_load(path.read_text()) or {}
    audio = raw.get("audio") or {}
    vocab_cfg = raw.get("vocabulary") or {}

    profiles = {}
    for name, p in (raw.get("profiles") or {}).items():
        p = p or {}
        profiles[name] = Profile(
            capitalize_first=p.get("capitalize_first", True),
            strip_trailing_period=p.get("strip_trailing_period", False),
            prompt_terms=tuple(p.get("prompt_terms") or ()),
        )

    settings = load_settings()
    mode = settings.get("mode", MODE_HOLD)
    if mode not in (MODE_HOLD, MODE_TOGGLE):
        mode = MODE_HOLD

    return Config(
        model=raw.get("model", Config.model),
        vad=audio.get("vad", True),
        vad_threshold=float(audio.get("vad_threshold", 0.012)),
        vad_pad_ms=int(audio.get("vad_pad_ms", 150)),
        vocabulary=Vocabulary(
            vocab_cfg.get("replacements") or {},
            vocab_cfg.get("protect") or [],
        ),
        profiles=profiles,
        hotkey=Hotkey.from_dict(settings.get("hotkey")),
        mode=mode,
        sound=bool(settings.get("sound", True)),
        volume=float(settings.get("volume", 0.35)),
        input_device=settings.get("input_device") or None,
        min_press_ms=int(settings.get("min_press_ms", 250)),
        prompt_terms=tuple(raw.get("prompt_terms") or ()),
    )
