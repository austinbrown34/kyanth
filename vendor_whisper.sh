#!/usr/bin/env bash
# Collect whisper-server and its entire non-system dylib closure into vendor/,
# so a packaged Kyanth.app needs no Homebrew.
#
# Two things that will waste your afternoon if you don't know them:
#
#   1. install_name_tool invalidates a Mach-O code signature. macOS then kills
#      the process with SIGKILL and *no output at all* — empty stdout, empty
#      stderr, exit 137. Everything must be re-signed after rewriting, and
#      dependencies must be signed before the binaries that load them.
#
#   2. ggml loads its compute backends (Metal, CPU, BLAS) as separate .so files
#      at runtime. They are placed next to the executable so ggml finds them
#      without an absolute Homebrew path baked in.
set -euo pipefail
cd "$(dirname "$0")"

VENDOR="${1:-vendor}"
SRC_BIN="$(command -v whisper-server || echo /opt/homebrew/bin/whisper-server)"

[ -x "$SRC_BIN" ] || { echo "whisper-server not found — brew install whisper-cpp" >&2; exit 1; }

rm -rf "$VENDOR"
mkdir -p "$VENDOR/bin" "$VENDOR/lib"
cp "$SRC_BIN" "$VENDOR/bin/"

# backends live beside the binary so ggml discovers them locally
shopt -s nullglob
for so in /opt/homebrew/Cellar/ggml/*/libexec/*.so /opt/homebrew/lib/ggml/*.so; do
  cp "$so" "$VENDOR/bin/"
done
shopt -u nullglob

resolve() {                      # dependency reference -> absolute path
  local dep="$1" origin="$2" base
  base="$(basename "$dep")"
  case "$dep" in
    /usr/lib/*|/System/*) return ;;
    @rpath/*|@loader_path/*)
      for d in /opt/homebrew/opt/whisper-cpp/lib /opt/homebrew/lib \
               /opt/homebrew/Cellar/ggml/*/lib "$(dirname "$origin")"; do
        [ -f "$d/$base" ] && { echo "$d/$base"; return; }
      done ;;
    /opt/homebrew/*) [ -f "$dep" ] && echo "$dep" ;;
  esac
}

# breadth-first over the dependency graph
declare -a queue=()
for f in "$VENDOR"/bin/*; do queue+=("$f"); done
seen=""
while [ ${#queue[@]} -gt 0 ]; do
  f="${queue[0]}"; queue=("${queue[@]:1}")
  [ -f "$f" ] || continue
  while read -r dep; do
    [ -n "$dep" ] || continue
    abs="$(resolve "$dep" "$f")" || true
    [ -n "${abs:-}" ] || continue
    base="$(basename "$abs")"
    case "$seen" in *"|$base|"*) continue ;; esac
    seen="$seen|$base|"
    cp "$abs" "$VENDOR/lib/$base"
    chmod u+w "$VENDOR/lib/$base"
    queue+=("$VENDOR/lib/$base")
  done < <(otool -L "$f" 2>/dev/null | tail -n +2 | awk '{print $1}')
done

# rewrite every reference to a @loader_path-relative one
for f in "$VENDOR"/bin/* "$VENDOR"/lib/*.dylib; do
  [ -f "$f" ] || continue
  case "$f" in */lib/*) rel="@loader_path" ;; *) rel="@loader_path/../lib" ;; esac
  install_name_tool -id "@loader_path/$(basename "$f")" "$f" 2>/dev/null || true
  otool -L "$f" 2>/dev/null | tail -n +2 | awk '{print $1}' | while read -r dep; do
    case "$dep" in
      /usr/lib/*|/System/*|@loader_path/*) continue ;;
    esac
    install_name_tool -change "$dep" "$rel/$(basename "$dep")" "$f" 2>/dev/null || true
  done
done

# Re-sign: dependencies first, then the executables that load them.
for f in "$VENDOR"/lib/*.dylib; do codesign --force --sign - "$f" >/dev/null 2>&1; done
for f in "$VENDOR"/bin/*.so;    do codesign --force --sign - "$f" >/dev/null 2>&1; done
codesign --force --sign - "$VENDOR/bin/whisper-server" >/dev/null 2>&1
codesign -v "$VENDOR/bin/whisper-server" 2>/dev/null \
  || { echo "signature verification failed" >&2; exit 1; }

echo "vendored -> $VENDOR"
echo "  $(ls "$VENDOR/lib" | wc -l | tr -d ' ') dylibs, $(ls "$VENDOR"/bin/*.so 2>/dev/null | wc -l | tr -d ' ') backends, $(du -sh "$VENDOR" | cut -f1)"

# Prove it runs with Homebrew removed from the environment entirely.
if [ -n "${2:-}" ] && [ -f "$2" ]; then
  echo "  verifying against $2 with no Homebrew on PATH…"
  env -i HOME="$HOME" PATH=/usr/bin:/bin \
    "$VENDOR/bin/whisper-server" -m "$2" --host 127.0.0.1 --port 8231 \
    >/tmp/vendor-verify.log 2>&1 &
  pid=$!
  for _ in $(seq 1 40); do sleep 1; nc -z 127.0.0.1 8231 2>/dev/null && break; done
  if nc -z 127.0.0.1 8231 2>/dev/null; then echo "  OK — server runs standalone"
  else echo "  FAILED — see /tmp/vendor-verify.log" >&2; kill $pid 2>/dev/null; exit 1; fi
  kill $pid 2>/dev/null || true
fi
