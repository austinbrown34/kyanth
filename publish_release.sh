#!/usr/bin/env bash
# Publish the DMG to a GitHub release — but only if it is genuinely notarized.
#
# This exists because of a real failure: the DMG was notarized, then rebuilt
# several times with plain `build_release.sh` (which signs but does not
# notarize), and the unnotarized result was uploaded over the good asset with
# `--clobber`. Nothing complained, and users got
# "Apple could not verify Kyanth is free of malware".
#
# The upload is now gated on the artifact's own stapled ticket, so a build that
# skipped --notarize can never reach the release page.
#
#   ./publish_release.sh            publish to the version in kyanth.spec
#   ./publish_release.sh --allow-unnotarized   escape hatch, prints a warning
set -euo pipefail
cd "$(dirname "$0")"

VERSION="$(grep -m1 '^VERSION = ' kyanth.spec | cut -d'"' -f2)"
DMG="dist/kyanth-$VERSION.dmg"
TAG="v$VERSION"
ALLOW_UNNOTARIZED=0
[ "${1:-}" = "--allow-unnotarized" ] && ALLOW_UNNOTARIZED=1

[ -f "$DMG" ] || { echo "no $DMG — run ./build_release.sh --notarize first" >&2; exit 1; }

echo "==> verifying $DMG"

fail() { echo "  ✗ $1" >&2; return 1; }

# 1. the disk image itself carries a stapled ticket
if xcrun stapler validate "$DMG" >/dev/null 2>&1; then
  echo "  ✔ DMG has a stapled notarization ticket"
else
  fail "DMG is NOT notarized" || NOTARIZED=0
fi

# 2. the app inside it does too, and Gatekeeper accepts it
MP="$(mktemp -d)"
hdiutil attach "$DMG" -nobrowse -quiet -mountpoint "$MP"
trap 'hdiutil detach "$MP" -quiet 2>/dev/null || true' EXIT

APP_OK=1
xcrun stapler validate "$MP/Kyanth.app" >/dev/null 2>&1 \
  && echo "  ✔ app has a stapled ticket" \
  || { echo "  ✗ app is NOT notarized" >&2; APP_OK=0; }

ASSESS="$(spctl --assess --type execute --verbose "$MP/Kyanth.app" 2>&1 || true)"
echo "$ASSESS" | grep -q "accepted" \
  && echo "  ✔ Gatekeeper: $(echo "$ASSESS" | grep source= | tr -d ' ')" \
  || { echo "  ✗ Gatekeeper REJECTS the app" >&2; APP_OK=0; }

hdiutil detach "$MP" -quiet 2>/dev/null || true
trap - EXIT

if ! xcrun stapler validate "$DMG" >/dev/null 2>&1 || [ "$APP_OK" -eq 0 ]; then
  if [ "$ALLOW_UNNOTARIZED" -eq 1 ]; then
    echo
    echo "WARNING: publishing an unnotarized build. Users will see" >&2
    echo "\"Apple could not verify Kyanth is free of malware\" and must" >&2
    echo "right-click > Open." >&2
    echo
  else
    echo
    echo "REFUSING TO PUBLISH — this build is not notarized." >&2
    echo "Run:  ./build_release.sh --notarize" >&2
    exit 1
  fi
fi

echo "==> uploading to $TAG"
if gh release view "$TAG" >/dev/null 2>&1; then
  gh release upload "$TAG" "$DMG" --clobber
else
  gh release create "$TAG" "$DMG" --title "Kyanth $VERSION" --generate-notes
fi

echo
echo "published $DMG to $TAG"
shasum -a 256 "$DMG" | awk '{print "  sha256 " $1}'
