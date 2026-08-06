#!/usr/bin/env bash
# Unregister the login item, stop shout, and remove the installed runtime.
set -euo pipefail

PREFIX="$HOME/Library/Application Support/shout"
APP="$HOME/Applications/shout.app"
LABEL="local.shout.dictation"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null && echo "agent unloaded" || echo "agent not loaded"
rm -f "$PLIST" && echo "removed login item"

pkill -f "menubar.py" 2>/dev/null && echo "stopped menubar" || true
pkill -f "whisper-server" 2>/dev/null && echo "stopped model server" || true

rm -rf "$APP" && echo "removed $APP"

if [ "${1:-}" = "--purge" ]; then
  rm -rf "$PREFIX" && echo "removed $PREFIX"
else
  echo "kept runtime at $PREFIX  (./uninstall.sh --purge to delete)"
fi

echo
echo "Remove the Accessibility entry manually in System Settings for a clean slate."
