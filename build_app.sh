#!/usr/bin/env bash
# Build Kyanth.app.
#
# Usage: ./build_app.sh <runtime-prefix> <output-app-path>
#
# Why a bundle: macOS attributes TCC permissions (Accessibility, Microphone)
# to the responsible process, which for a bundled app is the app itself.
# Running menubar.py from a terminal attaches the grant to the terminal — which
# is why the Phase 0 spike needed cmux.app granted.
#
# Why <runtime-prefix> is a parameter: an app launched through LaunchServices
# gets NO access to ~/Documents, ~/Desktop or ~/Downloads without an explicit
# TCC grant. A runtime living under ~/Documents fails at interpreter startup
# with `PermissionError: .venv/pyvenv.cfg`. install.sh therefore stages the
# runtime under ~/Library/Application Support, which is unrestricted.
set -euo pipefail

PREFIX="${1:?usage: build_app.sh <runtime-prefix> <output-app-path>}"
APP="${2:?usage: build_app.sh <runtime-prefix> <output-app-path>}"
CONTENTS="$APP/Contents"

rm -rf "$APP"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>              <string>Kyanth</string>
  <key>CFBundleDisplayName</key>       <string>Kyanth</string>
  <key>CFBundleIdentifier</key>        <string>local.kyanth.dictation</string>
  <key>CFBundleVersion</key>           <string>0.4.0</string>
  <key>CFBundleShortVersionString</key><string>0.4.0</string>
  <key>CFBundlePackageType</key>       <string>APPL</string>
  <key>CFBundleExecutable</key>        <string>Kyanth</string>
  <key>CFBundleIconFile</key>          <string>Kyanth</string>
  <!-- menu-bar only: no Dock icon, no app-switcher entry -->
  <key>LSUIElement</key>               <true/>
  <key>LSMinimumSystemVersion</key>    <string>13.0</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>Kyanth transcribes your speech locally to type it into the focused app.</string>
</dict>
</plist>
PLIST

cat > "$CONTENTS/MacOS/Kyanth" <<LAUNCHER
#!/bin/bash
# exec so python replaces this shell and remains the bundle's main process.
#
# A bundle launched via \`open\` inherits no terminal, so without this redirect
# every traceback vanishes and failure looks like "it just doesn't start".
cd "$PREFIX"
mkdir -p "$PREFIX/logs"
# -u: stdout to a file is block-buffered, so without this the log stays
# empty until the buffer fills or the process dies — which made a working
# app look like a silent one.
exec "$PREFIX/.venv/bin/python" -u "$PREFIX/menubar.py" "\$@" \\
  >> "$PREFIX/logs/app.log" 2>&1
LAUNCHER
chmod +x "$CONTENTS/MacOS/Kyanth"

# Finder, Login Items, and the Accessibility list all read this.
if [ -f "$PREFIX/assets/kyanth.icns" ]; then
  cp "$PREFIX/assets/kyanth.icns" "$CONTENTS/Resources/kyanth.icns"
else
  echo "warning: no icon at $PREFIX/assets/kyanth.icns (run make_icons.py)"
fi

# Ad-hoc signature gives the bundle a stable identity so TCC grants survive
# rebuilds instead of silently reverting to "not granted".
codesign --force --sign - --identifier local.kyanth.dictation "$APP" 2>/dev/null \
  || echo "warning: codesign failed; grants may not persist across rebuilds"

echo "built $APP  (runtime: $PREFIX)"
