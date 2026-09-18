#!/usr/bin/env python3
"""Run tools/smoke.py unchanged, with every search job's clock pinned to one epoch (read-only).

The search/jobs `now` parameter fixes both the job's relative time range and SPL's now(), so the
dashboard, KPI, scoreboard, timeline and table checks see exactly the data window they saw at that
moment. Use it to compare a new Splunk version with a baseline run over the same data: pin to the
last minute that was fully indexed when the baseline ran. Refuses --dispatch-alerts and --confirm;
writes dist/smoke_pinned.txt unless --out is given.

  $SPLUNK_HOME/bin/splunk cmd python3 tools/smoke_pinned.py 1789764360 --json dist/smoke_pinned.json
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _splunkrest  # noqa: E402
import smoke  # noqa: E402


def main(argv):
    if not argv or not argv[0].isdigit() or "--dispatch-alerts" in argv or "--confirm" in argv:
        print("usage: smoke_pinned.py <epoch> [smoke.py options except --dispatch-alerts/--confirm]")
        return 2
    pin, args = int(argv[0]), argv[1:]
    if "--out" not in args:
        args += ["--out", "dist/smoke_pinned.txt"]
    post = _splunkrest.Mgmt.post

    def pinned_post(self, path, data=None, params=None, **kw):
        if path.endswith("/search/jobs") and data and "search" in data:
            data = dict(data, now=pin)
        return post(self, path, data, params, **kw)

    _splunkrest.Mgmt.post = pinned_post
    print("smoke.py with every search job pinned to epoch %d" % pin)
    return smoke.main(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
