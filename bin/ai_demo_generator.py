#!/usr/bin/env python3
"""ai_demo_generator.py - deterministic data generator for the AI Infrastructure Monitoring demo app.

Modes
  --backfill 30d              write history (tiered cadence) to HEC (--hec/--token), files (--out) or stdout
  --stream --sourcetype ST    scripted-input mode: emit the previous full minute for one sourcetype to stdout
  --fire-incident [--instant] replay the 12:45-15:00 incident compressed into 20 minutes starting now
  --self-check                recompute every dashboard KPI offline and compare with the targets

Every event carries host=ai-demo-generator (HEC) / relies on inputs.conf host= for --stream, a `timestamp`
in ISO-8601 with milliseconds and offset, and is reproducible for a given --seed and minute.
Standard library only; runs under Python 3.9 and 3.13.
"""
import argparse
import os
import sys
import time
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_demo_lib import calib as C                      # noqa: E402
from ai_demo_lib import feeds as F                      # noqa: E402
from ai_demo_lib import history as H                    # noqa: E402
from ai_demo_lib import selfcheck as SC                 # noqa: E402
from ai_demo_lib.catalog import SOURCETYPE_INDEX, ALL_SOURCETYPES, tier_for, TIER_CADENCE   # noqa: E402
from ai_demo_lib.schedule import Ctx, DaySchedule       # noqa: E402
from ai_demo_lib.timeutil import (get_tz, parse_now, parse_duration_days, local_day, wall_epoch,   # noqa: E402
                                  local_dt, DEFAULT_TZ)
from ai_demo_lib.transport import Counter, FileSink, StdoutSink, HecSink   # noqa: E402

DEFAULT_SEED = 20260916


def log(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--backfill", metavar="30d", help="generate N days of history ending now")
    mode.add_argument("--stream", action="store_true", help="emit the previous minute for --sourcetype to stdout")
    mode.add_argument("--fire-incident", action="store_true", help="replay the incident compressed into 20 minutes")
    p.add_argument("--self-check", action="store_true", help="recompute the KPIs offline (can be combined with a mode)")
    p.add_argument("--sourcetype", help="sourcetype for --stream (or a comma list to restrict --backfill)")
    p.add_argument("--hec", metavar="URL", help="HEC base URL, e.g. https://localhost:8088")
    p.add_argument("--token", metavar="T", help="HEC token")
    p.add_argument("--out", metavar="DIR", help="write <index>__<sourcetype>.ndjson files instead of HEC/stdout")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--tz", default=DEFAULT_TZ)
    p.add_argument("--now", help="freeze the clock (ISO-8601, local unless an offset is given)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--batch-bytes", type=int, default=3000000)
    p.add_argument("--instant", action="store_true", help="with --fire-incident: do not sleep between steps")
    p.add_argument("--force", action="store_true", help="backfill even if the target already holds demo data")
    p.add_argument("--resume", action="store_true",
                   help="backfill only what is missing: skip every minute already indexed per sourcetype (needs REST creds in the environment)")
    p.add_argument("--insecure", dest="insecure", action="store_true", default=None, help="skip TLS verification (default for localhost)")
    p.add_argument("--verify-tls", dest="insecure", action="store_false")
    p.add_argument("--no-tune", action="store_true", help="self-check: verify only, do not re-solve tuned parameters")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args(argv)


def latest_day_for(tz, now):
    """Day whose scripted rows carry the deck literal ids: today if the incident has finished, else yesterday."""
    d = local_day(tz, now)
    if now < wall_epoch(tz, d, 15):
        d = d - timedelta(days=1)
    return d


def make_ctx(args, now):
    tz = get_tz(args.tz)
    return Ctx(args.seed, tz, now, latest_day_for(tz, now))


def open_sink(args, ctx, counter, extra_fields=None):
    if args.out:
        return FileSink(ctx.tz, args.out, counter, extra_fields)
    if args.hec:
        if not args.token:
            raise SystemExit("--hec requires --token")
        insecure = args.insecure
        if insecure is None:
            insecure = ("localhost" in args.hec) or ("127.0.0.1" in args.hec)
        sink = HecSink(ctx.tz, args.hec, args.token, counter, args.workers, args.batch_bytes, insecure, extra_fields, log)
        sink.probe()
        return sink
    return StdoutSink(ctx.tz, counter, extra_fields)



# ---- resume support: which 5-minute buckets are already indexed per sourcetype ----------
RESUME_BUCKET = 300


def existing_buckets(log, days):
    """Return {sourcetype: set(5-minute bucket epochs)} for demo data already in Splunk, via the
    management port. Uses SPLUNK_MGMT_URL and SPLUNK_TOKEN or SPLUNK_USERNAME/SPLUNK_PASSWORD from the
    environment (backfill.sh sources .env). Returns None when no credentials are available."""
    import base64, json, ssl, urllib.parse, urllib.request
    base = (os.environ.get("SPLUNK_MGMT_URL") or "https://127.0.0.1:8090").rstrip("/")
    tok, user, pw = os.environ.get("SPLUNK_TOKEN"), os.environ.get("SPLUNK_USERNAME"), os.environ.get("SPLUNK_PASSWORD")
    if tok:
        auth = "Bearer " + tok
    elif user and pw:
        auth = "Basic " + base64.b64encode(("%s:%s" % (user, pw)).encode()).decode()
    else:
        return None
    ctx = ssl._create_unverified_context()

    def search(spl):
        body = urllib.parse.urlencode({"search": spl, "exec_mode": "blocking", "earliest_time": "-%dd@d" % (days + 1),
                                       "latest_time": "+2d", "output_mode": "json", "count": 0}).encode()
        req = urllib.request.Request(base + "/services/search/jobs", data=body, headers={"Authorization": auth})
        sid = json.loads(urllib.request.urlopen(req, timeout=600, context=ctx).read())["sid"]
        req = urllib.request.Request(base + "/services/search/jobs/%s/results?output_mode=json&count=0" % sid, headers={"Authorization": auth})
        return json.loads(urllib.request.urlopen(req, timeout=600, context=ctx).read()).get("results", [])

    out = {}
    for r in search("| tstats count where index=* host=ai-demo-generator by sourcetype _time span=%ds | eval b=_time | fields sourcetype b" % RESUME_BUCKET):
        out.setdefault(r["sourcetype"], set()).add(int(float(r["b"])))
    for r in search("| mstats count(DCGM_FI_DEV_GPU_UTIL) AS c WHERE index=ai_infra_metrics host=ai-demo-generator span=%ds | eval b=_time | fields b" % RESUME_BUCKET):
        out.setdefault("ai:gpu:metrics", set()).add(int(float(r["b"])))
    log("resume: %d sourcetypes already indexed (%d five-minute buckets); only missing buckets are generated" % (len(out), sum(len(v) for v in out.values())))
    return out


def _present(last, st, ts):
    b = last.get(st)
    return bool(b) and (int(ts) // RESUME_BUCKET * RESUME_BUCKET) in b


# ---- backfill -------------------------------------------------------------------------
def do_backfill(args, ctx):
    days = parse_duration_days(args.backfill)
    wanted = set(args.sourcetype.split(",")) if args.sourcetype else None
    counter = Counter()
    last = {}
    if args.resume:
        last = existing_buckets(log, days)
        if last is None:
            log("resume: no SPLUNK_TOKEN or SPLUNK_USERNAME/SPLUNK_PASSWORD in the environment; doing a full backfill")
            last = {}
    sink = open_sink(args, ctx, counter)
    cache = F.DayCache(ctx)
    end_minute = (int(ctx.now) // 60 - 1) * 60          # backfill stops at floor(now/60)-1; --stream continues from there
    first_day = local_day(ctx.tz, ctx.now) - timedelta(days=days - 1)
    start = wall_epoch(ctx.tz, first_day, 0)
    t0 = time.time()
    n = 0
    # seeded-once history (scoreboard, incidents, eval history) - never in the future
    for ts, st, ev in H.history_rows(ctx):
        if ts <= ctx.now and (wanted is None or st in wanted) and not _present(last, st, ts):
            sink.write(ts, st, ev)
            n += 1
    m = start
    last_day = None
    while m <= end_minute:
        tier = tier_for(m, ctx.now)
        day = local_day(ctx.tz, m)
        if day != last_day:
            if not args.quiet:
                log("backfill %s tier %d  (%d events so far, %.0fs)" % (day.isoformat(), tier, n, time.time() - t0))
            last_day = day
        for ts, st, ev in F.minute_events(ctx, cache, m, tier, wanted):
            if ts > ctx.now or _present(last, st, ts):
                continue
            sink.write(ts, st, ev)
            n += 1
        m += 60
    sink.close()
    log("backfill done: %d events in %.0fs" % (n, time.time() - t0))
    print_counts(counter)
    if getattr(sink, "errors", None):
        for e in sink.errors[:10]:
            log("ERROR " + e)
        return 1
    return 0


def print_counts(counter):
    log("%-26s %-18s %12s" % ("sourcetype", "index", "events"))
    for st in ALL_SOURCETYPES:
        if st in counter.counts:
            log("%-26s %-18s %12s" % (st, SOURCETYPE_INDEX[st], "{:,}".format(counter.counts[st])))
    if counter.posts:
        log("HEC posts %d, %.1f MB, failed events %d" % (counter.posts, counter.bytes / 1e6, counter.failed))


def expected_table(days):
    """Expected events per sourcetype for an N-day backfill (tier mix), for backfill.sh."""
    rows = {}
    for st in ALL_SOURCETYPES:
        rows[st] = 0
    for back in range(days):
        tier = 1 if back == 0 else (2 if back <= 6 else 3)
        for st, n in F.expected_counts(tier).items():
            rows[st] += n
    rows["ai:scoreboard"] = 60 * len(H.SCOREBOARD_METRICS) + 7
    rows["ai:incident"] = 8 * 5
    rows["ai:eval:run"] += 12
    rows["ai:security:finding"] = 7 + sum(v for o, v in {1: 15, 2: 7, 3: 5, 4: 5, 5: 4, 6: 5}.items() if o < days)
    return rows


# ---- stream (scripted input) ----------------------------------------------------------------
def do_stream(args, ctx):
    if not args.sourcetype:
        raise SystemExit("--stream requires --sourcetype")
    st = args.sourcetype
    if st not in SOURCETYPE_INDEX:
        raise SystemExit("unknown sourcetype %s" % st)
    minute = (int(ctx.now) // 60 - 1) * 60
    counter = Counter()
    sink = StdoutSink(ctx.tz, counter)
    if st in ("ai:scoreboard", "ai:incident"):
        # daily seeds: emit at local midnight minute only (the full history the first time)
        if local_dt(ctx.tz, minute).hour == 0 and local_dt(ctx.tz, minute).minute == 0:
            for ts, s2, ev in H.history_rows(ctx):
                if s2 == st and ts <= ctx.now:
                    sink.write(ts, s2, ev)
        sink.close()
        return 0
    cache = F.DayCache(ctx)
    for ts, s2, ev in F.minute_events(ctx, cache, minute, 1, {st}):
        if s2 == st:
            sink.write(ts, s2, ev)
    sink.close()
    return 0


# ---- fire-incident ----------------------------------------------------------------------------
FIRE_SCALE = 20.0 / 135.0          # 135 incident minutes -> 20 wall-clock minutes
HOT_LINKS = {("dc1-spine-02", "Eth2/05"), ("dc1-leaf-112", "Eth1/31"), ("dc1-leaf-112", "Eth1/14")}
HOT_NODES = {"dc1-ucs-gpu-07", "dc2-ucs-gpu-19"}
ALERTS_EXPECTED = 25


def do_fire(args, ctx):
    t_fire = (int(ctx.now) // 60) * 60
    tag = "fire-%d" % t_fire
    fire_seed = ctx.seed * 1000003 + t_fire
    fctx = Ctx(fire_seed, ctx.tz, ctx.now + 7200, ctx.latest_day, fire_tag=tag)   # hashed (non-literal) ids in the fired copy
    day = ctx.latest_day
    counter = Counter()
    sink = open_sink(args, ctx, counter, extra_fields={"incident_run": tag})
    sched = DaySchedule(fctx, day)
    w0, w1 = wall_epoch(ctx.tz, day, 12, 45), wall_epoch(ctx.tz, day, 15, 0)
    scripted = []
    for st, rows in sched.events.items():
        if st in ("ai:cost:daily", "ai:cost:tokens", "cisco:ucs:inventory"):
            continue
        for ts, ev in rows:
            if w0 <= ts < w1:
                scripted.append((t_fire + (ts - w0) * FIRE_SCALE, st, ev))
    scripted.sort(key=lambda r: r[0])
    log("fire-incident %s: %d scripted rows over 20 minutes (%s)" % (tag, len(scripted), "instant" if args.instant else "real time"))
    si = 0
    n = 0
    for k in range(121):
        t_step = t_fire + 10 * k
        v = w0 + (t_step - t_fire) / FIRE_SCALE          # virtual incident time
        h = 12.75 + (t_step - t_fire) / FIRE_SCALE / 3600.0
        rng = fctx.rng(int(t_step), "fire")
        rows = []
        for ts, st, ev in F.gpu_metrics(fctx, t_step, h, rng, C.TUNED):
            if ev["node"] in HOT_NODES:
                rows.append((ts, st, ev))
        for ts, st, ev in F.nexus_interface(fctx, t_step, h, rng, 1, 1):
            if (ev["device"], ev["interface"]) in HOT_LINKS:
                ev["pfc_pause_rx"] = int(ev["pfc_pause_rx"] / 6.0)     # 10-s rows: keep the 20-minute sum close to the daily one
                ev["pfc_pause_tx"] = int(ev["pfc_pause_tx"] / 6.0)
                ev["ecn_marked_packets"] = int(ev["ecn_marked_packets"] / 6.0)
                rows.append((ts, st, ev))
        rows.extend(F.inference_servers(fctx, t_step, h, rng, C.TUNED))
        from ai_demo_lib.schedule import request_event
        from ai_demo_lib.timeutil import ramp, hex_id
        r = ramp(h)
        for app, model, system, nstreams, wl in F.T.STREAMS[:4]:
            ev = request_event(rng, t_step + rng.uniform(0, 9), app, model, system, wl, hex_id(rng, 12), r, request_count=max(1, int(48 * nstreams / 6.0)), row_kind="minute")
            rows.append((t_step + 1, "gen_ai:request", ev))
        while si < len(scripted) and scripted[si][0] < t_step + 10:
            rows.append(scripted[si])
            si += 1
        for ts, st, ev in rows:
            sink.write(ts, st, ev)
            n += 1
        if k % 6 == 0 and not args.quiet:
            log("  +%02d:%02d  virtual %s  events %d" % (k * 10 // 60, k * 10 % 60, local_dt(ctx.tz, v).strftime("%H:%M"), n))
        if not args.instant and k < 120:
            wait = t_step + 10 - time.time()
            if wait > 0:
                time.sleep(wait)
    sink.close()
    log("fire-incident done: %d events; incident_run=%s; alerts expected to fire: %d" % (n, tag, ALERTS_EXPECTED))
    print_counts(counter)
    return 0


# ---- self-check ------------------------------------------------------------------------------
def do_self_check(args, ctx):
    tuned = dict(C.TUNED)
    log("self-check: seed %d, tz %s, latest day %s" % (ctx.seed, args.tz, ctx.latest_day.isoformat()))
    if not args.no_tune:
        tuned = SC.tune(ctx, tuned, log)
        drift = [k for k in tuned if abs(tuned[k] - C.TUNED[k]) > 0.02 * abs(C.TUNED[k])]
        if drift:
            log("  NOTE: re-solved parameters differ from ai_demo_lib/calib.py TUNED: %s" % ", ".join("%s=%.4g" % (k, tuned[k]) for k in drift))
    k = SC.compute_kpis(ctx, tuned, log)
    fails = 0
    log("%-40s %14s %14s %8s  %s" % ("KPI", "target", "computed", "delta", "status"))
    for name, (target, tol, headline) in SC.TARGETS.items():
        v = k.get(name)
        if v is None:
            status, fails = "MISSING", fails + 1
            delta = float("nan")
        else:
            delta = (v - target) / abs(target) if target else v - target
            ok = abs(delta) <= max(tol, 0.03 if tol else 0.0) + 1e-9 if tol else abs(v - target) < 1e-9
            status = "pass" if ok else "FAIL"
            if not ok:
                fails += 1
        log("%-40s %14s %14s %7.2f%%  %s%s" % (name, target, ("%.4g" % v) if isinstance(v, float) else v, delta * 100, status, " *" if headline else ""))
    log("self-check: %d KPIs, %d failures (* = headline)" % (len(SC.TARGETS), fails))
    return 1 if fails else 0


def main(argv=None):
    args = parse_args(argv)
    tz = get_tz(args.tz)
    now = parse_now(args.now, tz)
    ctx = make_ctx(args, now)
    rc = 0
    if args.self_check:
        rc = do_self_check(args, ctx)
        if rc and (args.backfill or args.fire_incident):
            log("self-check failed; aborting")
            return rc
    if args.backfill:
        rc = do_backfill(args, ctx) or rc
    elif args.stream:
        rc = do_stream(args, ctx) or rc
    elif args.fire_incident:
        rc = do_fire(args, ctx) or rc
    elif not args.self_check:
        parse_args(["--help"])
    return rc


if __name__ == "__main__":
    sys.exit(main())
