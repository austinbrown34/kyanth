#!/usr/bin/env bash
# Build a signed, notarizable shout.app and wrap it in a drag-to-Applications
# DMG. Produces dist/shout-<version>.dmg.
#
#   ./build_release.sh                 sign with Developer ID, no notarization
#   ./build_release.sh --notarize      also submit to Apple and staple
#   ./build_release.sh --adhoc         ad-hoc signature (local testing only)
#
# Notarization needs credentials, supplied either as a stored keychain profile
#   xcrun notarytool store-credentials shout-notary \
#     --apple-id you@example.com --team-id TEAMID --password APP_SPECIFIC_PW
# or as APPLE_ID / TEAM_ID / APP_PASSWORD in the environment.
set -euo pipefail
cd "$(dirname "$0")"

VERSION="$(grep -m1 '^VERSION = ' shout.spec | cut -d'"' -f2)"
APP="dist/shout.app"
DMG="dist/shout-$VERSION.dmg"
IDENTITY="${SHOUT_IDENTITY:-Developer ID Application}"
NOTARY_PROFILE="${SHOUT_NOTARY_PROFILE:-shout-notary}"

NOTARIZE=0
ADHOC=0
for arg in "$@"; do
  case "$arg" in
    --notarize) NOTARIZE=1 ;;
    --adhoc)    ADHOC=1 ;;
    *) echo "unknown option: $arg" >&2; exit 1 ;;
  esac
done

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

# -------------------------------------------------------------- 3. build
echo "==> building app bundle"
rm -rf build dist/shout dist/shout.app
uv run pyinstaller shout.spec --noconfirm --clean --log-level WARN

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

find "$APP/Contents" \( -name '*.dylib' -o -name '*.so' \) -type f -print0 \
  | xargs -0 -n1 codesign "${SIGN_ARGS[@]}" 2>/dev/null || true
# whisper-server is a nested executable, not a library
codesign "${SIGN_ARGS[@]}" "$APP/Contents/Resources/vendor/bin/whisper-server" 2>/dev/null || true
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
  ZIP="dist/shout-$VERSION.zip"
  ditto -c -k --keepParent "$APP" "$ZIP"
  if xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1; then
    CRED=(--keychain-profile "$NOTARY_PROFILE")
  elif [ -n "${APPLE_ID:-}" ] && [ -n "${TEAM_ID:-}" ] && [ -n "${APP_PASSWORD:-}" ]; then
    CRED=(--apple-id "$APPLE_ID" --team-id "$TEAM_ID" --password "$APP_PASSWORD")
  else
    echo "no notarization credentials — see the header of this script" >&2
    exit 1
  fi
  xcrun notarytool submit "$ZIP" "${CRED[@]}" --wait
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
hdiutil create -volname "shout" -srcfolder dist/dmg -ov -format UDZO "$DMG" >/dev/null
rm -rf dist/dmg
[ "$ADHOC" -eq 0 ] && codesign --force --sign "$IDENTITY" "$DMG"
[ "$NOTARIZE" -eq 1 ] && xcrun stapler staple "$DMG"

echo
echo "built $DMG  ($(du -h "$DMG" | cut -f1))"
[ "$NOTARIZE" -eq 0 ] && [ "$ADHOC" -eq 0 ] && \
  echo "not notarized — first launch elsewhere needs right-click > Open"
exit 0
