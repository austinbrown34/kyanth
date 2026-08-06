#!/usr/bin/env bash
# Install shout as a menu-bar app that starts at login.
#
# Layout:
#   ~/Library/Application Support/shout/   runtime: code, venv, model, config
#   ~/Applications/shout.app               the bundle
#   ~/Library/LaunchAgents/…plist          login item
#
# The runtime is staged out of this directory rather than run in place because
# an app launched by LaunchServices gets no access to ~/Documents without an
# explicit TCC grant — the interpreter dies reading .venv/pyvenv.cfg.
set -euo pipefail
cd "$(dirname "$0")"

SRC="$(pwd)"
PREFIX="$HOME/Library/Application Support/shout"
APP="$HOME/Applications/shout.app"
LABEL="local.shout.dictation"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

# ---------------------------------------------------------------- checks
missing=""
command -v uv          >/dev/null || missing="$missing\n  uv           https://docs.astral.sh/uv/  (or: brew install uv)"
command -v whisper-server >/dev/null || \
  [ -x /opt/homebrew/bin/whisper-server ] || [ -x /usr/local/bin/whisper-server ] || \
  missing="$missing\n  whisper-cpp  brew install whisper-cpp"
if [ -n "$missing" ]; then
  printf "Missing prerequisites:%b\n\n" "$missing"
  exit 1
fi

# --------------------------------------------------------- model download
MODEL_REL="$(uv run python -c 'import config; print(config.load().model)')"
if [ ! -f "$SRC/$MODEL_REL" ]; then
  echo "==> downloading $(basename "$MODEL_REL") (not in git — too large)"
  mkdir -p "$SRC/$(dirname "$MODEL_REL")"
  curl -fL --progress-bar \
    -o "$SRC/$MODEL_REL.part" \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$(basename "$MODEL_REL")"
  # Guard against a truncated or error-page download being staged as a model.
  size=$(stat -f%z "$SRC/$MODEL_REL.part")
  if [ "$size" -lt 10000000 ]; then
    rm -f "$SRC/$MODEL_REL.part"
    echo "download failed (got $size bytes)" >&2
    exit 1
  fi
  mv "$SRC/$MODEL_REL.part" "$SRC/$MODEL_REL"
fi

echo "==> staging runtime to $PREFIX"
mkdir -p "$PREFIX/models" "$PREFIX/logs"
cp menubar.py shout.py config.py postprocess.py vad.py hotkey.py settings_ui.py \
   sounds.py history.py make_icons.py pyproject.toml "$PREFIX/"
mkdir -p "$PREFIX/assets"
cp assets/shout.icns assets/menubar-*.png "$PREFIX/assets/"
[ -f uv.lock ] && cp uv.lock "$PREFIX/"

# Don't clobber a config the user has already tuned in place.
if [ -f "$PREFIX/config.yaml" ]; then
  echo "    keeping existing config.yaml"
else
  cp config.yaml "$PREFIX/"
fi

# Copy only the model actually configured — the others are ~1GB of dead weight.
if [ ! -f "$PREFIX/$MODEL_REL" ]; then
  echo "    copying $MODEL_REL"
  mkdir -p "$PREFIX/$(dirname "$MODEL_REL")"
  cp "$SRC/$MODEL_REL" "$PREFIX/$MODEL_REL"
else
  echo "    model already staged"
fi

echo "==> building venv in place"
( cd "$PREFIX" && uv sync --quiet )

echo "==> building app bundle"
mkdir -p "$HOME/Applications"
./build_app.sh "$PREFIX" "$APP"

echo "==> registering login item"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <!-- via \`open\` rather than the inner binary: LaunchServices preserves the
       bundle identity TCC keys permissions on. -->
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-a</string>
    <string>$APP</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <!-- KeepAlive would fight the Quit menu item: launchd would relaunch the app
       every time you quit it deliberately. -->
  <key>KeepAlive</key>
  <false/>
  <key>StandardOutPath</key>
  <string>$PREFIX/logs/launchd.log</string>
  <key>StandardErrorPath</key>
  <string>$PREFIX/logs/launchd.log</string>
</dict>
</plist>
PLISTEOF

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"

# Make sure LaunchServices knows the bundle before anything tries `open -a`.
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  -f "$APP" 2>/dev/null || true

cat <<EOF

Installed.

  app       $APP
  runtime   $PREFIX
  login     $PLIST

Start it now:   open -a "$APP"

FIRST RUN: grant Accessibility to shout.app.
  System Settings > Privacy & Security > Accessibility  ->  add
  $APP

The grant follows the bundle, so this is once — not per terminal — and it
survives rebuilds thanks to the ad-hoc signature.

Logs:      $PREFIX/logs/app.log
Update:    ./install.sh          (re-stages code, keeps your config)
Remove:    ./uninstall.sh
EOF
