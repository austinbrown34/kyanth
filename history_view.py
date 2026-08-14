"""The History table — Level.

v1.2.0 was a plain NSTableView truncating at ~96 characters, with timestamp,
marker and text crushed into one undifferentiated string, no search, no
grouping and no delete. History is the surface that changed most.

It is drawn rather than assembled from NSTableView cell views. The reasons:
day headings, expand-in-place and the Spoken bar all want direct control of
row geometry, and 500 rows is small enough that hit-testing a list is not
worth a data source. The scroll view clips, and drawRect_ only paints the
dirty rect, so scrolling stays cheap.

The Spoken column is the meter applied to the archive: a bar as wide as the
time you spent talking, so an eleven-second paragraph is findable without
reading a word.
"""

import time

import objc
from objc import python_method
from AppKit import (
    NSBezierPath,
    NSMakePoint,
    NSMakeRect,
    NSMakeSize,
    NSPasteboard,
    NSPasteboardTypeString,
    NSScrollView,
    NSTrackingActiveInKeyWindow,
    NSTrackingMouseMoved,
    NSTrackingArea,
    NSView,
)

import chrome
import tokens

PAD_X = 22.0
FILTER_H = 46.0
HEAD_H = 30.0
ROW_H = 40.0
DAY_H = 30.0
BAR_W = 46.0
BAR_H = 4.0
BAR_MAX_SEC = 12.0        # a bar this long is "a long one"; beyond it saturates

FILTERS = [("all", "All"), ("pasted", "Pasted"),
           ("clipboard", "Clipboard"), ("ignored", "Nothing heard")]


def _fmt_delay(ms):
    return f"{int(round(ms))} ms" if ms else "—"


def _day_key(when):
    return time.strftime("%Y-%m-%d", time.localtime(when))


def _day_title(when):
    key = _day_key(when)
    today = time.strftime("%Y-%m-%d")
    yesterday = time.strftime("%Y-%m-%d",
                              time.localtime(time.time() - 86400))
    if key == today:
        return "Today"
    if key == yesterday:
        return "Yesterday"
    return time.strftime("%A", time.localtime(when))


class HistoryPane(NSView):
    """Filter bar, column header, and the scrolling list beneath them."""

    def initWithFrame_store_(self, frame, store):
        self = objc.super(HistoryPane, self).initWithFrame_(frame)
        if self is None:
            return None
        self.store = store
        self.query = ""
        self.filter = "all"
        self.chips = []

        self.list = HistoryList.alloc().initWithFrame_pane_(
            NSMakeRect(0, 0, frame.size.width, 10.0), self)
        self.scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.scroll.setDrawsBackground_(True)
        self.scroll.setBackgroundColor_(tokens.SURFACE)
        self.scroll.setHasVerticalScroller_(True)
        self.scroll.setAutohidesScrollers_(True)
        self.scroll.setBorderType_(0)
        self.scroll.setDocumentView_(self.list)
        self.addSubview_(self.scroll)

        self.count_label = chrome.label("", "version", tokens.MUTED, x=0, y=0)
        self.addSubview_(self.count_label)

        for key, title in FILTERS:
            chip = ChipView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 26.0))
            chip.title, chip.key, chip.pane = title, key, self
            chip.sizeToFit()
            self.chips.append(chip)
            self.addSubview_(chip)

        self.reload()
        return self

    def isFlipped(self):
        return True

    # ------------------------------------------------------------ data

    @python_method
    def rows(self):
        """Visible entries after the filter and the query, newest first."""
        out = []
        needle = self.query.lower().strip()
        for e in (self.store.entries if self.store else []):
            if self.filter != "all" and e.where != self.filter:
                continue
            if needle and needle not in e.text.lower():
                continue
            out.append(e)
        return out

    @python_method
    def set_query(self, text):
        if text != self.query:
            self.query = text
            self.reload()

    @python_method
    def set_filter(self, key):
        if key != self.filter:
            self.filter = key
            self.reload()

    @python_method
    def reload(self):
        self.list.rebuild(self.rows())
        total = len(self.store.entries) if self.store else 0
        shown = len(self.list.entries)
        words = sum(len(e.text.split()) for e in self.list.entries)
        chrome.set_text(
            self.count_label,
            f"{shown} of {total} · {words} word{'' if words == 1 else 's'}",
            "version", tokens.MUTED)
        self.count_label.sizeToFit()
        for chip in self.chips:
            chip.set_selected(chip.key == self.filter)
        self.setNeedsDisplay_(True)
        self.layout()

    # ---------------------------------------------------------- layout

    def layout(self):
        box = self.bounds()
        x = PAD_X
        for chip in self.chips:
            chip.setFrameOrigin_(NSMakePoint(x, 10.0))
            x += chip.frame().size.width + 8.0
        self.count_label.setFrameOrigin_(NSMakePoint(
            box.size.width - PAD_X - self.count_label.frame().size.width, 15.0))

        self.scroll.setFrame_(NSMakeRect(
            0, FILTER_H + HEAD_H, box.size.width,
            max(0.0, box.size.height - FILTER_H - HEAD_H)))
        self.list.setFrameSize_(NSMakeSize(box.size.width,
                                           max(self.list.total_height(),
                                               self.scroll.frame().size.height)))
        objc.super(HistoryPane, self).layout()

    def setFrameSize_(self, size):
        objc.super(HistoryPane, self).setFrameSize_(size)
        self.layout()

    # ----------------------------------------------------------- chrome

    def drawRect_(self, rect):
        box = self.bounds()
        tokens.SURFACE.set()
        NSBezierPath.fillRect_(box)

        tokens.BORDER.set()
        NSBezierPath.fillRect_(NSMakeRect(0, FILTER_H, box.size.width, 1.0))

        #  Column header. Not inside the scroll view, so it stays put — the
        #  cheap version of a sticky header.
        tokens.FOOTER.set()
        NSBezierPath.fillRect_(NSMakeRect(0, FILTER_H, box.size.width, HEAD_H))
        tokens.BORDER.set()
        NSBezierPath.fillRect_(
            NSMakeRect(0, FILTER_H + HEAD_H - 1.0, box.size.width, 1.0))

        cols = columns(box.size.width)
        for name, x in (("Time", cols["time"]), ("Transcription", cols["text"]),
                        ("Spoken", cols["spoken"]), ("Landed in", cols["app"]),
                        ("Delay", cols["delay"])):
            tokens.attributed(name.upper(), "tableHead", tokens.MUTED
                              ).drawAtPoint_(NSMakePoint(x, FILTER_H + 10.0))


def columns(width):
    """Column origins. Time and the three right-hand columns are fixed; the
    transcription takes whatever is left, which is the column that benefits."""
    delay = width - PAD_X - 74.0
    app = delay - 118.0
    spoken = app - 108.0
    return {"time": PAD_X, "text": PAD_X + 76.0,
            "spoken": spoken, "app": app, "delay": delay,
            "text_w": spoken - (PAD_X + 76.0) - 18.0}


class ChipView(NSView):
    """A filter chip. Pasted / clipboard / nothing-heard are already the app's
    outcome model — Clipboard is the list you open when text went missing."""

    def initWithFrame_(self, frame):
        self = objc.super(ChipView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.title = ""
        self.key = ""
        self.pane = None
        self.selected = False
        return self

    @python_method
    def sizeToFit(self):
        w = tokens.attributed(self.title, "note").size().width
        self.setFrameSize_(NSMakeSize(w + 26.0, 26.0))

    @python_method
    def set_selected(self, on):
        if on != self.selected:
            self.selected = on
            self.setNeedsDisplay_(True)

    def isAccessibilityElement(self):
        return True

    def accessibilityRole(self):
        return "AXRadioButton"

    def accessibilityLabel(self):
        return self.title

    def accessibilityTitle(self):
        #  AXTitle is what assistive tools and UI scripting read as the
        #  element's name; AXLabel alone leaves it nameless.
        return self.title

    def accessibilityValue(self):
        return 1 if self.selected else 0

    def accessibilityPerformPress(self):
        if self.pane is not None:
            self.pane.set_filter(self.key)
            return True
        return False

    def drawRect_(self, rect):
        box = self.bounds()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(0.5, 0.5, box.size.width - 1, box.size.height - 1),
            box.size.height / 2.0, box.size.height / 2.0)
        if self.selected:
            tokens.MARK_DONE.set()
            path.fill()
        else:
            tokens.CTL.set()
            path.fill()
            tokens.BORDER.set()
            path.setLineWidth_(1.0)
            path.stroke()
        s = tokens.attributed(self.title, "note",
                              tokens.SILVER if self.selected else tokens.FG)
        s.drawAtPoint_(NSMakePoint((box.size.width - s.size().width) / 2.0,
                                   box.size.height / 2.0 - 8.0))

    def mouseDown_(self, event):
        if self.pane is not None:
            self.pane.set_filter(self.key)


class HistoryList(NSView):
    """The rows themselves, inside the scroll view."""

    def initWithFrame_pane_(self, frame, pane):
        self = objc.super(HistoryList, self).initWithFrame_(frame)
        if self is None:
            return None
        self.pane = pane
        self.entries = []
        self.layout_rows = []      # (kind, y, height, payload)
        self.expanded = None       # the entry whose detail row is open
        self.hover = -1
        return self

    def isFlipped(self):
        return True

    @python_method
    def rebuild(self, entries):
        self.entries = entries
        if self.expanded is not None and self.expanded not in entries:
            self.expanded = None
        self._relayout()

    @python_method
    def _relayout(self):
        self.layout_rows = []
        y = 0.0
        day = None
        width = self.frame().size.width or self.pane.frame().size.width
        for e in self.entries:
            key = _day_key(e.when)
            if key != day:
                day = key
                count = sum(1 for x in self.entries if _day_key(x.when) == key)
                self.layout_rows.append(("day", y, DAY_H, (e.when, count)))
                y += DAY_H
            self.layout_rows.append(("row", y, ROW_H, e))
            y += ROW_H
            if e is self.expanded:
                height = self._detail_height(e, width)
                self.layout_rows.append(("detail", y, height, e))
                y += height
        self._height = y
        self.setFrameSize_(NSMakeSize(width, max(y, 10.0)))
        self.setNeedsDisplay_(True)

    @python_method
    def total_height(self):
        return getattr(self, "_height", 0.0)

    @python_method
    def _detail_height(self, entry, width):
        text_w = columns(width)["text_w"] + 180.0
        body = chrome.text_height(entry.text or "no speech detected",
                                  "body", text_w)
        return 18.0 + body + 12.0 + 18.0 + 14.0 + 30.0

    # ------------------------------------------------------------ paint

    def drawRect_(self, rect):
        box = self.bounds()
        tokens.SURFACE.set()
        NSBezierPath.fillRect_(rect)

        if not self.entries:
            self._draw_empty(box)
            return

        cols = columns(box.size.width)
        for i, (kind, y, height, payload) in enumerate(self.layout_rows):
            if y + height < rect.origin.y or y > rect.origin.y + rect.size.height:
                continue
            if kind == "day":
                self._draw_day(y, height, box, payload)
            elif kind == "row":
                self._draw_row(i, y, height, box, cols, payload)
            else:
                self._draw_detail(y, height, box, cols, payload)

    @python_method
    def _draw_empty(self, box):
        if self.pane.query or self.pane.filter != "all":
            head, note = ("No matches",
                          "Nothing here matches that search or filter.")
        else:
            head, note = ("Nothing dictated yet",
                          "Hold your shortcut, say something, and it will "
                          "appear here.")
        cy = min(box.size.height / 2.0, 160.0)
        s = tokens.attributed(head, "rowLabel", tokens.FG)
        s.drawAtPoint_(NSMakePoint((box.size.width - s.size().width) / 2.0, cy))
        n = tokens.attributed(note, "note", tokens.MUTED)
        n.drawAtPoint_(NSMakePoint((box.size.width - n.size().width) / 2.0,
                                   cy + 22.0))

    @python_method
    def _draw_day(self, y, height, box, payload):
        when, count = payload
        tokens.FOOTER.set()
        NSBezierPath.fillRect_(NSMakeRect(0, y, box.size.width, height))
        tokens.BORDER.set()
        NSBezierPath.fillRect_(NSMakeRect(0, y + height - 1, box.size.width, 1))
        tokens.attributed(_day_title(when).upper(), "tableHead",
                          tokens.FG).drawAtPoint_(NSMakePoint(PAD_X, y + 9.0))
        stamp = time.strftime("%-d %B", time.localtime(when))
        tokens.attributed(f"{stamp} · {count}", "note", tokens.MUTED
                          ).drawAtPoint_(NSMakePoint(PAD_X + 78.0, y + 7.0))

    @python_method
    def _draw_row(self, index, y, height, box, cols, e):
        if e is self.expanded:
            tokens.ACCENT.colorWithAlphaComponent_(0.07).set()
            NSBezierPath.fillRect_(NSMakeRect(0, y, box.size.width, height))
        elif index == self.hover:
            tokens.HOVER.set()
            NSBezierPath.fillRect_(NSMakeRect(0, y, box.size.width, height))
        tokens.BORDER.set()
        NSBezierPath.fillRect_(NSMakeRect(0, y + height - 1, box.size.width, 1))

        mid = y + height / 2.0
        stamp = time.strftime("%H:%M", time.localtime(e.when)) if e.when else "—"
        tokens.attributed(stamp, "numeric", tokens.MUTED).drawAtPoint_(
            NSMakePoint(cols["time"], mid - 8.0))

        text = e.text.replace("\n", " ") if e.text else "no speech detected"
        s = tokens.attributed(text, "body",
                              tokens.FG if e.text else tokens.MUTED)
        clipped = _truncate(s, text, "body",
                            tokens.FG if e.text else tokens.MUTED,
                            cols["text_w"])
        clipped.drawAtPoint_(NSMakePoint(cols["text"], mid - 9.0))

        #  Spoken: the meter, applied to the archive.
        if e.secs:
            track = NSMakeRect(cols["spoken"], mid - BAR_H / 2.0, BAR_W, BAR_H)
            tokens.METER_IDLE.set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                track, BAR_H / 2.0, BAR_H / 2.0).fill()
            frac = min(1.0, e.secs / BAR_MAX_SEC)
            (tokens.PEAK if e is self.expanded else tokens.FG
             .colorWithAlphaComponent_(0.34)).set()
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(track.origin.x, track.origin.y,
                           max(BAR_H, BAR_W * frac), BAR_H),
                BAR_H / 2.0, BAR_H / 2.0).fill()
            tokens.attributed(f"{e.secs:.1f}s", "numeric", tokens.MUTED
                              ).drawAtPoint_(
                NSMakePoint(cols["spoken"] + BAR_W + 8.0, mid - 8.0))

        landed = e.app or "—"
        if e.where == "clipboard":
            landed = "Clipboard"
        elif e.where == "ignored":
            landed = "—"
        s = tokens.attributed(landed, "note", tokens.MUTED)
        _truncate(s, landed, "note", tokens.MUTED, 104.0).drawAtPoint_(
            NSMakePoint(cols["app"], mid - 8.0))

        tokens.attributed(_fmt_delay(e.ms) if e.text else "—", "numeric",
                          tokens.MUTED).drawAtPoint_(
            NSMakePoint(cols["delay"], mid - 8.0))

    @python_method
    def _draw_detail(self, y, height, box, cols, e):
        tokens.FOOTER.set()
        NSBezierPath.fillRect_(NSMakeRect(0, y, box.size.width, height))
        tokens.BORDER.set()
        NSBezierPath.fillRect_(NSMakeRect(0, y + height - 1, box.size.width, 1))

        #  The peak rule down the left edge of the transcription is one of the
        #  screen's two permitted uses of the peak colour.
        text_x = cols["text"]
        text_w = cols["text_w"] + 180.0
        body = e.text or "no speech detected"
        body_h = chrome.text_height(body, "body", text_w)
        tokens.PEAK.set()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(text_x - 12.0, y + 16.0, 2.5, body_h), 1.25, 1.25).fill()

        tokens.attributed(body, "body", tokens.FG).drawInRect_(
            NSMakeRect(text_x, y + 16.0, text_w, body_h))

        facts = []
        if e.where == "clipboard":
            facts.append("Left on the clipboard")
        elif e.where == "ignored":
            facts.append("No speech detected")
        elif e.app:
            facts.append(f"Landed in {e.app}")
        if e.secs:
            facts.append(f"{e.secs:.1f}s spoken")
        if e.text:
            facts.append(f"{len(e.text.split())} words")
        if e.ms:
            facts.append(f"{int(round(e.ms))} ms key-up to text")
        tokens.attributed(" · ".join(facts), "note", tokens.MUTED).drawAtPoint_(
            NSMakePoint(text_x, y + 16.0 + body_h + 10.0))

        for label_text, rect in self._detail_buttons(y, height, box, e):
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                rect, tokens.RADIUS_CTL, tokens.RADIUS_CTL)
            tokens.CTL.set()
            path.fill()
            (tokens.RECORD.colorWithAlphaComponent_(0.4)
             if label_text == "Delete" else tokens.BORDER).set()
            path.setLineWidth_(1.0)
            path.stroke()
            s = tokens.attributed(
                label_text, "note",
                tokens.RECORD if label_text == "Delete" else tokens.FG)
            s.drawAtPoint_(NSMakePoint(
                rect.origin.x + (rect.size.width - s.size().width) / 2.0,
                rect.origin.y + 5.0))

    @python_method
    def _detail_buttons(self, y, height, box, e):
        titles = ["Copy", "Paste again", "Delete"] if e.text else ["Delete"]
        out = []
        x = columns(box.size.width)["text"]
        by = y + height - 38.0
        for title in titles:
            w = tokens.attributed(title, "note").size().width + 24.0
            out.append((title, NSMakeRect(x, by, w, 26.0)))
            x += w + 8.0
        return out

    # ------------------------------------------------------------ input

    def mouseDown_(self, event):
        where = self.convertPoint_fromView_(event.locationInWindow(), None)
        box = self.bounds()
        for kind, y, height, payload in self.layout_rows:
            if not (y <= where.y < y + height):
                continue
            if kind == "row":
                self.expanded = None if payload is self.expanded else payload
                self._relayout()
                self.pane.layout()
            elif kind == "detail":
                for title, rect in self._detail_buttons(y, height, box, payload):
                    if _contains(rect, where):
                        self._act(title, payload)
                        return
            return

    @python_method
    def _act(self, title, entry):
        if title == "Copy" or title == "Paste again":
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            pb.setString_forType_(entry.text, NSPasteboardTypeString)
        if title == "Paste again":
            #  Re-paste through the same path a live dictation uses, so it
            #  obeys the same "is this field editable" rule.
            import shout
            self.window().orderOut_(None)
            shout.paste(entry.text)
        elif title == "Delete":
            self.pane.store.delete(entry)
            self.expanded = None
            self.pane.reload()

    def updateTrackingAreas(self):
        for area in list(self.trackingAreas()):
            self.removeTrackingArea_(area)
        self.addTrackingArea_(NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            NSTrackingMouseMoved | NSTrackingActiveInKeyWindow, self, None))

    def mouseMoved_(self, event):
        where = self.convertPoint_fromView_(event.locationInWindow(), None)
        hit = -1
        for i, (kind, y, height, _payload) in enumerate(self.layout_rows):
            if kind == "row" and y <= where.y < y + height:
                hit = i
                break
        if hit != self.hover:
            self.hover = hit
            self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        if self.hover != -1:
            self.hover = -1
            self.setNeedsDisplay_(True)


def _truncate(attributed, text, role, color, width):
    """Tail-truncate to `width`. Nothing in this table wraps: a row that grows
    breaks the alignment the columns exist to provide — the full text is one
    click away in the detail row."""
    if attributed.size().width <= width:
        return attributed
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if tokens.attributed(text[:mid] + "…", role).size().width <= width:
            lo = mid
        else:
            hi = mid - 1
    return tokens.attributed(text[:lo] + "…", role, color)


def _contains(rect, point):
    return (rect.origin.x <= point.x <= rect.origin.x + rect.size.width
            and rect.origin.y <= point.y <= rect.origin.y + rect.size.height)
