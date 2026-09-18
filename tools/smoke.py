#!/usr/bin/env python3
"""Smoke test for ai_infra_monitoring against a live Splunk (management REST, .env credentials).

Checks: every dashboard dataSource query returns rows with no ERROR message; the 14 headline
KPI macros land within 5% of their targets; all 25 alerts have written an ai:alert event
(optionally force-dispatched at the last incident's 14:55 local, the four AI Security alerts
at the newest incident that holds the scripted security storyline); scoreboard values equal
the tile macros; the node timeline drilldown spans 3+ sourcetypes; the attention tables
lead with (ai_applications: list among their attention rows) the scripted incident rows.
Prints a fixed-width PASS/FAIL table and writes dist/smoke.txt (and --json).
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _splunkrest import APP, Mgmt, RestError  # noqa: E402

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

TZ = "America/Los_Angeles"

# label, macro call, earliest, latest, target, mode ("pct" = 5% relative, "abs" = +/-0.05 absolute)
KPIS = [
    ("GPUs Monitored", "| `ai_kpi_gpus_monitored(\"*\",\"*\")`", "-24h", "now", 512, "pct"),
    ("Avg GPU Utilization", "| `ai_kpi_gpu_util_avg(\"*\",\"*\")`", "-24h", "now", 61.8, "pct"),
    ("Idle GPU-Hours (7d)", "`ai_kpi_idle_gpu_hours_7d(\"*\")`", "-7d@d", "now", 17100, "pct"),
    ("Fabric Links Monitored", "`ai_kpi_fabric_links(\"*\")`", "-24h", "now", 1152, "pct"),
    ("Pod Restarts (24h)", "`ai_kpi_pod_restarts(\"*\",\"*\")`", "-24h", "now", 37, "pct"),
    ("Requests (24h)", "`ai_kpi_requests(\"*\",\"*\")`", "-24h", "now", 1280000, "pct"),
    ("Availability", "`ai_kpi_availability(\"*\",\"*\")`", "-24h", "now", 99.93, "abs"),
    ("p95 Time-to-First-Token", "`ai_kpi_p95_ttft(\"*\",\"*\")`", "-24h", "now", 820, "pct"),
    ("Safety Compliance", "`ai_kpi_safety_compliance(\"*\")`", "-24h", "now", 99.2, "abs"),
    ("Hallucination Rate", "`ai_kpi_hallucination_rate(\"*\")`", "-24h", "now", 1.8, "pct"),
    ("Agent Runs (24h)", "`ai_kpi_agent_runs(\"*\",\"*\")`", "-24h", "now", 48320, "pct"),
    ("GPU-Hours Allocated (7d)", "`ai_kpi_gpu_hours_allocated_7d(\"*\")`", "-7d@d", "now", 68900, "pct"),
    ("Open Findings", "`ai_kpi_open_findings(\"*\",\"*\")`", "-7d@d", "now", 22, "pct"),
    ("Prompt Injections Detected", "`ai_kpi_prompt_injections(\"*\")`", "-7d@d", "now", 214, "pct"),
]

# scoreboard (board, metric) -> (macro call, earliest) ; tile value must equal the rollup within 0.5%
SCOREBOARD = [
    ("reliability", "Availability", "`ai_kpi_availability(\"*\",\"*\")`", "-24h@m"),
    ("velocity", "Pilot to production", "| `ai_kpi_pilot_to_production`", "-30d@d"),
    ("efficiency", "GPU utilization", "| `ai_kpi_gpu_util_avg(\"*\",\"*\")`", "-24h@m"),
    ("trust", "Safety compliance", "`ai_kpi_safety_compliance(\"*\")`", "-24h@m"),
    ("security", "Open findings", "`ai_kpi_open_findings(\"*\",\"*\")`", "-7d@d"),
]

NODE_TIMELINE = ("(index=ai_infra OR index=ai_network OR index=ai_platform) host=ai-demo-generator \"dc1-ucs-gpu-07\" "
                 "| stats count BY sourcetype")
NODE_TIMELINE_EXPECT = {"ai:gpu:fault", "cisco:nexus:anomaly", "kube:events"}

# view -> (key fields, expected leading rows in spec order). The table dataSource is discovered
# from the view's splunk.table visualization, so ids do not need to be known here.
TABLE_EXPECT = {
    "ai_infrastructure_health": (("node", "fault"), [
        ("dc1-ucs-gpu-07", "ecc_dbe_volatile"), ("dc1-ucs-gpu-07", "xid_79_fallen_off_bus")]),
    "ai_network_fabric": (("device", "interface"), [
        ("dc1-leaf-112", "Eth1/14"), ("dc1-leaf-112", "Eth1/31"), ("dc1-spine-02", "Eth2/05")]),
    "ai_platform_workloads": (("workload", "reason"), [
        ("med-advisor-v41-7c9f4", "NodeNotReady"), ("med-advisor-v41-5b21d", "OOMKilled")]),
    "model_performance_quality": (("suite", "status"), [("reasoning", "regression")]),
    "ai_agents": (("trace_id", "outcome"), [("c41e77a09b3d", "loop_stopped")]),
    "ai_security_posture": (("user", "src"), [
        ("svc-mlops-ci", "10.42.17.88"), ("maya.okonkwo@buttercupgames.com", "198.51.100.20"),
        ("probe@example.com", "203.0.113.10"), ("svc-eval-runner", "10.42.30.14"),
        ("j.alvarez@buttercupgames.com", "10.18.4.201"), ("svc-mlops-ci", "10.42.17.88"),
        ("probe@example.com", "203.0.113.10")]),
}
# accept these key spellings in addition to the canonical ones (aliases the views may use)
FIELD_ALIASES = {"gen_ai.app": ("gen_ai.app", "app"), "trace_id": ("trace_id",), "user": ("user",)}
# view -> (key field, scripted rows). During the incident several applications write attention rows
# every minute, so which one is newest depends on indexing order. These tables are read over the
# 24 hours ending at the last incident's 15:00 and must list the scripted rows among their leading
# attention rows (guardrail other than pass, or retrieval timeout).
TABLE_CONTAINS = {
    "ai_applications": (("gen_ai.app", "trace_id"), [
        ("medadvice-chat", "7f3a9c1e04b2"), ("medadvice-chat", "2c6e0b77d1f5"), ("medadvice-chat", "9d02b6f1c47a")]),
}

# The generator writes the scripted security storyline (the seven findings with their raw events and
# the 59-attempt prompt-injection campaign) only on its latest day at backfill time; streaming never
# adds it. The AI Security alerts are dispatched at the newest incident whose day holds all four pieces
# they detect, within the security dashboard's 7-day window; the other alerts at the last incident.
STORYLINE_ALERT_PREFIX = "AI Security - "
STORYLINE_DAYS = 7
STORYLINE_SEARCH = (
    "(index=ai_security host=ai-demo-generator sourcetype IN (\"aws:cloudtrail:sim\",\"k8s:audit:sim\") "
    "((user=\"svc-mlops-ci\" first_seen=true object=\"weights/med-advisor-v41/\") "
    "OR (user=\"maya.okonkwo@buttercupgames.com\" action=\"kubectl exec\" off_hours=true) "
    "OR (user=\"svc-eval-runner\" asn_new=true bytes_out>10737418240))) "
    "OR (index=ai_application host=ai-demo-generator sourcetype=gen_ai:guardrail category=prompt_injection "
    "verdict=blocked src=\"203.0.113.10\") "
    "| eval day=strftime(_time,\"%Y-%m-%d\"), hour=tonumber(strftime(_time,\"%H\")), "
    "piece=case(sourcetype=\"gen_ai:guardrail\" AND hour>=13 AND hour<15,\"injection\", sourcetype=\"gen_ai:guardrail\",\"other\", "
    "sourcetype=\"k8s:audit:sim\",\"credential\", like(object,\"weights/%\"),\"weights\", true(),\"egress\") "
    "| chart count OVER day BY piece "
    "| where weights>0 AND credential>0 AND egress>0 AND injection>=20 | sort - day | head 1 | fields day")


# --------------------------------------------------------------------------- views
TOKEN_RE = re.compile(r"\$([A-Za-z0-9_.:|]+)\$")


def load_view(path):
    """Parse a Dashboard Studio XML view; return (view_id, definition dict)."""
    tree = ET.parse(path)
    root = tree.getroot()
    d = root.find("definition")
    if d is None or not (d.text or "").strip():
        raise ValueError("%s: no <definition>" % path)
    return os.path.splitext(os.path.basename(path))[0], json.loads(d.text)


def input_defaults(defn):
    """Map token name -> default value from the view's inputs (timerange gives time.earliest/latest)."""
    tokens = {}
    for _, inp in (defn.get("inputs") or {}).items():
        opts = inp.get("options") or {}
        tok = opts.get("token")
        if not tok:
            continue
        dv = opts.get("defaultValue", "*")
        if inp.get("type") == "input.timerange":
            if isinstance(dv, dict):
                tokens[tok + ".earliest"] = dv.get("earliest", "-24h")
                tokens[tok + ".latest"] = dv.get("latest", "now")
            else:
                parts = str(dv).split(",")
                tokens[tok + ".earliest"] = parts[0]
                tokens[tok + ".latest"] = parts[1] if len(parts) > 1 else "now"
        elif isinstance(dv, list):
            tokens[tok] = ",".join(str(x) for x in dv)
        else:
            tokens[tok] = str(dv)
    return tokens


def substitute(text, tokens):
    """Replace $tok$ with defaults; returns (text, unresolved list). Row/result tokens are left alone."""
    missing = []

    def rep(m):
        name = m.group(1)
        base = name.split("|")[0]
        if base.startswith(("row.", "result.", "click.", "name", "value")):
            return m.group(0)
        if base in tokens:
            return tokens[base]
        missing.append(base)
        return m.group(0)

    return TOKEN_RE.sub(rep, text), missing


def view_queries(defn):
    """Yield (ds_id, query, earliest, latest) for every ds.search dataSource, tokens substituted."""
    tokens = input_defaults(defn)
    dflt = ((defn.get("defaults") or {}).get("dataSources") or {}).get("ds.search") or {}
    dqp = (dflt.get("options") or {}).get("queryParameters") or {}
    for ds_id, ds in (defn.get("dataSources") or {}).items():
        if ds.get("type") != "ds.search":
            continue
        opts = ds.get("options") or {}
        q = opts.get("query")
        if not q:
            continue
        qp = opts.get("queryParameters") or dqp
        earliest = qp.get("earliest", "$time.earliest$")
        latest = qp.get("latest", "$time.latest$")
        q2, miss_q = substitute(q, tokens)
        e2, miss_e = substitute(str(earliest), tokens)
        l2, miss_l = substitute(str(latest), tokens)
        yield ds_id, q2, e2, l2, sorted(set(miss_q + miss_e + miss_l))


def table_datasource(defn):
    """Return the ds id feeding the first splunk.table visualization (None if absent)."""
    for _, viz in (defn.get("visualizations") or {}).items():
        if viz.get("type") == "splunk.table":
            return (viz.get("dataSources") or {}).get("primary")
    return None


# -------------------------------------------------------------------------- results
class Results:
    def __init__(self):
        self.rows = []

    def add(self, check, where, expected, actual, ok, note=""):
        self.rows.append({"status": "PASS" if ok else "FAIL", "check": check, "where": where,
                          "expected": str(expected), "actual": str(actual), "note": note})

    def table(self):
        cols = [("STATUS", 6), ("CHECK", 16), ("VIEW/DS", 44), ("EXPECTED", 14), ("ACTUAL", 14), ("NOTE", 40)]
        head = " | ".join(n.ljust(w) for n, w in cols)
        out = [head, "-" * len(head)]
        for r in self.rows:
            vals = [r["status"], r["check"], r["where"], r["expected"], r["actual"], r["note"]]
            out.append(" | ".join(str(v)[:w].ljust(w) for v, (_, w) in zip(vals, cols)))
        n_ok = sum(1 for r in self.rows if r["status"] == "PASS")
        out.append("-" * len(head))
        out.append("%s %d/%d" % ("PASS" if n_ok == len(self.rows) else "FAIL", n_ok, len(self.rows)))
        return "\n".join(out)

    def failed(self):
        return any(r["status"] == "FAIL" for r in self.rows)


def errors_in(messages):
    return [m.get("text", "") for m in messages if str(m.get("type", "")).upper() in ("ERROR", "FATAL")]


def pct_delta(actual, target):
    if target == 0:
        return abs(actual)
    return 100.0 * (actual - target) / target


# --------------------------------------------------------------------------- checks
def check_views(m, res, views_dir):
    files = sorted(f for f in os.listdir(views_dir) if f.endswith(".xml"))
    if not files:
        res.add("datasource", views_dir, ">0 views", "0 views", False, "no XML views found")
        return {}
    defs = {}
    for f in files:
        try:
            view_id, defn = load_view(os.path.join(views_dir, f))
        except (ET.ParseError, ValueError, json.JSONDecodeError) as e:
            res.add("datasource", f, "parses", "error", False, str(e)[:80])
            continue
        defs[view_id] = defn
        for ds_id, q, earliest, latest, missing in view_queries(defn):
            where = "%s/%s" % (view_id, ds_id)
            if missing:
                res.add("datasource", where, "tokens resolved", "unresolved", False, ",".join(missing))
                continue
            try:
                rows, msgs = m.search(q, earliest, latest)
            except RestError as e:
                res.add("datasource", where, "rows>0", "HTTP %s" % e.status, False, str(e)[:80])
                continue
            errs = errors_in(msgs)
            res.add("datasource", where, "rows>0, no ERROR", "%d rows" % len(rows),
                    len(rows) > 0 and not errs, (errs[0][:80] if errs else ""))
    return defs


def check_kpis(m, res):
    for label, macro, earliest, latest, target, mode in KPIS:
        try:
            v, msgs = m.search_value(macro, earliest, latest)
        except RestError as e:
            res.add("kpi", label, target, "HTTP %s" % e.status, False, str(e)[:80])
            continue
        errs = errors_in(msgs)
        if not isinstance(v, float):
            res.add("kpi", label, target, v, False, (errs[0][:80] if errs else "no numeric value"))
            continue
        if mode == "abs":
            ok = abs(v - target) <= 0.05 and not errs
            note = "abs tol 0.05 (delta %+.3f)" % (v - target)
        else:
            d = pct_delta(v, target)
            ok = abs(d) <= 5.0 and not errs
            note = "delta %+.1f%% (tol 5%%)" % d
        res.add("kpi", label, target, round(v, 3), ok, note)


def alert_names(savedsearches_path):
    names = []
    if not os.path.isfile(savedsearches_path):
        return names
    for line in open(savedsearches_path, encoding="utf-8"):
        mm = re.match(r"^\[(.+)\]\s*$", line.strip())
        if not mm:
            continue
        n = mm.group(1)
        if n.endswith(" - Rule") or n.startswith("AI Scoreboard") or n == "default":
            continue
        names.append(n)
    return names


def local_now(epoch=None):
    """Aware local datetime for `epoch`, or for the real clock when None."""
    tz = ZoneInfo(TZ) if ZoneInfo else None
    return dt.datetime.fromtimestamp(epoch, tz) if epoch is not None else dt.datetime.now(tz)


def incident_anchor(now=None):
    """Epoch of the most recent completed incident's 14:55 local (today if past 15:05, else yesterday)."""
    tz = ZoneInfo(TZ) if ZoneInfo else None
    now = now or dt.datetime.now(tz)
    day = now.date()
    if now.time() < dt.time(15, 5):
        day = day - dt.timedelta(days=1)
    anchor = dt.datetime.combine(day, dt.time(14, 55))
    if tz:
        anchor = anchor.replace(tzinfo=tz)
    return anchor


def storyline_anchor(m, now=None):
    """14:55 local on the newest day, up to the last incident and within the last STORYLINE_DAYS days,
    whose data holds the scripted security storyline (STORYLINE_SEARCH); None if there is none."""
    now = now or local_now()
    last = incident_anchor(now)
    start = dt.datetime.combine(now.date() - dt.timedelta(days=STORYLINE_DAYS), dt.time(0)).replace(tzinfo=last.tzinfo)
    end = last + dt.timedelta(minutes=5)
    rows, _ = m.search(STORYLINE_SEARCH, int(start.timestamp()), int(end.timestamp()))
    if not rows or not rows[0].get("day"):
        return None
    day = dt.date.fromisoformat(rows[0]["day"])
    return dt.datetime.combine(day, dt.time(14, 55)).replace(tzinfo=last.tzinfo)


def check_alerts(m, res, savedsearches_path, dispatch, saved=None, now=None):
    expected = alert_names(savedsearches_path)
    if len(expected) != 25:
        res.add("alerts", "savedsearches.conf", "25 alert stanzas", len(expected), False, "parsed from default/")
    if dispatch:
        anchor = incident_anchor(now)
        story, story_note = None, "no day in the last %d days holds the scripted security storyline" % STORYLINE_DAYS
        if any(n.startswith(STORYLINE_ALERT_PREFIX) for n in expected):
            try:
                story = storyline_anchor(m, now)
            except RestError as e:
                story_note = "storyline search failed: HTTP %s" % e.status
        saved = saved or {}
        try:
            saved = m.saved_searches()
        except RestError as e:
            res.add("alerts", "dispatch", "saved searches listed", "HTTP %s" % e.status, False, str(e)[:80])
        for name in expected:
            at = story if name.startswith(STORYLINE_ALERT_PREFIX) else anchor
            if at is None:
                res.add("dispatch", name, "results>0 @storyline", "no anchor", False, story_note)
                continue
            content = saved.get(name, {})
            earliest = content.get("dispatch.earliest_time", "-15m@m")
            try:
                sid = m.dispatch_saved_search(name, **{"trigger_actions": 1, "dispatch.now": int(at.timestamp()),
                                                       "dispatch.earliest_time": earliest, "dispatch.latest_time": "now"})
                job = m.wait_job(sid)
                n = int(job.get("resultCount", 0))
                res.add("dispatch", name, "results>0 @%s" % at.strftime("%m-%d %H:%M"), n, n > 0,
                        "newest incident with the security storyline" if at is story and at != anchor else "")
            except RestError as e:
                res.add("dispatch", name, "dispatched", "HTTP %s" % e.status, False, str(e)[:80])
        time.sleep(30)
    try:
        rows, msgs = m.search("index=ai_summary sourcetype=ai:alert | stats count BY search_name", "-30d", "now")
    except RestError as e:
        res.add("alerts", "ai:alert", "25 names", "HTTP %s" % e.status, False, str(e)[:80])
        return
    seen = {r.get("search_name") for r in rows}
    missing = [n for n in expected if n not in seen]
    res.add("alerts", "ai:alert search_name", "25 names", len(seen & set(expected)), not missing,
            ("missing: " + "; ".join(missing))[:200] if missing else "")


def check_scoreboard(m, res):
    for board, metric, macro, earliest in SCOREBOARD:
        q = "index=ai_summary sourcetype=ai:scoreboard scoreboard=%s metric=\"%s\" | stats latest(value) AS value" % (board, metric)
        try:
            sb, _ = m.search_value(q, "-30d", "now")
            tile, _ = m.search_value(macro, earliest, "now")
        except RestError as e:
            res.add("scoreboard", "%s/%s" % (board, metric), "equal", "HTTP %s" % e.status, False, str(e)[:80])
            continue
        if not isinstance(sb, float) or not isinstance(tile, float):
            res.add("scoreboard", "%s/%s" % (board, metric), tile, sb, False, "missing rollup or tile value")
            continue
        d = pct_delta(sb, tile)
        res.add("scoreboard", "%s/%s" % (board, metric), round(tile, 3), round(sb, 3), abs(d) <= 0.5, "delta %+.2f%%" % d)


def check_node_timeline(m, res):
    try:
        rows, msgs = m.search(NODE_TIMELINE, "-24h", "now")
    except RestError as e:
        res.add("node_timeline", "dc1-ucs-gpu-07", ">=3 sourcetypes", "HTTP %s" % e.status, False, str(e)[:80])
        return
    st = {r.get("sourcetype") for r in rows}
    missing = sorted(NODE_TIMELINE_EXPECT - st)
    res.add("node_timeline", "dc1-ucs-gpu-07", ">=3 sourcetypes incl. fault/anomaly/kube", len(st),
            len(st) >= 3 and not missing, ("missing " + ",".join(missing)) if missing else ",".join(sorted(st)))


def row_key(row, fields):
    out = []
    for f in fields:
        v = None
        for alt in FIELD_ALIASES.get(f, (f,)):
            if alt in row:
                v = row[alt]
                break
        out.append(str(v) if v is not None else "")
    return tuple(out)


def table_query(defn):
    """(ds id, (query, earliest, latest)) of the view's first table; the query is None if unresolvable."""
    ds_id = table_datasource(defn)
    query = None
    for d, q, e, l, missing in view_queries(defn):
        if d == ds_id and not missing:
            query = (q, e, l)
    return ds_id, query


def is_attention(row):
    """True for a request row the table ranks as needing attention (guardrail hit or retrieval timeout)."""
    return row.get("guardrail", "pass") not in ("pass", "") or row.get("retrieval_ms") == "timeout"


def check_table_contains(m, res, defs, now=None):
    end = incident_anchor(now) + dt.timedelta(minutes=5)
    for view_id, (fields, scripted) in TABLE_CONTAINS.items():
        defn = defs.get(view_id)
        if not defn:
            res.add("table_order", view_id, "view present", "absent", False, "view not loaded")
            continue
        ds_id, query = table_query(defn)
        if not query:
            res.add("table_order", view_id, "table dataSource", ds_id, False, "no resolvable table query")
            continue
        where = "%s/%s" % (view_id, ds_id)
        try:
            rows, _ = m.search(query[0], int(end.timestamp()) - 86400, int(end.timestamp()))
        except RestError as e:
            res.add("table_order", where, "%d scripted rows" % len(scripted), "HTTP %s" % e.status, False, str(e)[:80])
            continue
        # the query sorts attention rows first, so a scripted attention row in the table sits in that block
        pos = {row_key(r, fields): n for n, r in reversed(list(enumerate(rows, 1))) if is_attention(r)}
        found = [pos.get(k) for k in scripted]
        missing = ["/".join(k) for k, p in zip(scripted, found) if p is None]
        res.add("table_order", where, "%d scripted rows" % len(scripted), "%d of %d" % (len(scripted) - len(missing), len(rows)),
                not missing, ("24h to %s: attention rows %s" % (end.strftime("%m-%d %H:%M"), ",".join(str(p) for p in found)))
                if not missing else ("missing " + ", ".join(missing))[:200])


def check_table_order(m, res, defs, now=None):
    check_table_contains(m, res, defs, now)
    for view_id, (fields, expected) in TABLE_EXPECT.items():
        defn = defs.get(view_id)
        if not defn:
            res.add("table_order", view_id, "view present", "absent", False, "view not loaded")
            continue
        ds_id, query = table_query(defn)
        if not query:
            res.add("table_order", view_id, "table dataSource", ds_id, False, "no resolvable table query")
            continue
        earliest = query[1]  # the dashboard's own default window (attention-first ordering keeps incident rows on top)
        try:
            rows, _ = m.search(query[0], earliest, query[2])
        except RestError as e:
            res.add("table_order", view_id, expected[0], "HTTP %s" % e.status, False, str(e)[:80])
            continue
        got = [row_key(r, fields) for r in rows[:len(expected)]]
        ok = got == expected
        res.add("table_order", "%s/%s" % (view_id, ds_id), " > ".join("/".join(x) for x in expected)[:14],
                " > ".join("/".join(x) for x in got)[:14], ok, "" if ok else ("got " + " > ".join("/".join(x) for x in got))[:40])


# ------------------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description="ai_infra_monitoring smoke test (REST, .env credentials)")
    ap.add_argument("--views", default="default/data/ui/views")
    ap.add_argument("--macros", default="default/macros.conf", help="kept for the Makefile; macros run server-side")
    ap.add_argument("--savedsearches", default="default/savedsearches.conf")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--out", default="dist/smoke.txt")
    ap.add_argument("--json", dest="json_out", help="also write results as JSON")
    ap.add_argument("--dispatch-alerts", action="store_true",
                    help="force-dispatch all 25 alerts at the last incident's 14:55 local (AI Security: the newest incident with the storyline)")
    ap.add_argument("--now", type=int, help="epoch that decides which incident is the last one (default: the real clock)")
    ap.add_argument("--only", help="comma-separated subset: views,kpis,alerts,scoreboard,timeline,tables")
    ap.add_argument("--run", help="run one SPL (used by make clean) and print the row count")
    ap.add_argument("--confirm", action="store_true", help="required with --run when the SPL contains | delete")
    ap.add_argument("--earliest", default="-24h")
    ap.add_argument("--latest", default="now")
    a = ap.parse_args(argv)

    m = Mgmt(env_file=a.env_file)
    if not m.has_creds():
        print("ERROR: no credentials in %s (SPLUNK_TOKEN or SPLUNK_USERNAME/SPLUNK_PASSWORD)" % a.env_file)
        return 2

    if a.run:
        if "| delete" in a.run and not a.confirm:
            print("refusing to run a delete without --confirm")
            return 2
        rows, msgs = m.search(a.run, a.earliest, a.latest)
        errs = errors_in(msgs)
        print("%d rows%s" % (len(rows), ("; ERROR: " + errs[0]) if errs else ""))
        if rows:
            print(json.dumps(rows[:20], indent=1))
        return 1 if errs else 0

    only = set(a.only.split(",")) if a.only else {"views", "kpis", "alerts", "scoreboard", "timeline", "tables"}
    now = local_now(a.now) if a.now is not None else None
    res = Results()
    defs = {}
    if "views" in only or "tables" in only:
        defs = check_views(m, res, a.views) if "views" in only else {
            v: d for v, d in (load_view(os.path.join(a.views, f)) for f in sorted(os.listdir(a.views)) if f.endswith(".xml"))}
    if "kpis" in only:
        check_kpis(m, res)
    if "alerts" in only:
        check_alerts(m, res, a.savedsearches, a.dispatch_alerts, now=now)
    if "scoreboard" in only:
        check_scoreboard(m, res)
    if "timeline" in only:
        check_node_timeline(m, res)
    if "tables" in only:
        check_table_order(m, res, defs, now=now)

    text = res.table()
    print(text)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as fh:
            json.dump(res.rows, fh, indent=1)
    return 1 if res.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
