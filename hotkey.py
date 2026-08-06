"""Hotkey representation, matching, and display.

Two kinds of binding:

  * modifier-only  — right-Option, left-Command, fn. Press and release arrive
    as `flagsChanged` events, so they're detected from the flag bits.
  * regular key    — F13, backslash, X-with-modifiers. Press and release arrive as
    `keyDown` / `keyUp`.

Modifier-only bindings use the *device-dependent* flag bits so that left and
right of the same key are distinguishable. The generic masks (e.g.
kCGEventFlagMaskAlternate) are set by either side and cannot tell them apart.
"""

from dataclasses import dataclass

# --- generic (side-agnostic) modifier masks
MASK_SHIFT = 0x00020000
MASK_CONTROL = 0x00040000
MASK_ALTERNATE = 0x00080000
MASK_COMMAND = 0x00100000
MASK_FN = 0x00800000

MODIFIER_ORDER = [
    (MASK_CONTROL, "⌃"),
    (MASK_ALTERNATE, "⌥"),
    (MASK_SHIFT, "⇧"),
    (MASK_COMMAND, "⌘"),
]

#  keycode -> (device-dependent bit, generic mask, label)
#  The device bits are the NX_DEVICE*KEYMASK constants from IOLLEvent.h.
MODIFIER_KEYS = {
    54: (0x00000010, MASK_COMMAND,   "Right ⌘"),
    55: (0x00000008, MASK_COMMAND,   "Left ⌘"),
    56: (0x00000002, MASK_SHIFT,     "Left ⇧"),
    60: (0x00000004, MASK_SHIFT,     "Right ⇧"),
    58: (0x00000020, MASK_ALTERNATE, "Left ⌥"),
    61: (0x00000040, MASK_ALTERNATE, "Right ⌥"),
    59: (0x00000001, MASK_CONTROL,   "Left ⌃"),
    62: (0x00002000, MASK_CONTROL,   "Right ⌃"),
    63: (0x00000000, MASK_FN,        "fn"),
}

#  Only what's needed to render a binding. Unknown codes fall back to "key NN",
#  which is still a usable label.
KEY_NAMES = {
    0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X", 8: "C",
    9: "V", 11: "B", 12: "Q", 13: "W", 14: "E", 15: "R", 16: "Y", 17: "T",
    31: "O", 32: "U", 34: "I", 35: "P", 37: "L", 38: "J", 40: "K", 45: "N",
    46: "M", 18: "1", 19: "2", 20: "3", 21: "4", 23: "5", 22: "6", 26: "7",
    28: "8", 25: "9", 29: "0", 33: "[", 30: "]", 41: ";", 39: "'", 43: ",",
    47: ".", 44: "/", 42: "\\", 27: "-", 24: "=", 50: "`",
    36: "Return", 48: "Tab", 49: "Space", 51: "Delete", 53: "Escape",
    122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5", 97: "F6",
    98: "F7", 100: "F8", 101: "F9", 109: "F10", 103: "F11", 111: "F12",
    105: "F13", 107: "F14", 113: "F15", 106: "F16", 64: "F17", 79: "F18",
    80: "F19", 90: "F20",
    123: "←", 124: "→", 125: "↓", 126: "↑",
    115: "Home", 119: "End", 116: "Page Up", 121: "Page Down",
}

MODE_HOLD = "hold"
MODE_TOGGLE = "toggle"


def keys_down(flags: int) -> list[int]:
    """Which modifier keycodes are physically held, per the device bits."""
    out = []
    for kc, (device_bit, generic, _) in MODIFIER_KEYS.items():
        if flags & (device_bit if device_bit else generic):
            out.append(kc)
    return out


def _device_bit(keycode: int) -> int:
    device_bit, generic, _ = MODIFIER_KEYS[keycode]
    return device_bit if device_bit else generic


@dataclass(frozen=True)
class Hotkey:
    """`keycode` is the trigger; `modifiers` are the keys that must also be held.

    The meaning of `modifiers` depends on the trigger:
      * regular key   -> generic masks (⇧⌃⌥⌘), since either side will do
      * modifier-only -> device bits, so "⌃ + right-⌥" stays distinct from
                         "⌃ + left-⌥"
    """

    keycode: int = 61                 # right-Option
    modifiers: int = 0

    @property
    def is_modifier_only(self) -> bool:
        return self.keycode in MODIFIER_KEYS

    def label(self) -> str:
        if self.is_modifier_only:
            # Held-modifier prefixes, then the trigger, in a stable order.
            prefix = [
                MODIFIER_KEYS[kc][2]
                for kc in sorted(MODIFIER_KEYS)
                if kc != self.keycode and self.modifiers & _device_bit(kc)
            ]
            return " + ".join(prefix + [MODIFIER_KEYS[self.keycode][2]])
        parts = [sym for mask, sym in MODIFIER_ORDER if self.modifiers & mask]
        parts.append(KEY_NAMES.get(self.keycode, f"key {self.keycode}"))
        return "".join(parts)

    # ---------------------------------------------------------- matching

    def is_pressed(self, flags: int) -> bool:
        """For modifier-only bindings: trigger down AND every co-modifier held."""
        if not flags & _device_bit(self.keycode):
            return False
        return (flags & self.modifiers) == self.modifiers

    #  fn is deliberately excluded from matching. macOS sets it on F-keys and
    #  arrows depending on the "use F1..F12 as function keys" setting, so
    #  requiring it makes a binding work on one machine and not another.
    MATCH_MASK = MASK_SHIFT | MASK_CONTROL | MASK_ALTERNATE | MASK_COMMAND

    def matches_regular(self, keycode: int, flags: int) -> bool:
        if keycode != self.keycode:
            return False
        return (flags & self.MATCH_MASK) == (self.modifiers & self.MATCH_MASK)

    # ---------------------------------------------------- serialization

    def to_dict(self) -> dict:
        return {"keycode": self.keycode, "modifiers": self.modifiers}

    @classmethod
    def from_dict(cls, d: dict | None) -> "Hotkey":
        if not d:
            return cls()
        try:
            return cls(int(d.get("keycode", 61)), int(d.get("modifiers", 0)))
        except (TypeError, ValueError):
            return cls()


class ChordRecorder:
    """Accumulates a key combination from a stream of events.

    Kept out of the UI so it can be tested without a window. The rule: grow the
    chord while keys go down, commit when they have all come back up. Committing
    on first press was the original bug — pressing ⌘ on the way to ⇧⌘V ended
    recording after a single key.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.chord: list[int] = []      # modifier keycodes, in press order
        self.pending: Hotkey | None = None

    def on_flags(self, flags: int):
        """Returns ("preview", hk), ("commit", hk), or None."""
        down = keys_down(flags)
        for kc in down:
            if kc not in self.chord:
                self.chord.append(kc)

        if self.chord:
            trigger = self.chord[-1]        # last pressed is the trigger
            extra = 0
            for kc in self.chord[:-1]:
                extra |= _device_bit(kc)
            self.pending = Hotkey(trigger, extra)

        if not down and self.pending is not None:
            return ("commit", self.pending)
        return ("preview", self.pending) if self.pending else None

    def on_key(self, keycode: int, flags: int) -> Hotkey:
        """A regular key ends the chord at once; held modifiers qualify it."""
        return Hotkey(keycode, flags & Hotkey.MATCH_MASK)
