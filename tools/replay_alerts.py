#!/usr/bin/env python3
"""Replay the 25 alert searches at chosen anchors without side effects.

Each alert's saved SPL runs as an ad-hoc job with every `| collect` stage removed and no alert
actions, over its saved dispatch.earliest_time/latest_time with the job clock set to the anchor.
Prints the result count per alert and anchor; exits 1 if any alert returns nothing at any anchor.
Anchors are epochs or local ISO times (America/Los_Angeles, as in smoke.py).

  $SPLUNK_HOME/bin/splunk cmd python3 tools/replay_alerts.py 2026-09-17T14:55 2026-09-18T14:55
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _splunkrest import APP, Mgmt, RestError  # noqa: E402
import smoke  # noqa: E402

WRITES = re.compile(r"\|\s*(collect|delete|outputlookup|outputcsv|sendalert|sendemail|tscollect|mcollect)\b")


def to_epoch(s):
    if s.isdigit():
        return int(s)
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None and smoke.ZoneInfo:
        t = t.replace(tzinfo=smoke.ZoneInfo(smoke.TZ))
    return int(t.timestamp())


def main(argv=None):
    ap = argparse.ArgumentParser(description="Replay the alert searches at fixed anchors (read-only)")
    ap.add_argument("anchors", nargs="+", help="epoch or local ISO time, e.g. 2026-09-17T14:55")
    ap.add_argument("--savedsearches", default="default/savedsearches.conf")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--json", dest="json_out", help="also write {anchor: {alert: result count}}")
    a = ap.parse_args(argv)

    m = Mgmt(env_file=a.env_file)
    names = smoke.alert_names(a.savedsearches)
    saved = m.saved_searches()
    out, misses = {}, 0
    for anchor in a.anchors:
        epoch = to_epoch(anchor)
        out[anchor] = {}
        for name in names:
            c = saved.get(name, {})
            q = re.sub(r"\|\s*collect\b[^|]*", "", c.get("search", "")).strip()
            if not q or WRITES.search(q):
                n = "skipped (missing or writes)"
            else:
                data = {"search": q if q.startswith("|") else "search " + q, "exec_mode": "blocking",
                        "earliest_time": c.get("dispatch.earliest_time", "-15m@m"),
                        "latest_time": c.get("dispatch.latest_time", "now"), "now": epoch, "timeout": 300}
                try:
                    sid = m.post("/servicesNS/nobody/%s/search/jobs" % APP, data, timeout=330)["sid"]
                    job = m.get("/servicesNS/nobody/%s/search/jobs/%s" % (APP, sid))["entry"][0]["content"]
                    n = int(job.get("resultCount", 0))
                except RestError as e:
                    n = "HTTP %s" % e.status
            out[anchor][name] = n
            misses += 0 if isinstance(n, int) and n > 0 else 1
            print("%-17s %-62s %s" % (anchor, name, n), flush=True)
    for anchor in a.anchors:
        hits = sum(1 for v in out[anchor].values() if isinstance(v, int) and v > 0)
        print("%s: %d/%d alerts return results" % (anchor, hits, len(names)))
    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump(out, f, indent=1)
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
