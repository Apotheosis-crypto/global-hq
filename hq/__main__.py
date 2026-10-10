"""python -m hq [run|once|briefing|export|test-alert] [--config config.json] [--out site]"""
import argparse

from . import app, briefing, store

p = argparse.ArgumentParser(prog="hq")
p.add_argument("command", choices=["run", "once", "briefing", "export", "test-alert"], nargs="?", default="run")
p.add_argument("--config", default=str(app.ROOT / "config.json"))
p.add_argument("--out", default=str(app.ROOT / "site"))
a = p.parse_args()
cfg, src = app.load(a.config)
if a.command == "briefing":
    db = store.connect(str(app.ROOT / cfg["db_path"]))
    print(briefing.build(db, app.source_index(src), tz=cfg["briefing"]["timezone"])[1])
elif a.command == "test-alert":
    from . import notify
    for channel, err in notify.send(cfg, "Global HQ test alert", "Alerts are working. You'll get a FLASH like this when a major event is confirmed."):
        print(channel, "OK" if err is None else err)
elif a.command == "export":
    app.export(store.connect(str(app.ROOT / cfg["db_path"])), cfg, src, a.out)
    print(f"static site written to {a.out}")
else:
    app.run(cfg, src, once=a.command == "once")
