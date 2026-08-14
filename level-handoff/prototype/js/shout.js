/* ==========================================================================
   shout — shared behaviour for all three concepts.
   Appearance, live level meters, shortcut chord recording, clipboard,
   menu toggling and the transcript corpus every History surface reads from.
   ========================================================================== */
(function (global) {
  'use strict';

  var SHOUT = {};

  /* ---------------------------------------------------------------- theme */
  SHOUT.appearance = function () {
    var KEY = 'shout:appearance';
    var stored = null;
    try { stored = localStorage.getItem(KEY); } catch (_) {}
    var sysDark = global.matchMedia && global.matchMedia('(prefers-color-scheme: dark)').matches;
    var mode = stored || (sysDark ? 'dark' : 'light');

    function apply(m) {
      document.documentElement.setAttribute('data-appearance', m);
      Array.prototype.forEach.call(document.querySelectorAll('[data-set-appearance]'), function (b) {
        b.setAttribute('aria-pressed', String(b.getAttribute('data-set-appearance') === m));
      });
      try { localStorage.setItem(KEY, m); } catch (_) {}
    }
    apply(mode);
    document.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('[data-set-appearance]');
      if (b) apply(b.getAttribute('data-set-appearance'));
    });
  };

  /* ---------------------------------------------------------------- meter */
  /* Builds `bars` <i> elements inside el and animates them from a smoothed
     pseudo-speech envelope. This is a prototype stand-in for the real
     AVAudioEngine input level — the shape is what matters here. */
  SHOUT.meter = function (el, opts) {
    opts = opts || {};
    var bars = opts.bars || 14;
    var min = opts.min || 3;
    var max = opts.max || 18;
    var i, frag = document.createDocumentFragment();
    el.innerHTML = '';
    for (i = 0; i < bars; i++) frag.appendChild(document.createElement('i'));
    el.appendChild(frag);
    var items = Array.prototype.slice.call(el.children);

    var raf = null, t = 0, env = 0, target = 0, running = false;

    function frame() {
      t += 0.055;
      if (Math.random() < 0.09) target = Math.random();
      env += (target - env) * 0.16;
      var speech = Math.max(0, Math.sin(t * 1.7) * 0.45 + Math.sin(t * 0.6) * 0.3 + 0.35);
      items.forEach(function (bar, idx) {
        var centre = 1 - Math.abs((idx - (bars - 1) / 2) / ((bars - 1) / 2));
        var v = env * speech * (0.35 + centre * 0.85) + Math.random() * 0.1;
        var h = Math.round(min + Math.min(1, v) * (max - min));
        bar.style.height = h + 'px';
        bar.classList.toggle('hot', h > min + (max - min) * 0.55);
      });
      raf = requestAnimationFrame(frame);
    }

    return {
      start: function () { if (!running) { running = true; frame(); } },
      stop: function () {
        running = false;
        if (raf) cancelAnimationFrame(raf);
        raf = null;
        items.forEach(function (b) { b.style.height = min + 'px'; b.classList.remove('hot'); });
      },
      flat: function (h) {
        items.forEach(function (b) { b.style.height = (h || min) + 'px'; b.classList.remove('hot'); });
      }
    };
  };

  /* ------------------------------------------------------------- recorder */
  /* Chord capture that survives the current app's headline trick: modifiers
     are side-aware, so "⌃ + Right ⌥" is recordable, and the chord commits on
     the first key-up rather than the first key-down. */
  var SYM = { Meta: '⌘', Control: '⌃', Alt: '⌥', Shift: '⇧' };
  var SIDE = { Left: 'Left ', Right: 'Right ' };

  function label(e) {
    var code = e.code || '';
    var k = e.key;
    if (SYM[k]) {
      var side = /Left$/.test(code) ? 'Left' : (/Right$/.test(code) ? 'Right' : '');
      return (side ? SIDE[side] : '') + SYM[k];
    }
    if (k === ' ') return 'Space';
    if (k && k.length === 1) return k.toUpperCase();
    return k || code;
  }

  SHOUT.recorder = function (btn, out, onCommit) {
    var held = [], armed = false;

    function paint(list, live) {
      out.innerHTML = '';
      if (!list.length) {
        out.appendChild(Object.assign(document.createElement('span'), {
          className: 'muted', textContent: live ? 'Listening for keys…' : 'Not set'
        }));
        return;
      }
      list.forEach(function (l, i) {
        if (i) out.appendChild(Object.assign(document.createElement('span'), { className: 'muted', textContent: '+' }));
        out.appendChild(Object.assign(document.createElement('kbd'), { className: 'kbd', textContent: l }));
      });
    }

    function down(e) {
      if (!armed) return;
      e.preventDefault();
      var l = label(e);
      if (held.indexOf(l) === -1) held.push(l);
      paint(held, true);
    }
    function up(e) {
      if (!armed) return;
      e.preventDefault();
      armed = false;
      btn.textContent = 'Change…';
      btn.setAttribute('aria-pressed', 'false');
      document.removeEventListener('keydown', down, true);
      document.removeEventListener('keyup', up, true);
      paint(held, false);
      if (onCommit) onCommit(held.slice());
    }

    btn.addEventListener('click', function () {
      armed = true; held = [];
      btn.textContent = 'Press keys…';
      btn.setAttribute('aria-pressed', 'true');
      paint([], true);
      document.addEventListener('keydown', down, true);
      document.addEventListener('keyup', up, true);
    });

    return { paint: paint };
  };

  /* ------------------------------------------------------------ clipboard */
  SHOUT.copy = function (text, btn) {
    var restore = btn ? btn.textContent : null;
    function done() {
      if (!btn) return;
      btn.textContent = 'Copied';
      setTimeout(function () { btn.textContent = restore; }, 1300);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, done);
    } else { done(); }
  };

  /* ----------------------------------------------------------------- menu */
  SHOUT.menu = function (trigger, panel) {
    function close(e) {
      if (e && (panel.contains(e.target) || trigger.contains(e.target))) return;
      panel.hidden = true; trigger.classList.remove('open');
      document.removeEventListener('mousedown', close);
    }
    trigger.addEventListener('click', function () {
      var opening = panel.hidden;
      panel.hidden = !opening;
      trigger.classList.toggle('open', opening);
      if (opening) setTimeout(function () { document.addEventListener('mousedown', close); }, 0);
    });
  };

  /* ------------------------------------------------------------- hold key */
  /* Press-and-hold on a button OR the ⌥ key; mirrors hold-to-talk. */
  SHOUT.hold = function (el, onStart, onEnd) {
    var down = false;
    function start(e) { if (down) return; down = true; if (e) e.preventDefault(); onStart(); }
    function end() { if (!down) return; down = false; onEnd(); }
    if (el) {
      el.addEventListener('mousedown', start);
      el.addEventListener('touchstart', start, { passive: false });
    }
    document.addEventListener('mouseup', end);
    document.addEventListener('touchend', end);
    document.addEventListener('keydown', function (e) { if (e.key === 'Alt' && !e.repeat) start(e); });
    document.addEventListener('keyup', function (e) { if (e.key === 'Alt') end(); });
    return { start: start, end: end };
  };

  /* ------------------------------------------------------------ transcript corpus */
  /* Shared across all three History surfaces so the concepts are comparable.
     `out` mirrors the app's real outcome model: pasted / clipboard / ignored. */
  SHOUT.history = [
    { day: 'Today', date: 'Friday 14 August', t: '14:32', app: 'Mail', out: 'pasted', ms: 214, sec: 8.1,
      text: 'Pushing the release to Thursday so QA gets a full day with the notarized build. Nothing in the changelog is time-sensitive, and I would rather ship it slow than pull it back.' },
    { day: 'Today', date: 'Friday 14 August', t: '14:19', app: 'Notes', out: 'pasted', ms: 187, sec: 5.4,
      text: 'Note to self — the status item vanishes when the menu bar is full, so the overlay is the primary surface, not the fallback. Design for it that way.' },
    { day: 'Today', date: 'Friday 14 August', t: '13:58', app: '—', out: 'clipboard', ms: 203, sec: 3.2,
      text: 'Ask about the input monitoring prompt appearing twice on a clean install.' },
    { day: 'Today', date: 'Friday 14 August', t: '11:47', app: 'Xcode', out: 'pasted', ms: 176, sec: 6.9,
      text: 'Overlay must never become key window. If it takes focus the paste target changes underneath the user and the dictation lands in the overlay itself.' },
    { day: 'Today', date: 'Friday 14 August', t: '11:02', app: 'Slack', out: 'pasted', ms: 231, sec: 4.6,
      text: 'Can you take a look at the setup check when you get a minute — step six passes on my machine but not on the loaner.' },
    { day: 'Today', date: 'Friday 14 August', t: '09:41', app: '—', out: 'ignored', ms: 0, sec: 0.4,
      text: '' },
    { day: 'Yesterday', date: 'Thursday 13 August', t: '17:24', app: 'Terminal', out: 'clipboard', ms: 198, sec: 2.8,
      text: 'git log --oneline since the last tag, then pipe it into the changelog script.' },
    { day: 'Yesterday', date: 'Thursday 13 August', t: '16:10', app: 'Notes', out: 'pasted', ms: 244, sec: 11.3,
      text: 'Six states, three glyphs. Idle and transcribing look identical, and disabled, error and needs-permission all share one mark. Splitting those apart is most of the redesign — everything else is polish on top of a state model that already works.' },
    { day: 'Yesterday', date: 'Thursday 13 August', t: '15:35', app: 'Mail', out: 'pasted', ms: 169, sec: 3.7,
      text: 'Thanks — received. I will look at it tonight and come back with notes tomorrow morning.' },
    { day: 'Mon 11 Aug', date: 'Monday 11 August', t: '10:08', app: 'Notes', out: 'pasted', ms: 221, sec: 7.5,
      text: 'History is the most under-designed surface in the app and the most reusable content it holds. Everything a person dictated in a week is sitting in a JSONL file behind a plain table view.' },
    { day: 'Mon 11 Aug', date: 'Monday 11 August', t: '09:12', app: 'Safari', out: 'pasted', ms: 192, sec: 2.1,
      text: 'macOS accessibility permission programmatic grant' }
  ];

  SHOUT.words = function (s) { return s.trim() ? s.trim().split(/\s+/).length : 0; };
  SHOUT.esc = function (s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  };

  /* Deterministic bar heights for a waveform thumbnail — same text always
     draws the same shape, so rows stay stable across renders. */
  SHOUT.waveform = function (seed, n, max) {
    var out = [], h = 0, i;
    for (i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
    for (i = 0; i < n; i++) {
      h = (h * 1103515245 + 12345) >>> 0;
      out.push(2 + ((h >>> 16) % (max - 2)));
    }
    return out;
  };

  document.addEventListener('DOMContentLoaded', SHOUT.appearance);
  global.SHOUT = SHOUT;
})(window);
