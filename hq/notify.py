"""Delivery channels: console, ntfy push (phone app), email (SMTP), generic webhook."""
import json
import os
import platform
import shutil
import smtplib
import subprocess
import urllib.request
from email.message import EmailMessage


def _post(url, data, headers):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=15).read()


def send(cfg, subject, body, html_body=None, urgent=False):
    """Send on every configured channel; return a list of (channel, error-or-None)."""
    results = []
    for ch in cfg["alerts"]["channels"]:
        try:
            if ch == "console":
                print(f"\n=== {subject} ===\n{body}\n")
            elif ch == "ntfy":
                n = cfg["ntfy"]
                if not n["topic"] or n["topic"].startswith("CHANGE-ME"):
                    raise ValueError("no ntfy topic configured, skipping")  # never post to the shared placeholder topic
                _post(f"{n['server'].rstrip('/')}/{n['topic']}", body.encode(),
                      {"Title": subject.encode("ascii", "ignore").decode(), "Priority": "urgent" if urgent else "default", "Tags": "globe_with_meridians"})
            elif ch == "email":
                e = cfg["email"]
                msg = EmailMessage()
                msg["Subject"], msg["From"], msg["To"] = subject, e["username"], e["to"]
                msg.set_content(body)
                if html_body:
                    msg.add_alternative(html_body, subtype="html")
                with smtplib.SMTP(e["smtp_host"], e["smtp_port"], timeout=20) as s:
                    s.starttls()
                    s.login(e["username"], os.environ.get(e["password_env"], ""))
                    s.send_message(msg)
            elif ch == "desktop":
                desktop(subject, body.splitlines()[0] if body else "")
            elif ch == "webhook":
                _post(cfg["webhook"]["url"], json.dumps({"subject": subject, "body": body}).encode(), {"Content-Type": "application/json"})
            results.append((ch, None))
        except Exception as err:  # noqa: BLE001 - one channel failing must not block others
            results.append((ch, f"{type(err).__name__}: {err}"))
    return results


def alert_text(ev, items):
    lines = [f"[{ev['category']} | {ev['region']} | score {ev['score']}] {ev['headline']}", ""]
    lines += [f"- {r}" for r in json.loads(ev["reasons"]) if r]
    lines += ["", "Evidence:"] + [f"- {i['source_name']}: {i['url']}" for i in items if i["verified"]][:6]
    return "\n".join(lines)


def desktop(title, message):
    """Native notification on this computer (macOS, Windows 10+, Linux with notify-send)."""
    system = platform.system()
    if system == "Darwin":
        q = lambda t: '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"'
        subprocess.run(["osascript", "-e", f"display notification {q(message)} with title {q(title)} sound name \"Glass\""], check=True, timeout=10)
    elif system == "Windows":
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
            "$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            "$t = $x.GetElementsByTagName('text'); $t.Item(0).AppendChild($x.CreateTextNode($env:HQ_T)) > $null; $t.Item(1).AppendChild($x.CreateTextNode($env:HQ_M)) > $null;"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Global HQ').Show([Windows.UI.Notifications.ToastNotification]::new($x))"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=15,
                       env={**os.environ, "HQ_T": title, "HQ_M": message}, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    elif shutil.which("notify-send"):
        subprocess.run(["notify-send", "-u", "critical", title, message], check=True, timeout=10)
    else:
        raise RuntimeError("no desktop notification method on this system")
