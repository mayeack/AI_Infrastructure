#!/usr/bin/env python3
"""Read a splunk-appinspect JSON report, print failures/errors/warnings, exit 1 on any error or failure."""
import json
import sys


def main(path):
    r = json.load(open(path))
    s = r.get("summary", {})
    print("appinspect summary:", {k: s.get(k, 0) for k in ("error", "failure", "warning", "manual_check", "success", "not_applicable", "skipped")})
    for rep in r.get("reports", []):
        for g in rep.get("groups", []):
            for c in g.get("checks", []):
                if c.get("result") in ("failure", "error", "warning"):
                    msgs = [m.get("message", "") for m in c.get("messages", [])]
                    print("  %-8s %s: %s" % (c["result"], c["name"], (msgs[0] if msgs else "").replace("\n", " ")[:220]))
    return 1 if (s.get("error", 0) or s.get("failure", 0)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "dist/appinspect.json"))
