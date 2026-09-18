"""--self-check: regenerate the latest day (tier 1) plus the 7-day schedule rows in memory and
recompute every dashboard KPI with the same arithmetic as the SPL macros."""
import math
import time
from datetime import timedelta

from . import calib as C
from . import topology as T
from . import feeds as F
from .timeutil import wall_epoch, local_hour
from .catalog import SOURCETYPE_INDEX

# name -> (target, tolerance, headline?)
TARGETS = {
    "GPUs Monitored": (512, 0.0, True),
    "Avg GPU Utilization (%)": (61.8, 0.03, True),
    "Idle GPU-Hours (7d)": (17136, 0.03, True),
    "Degraded Nodes": (3, 0.0, True),
    "ECC / Xid Errors (24h)": (41, 0.03, True),
    "Fabric Links Monitored": (1152, 0.0, True),
    "Congested Links": (14, 0.0, False),
    "PFC Pause Frames (24h)": (38200, 0.03, True),
    "Link Flaps": (9, 0.0, False),
    "p95 Latency to Model APIs (ms)": (182, 0.03, False),
    "Inference Replicas Running": (184, 0.0, False),
    "Pod Restarts (24h)": (37, 0.0, False),
    "Pending GPU Pods": (12, 0.0, False),
    "p95 Queue Time (s)": (1.8, 0.03, False),
    "Failed Jobs (7d)": (9, 0.0, False),
    "Requests": (1280000, 0.03, True),
    "Availability (%)": (99.93, 0.0005, True),
    "p95 Time-to-First-Token (ms)": (820, 0.03, True),
    "Token Spend (24h, USD)": (30300, 0.03, True),
    "Guardrails Triggered": (1906, 0.0, True),
    "Safety Compliance (%)": (99.2, 0.002, False),
    "Groundedness (%)": (96.1, 0.005, False),
    "Hallucination Rate (%)": (1.8, 0.03, True),
    "Score Drift vs Baseline": (-2.1, 0.0, False),
    "Evaluation Cycle Time (h)": (4.2, 0.03, False),
    "Agent Runs (24h)": (48320, 0.0, True),
    "Task Completion (%)": (93.8, 0.003, True),
    "Avg Steps per Task": (6.4, 0.03, False),
    "Tool Call Failures": (1204, 0.0, False),
    "Runaway Loops Stopped": (37, 0.0, False),
    "GPU-Hours Allocated (7d)": (68944, 0.03, False),
    "Cost per 1M Tokens self-hosted (USD)": (0.84, 0.03, False),
    "Model API Spend (7d, USD)": (212100, 0.03, False),
    "Tokens per GPU-Second": (2140, 0.03, False),
    "Open Findings (7d)": (22, 0.0, False),
    "Model Asset Access Anomalies (7d)": (7, 0.0, False),
    "Credential Misuse (7d)": (3, 0.0, False),
    "Data Movement Alerts (7d)": (12, 0.0, False),
    "Prompt Injections Detected (7d)": (214, 0.0, False),
}


def perc95(values):
    if not values:
        return 0.0
    v = sorted(values)
    k = int(math.ceil(0.95 * len(v))) - 1
    return float(v[max(0, min(k, len(v) - 1))])


class Agg(object):
    """Streaming aggregator over one day's events."""

    def __init__(self):
        self.gpus = set()
        self.util_sum = 0.0
        self.util_n = 0
        self.node_state = {}
        self.ecc_xid = 0
        self.links = set()
        self.congested = set()
        self.pfc = 0
        self.flaps = 0
        self.path_lat = []
        self.replicas = {}
        self.restarts = 0
        self.pending_max = 0
        self.queue = []
        self.req = 0
        self.err = 0
        self.ttft = []
        self.cost = 0.0
        self.guard = 0
        self.safety = []
        self.ground = []
        self.halluc = 0
        self.req_gen = 0  # generative requests (embedding models excluded)
        self.drift = None
        self.drift_ts = -1
        self.runs = 0
        self.completed = 0
        self.steps_completed = []
        self.tool_fail = 0
        self.loops = 0
        self.pending_by_minute = {}

    def add(self, ts, st, ev):
        if st == "ai:gpu:metrics":
            self.gpus.add((ev["node"], ev["gpu"]))
            if ev["workload"] != "unallocated":
                self.util_sum += ev["DCGM_FI_DEV_GPU_UTIL"]
                self.util_n += 1
        elif st == "ai:gpu:fault":
            if ts >= self.node_state.get(ev["node"], (-1, None))[0]:
                self.node_state[ev["node"]] = (ts, ev["node_state"])
            if ev["fault"].startswith("ecc_") or ev["fault"].startswith("xid_"):
                self.ecc_xid += 1
        elif st == "cisco:nexus:interface":
            self.links.add((ev["device"], ev["interface"]))
            self.pfc += ev["pfc_pause_rx"] + ev["pfc_pause_tx"]
        elif st == "cisco:nexus:anomaly":
            if ev["anomaly"] in ("congestion", "pfc_pause_storm", "ecn_marked_packets high"):
                self.congested.add((ev["device"], ev["interface"]))
            if ev["anomaly"] == "link_flap":
                self.flaps += ev.get("flap_count", 0)
        elif st == "ai:path:test":
            if ev["target"] == "api.model-provider.example":
                self.path_lat.append(ev["latency_ms"])
        elif st == "ai:inference:server":
            self.replicas[ev["model_server"]] = (ts, ev["replicas_running"])
            m = int(ts // 60)
            self.pending_by_minute[m] = self.pending_by_minute.get(m, 0) + ev["pending_gpu_pods"]
            self.queue.append(ev["queue_time_p95_ms"])
        elif st == "kube:events":
            if ev["reason"] in ("OOMKilled", "NodeNotReady", "CrashLoopBackOff", "Evicted"):
                self.restarts += ev["restart_count"]
        elif st == "gen_ai:request":
            n = ev["request_count"]
            self.req += n
            if ev["status"] != "ok":
                self.err += n
            self.ttft.append(ev["ttft_ms"])
            self.cost += ev["cost_usd"]
            self.safety.append(ev["quality.safety_score"])
            self.ground.append(ev["quality.groundedness"])
            self.halluc += ev["hallucination_count"]
            if ev["gen_ai.request.model"] not in C.EMBEDDING_MODELS:
                self.req_gen += n
        elif st == "gen_ai:guardrail":
            if ev["verdict"] in ("flagged", "blocked"):
                self.guard += 1
        elif st == "ai:eval:run":
            if ev["suite"] == "reasoning" and ts > self.drift_ts:
                self.drift_ts, self.drift = ts, ev["delta_vs_baseline"]
        elif st == "gen_ai:agent:run":
            self.runs += 1
            if ev["outcome"] == "completed":
                self.completed += 1
                self.steps_completed.append(ev["steps"])
            if ev["outcome"] == "loop_stopped":
                self.loops += 1
        elif st == "gen_ai:agent:step":
            if ev["gen_ai.operation.name"] == "execute_tool" and ev["status"] == "error":
                self.tool_fail += 1


def run_day(ctx, cache, day, wanted, tuned, agg, cadence_minutes=1):
    start = wall_epoch(ctx.tz, day, 0)
    end = wall_epoch(ctx.tz, day + timedelta(days=1), 0)
    m = start
    while m < end:
        for ts, st, ev in F.minute_events(ctx, cache, m, 1, wanted, tuned):
            agg.add(ts, st, ev)
        m += 60 * cadence_minutes


def compute_kpis(ctx, tuned, verbose=None):
    """Return {kpi: value} for the latest day (24h) and the 7-day windows ending on it."""
    cache = F.DayCache(ctx)
    day = ctx.latest_day
    agg = Agg()
    t0 = time.time()
    # metrics at 15-min sampling (formula feed, diurnal mean preserved); everything else at full cadence
    run_day(ctx, cache, day, {"ai:gpu:metrics"}, tuned, agg, 15)
    rest = set(SOURCETYPE_INDEX) - {"ai:gpu:metrics", "ai:scoreboard", "ai:incident"}
    run_day(ctx, cache, day, rest, tuned, agg, 1)
    if verbose:
        verbose("self-check: generated latest day in %.1fs" % (time.time() - t0))
    k = {}
    k["GPUs Monitored"] = len(agg.gpus)
    k["Avg GPU Utilization (%)"] = agg.util_sum / max(1, agg.util_n)
    k["Degraded Nodes"] = sum(1 for _, s in agg.node_state.values() if s == "degraded")
    k["ECC / Xid Errors (24h)"] = agg.ecc_xid
    k["Fabric Links Monitored"] = len(agg.links)
    k["Congested Links"] = len(agg.congested)
    k["PFC Pause Frames (24h)"] = agg.pfc
    k["Link Flaps"] = agg.flaps
    k["p95 Latency to Model APIs (ms)"] = perc95(agg.path_lat)
    k["Inference Replicas Running"] = sum(v for _, v in agg.replicas.values())
    k["Pod Restarts (24h)"] = agg.restarts
    k["Pending GPU Pods"] = max(agg.pending_by_minute.values()) if agg.pending_by_minute else 0
    k["p95 Queue Time (s)"] = perc95(agg.queue) / 1000.0
    k["Requests"] = agg.req
    k["Availability (%)"] = 100.0 * (1.0 - agg.err / float(max(1, agg.req)))
    k["p95 Time-to-First-Token (ms)"] = perc95(agg.ttft)
    k["Token Spend (24h, USD)"] = agg.cost
    k["Guardrails Triggered"] = agg.guard
    k["Safety Compliance (%)"] = sum(agg.safety) / max(1, len(agg.safety))
    k["Groundedness (%)"] = sum(agg.ground) / max(1, len(agg.ground))
    k["Hallucination Rate (%)"] = 100.0 * agg.halluc / float(max(1, agg.req_gen))
    k["Score Drift vs Baseline"] = agg.drift
    k["Agent Runs (24h)"] = agg.runs
    k["Task Completion (%)"] = 100.0 * agg.completed / float(max(1, agg.runs))
    k["Avg Steps per Task"] = sum(agg.steps_completed) / float(max(1, len(agg.steps_completed)))
    k["Tool Call Failures"] = agg.tool_fail
    k["Runaway Loops Stopped"] = agg.loops
    # 7-day windows from the day schedules
    failed_jobs, cyc = set(), []
    gpu_h = idle_h = api_spend = 0.0
    sh_cost = sh_tok = gpu_s = 0.0
    findings = {}
    inj = 0
    for back in range(7, -1, -1):
        d = day - timedelta(days=back)
        s = cache.schedule(d)
        if 1 <= back <= 7:   # cost rows are stamped 23:59:59, so D-7..D-1 fall inside -7d@d..now
            for _, ev in s.events["ai:cost:daily"]:
                gpu_h += ev["gpu_hours"]
                idle_h += ev["idle_gpu_hours"]
            for _, ev in s.events["ai:cost:tokens"]:
                if ev["gen_ai.system"] == "provider":
                    api_spend += ev["cost_usd"]
                else:
                    sh_cost += ev["cost_usd"]
                    sh_tok += ev["tokens_millions"]
                    gpu_s += ev["gpu_seconds"]
        if back <= 6:
            for _, ev in s.events.get("ai:security:finding", []):
                findings[ev["finding_id"]] = ev
            inj += sum(1 for _, ev in s.events["gen_ai:guardrail"] if ev["category"] == "prompt_injection" and ev["verdict"] == "blocked")
            for _, ev in s.events["ai:job:lifecycle"]:
                if ev["state"] == "failed":
                    failed_jobs.add(ev["job_id"])
            cyc += [ev["cycle_time_h"] for _, ev in s.events["ai:eval:run"]]
    k["Failed Jobs (7d)"] = len(failed_jobs)
    k["Evaluation Cycle Time (h)"] = sum(cyc) / max(1, len(cyc))
    k["Idle GPU-Hours (7d)"] = idle_h
    k["GPU-Hours Allocated (7d)"] = gpu_h
    k["Cost per 1M Tokens self-hosted (USD)"] = sh_cost / max(1e-9, sh_tok)
    k["Model API Spend (7d, USD)"] = api_spend
    k["Tokens per GPU-Second"] = sh_tok * 1e6 / max(1e-9, gpu_s)
    k["Open Findings (7d)"] = sum(1 for ev in findings.values() if ev["status"] == "open")
    for name, cat in [("Model Asset Access Anomalies (7d)", "model_asset_access"), ("Credential Misuse (7d)", "credential_misuse"),
                      ("Data Movement Alerts (7d)", "data_movement")]:
        k[name] = sum(1 for ev in findings.values() if ev["category"] == cat)
    k["Prompt Injections Detected (7d)"] = inj
    return k


def _quick(ctx, tuned, wanted, extract):
    """Regenerate only `wanted` feeds for the latest day and return extract(agg)."""
    cache = F.DayCache(ctx)
    agg = Agg()
    run_day(ctx, cache, ctx.latest_day, wanted, tuned, agg, 1)
    return extract(agg)


def tune(ctx, tuned, log):
    """Solve the tuned parameters by bisection/secant so their KPIs land on target. Returns a new dict."""
    t = dict(tuned)
    plans = [
        ("path_median", {"ai:path:test"}, lambda a: perc95(a.path_lat), 182.0, "p95 Latency to Model APIs (ms)"),
        ("queue_burst", {"ai:inference:server"}, lambda a: perc95(a.queue), 1800.0, "p95 Queue Time (ms)"),
        ("ttft_sigma", {"gen_ai:request"}, lambda a: perc95(a.ttft), 820.0, "p95 Time-to-First-Token (ms)"),
        ("halluc_med", {"gen_ai:request"}, lambda a: 100.0 * a.halluc / float(max(1, a.req_gen)), 1.8, "Hallucination Rate (%)"),
        ("safety_med", {"gen_ai:request"}, lambda a: sum(a.safety) / max(1, len(a.safety)), 99.2, "Safety Compliance (%)"),
    ]
    for name, wanted, extract, target, label in plans:
        lo, hi = C.TUNABLE_BOUNDS[name]
        cur = t[name]
        val = _quick(ctx, t, wanted, extract)
        if abs(val - target) <= 0.01 * abs(target):
            log("  tune %-12s = %-8.4g ok (%s = %.4g)" % (name, cur, label, val))
            continue
        for _ in range(14):
            if val < target:
                lo = cur
            else:
                hi = cur
            cur = (lo + hi) / 2.0
            t[name] = cur
            val = _quick(ctx, t, wanted, extract)
            if abs(val - target) <= 0.005 * abs(target):
                break
        log("  tune %-12s = %-8.4g (was %.4g) -> %s = %.4g" % (name, cur, tuned[name], label, val))
    return t
