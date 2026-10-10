"""Run Global HQ as a desktop app: the watch runs in the background and the dashboard opens in its own window.

Window, in order of preference:
  1. a native window via pywebview (installed by the launchers; optional)
  2. Chrome or Edge in app mode (no tabs or address bar)
  3. the default browser
"""
import os
import platform
import shutil
import subprocess
import threading
import time
import urllib.request
import webbrowser

from . import app, store

TITLE = "Global HQ"


def _wait_for(url, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1).read(1)
            return True
        except OSError:
            time.sleep(0.2)
    return False


def _chromium():
    candidates = {
        "Darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                   "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                   "/Applications/Chromium.app/Contents/MacOS/Chromium"],
        "Windows": [os.path.expandvars(p) for p in (
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")],
    }.get(platform.system(), [])
    found = [p for p in candidates if os.path.exists(p)]
    found += [shutil.which(n) for n in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge") if shutil.which(n)]
    return found[0] if found else None


def open_window(url):
    """Open the dashboard. Returns True if the call blocks until the window closes."""
    try:
        import webview  # pywebview
        webview.create_window(TITLE, url, width=1480, height=940, min_size=(900, 600), background_color="#03060c")
        webview.start()
        return True
    except ImportError:
        pass
    exe = _chromium()
    if exe:
        subprocess.Popen([exe, f"--app={url}", "--window-size=1480,940", "--new-window"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(url)
    return False


def main(cfg, src, demo=False):
    cfg.setdefault("alerts", {}).setdefault("channels", ["console", "desktop"])
    if demo:
        db = store.connect(":memory:")
        app.seed_sample(db, src)
        threading.Thread(target=app.serve, args=(db, cfg, src), daemon=True).start()
    else:
        db = store.connect(str(app.ROOT / cfg["db_path"]))
        threading.Thread(target=app.watch, args=(db, cfg, src), daemon=True).start()
    url = f"http://localhost:{cfg['port']}/"
    if not _wait_for(url):
        print(f"The dashboard didn't start. Is port {cfg['port']} already in use? Change \"port\" in config.json.")
        return
    print(f"{TITLE} is running at {url} (close this window or press Ctrl+C to quit)")
    if not open_window(url):
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
