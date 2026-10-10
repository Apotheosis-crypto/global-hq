#!/bin/bash
# Double-click to open Global HQ on a Mac.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display alert "Global HQ needs Python 3" message "Install it from python.org, then double-click Global HQ again."'
  open "https://www.python.org/downloads/"
  exit 1
fi
[ -f config.json ] || cp config.example.json config.json
python3 -c "import webview, certifi" 2>/dev/null || python3 -m pip install --user --quiet pywebview certifi || echo "Couldn't install the app window; opening in your browser instead."
python3 -m hq app
