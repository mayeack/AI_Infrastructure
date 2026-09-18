"""Per-minute formula feeds (high volume): GPU metrics, Nexus interfaces, path tests,
inference servers, request rows, agent runs and steps.

`minute_events(ctx, cache, minute_epoch, tier, wanted)` returns [(epoch, sourcetype, event), ...]
for one minute; the RNG is seeded with (seed, minute, sourcetype) so output is reproducible."""
import math

from . import topology as T
from . import calib as C
from .catalog import TIER_CADENCE, INTERFACE_WINDOW_CADENCE
from .timeutil import (diurnal, ramp, in_window, local_hour, local_dt, local_day, minute_weights_for_day,
                       cumulative_alloc, hex_id, lognormal, clamp, wall_epoch, pick_distinct)
from .schedule import DaySchedule, request_event, SINGLETONS_PER_DAY


class DayCache(object):
    """Caches per-day schedules and cumulative diurnal allocations."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.sched = {}
        self.weights = {}

    def schedule(self, day):
        if day not in self.sched:
            if len(self.sched) > 3:
                self.sched.clear()
            self.sched[day] = DaySchedule(self.ctx, day)
        return self.sched[day]

    def day_weights(self, day):
        if day not in self.weights:
            if len(self.weights) > 3:
                self.weights.clear()
            start, w = minute_weights_for_day(self.ctx.tz, day)
            cum = [0.0]
            for x in w:
                cum.append(cum[-1] + x)
            self.weights[day] = (start, cum)
        return self.weights[day]

    def cum_count(self, day, total, minute_index):
        """Cumulative count of a daily total (diurnal-weighted) up to minute_index."""
        start, cum = self.day_weights(day)
        i = max(0, min(minute_index, len(cum) - 1))
        return int(round(total * cum[i] / cum[-1]))

    def count_between(self, day, total, a, b):
        return self.cum_count(day, total, b) - self.cum_count(day, total, a)

    def minute_index(self, day, minute_epoch):
        start, cum = self.day_weights(day)
        return int(round((minute_epoch - start) / 60.0))


def _shape(h):
    """Diurnal multiplier with mean 1.0 over a day: 0.75 at the trough, 1.25 at the peak."""
    return 1.0 + 0.25 * (diurnal(h) - 0.55) / 0.45


# ---- ai:gpu:metrics ---------------------------------------------------------------
def gpu_metrics(ctx, minute, h, rng, tuned):
    out = []
    f = _shape(h)
    day_end_hot = h >= 14.0 + 49.55 / 60
    for node, gpu, wl, kind in T.GPU_ROWS:
        if wl == "unallocated":
            util = rng.uniform(0.0, 3.0)
            temp = rng.randint(34, 38)
            power = round(rng.uniform(60.0, 70.0), 1)
            fb, clock, mcu = 0, 1200, 0.0
        else:
            mean = T.WORKLOAD_UTIL_24H[wl]
            ff = f if kind == "inference" else 1.0
            util = clamp(mean * ff + rng.gauss(0.0, 4.0), 1.0, 100.0)
            temp = int(round(58 + util * 0.25 + rng.gauss(0, 1.5)))
            power = round(95.0 + util * 3.4 + rng.gauss(0, 8.0), 1)
            fb = 61440 if kind == "inference" else (40960 if kind == "evaluation" else 73728)
            clock = 1980 if rng.random() < 0.9 else 1755
            mcu = round(util * 0.6 + rng.gauss(0, 2.0), 1)
        if node == "dc1-ucs-gpu-07" and gpu == "GPU5":
            if 14.0 + 38.0 / 60 <= h < 14.0 + 49.55 / 60:
                temp = int(round(68 + (91 - 68) * (h - (14.0 + 38.0 / 60)) / (11.55 / 60)))
            elif day_end_hot:
                util, mcu, clock, power = 0.0, 0.0, 0, 42.0
                temp = 88 if h < 14.0 + 52.2 / 60 else max(45, int(round(88 - (h - (14.0 + 52.2 / 60)) * 60 * 2)))
        if node == "dc2-ucs-gpu-19" and gpu == "GPU2" and 14.0 + 31.0 / 60 <= h < 14.0 + 50.0 / 60:
            temp, clock = 93, 1200
        ev = {"ai_pod": T.pod_of(node), "node": node, "gpu": gpu, "workload": wl, "kind": kind,
              "DCGM_FI_DEV_GPU_UTIL": round(util, 1), "DCGM_FI_DEV_MEM_COPY_UTIL": max(0.0, mcu), "DCGM_FI_DEV_FB_USED": fb,
              "DCGM_FI_DEV_POWER_USAGE": power, "DCGM_FI_DEV_GPU_TEMP": temp, "DCGM_FI_DEV_SM_CLOCK": clock}
        if gpu == "GPU0":
            ev["storage_read_mbps"] = round(1840.0 * f * rng.uniform(0.9, 1.1), 1)
            ev["storage_write_mbps"] = round(420.0 * f * rng.uniform(0.9, 1.1), 1)
            ev["storage_latency_ms"] = round(2.3 * rng.uniform(0.85, 1.25), 2)
        out.append((minute, "ai:gpu:metrics", ev))
    return out


# ---- cisco:nexus:interface ------------------------------------------------------------
def interface_rows_per_day(tier):
    cad = TIER_CADENCE[tier]["cisco:nexus:interface"]
    if tier == 1:
        return 1152 * ((1440 - 135) // cad + 135 // INTERFACE_WINDOW_CADENCE)
    return 1152 * (1440 // cad)


def nexus_interface(ctx, minute, h, rng, tier, cadence):
    out = []
    f = _shape(h)
    p_noise = 98.0 / interface_rows_per_day(tier)
    lm = local_dt(ctx.tz, minute).minute
    for device, intf, peer, fabric, kind in T.LINKS:
        base = {"server": 34.0, "uplink": 48.0, "spine": 48.0}[kind] * (1.0 if fabric != "aipod-lab" else 0.55)
        in_u = clamp(base * f + rng.gauss(0, 6.0), 0.5, 99.0)
        out_u = clamp(base * f * 0.8 + rng.gauss(0, 6.0), 0.5, 99.0)
        ecn = 0
        pfc_rx = pfc_tx = 0
        crc = 0
        state = "up"
        optic = round(-2.1 + rng.gauss(0, 0.2), 2)
        sev = "low"
        if rng.random() < p_noise:
            pfc_rx = rng.randint(5, 40)
        if rng.random() < 0.002:
            crc = rng.randint(1, 12)
        if device == "dc1-spine-02" and intf == "Eth2/05" and h >= 14.0 + 38.0 / 60 and h < 15.0:
            in_u, out_u, ecn, sev = 94.0 + rng.uniform(-0.5, 0.5), 91.0 + rng.uniform(-1, 1), int(18000 * cadence * rng.uniform(0.95, 1.05)), "high"
        elif device == "dc1-leaf-112" and intf == "Eth1/31" and h >= 14.0 + 41.0 / 60 and h < 15.0:
            share = min(cadence, 19.0) / 19.0
            pfc_rx = int(round(36000 * share * 0.7))
            pfc_tx = int(round(36000 * share)) - pfc_rx
            in_u, out_u, sev = 97.0 + rng.uniform(-0.5, 0.5), 88.0, "critical"
        elif device == "dc1-leaf-112" and intf == "Eth1/14" and h >= 14.0 + 40.0 / 60 and h < 14.0 + 50.0 / 60:
            state = "down" if (lm % 2 == 0 or lm == 49) else "up"
            in_u = out_u = 12.0 if state == "up" else 0.0
            sev = "high"
        elif device == "dc2-leaf-207" and intf == "Eth1/03" and h >= 13.0 and h < 15.0:
            crc = rng.randint(20, 60)
            sev = "medium"
        elif device == "lab-leaf-158" and intf == "Eth1/09":
            optic = round(-9.8 + rng.gauss(0, 0.2), 2)
        ev = {"device": device, "interface": intf, "peer": peer, "fabric": fabric, "ai_pod": fabric, "speed_gbps": 400,
              "in_util_pct": round(in_u, 1), "out_util_pct": round(out_u, 1), "in_gbps": round(in_u * 4.0, 1), "out_gbps": round(out_u * 4.0, 1),
              "ecn_marked_packets": ecn, "pfc_pause_rx": pfc_rx, "pfc_pause_tx": pfc_tx, "crc_errors": crc, "link_state": state,
              "optic_rx_power_dbm": optic, "severity": sev}
        out.append((minute, "cisco:nexus:interface", ev))
    return out


# ---- ai:path:test ---------------------------------------------------------------------
def path_tests(ctx, minute, h, rng, tuned):
    out = []
    for probe in T.PATH_PROBES:
        for target, med in T.PATH_TARGETS.items():
            if target == "api.model-provider.example":
                med = tuned["path_median"]
            lat = lognormal(rng, med, 0.10)
            slow_hop, delta, sev = None, 0, "low"
            if probe == "probe-dc1" and target == "api.model-provider.example" and 13.0 + 56.0 / 60 <= h < 14.0 + 25.0 / 60:
                lat += 140.0
                slow_hop, delta, sev = 9, 140, "medium"
            ev = {"probe": probe, "target": target, "latency_ms": round(lat, 1), "loss_pct": round(max(0.0, rng.gauss(0.02, 0.03)), 2),
                  "hops": 12 if target == "api.model-provider.example" else rng.choice([8, 9, 10]), "slow_hop": slow_hop,
                  "slow_hop_delta_ms": delta, "source": "path_test", "severity": sev}
            out.append((minute + rng.uniform(0, 20), "ai:path:test", ev))
    return out


# ---- ai:inference:server ----------------------------------------------------------------
def inference_servers(ctx, minute, h, rng, tuned):
    out = []
    d = diurnal(h)
    r = ramp(h)
    degraded = 14.0 + 50.2 / 60 <= h < 15.0 + 37.2 / 60
    for server, (pod, replicas) in T.MODEL_SERVERS.items():
        if server == "med-advisor-v41":
            rep = replicas - 2 if degraded else replicas
            depth = int(round((5 + 6 * d) * (1 - r) + (10 + 30 * r) * r + rng.gauss(0, 1)))
            base_q = lognormal(rng, 400.0 * (0.7 + 0.6 * d), 0.25)
            mi = int(round((minute - wall_epoch(ctx.tz, local_day(ctx.tz, minute), 0)) / 60.0))
            if ((mi * 2654435761) % 4294967296) / 4294967296.0 < tuned["queue_burst"]:
                base_q = rng.uniform(1600.0, 2000.0)          # deterministic burst minutes shape the 24h p95
            q = int(round(base_q * (1 - r) + 2600.0 * rng.uniform(0.92, 1.08) * r))
            pending = int(round(2 + 6 * r))
        elif server == "claims-v12":
            rep, depth = replicas, int(round(3 + 4 * d + rng.gauss(0, 0.8)))
            q = int(round(lognormal(rng, 260.0 * (0.7 + 0.6 * d), 0.25)))
            pending = int(round(3 * r))
        else:
            rep, depth = replicas, int(round(2 + 3 * d + rng.gauss(0, 0.6)))
            q = int(round(lognormal(rng, 220.0 * (0.7 + 0.6 * d), 0.25)))
            pending = int(round(1 * r))
        ev = {"model_server": server, "ai_pod": pod, "replicas_running": rep, "queue_depth": max(0, depth), "queue_time_p95_ms": max(20, q),
              "batch_size": rng.choice([8, 16, 16, 32]), "kv_cache_util_pct": round(clamp(55 + 30 * d + 15 * r + rng.gauss(0, 3), 5, 100), 1),
              "pending_gpu_pods": pending, "requests_per_s": round((14.8 * d * (0.38 if server == "med-advisor-v41" else 0.22 if server == "claims-v12" else 0.14)) * 60 / 60, 1),
              "severity": "high" if (server == "med-advisor-v41" and r > 0.5) else "low"}
        out.append((minute, "ai:inference:server", ev))
    return out


# ---- gen_ai:request (aggregate per-minute rows) ---------------------------------------
_SLOTS = []
for _app, _model, _system, _n, _wl in T.STREAMS:
    _share = T.APP_SHARE["provider"] / 3.0 if _system == "provider" else T.APP_SHARE[_app] * (1.0 if _model != "med-advisor-v40" else 0.0)
    if _model == "med-advisor-v41":
        _share = T.APP_SHARE["medadvice-chat"] * 8.0 / 9.0
    elif _model == "med-advisor-v40":
        _share = T.APP_SHARE["medadvice-chat"] / 9.0
    for _k in range(_n):
        _SLOTS.append((_app, _model, _system, _wl, _share / _n))
SLOT_WEIGHTS = [s[4] for s in _SLOTS]


def request_rows(ctx, cache, minute, h, rng, tuned, cadence):
    day = local_day(ctx.tz, minute)
    mi = cache.minute_index(day, minute)
    total = cache.count_between(day, C.REQUESTS_PER_DAY - SINGLETONS_PER_DAY, mi, mi + cadence)
    counts = cumulative_alloc(total, SLOT_WEIGHTS)
    r = ramp(h)
    out = []
    for (app, model, system, wl, _w), n in zip(_SLOTS, counts):
        if n <= 0:
            continue
        ts = minute + rng.uniform(0, 59.0)
        ev = request_event(rng, ts, app, model, system, wl, hex_id(rng, 12), r, request_count=n, row_kind="minute", tuned=tuned)
        out.append((ts, "gen_ai:request", ev))
    return out


# ---- gen_ai:agent:run / gen_ai:agent:step ------------------------------------------------
_AGENT_NAMES = list(T.AGENTS)
_AGENT_W_DONE = [T.AGENTS[a][0] * T.AGENTS[a][1] for a in _AGENT_NAMES]
_AGENT_W_FAIL = [T.AGENTS[a][0] * (100.0 - T.AGENTS[a][1]) for a in _AGENT_NAMES]
_STEP_VALS = [v for v, _ in C.STEPS_DIST]
_STEP_W = [w for _, w in C.STEPS_DIST]
_AGENT_TOOLS = {"claims-intake-agent": ["claims_api", "search_kb", "send_notification"], "care-navigator": ["ehr_lookup", "search_kb", "send_notification"],
                "it-helpdesk-agent": ["search_kb", "send_notification"], "policy-qa-agent": ["search_kb", "claims_api"],
                "scheduling-agent": ["send_notification", "ehr_lookup", "search_kb"]}


def agent_runs(ctx, cache, minute, h, rng, tier, want_steps):
    day = local_day(ctx.tz, minute)
    sched = cache.schedule(day)
    mi = cache.minute_index(day, minute)
    div = 4 if tier == 3 else 1
    scripted = len(sched.events.get("gen_ai:agent:run", []))
    out = []
    err_budget = cache.count_between(day, C.STEP_ERRORS_PER_DAY - sched.scripted_step_errors(), mi, mi + 1)
    runs = []
    for outcome, total in C.AGENT_OUTCOMES.items():
        if outcome == "loop_stopped":
            continue
        if outcome == "completed":
            total -= 4
        elif outcome == "escalated_to_human":
            total -= 1
        elif outcome == "blocked:guardrail":
            total -= 1
        n = cache.count_between(day, total // div, mi, mi + 1)
        for _ in range(n):
            runs.append(outcome)
    rng.shuffle(runs)
    tool_steps = []
    for outcome in runs:
        done = outcome == "completed"
        agent = rng.choices(_AGENT_NAMES, _AGENT_W_DONE if done else _AGENT_W_FAIL)[0]
        share, pct, model, bu = T.AGENTS[agent]
        steps = rng.choices(_STEP_VALS, _STEP_W)[0] if done else rng.randint(8, 16)
        chats = max(1, int(round(steps / 3.0)))
        calls = steps - chats
        tools = _AGENT_TOOLS[agent]
        top = tools[0]
        topn = max(1, int(round(calls * 0.6)))
        tokens = int(steps * rng.uniform(1100, 1650))
        dur = int(steps * rng.uniform(1500, 2800))
        ts = minute + rng.uniform(0.5, 59.5)
        tid = hex_id(rng, 12)
        run = {"gen_ai.agent.name": agent, "trace_id": tid, "session_id": hex_id(rng, 16), "steps": steps, "tool_calls": calls,
               "tool_call_failures": 0, "outcome": outcome, "tokens": tokens, "cost_usd": round(tokens * 1.1e-5, 2), "duration_ms": dur,
               "gen_ai.request.model": model, "business_unit": bu, "tools_used": tools[:2], "top_tool": top, "top_tool_calls": topn,
               "severity": "low" if done else "medium"}
        emit_steps = want_steps and (tier == 1 or not done or (tier == 2 and rng.random() < 0.10))
        step_rows = []
        if emit_steps:
            t0 = max(minute, ts - dur / 1000.0)
            names = [top] * topn + [tools[(k % (len(tools) - 1)) + 1] if len(tools) > 1 else top for k in range(calls - topn)]
            chat_slots = set(pick_distinct(rng, range(steps), chats))
            ti = 0
            for n in range(steps):
                st = t0 + (ts - t0) * (n + 1) / steps
                ev = {"gen_ai.agent.name": agent, "trace_id": tid, "step_no": n + 1, "duration_ms": rng.randint(300, 2400),
                      "tokens": max(40, int(tokens / steps * rng.uniform(0.6, 1.4))), "status": "ok", "error_type": None, "severity": "low"}
                if n in chat_slots or ti >= len(names):
                    ev["gen_ai.operation.name"], ev["gen_ai.tool.name"] = "chat", None
                else:
                    ev["gen_ai.operation.name"], ev["gen_ai.tool.name"] = "execute_tool", names[ti]
                    ti += 1
                    tool_steps.append((run, ev))
                step_rows.append((st, "gen_ai:agent:step", ev))
        out.append((ts, "gen_ai:agent:run", run))
        out.extend(step_rows)
    # assign this minute's tool-call failures
    if err_budget > 0 and tool_steps:
        for run, ev in pick_distinct(rng, tool_steps, min(err_budget, len(tool_steps))):
            ev["status"] = "error"
            ev["error_type"] = "http_503" if ev["gen_ai.tool.name"] == "claims_api" else rng.choice(["timeout", "schema_error"])
            ev["severity"] = "medium"
            run["tool_call_failures"] += 1
    return out


# ---- dispatcher -------------------------------------------------------------------------
def minute_events(ctx, cache, minute, tier, wanted, tuned=None):
    """All events for the minute [minute, minute+60) for the wanted sourcetypes (set or None=all)."""
    tuned = tuned or C.TUNED
    day = local_day(ctx.tz, minute)
    mi = cache.minute_index(day, minute)
    h = local_hour(ctx.tz, minute)
    cad = TIER_CADENCE[tier]
    out = []

    def want(st):
        return wanted is None or st in wanted

    if want("ai:gpu:metrics") and mi % cad["ai:gpu:metrics"] == 0:
        out.extend(gpu_metrics(ctx, minute, h, ctx.rng(int(minute), "ai:gpu:metrics"), tuned))
    if want("cisco:nexus:interface"):
        c = INTERFACE_WINDOW_CADENCE if (tier == 1 and in_window(h)) else cad["cisco:nexus:interface"]
        if mi % c == 0:
            out.extend(nexus_interface(ctx, minute, h, ctx.rng(int(minute), "cisco:nexus:interface"), tier, c))
    if want("ai:path:test") and mi % cad["ai:path:test"] == 0:
        out.extend(path_tests(ctx, minute, h, ctx.rng(int(minute), "ai:path:test"), tuned))
    if want("ai:inference:server") and mi % cad["ai:inference:server"] == 0:
        out.extend(inference_servers(ctx, minute, h, ctx.rng(int(minute), "ai:inference:server"), tuned))
    if want("gen_ai:request") and mi % cad["gen_ai:request"] == 0:
        out.extend(request_rows(ctx, cache, minute, h, ctx.rng(int(minute), "gen_ai:request"), tuned, cad["gen_ai:request"]))
    if want("gen_ai:agent:run") or want("gen_ai:agent:step"):
        rows = agent_runs(ctx, cache, minute, h, ctx.rng(int(minute), "gen_ai:agent"), tier, want("gen_ai:agent:step"))
        out.extend(r for r in rows if want(r[1]))
    # schedule feeds (scripted incident + filler), including the schedule's extra request/agent rows
    sched = cache.schedule(day)
    for st, rows in sched.events.items():
        if not want(st):
            continue
        for ts, ev in rows:
            if minute <= ts < minute + 60:
                out.append((ts, st, ev))
    return out


def expected_counts(tier):
    """Approximate events per day per sourcetype for a tier (used by backfill.sh's table)."""
    cad = TIER_CADENCE[tier]
    div = 4 if tier == 3 else 1
    steps = {1: 309000, 2: 64000, 3: 8700}[tier]
    return {
        "ai:gpu:metrics": 512 * (1440 // cad["ai:gpu:metrics"]),
        "cisco:nexus:interface": interface_rows_per_day(tier),
        "ai:path:test": 6 * (1440 // cad["ai:path:test"]) + 1,
        "ai:inference:server": 3 * (1440 // cad["ai:inference:server"]),
        "gen_ai:request": 28 * (1440 // cad["gen_ai:request"]) + SINGLETONS_PER_DAY,
        "gen_ai:agent:run": (C.AGENT_RUNS_PER_DAY - 43) // div + 43,
        "gen_ai:agent:step": steps,
        "gen_ai:guardrail": 1906, "ai:gpu:fault": 62, "cisco:ucs:alarm": 40, "cisco:ucs:inventory": 72, "cisco:ucs:audit": 20,
        "cisco:nexus:anomaly": 259, "cisco:nexus:config": 6, "kube:events": 639, "ai:job:lifecycle": 145, "ai:eval:run": 7,
        "ai:cost:daily": 13, "ai:cost:tokens": 5, "aws:cloudtrail:sim": 1502, "k8s:audit:sim": 801, "iam:sim": 302,
        "ai:security:finding": 7 if tier == 1 else 0,
    }
