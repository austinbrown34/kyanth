#!/usr/bin/env bash
# Build a signed, notarizable Kyanth.app and wrap it in a drag-to-Applications
# DMG. Produces dist/kyanth-<version>.dmg.
#
#   ./build_release.sh                 sign with Developer ID, no notarization
#   ./build_release.sh --notarize      also submit to Apple and staple
#   ./build_release.sh --adhoc         ad-hoc signature (local testing only)
#
# Notarization needs credentials, supplied either as a stored keychain profile
#   xcrun notarytool store-credentials kyanth-notary \
#     --apple-id you@example.com --team-id TEAMID --password APP_SPECIFIC_PW
# or as APPLE_ID / TEAM_ID / APP_PASSWORD in the environment.
set -euo pipefail
cd "$(dirname "$0")"

VERSION="$(grep -m1 '^VERSION = ' kyanth.spec | cut -d'"' -f2)"
APP="dist/Kyanth.app"
DMG="dist/kyanth-$VERSION.dmg"
IDENTITY="${KYANTH_IDENTITY:-Developer ID Application}"
NOTARY_PROFILE="${KYANTH_NOTARY_PROFILE:-kyanth-notary}"
NOTARIZE=0
ADHOC=0
for arg in "$@"; do
  case "$arg" in
    --notarize) NOTARIZE=1 ;;
    --adhoc)    ADHOC=1 ;;
    *) echo "unknown option: $arg" >&2; exit 1 ;;
  esac
done

# Check the credential before building rather than after: notarization is the
# last step, so a bad profile otherwise wastes the whole build to find out.
#   xcrun notarytool store-credentials kyanth-notary --apple-id ... --team-id ...
if [ "$NOTARIZE" -eq 1 ] \
   && ! xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1; then
  echo "keychain profile '$NOTARY_PROFILE' does not authenticate — fix it before building" >&2
  echo "  xcrun notarytool store-credentials $NOTARY_PROFILE --apple-id <id> --team-id <team>" >&2
  exit 1
fi

# ------------------------------------------------------------- 1. vendor
echo "==> vendoring whisper-server"
./vendor_whisper.sh vendor >/dev/null

# -------------------------------------------------------------- 2. model
MODEL_REL="$(uv run python -c 'import yaml;print(yaml.safe_load(open("config.yaml"))["model"])')"
if [ ! -f "$MODEL_REL" ]; then
  echo "==> downloading $(basename "$MODEL_REL")"
  mkdir -p "$(dirname "$MODEL_REL")"
  curl -fL --progress-bar -o "$MODEL_REL.part" \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$(basename "$MODEL_REL")"
  [ "$(stat -f%z "$MODEL_REL.part")" -gt 10000000 ] || { echo "download failed" >&2; exit 1; }
  mv "$MODEL_REL.part" "$MODEL_REL"
fi

# ------------------------------------------------------------ 2b. import
# Import every module for real. `py_compile` only parses — it never executes a
# class body, so pyobjc selector errors (BadPrototypeError) sail through it and
# surface only when the frozen app refuses to launch.
# Version must match in both places or the upgrade handover compares against
# the wrong number.
SPEC_V="$(grep -m1 '^VERSION = ' kyanth.spec | cut -d'"' -f2)"
MOD_V="$(grep -m1 '^VERSION = ' version.py | cut -d'"' -f2)"
[ "$SPEC_V" = "$MOD_V" ] || {
  echo "version mismatch: kyanth.spec=$SPEC_V version.py=$MOD_V" >&2; exit 1; }

echo "==> import check"
uv run python -c "
import ast, collections, importlib, pathlib, sys

# A pyobjc class name IS its Objective-C class name, so two modules defining
# the same one is a hard crash — but only once both are loaded together, which
# a single-module smoke test never does. Name the collision before importing,
# because the runtime error does not say which other module claimed the name.
OBJC = {'NSObject','NSView','NSWindow','NSPanel','NSButton','NSTextField',
        'NSScrollView','NSTableView','NSApplication'}
seen = collections.defaultdict(list)
for f in sorted(pathlib.Path('.').glob('*.py')):
    tree = ast.parse(f.read_text())
    local = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
        attrs = [b for b in node.bases if isinstance(b, ast.Attribute)]
        if bases & OBJC or bases & local or attrs:
            seen[node.name].append(f.name)
dupes = {k: v for k, v in seen.items() if len(v) > 1}
if dupes:
    for k, v in sorted(dupes.items()):
        print(f'    Objective-C class name {k!r} defined in {\" and \".join(v)}',
              file=sys.stderr)
    sys.exit(1)

for m in ('paths','config','hotkey','postprocess','vad','sounds','history',
          'loginitem','tokens','chrome','overlay','menuheader','history_view',
          'kyanth','settings_ui','setup_ui','menubar'):
    importlib.import_module(m)
print('    all modules import cleanly, no class-name collisions')
" || { echo "import check failed — not building" >&2; exit 1; }

# -------------------------------------------------------------- 3. build
echo "==> building app bundle"
rm -rf build dist/Kyanth dist/Kyanth.app
# PyInstaller logs "ERROR: Hidden import 'x' not found" and then exits 0, so a
# missing module sails through the build, gets signed and notarised, and only
# surfaces as a crash on the user's machine. Fail here instead.
uv run pyinstaller kyanth.spec --noconfirm --clean --log-level WARN 2>&1 \
  | tee /tmp/kyanth-pyinstaller.log
if grep -q "^[0-9]* ERROR:" /tmp/kyanth-pyinstaller.log; then
  grep "^[0-9]* ERROR:" /tmp/kyanth-pyinstaller.log >&2
  echo "pyinstaller reported errors — not shipping this bundle" >&2
  exit 1
fi

# --------------------------------------------------------------- 4. sign
# Inside-out order is mandatory: nested code must be signed before the bundle
# that contains it, or the outer signature seals an unsigned nested binary and
# Gatekeeper rejects it.
if [ "$ADHOC" -eq 1 ]; then
  SIGN_ARGS=(--force --sign -)
  echo "==> signing (ad-hoc — local testing only)"
else
  SIGN_ARGS=(--force --options runtime --timestamp
             --entitlements entitlements.plist --sign "$IDENTITY")
  echo "==> signing with: $IDENTITY"
fi

# Enumerate by content, not by filename. Matching *.dylib and *.so misses
# every extensionless Mach-O — which is how the embedded
# Python.framework/Versions/3.14/Python kept Homebrew's signature and got the
# whole submission rejected. It also silently missed whisper-server, because
# the hardcoded path guessed Resources/ when PyInstaller had put it in
# Frameworks/.
# NB: no `mapfile` — that is a bash 4 builtin and macOS ships bash 3.2, where
# it fails with "command not found".
MACHO_LIST="$(mktemp)"
find "$APP/Contents" -type f -print0 \
  | xargs -0 file 2>/dev/null \
  | awk -F: '/Mach-O/ {print $1}' \
  | awk '{print length"\t"$0}' | sort -rn | cut -f2- > "$MACHO_LIST"   # deepest first
echo "    signing $(wc -l < "$MACHO_LIST" | tr -d ' ') nested binaries"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  codesign "${SIGN_ARGS[@]}" "$f" || { echo "FAILED to sign: $f" >&2; exit 1; }
done < "$MACHO_LIST"
rm -f "$MACHO_LIST"

# Frameworks are signed as bundles, after their contents.
for fw in "$APP"/Contents/Frameworks/*.framework; do
  [ -d "$fw" ] || continue
  ver="$(ls -d "$fw"/Versions/* 2>/dev/null | grep -v Current | head -1)"
  [ -n "$ver" ] && codesign "${SIGN_ARGS[@]}" "$ver"
done

codesign "${SIGN_ARGS[@]}" "$APP"

echo "==> verifying"
codesign --verify --deep --strict --verbose=2 "$APP" 2>&1 | sed 's/^/    /'
if [ "$ADHOC" -eq 0 ]; then
  spctl --assess --type execute --verbose "$APP" 2>&1 | sed 's/^/    /' || \
    echo "    (spctl will fail until notarized — expected)"
fi

# ---------------------------------------------------------- 5. notarize
if [ "$NOTARIZE" -eq 1 ]; then
  echo "==> notarizing (this takes a few minutes)"
  ZIP="dist/kyanth-$VERSION.zip"
  ditto -c -k --keepParent "$APP" "$ZIP"
  if xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1; then
    CRED=(--keychain-profile "$NOTARY_PROFILE")
  elif [ -n "${APPLE_ID:-}" ] && [ -n "${TEAM_ID:-}" ] && [ -n "${APP_PASSWORD:-}" ]; then
    CRED=(--apple-id "$APPLE_ID" --team-id "$TEAM_ID" --password "$APP_PASSWORD")
  else
    echo "no notarization credentials — see the header of this script" >&2
    exit 1
  fi
  if ! xcrun notarytool submit "$ZIP" "${CRED[@]}" --wait | tee /tmp/notarytool-submit.log; then
    echo "notarization submission failed" >&2; exit 1
  fi
  # `notarytool submit --wait` exits 0 even when Apple rejects the archive, so
  # the status line has to be checked explicitly or the build happily ships an
  # unnotarized DMG.
  if ! grep -q "status: Accepted" /tmp/notarytool-submit.log; then
    SUB=$(grep -oE "id: [0-9a-f-]{36}" /tmp/notarytool-submit.log | head -1 | awk "{print \$2}")
    echo "NOTARIZATION REJECTED — fetching reasons:" >&2
    xcrun notarytool log "$SUB" "${CRED[@]}" 2>/dev/null \
      | python3 -c "import json,sys; d=json.load(sys.stdin); [print('  -', i.get('message'), '\n    ', i.get('path','')) for i in (d.get('issues') or [])]" >&2
    exit 1
  fi
  xcrun stapler staple "$APP"
  rm -f "$ZIP"
  echo "==> stapled"
fi

# ---------------------------------------------------------------- 6. dmg
echo "==> building DMG"
rm -rf dist/dmg "$DMG"
mkdir -p dist/dmg
cp -R "$APP" dist/dmg/
ln -s /Applications dist/dmg/Applications
hdiutil create -volname "Kyanth" -srcfolder dist/dmg -ov -format UDZO "$DMG" >/dev/null
rm -rf dist/dmg
[ "$ADHOC" -eq 0 ] && codesign --force --sign "$IDENTITY" "$DMG"

# The DMG needs its own notarization pass. Stapling the app does not give the
# disk image a ticket, so `stapler staple` on the DMG fails with "Record not
# found" — the first build looked successful right up to that point.
if [ "$NOTARIZE" -eq 1 ]; then
  echo "==> notarizing the DMG"
  xcrun notarytool submit "$DMG" "${CRED[@]}" --wait | tee /tmp/notarytool-dmg.log
  grep -q "status: Accepted" /tmp/notarytool-dmg.log || {
    echo "DMG notarization rejected" >&2; exit 1; }
  xcrun stapler staple "$DMG"
fi

echo
echo "built $DMG  ($(du -h "$DMG" | cut -f1))"

# State the notarization verdict plainly, every time. A previous build printed
# only a quiet one-line note when --notarize was omitted, and the unnotarized
# DMG was then published over a good one.
if xcrun stapler validate "$DMG" >/dev/null 2>&1; then
  echo "NOTARIZED — opens with no Gatekeeper warning. Publish: ./publish_release.sh"
else
  echo "*** NOT NOTARIZED ***"
  echo "    Users will see \"Apple could not verify Kyanth is free of malware\"."
  echo "    For a build you intend to ship, run: ./build_release.sh --notarize"
fi
exit 0
