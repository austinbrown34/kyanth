"""Persistent transcription history.

Append-only JSONL so a crash can never corrupt more than the last line, and so
appending stays O(1) regardless of how much history has accumulated. The file is
trimmed on load rather than on every write.

Everything here is local — the whole point of Kyanth is that transcripts never
leave the machine, and that includes this file.
"""

import json
import threading
from dataclasses import dataclass
from pathlib import Path

MAX_ENTRIES = 500


@dataclass
class Entry:
    text: str
    app: str
    when: float          # unix seconds
    ms: float            # transcription latency
    where: str = "pasted"   # "pasted" | "clipboard" | "ignored"
    #  Seconds of speech after trimming. The History table draws this as a bar,
    #  so an eleven-second paragraph is findable without reading a word.
    #  Entries written before this field existed carry 0.0 and draw no bar.
    secs: float = 0.0

    def to_json(self) -> str:
        return json.dumps({
            "text": self.text, "app": self.app, "when": self.when,
            "ms": self.ms, "where": self.where, "secs": self.secs,
        })

    @classmethod
    def from_dict(cls, d: dict) -> "Entry | None":
        try:
            return cls(str(d["text"]), str(d.get("app", "")),
                       float(d.get("when", 0)), float(d.get("ms", 0)),
                       str(d.get("where", "pasted")), float(d.get("secs", 0)))
        except (KeyError, TypeError, ValueError):
            return None


class History:
    def __init__(self, path: Path, limit: int = MAX_ENTRIES):
        self.path = path
        self.limit = limit
        self._lock = threading.Lock()
        self.entries: list[Entry] = []      # newest first
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        rows = []
        for line in self.path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = Entry.from_dict(json.loads(line))
            except json.JSONDecodeError:
                continue            # tolerate a torn final line
            if entry is not None:
                rows.append(entry)
        with self._lock:
            self.entries = list(reversed(rows[-self.limit:]))

    def add(self, entry: Entry) -> None:
        with self._lock:
            self.entries.insert(0, entry)
            over = len(self.entries) - self.limit
            if over > 0:
                del self.entries[self.limit:]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a") as f:
                f.write(entry.to_json() + "\n")
        except OSError:
            pass                    # never let logging break dictation

        if over > 0:
            self._compact()

    def _compact(self) -> None:
        """Rewrite the file from the in-memory window. Only runs once the file
        has grown past the limit, so it is rare."""
        try:
            with self._lock:
                rows = list(reversed(self.entries))
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("".join(e.to_json() + "\n" for e in rows))
            tmp.replace(self.path)
        except OSError:
            pass

    def delete(self, entry: Entry) -> bool:
        """Remove one entry. Deletion is per-row in the UI because "clear
        everything" is the wrong tool for one line you did not mean to say."""
        with self._lock:
            try:
                self.entries.remove(entry)
            except ValueError:
                return False
        self._compact()
        return True

    def clear(self) -> None:
        with self._lock:
            self.entries = []
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    def recent(self, n: int | None = None) -> list[Entry]:
        with self._lock:
            return self.entries[:n] if n else list(self.entries)
