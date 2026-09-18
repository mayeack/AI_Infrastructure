"""Seeded-once history: ai:scoreboard (60 daily rows per metric), ai:incident (8 weeks),
ai:eval:run history for v37-v41."""
from datetime import timedelta

from . import topology as T
from .timeutil import wall_epoch, rng_for

# (scoreboard, metric, unit, window, latest value, value 30 days ago)
SCOREBOARD_METRICS = [
    ("reliability", "Availability", "pct", "24h", 99.93, 99.72),
    ("reliability", "p95 time-to-first-token", "ms", "24h", 820.0, 610.0),
    ("reliability", "Degraded nodes", "count", "24h", 3.0, 1.0),
    ("reliability", "Congested links", "count", "24h", 14.0, 6.0),
    ("velocity", "Pilot to production", "days", "30d", 38.0, 50.0),
    ("velocity", "Evaluation cycle time", "h", "7d", 4.2, 5.1),
    ("velocity", "Evaluation pass rate", "pct", "7d", 94.6, 92.8),
    ("efficiency", "GPU utilization", "pct", "24h", 61.8, 54.1),
    ("efficiency", "Idle GPU-hours", "gpu_hours", "7d", 17136.0, 21400.0),
    ("efficiency", "Token spend", "usd", "24h", 30300.0, 27100.0),
    ("trust", "Safety compliance", "pct", "24h", 99.2, 99.1),
    ("trust", "Hallucination rate", "pct", "24h", 1.8, 1.6),
    ("trust", "Guardrails triggered", "count", "24h", 1906.0, 1650.0),
    ("security", "Open findings", "count", "7d", 22.0, 26.0),
    ("security", "Model asset access anomalies", "count", "7d", 7.0, 4.0),
    ("security", "Prompt injections detected", "count", "7d", 214.0, 160.0),
]
WEEKLY_GPU_UTIL = [54.1, 55.6, 57.3, 58.7, 60.0, 61.1, 61.8]
WEEKLY_INCIDENTS = [31, 29, 27, 24, 22, 20, 18]
INCIDENT_LAYER_SHARE = {"compute": 0.30, "network": 0.20, "platform": 0.22, "application": 0.16, "model": 0.12}
EVAL_HISTORY = {  # suite -> pass rates v37..v41
    "safety": [98.1, 98.6, 99.0, 99.3, 99.2],
    "reasoning": [88.2, 90.1, 92.4, 94.0, 91.9],
    "coding": [84.5, 86.0, 89.3, 91.2, 92.6],
}


def scoreboard_rows(ctx, days=60):
    """Daily ai:scoreboard rows stamped 23:45 local for the last `days` days (never in the future)."""
    rng = rng_for(ctx.seed, "scoreboard")
    out = []
    for back in range(days, 0, -1):
        day = ctx.latest_day - timedelta(days=back)
        ts = wall_epoch(ctx.tz, day, 23, 45)
        if ts > ctx.now:
            continue
        frac = 1.0 - (back - 1) / float(days - 1)
        for board, metric, unit, window, latest, old in SCOREBOARD_METRICS:
            if metric == "GPU utilization":
                wk = min(6, int(frac * 7))
                v = WEEKLY_GPU_UTIL[wk] + rng.gauss(0, 0.15)
            else:
                v = old + (latest - old) * frac + rng.gauss(0, abs(latest - old) * 0.03 + 1e-6)
                if back == 1:
                    v = latest
            prec = 2 if unit == "pct" and latest < 100 and "Availability" in metric else (1 if unit in ("pct", "h", "ms") else 0)
            out.append((ts, "ai:scoreboard", {"scoreboard": board, "metric": metric, "value": round(v, prec), "unit": unit, "window": window,
                                              "business_unit": "all", "environment": "production", "day": day.isoformat()}))
    # weekly GPU utilization series (window 7d) for the executive chart
    for k, v in enumerate(WEEKLY_GPU_UTIL):
        day = ctx.latest_day - timedelta(days=(6 - k) * 7)
        ts = wall_epoch(ctx.tz, day, 23, 50)
        if ts > ctx.now:
            ts = wall_epoch(ctx.tz, day, 0, 5)
        out.append((ts, "ai:scoreboard", {"scoreboard": "efficiency", "metric": "GPU utilization", "value": v, "unit": "pct", "window": "7d",
                                          "business_unit": "all", "environment": "production", "week_index": k + 1, "target": 65.0}))
    return out


def incident_rows(ctx):
    rng = rng_for(ctx.seed, "incidents")
    out = []
    # 8 weekly rows per layer; week_start = Monday
    anchor = ctx.latest_day - timedelta(days=ctx.latest_day.weekday())
    totals = [33] + WEEKLY_INCIDENTS
    for k, total in enumerate(totals):
        wk_start = anchor - timedelta(days=7 * (len(totals) - 1 - k))
        ts = wall_epoch(ctx.tz, wk_start, 0, 5)
        if ts > ctx.now:
            continue
        layers = list(INCIDENT_LAYER_SHARE)
        counts = [int(round(total * INCIDENT_LAYER_SHARE[l])) for l in layers]
        counts[0] += total - sum(counts)
        iso = wk_start.isocalendar()
        for l, c in zip(layers, counts):
            out.append((ts, "ai:incident", {"week": "%d-W%02d" % (iso[0], iso[1]), "week_start": wk_start.isoformat(), "root_cause_layer": l,
                                            "count": c, "environment": "production"}))
    return out


def eval_history_rows(ctx):
    """ai:eval:run rows for v37..v41 x safety/reasoning/coding over the last 90 days (v41 rows for earlier versions only;
    the daily schedule carries the v41 rows themselves)."""
    rng = rng_for(ctx.seed, "eval-history")
    out = []
    lab = [n for n in T.GPU_NODES if n.startswith("lab")]
    for vi, version in enumerate(["v37", "v38", "v39", "v40"]):
        day = ctx.latest_day - timedelta(days=88 - vi * 21 + rng.randint(0, 3))
        for si, suite in enumerate(["safety", "reasoning", "coding"]):
            ts = wall_epoch(ctx.tz, day, 9 + si * 3, rng.randint(0, 59), rng.randint(0, 59), rng.randint(0, 999))
            pr = EVAL_HISTORY[suite][vi]
            base = EVAL_HISTORY[suite][vi - 1] if vi else pr - 0.5
            delta = round(pr - base, 1)
            jid = "eval-%s-%s-%04d" % (suite, version, rng.randint(10, 99))
            out.append((ts, "ai:eval:run", {"job_id": jid, "model_version": "med-advisor-" + version, "model": "med-advisor", "version": version,
                                            "suite": suite, "pass_rate": pr, "baseline_pass_rate": base, "delta_vs_baseline": delta,
                                            "status": "improved" if delta > 0.5 else ("within_band" if delta > -1.0 else "watch"),
                                            "evidence": jid, "cycle_time_h": round(rng.uniform(4.6, 5.6), 1), "queue_wait_h": round(rng.uniform(0.6, 1.4), 1),
                                            "cases": 2400, "node": rng.choice(lab), "severity": "low"}))
    return out


def history_rows(ctx):
    return scoreboard_rows(ctx) + incident_rows(ctx) + eval_history_rows(ctx)
