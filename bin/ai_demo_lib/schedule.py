"""Per-day schedule of low-volume events: the scripted incident plus deterministic filler.

`DaySchedule(ctx, day)` builds, for one local calendar day, {sourcetype: [(epoch, event_dict), ...]}
sorted by time.  Everything is seeded from (seed, day, sourcetype) so any minute can be
regenerated identically by --stream and --backfill.
"""
from datetime import timedelta

from . import topology as T
from .timeutil import (wall_epoch, rng_for, trace_id, hex_id, cumulative_alloc, ramp,
                       minute_weights_for_day, local_hour, diurnal, pick_distinct)


class Ctx(object):
    def __init__(self, seed, tz, now_epoch, latest_day, fire_tag=None):
        self.seed = seed
        self.tz = tz
        self.now = now_epoch
        self.latest_day = latest_day   # date whose scripted rows use the deck literal ids
        self.fire_tag = fire_tag
        _HOUR_TZ[0] = tz

    def rng(self, *parts):
        return rng_for(self.seed, *parts)

    def tid(self, day, key, literal=None):
        # deck literal ids are used on every day (the incident replays daily); --fire-incident keeps hashed ids
        if literal and not self.fire_tag:
            return literal
        return trace_id(self.seed, day.isoformat(), key)


# deck literal ids (latest day only)
MOCK_REQUESTS = [  # (h,m,s,ms, app, model, trace, ttft, retrieval, guardrail)
    (14, 58, 45, 969, "medadvice-chat", "med-advisor-v41", "7f3a9c1e04b2", 1412, "timeout", "flagged:hallucination"),
    (14, 58, 44, 120, "claims-agent", "claims-v12", "b81d22f09a6c", 236, 41, "pass"),
    (14, 58, 43, 377, "medadvice-chat", "med-advisor-v41", "2c6e0b77d1f5", 1388, 2004, "blocked:prompt_injection"),
    (14, 58, 41, 902, "search-rag", "rag-embed-v7", "e90a4d3361bc", 188, 37, "pass"),
    (14, 58, 40, 515, "code-assist", "coder-v9", "41f7c8a2e0d9", 301, None, "pass"),
    (14, 58, 39, 48, "medadvice-chat", "med-advisor-v41", "9d02b6f1c47a", 1507, "timeout", "blocked:pii"),
    (14, 58, 37, 733, "claims-agent", "claims-v12", "66c1e9d8072f", 249, 44, "pass"),
]
MOCK_RUNS = [  # (h,m,s,ms, agent, trace, steps, tool_calls, outcome, tokens, cost, top_tool, top_calls)
    (14, 57, 12, 640, "claims-intake-agent", "c41e77a09b3d", 41, 38, "loop_stopped", 212480, 3.12, "claims_api", 31),
    (14, 56, 58, 104, "care-navigator", "0be29f6d51a7", 7, 5, "completed", 18902, 0.21, "ehr_lookup", 3),
    (14, 56, 41, 377, "it-helpdesk-agent", "f3a1c8e2d440", 5, 4, "completed", 9340, 0.09, "search_kb", 3),
    (14, 56, 20, 915, "claims-intake-agent", "7d90e1b2c6f8", 9, 7, "escalated_to_human", 31227, 0.38, "claims_api", 5),
    (14, 55, 59, 208, "policy-qa-agent", "a62f04c9e1b3", 4, 3, "completed", 7815, 0.08, "search_kb", 3),
    (14, 55, 37, 552, "care-navigator", "19c7d3a8f05e", 6, 4, "blocked:guardrail", 12660, 0.14, "ehr_lookup", 2),
    (14, 55, 12, 30, "scheduling-agent", "e8b4a7710c2d", 5, 5, "completed", 8204, 0.08, "send_notification", 3),
]
MOCK_EVALS = [  # (day_offset, h,m,s,ms, model_version, suite, pass, baseline, delta, status, evidence, cycle, queue)
    (0, 13, 40, 12, 501, "med-advisor-v41", "reasoning", 91.9, 94.0, -2.1, "regression", "eval-reasoning-v41-0089", 4.2, 1.5),
    (0, 12, 5, 44, 90, "med-advisor-v41", "safety", 99.2, 99.3, -0.1, "within_band", "eval-safety-v41-0094", 4.0, 1.1),
    (0, 10, 48, 30, 774, "med-advisor-v41", "coding", 92.6, 91.2, 1.4, "improved", "eval-coding-v41-0082", 4.1, 0.9),
    (0, 22, 16, 8, 336, "med-advisor-v41", "groundedness", 96.1, 96.7, -0.6, "watch", "eval-ground-v41-0040", 4.3, 1.2),
    (0, 19, 31, 55, 912, "claims-v12", "safety", 99.6, 99.4, 0.2, "within_band", "eval-safety-c12-0031", 4.4, 1.0),
    (0, 7, 2, 21, 158, "med-advisor-v40", "reasoning", 94.0, 92.4, 1.6, "improved", "eval-reasoning-v40-0077", 4.2, 0.8),  # 07:02 so latest(reasoning delta)=-2.1
    (0, 14, 44, 39, 667, "coder-v9", "coding", 90.8, 90.5, 0.3, "within_band", "eval-coding-c9-0019", 4.2, 1.3),
]
FINDINGS = [  # (h,m,s,ms, user, src, action, object, risk, disposition, category, mitre, owner, rule, sim_st)
    (14, 41, 9, 318, "svc-mlops-ci", "10.42.17.88", "s3:GetObject (first seen)", "weights/med-advisor-v41/", 80,
     "true_positive", "model_asset_access", "T1530", "soc-tier2", "AI Security - First-seen access to model weights", "aws:cloudtrail:sim"),
    (14, 37, 52, 6, "maya.okonkwo@buttercupgames.com", "198.51.100.20", "kubectl exec (off-hours)", "pod/med-advisor-v41-7c9f4", 65,
     "needs_review", "credential_misuse", "T1078", "soc-tier2", "AI Security - Credential misuse on an AI cluster", "k8s:audit:sim"),
    (13, 58, 45, 969, "probe@example.com", "203.0.113.10", "prompt_injection x38", "app/medadvice-chat", 80,
     "true_positive", "prompt_injection", "AML.T0051", "soc-tier1", "AI Security - Prompt-injection campaign from a single source", None),
    (12, 20, 31, 742, "svc-eval-runner", "10.42.30.14", "egress 41 GB to new ASN", "bucket/rag-corpus-clinical", 75,
     "true_positive", "data_movement", "T1567", "soc-tier2", "AI Security - Anomalous data movement from an AI data store", "aws:cloudtrail:sim"),
    (11, 6, 14, 455, "j.alvarez@buttercupgames.com", "10.18.4.201", "api_key.created", "model-registry/prod", 40,
     "benign", "off_hours_admin", "T1078", "soc-tier1", "AI Security - Credential misuse on an AI cluster", "iam:sim"),
    (9, 12, 57, 130, "svc-mlops-ci", "10.42.17.88", "assume_role (new principal)", "role/weights-reader", 60,
     "needs_review", "credential_misuse", "T1078", "soc-tier2", "AI Security - Credential misuse on an AI cluster", "iam:sim"),
    (8, 49, 3, 871, "probe@example.com", "203.0.113.10", "prompt_injection x21", "app/claims-agent", 70,
     "true_positive", "prompt_injection", "AML.T0051", "soc-tier1", "AI Security - Prompt-injection campaign from a single source", None),
]
# prompt-injection guardrail rows per day offset from the latest day (0 = latest), older days use 30
INJECTIONS_BY_OFFSET = {0: 59, 1: 17, 2: 34, 3: 30, 4: 28, 5: 25, 6: 21}
FINDINGS_BY_OFFSET = {1: 15, 2: 7, 3: 5, 4: 5, 5: 4, 6: 5}


class DaySchedule(object):
    """Low-volume events for one local day, grouped by sourcetype and sorted by epoch."""

    def __init__(self, ctx, day):
        self.ctx = ctx
        self.day = day
        self.offset = (ctx.latest_day - day).days   # 0 = latest day
        self.events = {}
        self._build()

    # ---- helpers ------------------------------------------------------------------
    def t(self, h, m=0, s=0, ms=0):
        return wall_epoch(self.ctx.tz, self.day, h, m, s, ms)

    def add(self, st, epoch, ev):
        self.events.setdefault(st, []).append((epoch, ev))

    def rng(self, name):
        # day-independent: the filler schedule repeats identically every day so any rolling
        # 24-hour window sums to the daily totals (ids and trace ids still vary per day via tid()).
        return self.ctx.rng("daily", name)

    def rand_minute_epochs(self, rng, n, weights=None, lo_h=0.0, hi_h=24.0):
        """n random epochs on this day, diurnal-weighted, restricted to [lo_h, hi_h)."""
        start, w = minute_weights_for_day(self.ctx.tz, self.day)
        idx = [i for i in range(len(w)) if lo_h <= local_hour(self.ctx.tz, start + 60 * i) < hi_h]
        ww = [w[i] for i in idx] if weights is None else [weights(i) for i in idx]
        out = []
        for _ in range(n):
            i = rng.choices(idx, ww)[0]
            out.append(start + 60 * i + rng.random() * 60.0)
        return out

    def _build(self):
        self._infra()
        self._network()
        self._platform()
        self._evals()
        self._security()
        self._guardrails_and_requests()
        self._agents()
        self._cost()
        for st in self.events:
            self.events[st].sort(key=lambda e: e[0])

    # ---- layer 1: GPU faults, UCS --------------------------------------------------
    def _fault(self, h, m, s, ms, node, gpu, fault, temp, sev, link_state="up", node_state="ok", xid=None, msg=None):
        ev = {"node": node, "ai_pod": T.pod_of(node), "gpu": gpu, "fault": fault, "gpu_temp_c": temp,
              "severity": sev, "fabric_link": T.node_fabric_link(node), "fabric_link_state": link_state,
              "node_state": node_state, "message": msg or ("%s on %s %s" % (fault, node, gpu))}
        if xid is not None:
            ev["xid"] = xid
        self.add("ai:gpu:fault", self.t(h, m, s, ms), ev)

    def _infra(self):
        f = self._fault
        f(12, 47, 29, 540, "dc2-ucs-gpu-02", "GPU1", "power_cap_throttle", 84, "medium")
        f(13, 12, 45, 7, "dc1-ucs-gpu-21", "GPU3", "ecc_sbe_rate_high", 74, "medium")
        f(13, 40, 2, 250, "lab-ucs-gpu-04", "GPU7", "xid_48_dbe", 76, "high", node_state="degraded", xid=48,
          msg="Xid 48: double bit ECC error on lab-ucs-gpu-04 GPU7; node marked degraded")
        f(13, 58, 41, 665, "dc1-ucs-gpu-11", "GPU0", "nvlink_crc_errors", 71, "high")
        for k, mm in enumerate([31, 36, 41, 46, 50]):
            f(14, mm, 18, 118, "dc2-ucs-gpu-19", "GPU2", "thermal_throttle", 93, "high", node_state="degraded",
              msg="thermal throttle active on dc2-ucs-gpu-19 GPU2 (93 C), SM clock 1200 MHz")
        f(14, 49, 33, 902, "dc1-ucs-gpu-07", "GPU5", "xid_79_fallen_off_bus", 91, "critical", "flapping", "degraded", 79,
          "Xid 79: GPU has fallen off the bus on dc1-ucs-gpu-07 GPU5 (91 C); fabric link dc1-leaf-112:Eth1/14 flapping")
        f(14, 52, 7, 431, "dc1-ucs-gpu-07", "GPU5", "ecc_dbe_volatile", 88, "critical", "up", "degraded",
          msg="volatile double-bit ECC errors on dc1-ucs-gpu-07 GPU5 (88 C); node marked degraded")
        # 37 background ecc/xid (low) + 14 other low faults, never on the three degraded nodes
        rng = self.rng("ai:gpu:fault")
        avoid = {"dc1-ucs-gpu-07", "dc2-ucs-gpu-19", "lab-ucs-gpu-04"}
        nodes = [n for n in T.GPU_NODES if n not in avoid]
        weights = lambda i: 1.0 + (3.0 if 12.75 * 60 <= i < 15 * 60 else 0.0)
        for ts in self.rand_minute_epochs(rng, 37, weights):
            n = rng.choice(nodes)
            ev = {"node": n, "ai_pod": T.pod_of(n), "gpu": "GPU%d" % rng.randrange(8), "fault": "ecc_sbe_rate_high",
                  "gpu_temp_c": rng.randint(62, 79), "severity": "low", "fabric_link": T.node_fabric_link(n),
                  "fabric_link_state": "up", "node_state": "ok", "message": "correctable ECC rate above threshold (page retired)"}
            self.add("ai:gpu:fault", ts, ev)
        for ts in self.rand_minute_epochs(rng, 14):
            n = rng.choice(nodes)
            fault = rng.choice(["nvlink_crc_errors", "power_cap_throttle", "thermal_throttle"])
            ev = {"node": n, "ai_pod": T.pod_of(n), "gpu": "GPU%d" % rng.randrange(8), "fault": fault,
                  "gpu_temp_c": rng.randint(66, 84), "severity": "low", "fabric_link": T.node_fabric_link(n),
                  "fabric_link_state": "up", "node_state": "ok", "message": "%s (transient, cleared)" % fault}
            self.add("ai:gpu:fault", ts, ev)
        # UCS alarms (40), audit (20)
        rng = self.rng("cisco:ucs")
        codes = [("F0283", "Server power usage above threshold", "minor"), ("F0479", "Fan speed below threshold", "minor"),
                 ("F1236", "GPU temperature above threshold", "major"), ("F0181", "Memory DIMM correctable errors", "minor"),
                 ("F0207", "PSU redundancy degraded", "warning")]
        for ts in self.rand_minute_epochs(rng, 40):
            n = rng.choice(T.ALL_NODES)
            code, desc, sev = rng.choice(codes)
            self.add("cisco:ucs:alarm", ts, {"server": n, "ai_pod": T.pod_of(n), "severity": sev, "code": code,
                                             "description": desc, "state": rng.choice(["raised", "raised", "cleared"])})
        users = ["ucs-admin", "svc-firmware-bot", "ops-kchen", "ops-pdas"]
        actions = [("firmware.update", "sys/chassis-%d/blade-%d"), ("bios.policy.modify", "org-root/bios-prof-%d-%d"),
                   ("service.profile.assoc", "org-root/ls-gpu-%d-%d"), ("kvm.session.open", "sys/rack-unit-%d/kvm-%d")]
        for ts in self.rand_minute_epochs(rng, 20):
            n = rng.choice(T.ALL_NODES)
            act, obj = rng.choice(actions)
            self.add("cisco:ucs:audit", ts, {"user": rng.choice(users), "action": act, "server": n, "ai_pod": T.pod_of(n),
                                             "object": obj % (rng.randint(1, 8), rng.randint(1, 8)), "severity": "low",
                                             "outcome": "success"})

    # ---- layer 2: Nexus anomalies, config, path-test excursion ----------------------
    def _anomaly(self, epoch, device, intf, peer, anomaly, util, sev, detail, flap_count=0):
        fabric = "aipod-" + device[:3]
        ev = {"device": device, "interface": intf, "peer": peer, "fabric": fabric, "ai_pod": fabric,
              "anomaly": anomaly, "utilization": util, "severity": sev, "source": "nexus", "detail": detail}
        if flap_count:
            ev["flap_count"] = flap_count
        self.add("cisco:nexus:anomaly", epoch, ev)

    def _network(self):
        a = self._anomaly
        a(self.t(11, 2, 8, 294), "lab-leaf-158", "Eth1/09", "lab-ucs-gpu-04", "optic rx power low", 38, "low",
          "optic rx power -9.8 dBm below warning threshold")
        a(self.t(13, 20, 33, 751), "dc2-leaf-207", "Eth1/03", "dc2-ucs-gpu-19", "crc_errors", 61, "medium",
          "crc_errors rising: 412 in 15 min")
        a(self.t(14, 38, 52, 440), "dc1-spine-02", "Eth2/05", "dc1-leaf-112", "ecn_marked_packets high", 94, "high",
          "ecn_marked_packets 18K/min after qos policy change on dc1-leaf-112")
        a(self.t(14, 41, 5, 873), "dc1-leaf-112", "Eth1/31", "dc1-ucs-gpu-21", "pfc_pause_storm", 97, "critical",
          "pfc pause storm: RoCE class no longer no-drop after qos policy change")
        a(self.t(14, 49, 31, 120), "dc1-leaf-112", "Eth1/14", "dc1-ucs-gpu-07", "link_flap", 12, "high",
          "link_flap x6 in 10 min", flap_count=6)
        self.add("cisco:nexus:config", self.t(14, 12, 19, 6), {
            "device": "dc1-leaf-112", "user": "netops-jrivera", "change": "qos policy", "severity": "medium",
            "diff_summary": "+policy-map type qos AI-ROCE: class cs3 set pause no-drop -> drop",
            "session_id": "vty-%d" % (100 + self.offset), "source": "nexus", "ai_pod": "aipod-dc1"})
        rng = self.rng("cisco:nexus:anomaly")
        # 12 more congested links (distinct, in the window, on dc1/dc2 links), 3 single flaps, filler crc/optic (low)
        pool = [l for l in T.LINKS if l[0] in ("dc1-leaf-113", "dc1-leaf-114", "dc2-leaf-204", "dc2-leaf-205", "dc1-spine-01")]
        picks = pick_distinct(rng, pool, 15)
        for k, (d, i, p, f, _) in enumerate(picks[:12]):
            ts = self.t(13, 0) + rng.random() * 7000
            typ = "congestion" if k % 3 else "pfc_pause_storm"
            a(ts, d, i, p, typ, rng.randint(90, 96), "medium", "%s: utilization above 90%% for 3 intervals" % typ)
        for (d, i, p, f, _) in picks[12:]:
            ts = self.t(0) + rng.random() * 86000
            a(ts, d, i, p, "link_flap", rng.randint(5, 30), "medium", "link_flap x1", flap_count=1)
        for ts in self.rand_minute_epochs(rng, 240):
            d, i, p, f, _ = rng.choice(T.LINKS)
            if rng.random() < 0.6:
                a(ts, d, i, p, "crc_errors", rng.randint(10, 70), "low", "crc_errors %d in 15 min" % rng.randint(3, 40))
            else:
                a(ts, d, i, p, "optic rx power low", rng.randint(5, 60), "low", "optic rx power %.1f dBm" % (-7.0 - rng.random() * 3))
        # routine config changes (low), 5/day
        rng = self.rng("cisco:nexus:config")
        for ts in self.rand_minute_epochs(rng, 5, lo_h=6, hi_h=22):
            d = rng.choice([l[0] for l in T.LINKS if l[4] == "server"])
            self.add("cisco:nexus:config", ts, {"device": d, "user": rng.choice(["netops-jrivera", "netops-asmith", "svc-netbox"]),
                                                "change": rng.choice(["interface description", "snmp community", "ntp server", "vlan add"]),
                                                "diff_summary": "routine change (ticket CHG%06d)" % rng.randint(1, 999999),
                                                "session_id": "vty-%d" % rng.randint(200, 900), "source": "nexus", "severity": "low",
                                                "ai_pod": "aipod-" + d[:3]})
        # path-test excursion row
        self.add("ai:path:test", self.t(13, 55, 47, 318), {
            "probe": "probe-dc1", "target": "api.model-provider.example", "latency_ms": 322.0, "baseline_ms": 182.0,
            "loss_pct": 0.2, "hops": 12, "slow_hop": 9, "slow_hop_delta_ms": 140, "source": "path_test", "severity": "medium",
            "detail": "latency +140 ms at hop 9 of 12"})

    # ---- layer 3: kube events, job lifecycle ---------------------------------------
    def _kube(self, epoch, pod, workload, kind, ns, node, reason, message, impact, restart_count=0, sev="low", typ="Warning"):
        self.add("kube:events", epoch, {"reason": reason, "namespace": ns, "pod": pod, "workload": workload, "kind": kind,
                                        "node": node, "message": message, "impact": impact, "restart_count": restart_count,
                                        "type": typ, "severity": sev})

    def _job(self, epoch, job_id, kind, state, node, reason, gpu_hours, gpus, queue_wait_s, workload, impact=None, sev="low"):
        ev = {"job_id": job_id, "kind": kind, "state": state, "node": node, "ai_pod": T.pod_of(node), "gpu_hours": gpu_hours,
              "gpus": gpus, "reason": reason, "queue_wait_s": queue_wait_s, "workload": workload, "namespace": "mlops",
              "severity": sev}
        if impact:
            ev["impact"] = impact
        self.add("ai:job:lifecycle", epoch, ev)

    def _platform(self):
        k = self._kube
        k(self.t(7, 31, 27, 650), "coder-v9-66c1e", "coder-v9", "inference", "inference", "dc2-ucs-gpu-02", "CUDA_OOM",
          "container runtime: CUDA out of memory, pod restarted", "restarted x1", 1, "medium")
        k(self.t(14, 44, 10, 310), "vector-db-2", "vector-db-2", "data service", "retrieval", "dc1-ucs-cpu-03",
          "slow queries p95 2.4 s", "vector-db-2 query latency p95 2.4 s (threshold 500 ms)", "retrieval timeouts", 0, "high")
        for (s, ms) in [(58, 877), (63, 210), (69, 442)]:
            k(self.t(14, 49, s % 60, ms) + (60 if s >= 60 else 0), "med-advisor-v41-5b21d", "med-advisor-v41", "inference", "inference",
              "dc1-ucs-gpu-07", "OOMKilled", "container med-advisor exceeded memory limit; killed", "restarted x3", 1, "high")
        k(self.t(14, 50, 12, 204), "med-advisor-v41-7c9f4", "med-advisor-v41", "inference", "inference", "dc1-ucs-gpu-07",
          "NodeNotReady", "node dc1-ucs-gpu-07 NotReady: GPU5 fallen off bus; pod evicted", "replica lost, 47 min degraded", 1, "high")
        j = self._job
        j(self.t(2, 57, 15, 412), "eval-coding-v41-0081", "evaluation", "preempted", "lab-ucs-gpu-12", "PREEMPTED", 14.5, 8, 320,
          "eval-suite-v41", "rescheduled", "medium")
        j(self.t(4, 12, 49, 993), "ft-claims-v13-s002", "fine-tuning", "failed", "lab-ucs-gpu-09", "CHECKPOINT_IO_STALL", 512.0, 40, 1800,
          "ft-claims-v13", "512 GPU-hours lost", "medium")
        j(self.t(9, 48, 3, 29), "eval-reasoning-v41-0088", "evaluation", "failed", "lab-ucs-gpu-04", "HARNESS_EXIT_1", 6.2, 8, 410,
          "eval-suite-v41", "rerun queued", "medium")
        rng = self.rng("kube:events")
        # background restarts: OOMKilled 12, CrashLoopBackOff 10, NodeNotReady 7, Evicted 4 (= 33, + 4 scripted = 37)
        pods = [("claims-v12", "inference", "aipod-dc2"), ("coder-v9", "inference", "aipod-dc1"), ("rag-embed-v7", "inference", "aipod-dc1"),
                ("policy-qa-v3", "inference", "aipod-dc2"), ("med-advisor-v40", "inference", "aipod-dc2"), ("vector-db-1", "retrieval", "cpu"),
                ("eval-harness", "mlops", "aipod-lab"), ("ft-runner", "mlops", "aipod-lab")]
        used = set()
        for reason, n in [("OOMKilled", 12), ("CrashLoopBackOff", 10), ("NodeNotReady", 7), ("Evicted", 4)]:
            for ts in self.rand_minute_epochs(rng, n):
                wl, ns, pod_hint = rng.choice(pods)
                while True:
                    suffix = hex_id(rng, 5)
                    if (wl, suffix) not in used:
                        used.add((wl, suffix))
                        break
                node = rng.choice(T.CPU_NODES) if pod_hint == "cpu" else rng.choice([x for x in T.GPU_NODES if T.pod_of(x) == pod_hint])
                kind = "data service" if ns == "retrieval" else ("evaluation" if wl == "eval-harness" else ("fine-tuning" if wl == "ft-runner" else "inference"))
                k(ts, "%s-%s" % (wl, suffix), wl, kind, ns, node, reason, "%s (restart_count=1)" % reason, "restarted x1", 1, "low")
        for ts in self.rand_minute_epochs(rng, 600):
            wl, ns, pod_hint = rng.choice(pods)
            reason = rng.choice(["Scheduled", "Pulled", "Pulled", "BackOff"])
            node = rng.choice(T.CPU_NODES) if pod_hint == "cpu" else rng.choice([x for x in T.GPU_NODES if T.pod_of(x) == pod_hint])
            k(ts, "%s-%s" % (wl, hex_id(rng, 5)), wl, "inference" if ns == "inference" else "data service", ns, node, reason,
              "%s: routine scheduler event" % reason, "none", 0, "low", "Normal" if reason != "BackOff" else "Warning")
        # job lifecycle filler: ~20 jobs/day x ~7 states + one unique failure per day
        rng = self.rng("ai:job:lifecycle")
        lab = [n for n in T.GPU_NODES if n.startswith("lab")]
        states = ["queued", "running", "checkpointing", "running", "checkpointing", "running", "completed"]
        for jn in range(20):
            kind = "fine-tuning" if jn % 4 == 0 else "evaluation"
            wl = "ft-claims-v13" if kind == "fine-tuning" else rng.choice(["eval-suite-v41", "eval-suite-c13"])
            jid = "%s-%s-%04d" % ("ft-claims-v13" if kind == "fine-tuning" else "eval-%s-v41" % rng.choice(["safety", "reasoning", "coding"]),
                                  self.day.strftime("%m%d"), rng.randint(100, 999))
            node = rng.choice(lab)
            t0 = self.t(0) + rng.random() * 70000
            gpus = 40 if kind == "fine-tuning" else 8
            for si, st in enumerate(states):
                j(t0 + si * rng.randint(600, 2400), jid, kind, st, node, None, round(gpus * si * 0.4, 1), gpus, rng.randint(60, 1500), wl)
        jid = "eval-safety-v41-%s-%04d" % (self.day.strftime("%m%d"), rng.randint(100, 999))
        node = rng.choice(lab)
        t0 = self.t(0) + rng.random() * 70000
        j(t0, jid, "evaluation", "running", node, None, 0.0, 8, 200, "eval-suite-v41")
        j(t0 + 1800, jid, "evaluation", "failed", node, "CUDA_OOM", 4.0, 8, 200, "eval-suite-v41", "rerun queued", "medium")

    # ---- layer 5: evaluation runs ----------------------------------------------------
    def _evals(self):
        rng = self.rng("ai:eval:run")
        for (doff, h, m, s, ms, mv, suite, pr, base, delta, status, ev_id, cyc, qw) in MOCK_EVALS:
            model, version = mv.rsplit("-", 1)
            self.add("ai:eval:run", self.t(h, m, s, ms), {
                "job_id": ev_id, "model_version": mv, "model": model, "version": version, "suite": suite, "pass_rate": pr,
                "baseline_pass_rate": base, "delta_vs_baseline": delta, "status": status, "evidence": ev_id,
                "cycle_time_h": cyc, "queue_wait_h": qw, "cases": rng.choice([1200, 1800, 2400, 3200]),
                "node": rng.choice([n for n in T.GPU_NODES if n.startswith("lab")]),
                "severity": "high" if status == "regression" else ("medium" if status == "watch" else "low")})

    # ---- security: raw sims, findings ------------------------------------------------
    def _finding(self, epoch, fid, user, src, action, obj, risk, disp, cat, mitre, owner, rule, status="open"):
        self.add("ai:security:finding", epoch, {
            "finding_id": fid, "user": user, "src": src, "action": action, "object": obj, "risk_score": risk, "rule": rule,
            "mitre_technique": mitre, "status": status, "triage_disposition": disp, "owner": owner, "category": cat,
            "environment": "production", "scoreboard": "security",
            "severity": "critical" if risk >= 80 else ("high" if risk >= 60 else "medium")})

    def _sim(self, st, epoch, user, src, action, obj, **extra):
        ev = {"user": user, "src": src, "action": action, "object": obj, "environment": "production", "outcome": "success",
              "severity": "low"}
        if st == "aws:cloudtrail:sim":
            ev.update({"bytes_out": 0, "asn": 16509, "asn_new": False, "first_seen": False, "region": "us-west-2"})
        elif st == "k8s:audit:sim":
            ev.update({"namespace": "inference", "off_hours": False, "cluster": "aipod-dc1"})
        else:
            ev.update({"first_seen": False})
        ev.update(extra)
        self.add(st, epoch, ev)

    def _security(self):
        day_tag = self.day.strftime("%Y%m%d")
        if self.offset == 0:
            for n, (h, m, s, ms, user, src, action, obj, risk, disp, cat, mitre, owner, rule, sim_st) in enumerate(FINDINGS):
                ts = self.t(h, m, s, ms)
                self._finding(ts, "F-%s-%04d" % (day_tag, 7 - n), user, src, action, obj, risk, disp, cat, mitre, owner, rule)
                if sim_st == "aws:cloudtrail:sim" and "weights" in obj:
                    self._sim(sim_st, ts - 0.4, user, src, "s3:GetObject", obj, first_seen=True, bytes_out=2147483648, severity="critical")
                elif sim_st == "aws:cloudtrail:sim":
                    self._sim(sim_st, ts - 0.4, user, src, "s3:GetObject", obj, bytes_out=44023414784, asn=396982, asn_new=True, severity="high")
                elif sim_st == "k8s:audit:sim":
                    self._sim(sim_st, ts - 0.4, user, src, "kubectl exec", obj, off_hours=True, severity="high")
                elif sim_st == "iam:sim" and "assume_role" in action:
                    self._sim(sim_st, ts - 0.4, user, src, "assume_role", obj, first_seen=True, severity="high")
                elif sim_st == "iam:sim":
                    self._sim(sim_st, ts - 0.4, user, src, "api_key.created", obj, first_seen=True, severity="medium")
        elif self.offset in FINDINGS_BY_OFFSET:
            rng = self.rng("ai:security:finding")
            n = FINDINGS_BY_OFFSET[self.offset]
            # category quotas across D-6..D-1: model_asset_access 6, credential_misuse 1, data_movement 11, rest off_hours_admin
            quota = {6: ["model_asset_access", "data_movement", "data_movement", "off_hours_admin", "off_hours_admin"],
                     5: ["model_asset_access", "data_movement", "off_hours_admin", "off_hours_admin"],
                     4: ["model_asset_access", "data_movement", "data_movement", "off_hours_admin", "off_hours_admin"],
                     3: ["model_asset_access", "data_movement", "data_movement", "off_hours_admin", "off_hours_admin"],
                     2: ["model_asset_access", "credential_misuse", "data_movement", "data_movement", "off_hours_admin", "off_hours_admin", "off_hours_admin"],
                     1: ["model_asset_access", "data_movement", "data_movement", "off_hours_admin"] + ["off_hours_admin"] * 11}[self.offset]
            assert len(quota) == n
            open_quota = {6: 2, 5: 2, 4: 2, 3: 2, 2: 3, 1: 4}[self.offset]   # 15 open on prior days
            times = sorted(self.rand_minute_epochs(rng, n))
            for k, (ts, cat) in enumerate(zip(times, quota)):
                user = rng.choice(["svc-mlops-ci", "svc-eval-runner", "svc-registry-sync", "d.park@buttercupgames.com", "r.nair@buttercupgames.com"])
                src = "10.%d.%d.%d" % (rng.randint(10, 60), rng.randint(1, 250), rng.randint(2, 250))
                if cat == "model_asset_access":
                    action, obj, mitre, rule = "s3:GetObject (first seen)", "weights/%s/" % rng.choice(["claims-v12", "coder-v9", "med-advisor-v40"]), "T1530", FINDINGS[0][13]
                    self._sim("aws:cloudtrail:sim", ts - 0.4, user, src, "s3:GetObject", obj, first_seen=True, bytes_out=rng.randint(10 ** 8, 3 * 10 ** 9), severity="high")
                elif cat == "credential_misuse":
                    action, obj, mitre, rule = "assume_role (new principal)", "role/registry-writer", "T1078", FINDINGS[1][13]
                    self._sim("iam:sim", ts - 0.4, user, src, "assume_role", obj, first_seen=True, severity="high")
                elif cat == "data_movement":
                    gb = rng.randint(11, 38)
                    action, obj, mitre, rule = "egress %d GB to new ASN" % gb, "bucket/%s" % rng.choice(["rag-corpus-clinical", "eval-artifacts", "ft-datasets"]), "T1567", FINDINGS[3][13]
                    self._sim("aws:cloudtrail:sim", ts - 0.4, user, src, "s3:GetObject", obj, bytes_out=gb * 1073741824, asn=rng.choice([396982, 14618, 13335]), asn_new=True, severity="high")
                else:
                    action, obj, mitre, rule = "kubectl exec (off-hours)", "pod/%s-%s" % (rng.choice(["claims-v12", "coder-v9"]), hex_id(rng, 5)), "T1078", FINDINGS[1][13]
                    self._sim("k8s:audit:sim", ts - 0.4, user, src, "kubectl exec", obj, off_hours=True, severity="medium")
                risk = {"model_asset_access": 80, "credential_misuse": 60, "data_movement": 75, "off_hours_admin": 45}[cat]
                status = "open" if k < open_quota else "closed"
                disp = "needs_review" if status == "open" else rng.choice(["benign", "true_positive"])
                self._finding(ts, "F-%s-%04d" % (day_tag, k + 1), user, src, action, obj, risk, disp, cat, mitre,
                              "soc-tier2" if risk >= 60 else "soc-tier1", rule, status)
        # background raw sims: cloudtrail 1,500, k8s 800, iam 300 (benign)
        rng = self.rng("security-sims")
        svc = ["svc-mlops-ci", "svc-eval-runner", "svc-registry-sync", "svc-rag-indexer", "svc-serving-dc1", "svc-serving-dc2"]
        people = ["d.park@buttercupgames.com", "r.nair@buttercupgames.com", "l.moreau@buttercupgames.com", "t.oyelaran@buttercupgames.com"]
        for ts in self.rand_minute_epochs(rng, 1500):
            u = rng.choice(svc)
            self._sim("aws:cloudtrail:sim", ts, u, "10.42.%d.%d" % (rng.randint(10, 40), rng.randint(2, 250)),
                      rng.choice(["s3:GetObject", "s3:GetObject", "s3:PutObject", "s3:ListBucket"]),
                      rng.choice(["bucket/rag-corpus-clinical/chunks/%05d" % rng.randint(0, 99999), "bucket/eval-artifacts/run-%04d" % rng.randint(0, 9999),
                                  "bucket/ft-datasets/claims/part-%03d" % rng.randint(0, 999), "weights/med-advisor-v41/shard-%02d" % rng.randint(0, 31)]),
                      bytes_out=rng.randint(10 ** 5, 5 * 10 ** 8))
        for ts in self.rand_minute_epochs(rng, 800, lo_h=7, hi_h=20):
            self._sim("k8s:audit:sim", ts, rng.choice(people + svc), "10.18.%d.%d" % (rng.randint(1, 8), rng.randint(2, 250)),
                      rng.choice(["kubectl get", "kubectl logs", "kubectl describe", "kubectl apply", "kubectl exec"]),
                      "pod/%s-%s" % (rng.choice(["claims-v12", "coder-v9", "med-advisor-v41", "rag-embed-v7"]), hex_id(rng, 5)),
                      namespace=rng.choice(["inference", "retrieval", "mlops"]))
        for ts in self.rand_minute_epochs(rng, 300, lo_h=6, hi_h=22):
            self._sim("iam:sim", ts, rng.choice(people + svc), "10.18.%d.%d" % (rng.randint(1, 8), rng.randint(2, 250)),
                      rng.choice(["assume_role", "assume_role", "login", "api_key.rotated"]),
                      rng.choice(["role/eval-runner", "role/serving-reader", "role/registry-reader", "model-registry/prod"]))

    # ---- layer 4: guardrails + request singletons/detail rows ----------------------
    def _guardrails_and_requests(self):
        rng = self.rng("gen_ai:guardrail")
        inj = INJECTIONS_BY_OFFSET.get(self.offset, 30)
        techniques = technique_sequence(self.ctx.seed)
        if 0 <= self.offset <= 6:
            start = sum(INJECTIONS_BY_OFFSET[o] for o in range(6, self.offset, -1))
            tech_iter = iter(techniques[start:start + inj])
        else:
            tech_iter = iter(rng.choices([t for t, _ in T.INJECTION_TECHNIQUES], [w for _, w in T.INJECTION_TECHNIQUES], k=inj))
        n_halluc, n_pii = 1250, 400
        n_policy = 1906 - n_halluc - n_pii - inj
        # scripted prompt-injection campaign: 21 on claims-agent 08:20-08:49, then 37 on medadvice-chat 13:20-13:58 (+1 deck rowckup)
        camp = [(self.t(8, 20) + k * (29 * 60.0 / 21), "claims-agent", "claims-v12") for k in range(21)]
        camp += [(self.t(13, 20) + k * (38 * 60.0 / 37), "medadvice-chat", "med-advisor-v41") for k in range(37)]
        extra = inj - 58
        if extra > 0:
            camp += [(ts, "claims-agent", "claims-v12") for ts in self.rand_minute_epochs(rng, extra)]
        camp = camp[:max(inj - 1, 0)]
        for k, (ts, app, model) in enumerate(camp):
            tid = self.ctx.tid(self.day, "inj-%d" % k)
            self._guard_pair(ts, tid, app, model, "blocked", "prompt_injection", next(tech_iter, "instruction_override"),
                             "203.0.113.10", "probe@example.com", rng)
        # hallucination flags (weighted into the incident window on medadvice), pii, policy/toxicity
        w_h = lambda i: diurnal(i / 60.0) * (1.0 + 2.5 * ramp(i / 60.0))
        for k, ts in enumerate(self.rand_minute_epochs(rng, n_halluc - 1, w_h)):
            app, model = ("medadvice-chat", "med-advisor-v41") if rng.random() < 0.7 else rng.choice(
                [("claims-agent", "claims-v12"), ("code-assist", "coder-v9"), ("medadvice-chat", "provider-api-large")])
            self._guard_pair(ts, self.ctx.tid(self.day, "hal-%d" % k), app, model, "flagged", "hallucination", None, None, None, rng)
        for k, ts in enumerate(self.rand_minute_epochs(rng, n_pii - 1)):
            app, model = rng.choice([("medadvice-chat", "med-advisor-v41"), ("claims-agent", "claims-v12"), ("search-rag", "rag-embed-v7")])
            self._guard_pair(ts, self.ctx.tid(self.day, "pii-%d" % k), app, model, "blocked", "pii", None, None, None, rng)
        for k, ts in enumerate(self.rand_minute_epochs(rng, n_policy)):
            app, model = rng.choice([("medadvice-chat", "med-advisor-v41"), ("claims-agent", "claims-v12"), ("code-assist", "coder-v9")])
            cat = "policy" if rng.random() < 0.6 else "toxicity"
            self._guard_pair(ts, self.ctx.tid(self.day, "pol-%d" % k), app, model, rng.choice(["flagged", "blocked"]), cat, None, None, None, rng)
        # error/timeout singletons: 896/day, 0.05% baseline -> 0.6% in the window
        w_e = lambda i: diurnal(i / 60.0) * (1.0 + 11.0 * ramp(i / 60.0))
        for k, ts in enumerate(self.rand_minute_epochs(rng, 896, w_e)):
            app, model, system, _, wl = rng.choice(T.STREAMS)
            status = "timeout" if (ramp(local_hour(self.ctx.tz, ts)) > 0 and rng.random() < 0.6) else "error"
            ev = request_event(rng, ts, app, model, system, wl, self.ctx.tid(self.day, "err-%d" % k), ramp(local_hour(self.ctx.tz, ts)),
                               status=status, request_count=1, row_kind="detail")
            self.add("gen_ai:request", ts, ev)
        # deck detail rows (7) + the loop run's own request
        for k, (h, m, s, ms, app, model, lit, ttft, retr, guard) in enumerate(MOCK_REQUESTS):
            ts = self.t(h, m, s, ms)
            tid = self.ctx.tid(self.day, "mock-req-%d" % k, lit)
            system = "provider" if model == "provider-api-large" else "self-hosted"
            wl = {"med-advisor-v41": "serve-med-advisor-v41", "claims-v12": "serve-claims-v12", "rag-embed-v7": "serve-rag-embed-v7",
                  "coder-v9": "serve-coder-v9"}[model]
            ev = request_event(rng, ts, app, model, system, wl, tid, 1.0, request_count=1, row_kind="detail")
            ev["ttft_ms"] = ttft
            ev["retrieval_ms"] = retr if retr is not None else None
            ev["guardrail"] = guard
            ev["quality.hallucination_flag"] = 1 if guard == "flagged:hallucination" else 0
            ev["hallucination_count"] = ev["quality.hallucination_flag"]
            ev["severity"] = "high" if guard != "pass" else "low"
            self.add("gen_ai:request", ts, ev)
            if guard != "pass":
                verdict, cat = guard.split(":")
                self._guard_event(ts + 0.05, tid, app, model, verdict, cat, next(tech_iter, "instruction_override") if cat == "prompt_injection" else None,
                                  "203.0.113.10" if cat == "prompt_injection" else None, "probe@example.com" if cat == "prompt_injection" else None, rng)
        ts = self.t(14, 57, 10, 120)
        ev = request_event(rng, ts, "claims-agent", "claims-v12", "self-hosted", "serve-claims-v12",
                           self.ctx.tid(self.day, "mock-run-0", MOCK_RUNS[0][5]), 1.0, request_count=1, row_kind="detail")
        self.add("gen_ai:request", ts, ev)

    def _guard_event(self, ts, tid, app, model, verdict, cat, technique, src, user, rng):
        ev = {"trace_id": tid, "gen_ai.app": app, "gen_ai.request.model": model, "verdict": verdict, "category": cat,
              "src": src or "10.%d.%d.%d" % (rng.randint(20, 60), rng.randint(1, 250), rng.randint(2, 250)),
              "user": user or "u_" + hex_id(rng, 12),
              "action_taken": "blocked_response" if verdict == "blocked" else "flag_for_review",
              "severity": "high" if cat == "prompt_injection" else ("medium" if verdict == "blocked" else "low")}
        if technique:
            ev["technique"] = technique
        self.add("gen_ai:guardrail", ts, ev)

    def _guard_pair(self, ts, tid, app, model, verdict, cat, technique, src, user, rng):
        """A guardrail event and the singleton request (request_count=1) that produced it."""
        self._guard_event(ts, tid, app, model, verdict, cat, technique, src, user, rng)
        system = "provider" if model == "provider-api-large" else "self-hosted"
        wl = {"med-advisor-v41": "serve-med-advisor-v41", "claims-v12": "serve-claims-v12", "rag-embed-v7": "serve-rag-embed-v7",
              "coder-v9": "serve-coder-v9", "med-advisor-v40": "serve-med-advisor-v40"}.get(model)
        ev = request_event(rng, ts - 0.02, app, model, system, wl, tid, ramp(local_hour(self.ctx.tz, ts)), request_count=1, row_kind="detail")
        ev["guardrail"] = "%s:%s" % (verdict, cat)
        ev["quality.hallucination_flag"] = 1 if cat == "hallucination" else 0
        ev["hallucination_count"] = ev["quality.hallucination_flag"]
        ev["severity"] = "high" if cat == "prompt_injection" else "medium"
        ev["user_id"] = "u_" + hex_id(rng, 12)
        self.add("gen_ai:request", ts - 0.02, ev)

    # ---- layer 6: scripted agent runs (loops + deck rows) --------------------------
    def _agents(self):
        rng = self.rng("gen_ai:agent:run")
        loops = sorted(self.t(13, 0) + rng.random() * (116 * 60.0) for _ in range(36))
        for k, ts in enumerate(loops):
            steps = rng.randint(31, 44)
            calls = steps - rng.randint(4, 8)
            top = int(calls * rng.uniform(0.7, 0.85))
            errs = rng.randint(9, 15)
            tokens = int(steps * rng.uniform(3900, 5200))
            self._agent_run(ts, self.ctx.tid(self.day, "loop-%d" % k), "claims-intake-agent", steps, calls, "loop_stopped", tokens,
                            round(tokens * 1.468e-5, 2), "claims_api", top, errs, rng, with_steps=True)
        for k, (h, m, s, ms, agent, lit, steps, calls, outcome, tokens, cost, top, topn) in enumerate(MOCK_RUNS):
            errs = 31 if outcome == "loop_stopped" else (2 if outcome == "escalated_to_human" else 0)
            self._agent_run(self.t(h, m, s, ms), self.ctx.tid(self.day, "mock-run-%d" % k, lit), agent, steps, calls, outcome, tokens,
                            cost, top, topn, errs, rng, with_steps=True)

    def _agent_run(self, ts, tid, agent, steps, calls, outcome, tokens, cost, top, topn, errs, rng, with_steps):
        share, pct, model, bu = T.AGENTS[agent]
        duration = int(steps * rng.uniform(1800, 3200))
        tools_used = [top] + [t for t in T.TOOLS if t != top][:2]
        run = {"gen_ai.agent.name": agent, "trace_id": tid, "session_id": hex_id(rng, 16), "steps": steps, "tool_calls": calls,
               "tool_call_failures": errs, "outcome": outcome, "tokens": tokens, "cost_usd": cost, "duration_ms": duration,
               "gen_ai.request.model": model, "business_unit": bu, "tools_used": tools_used, "top_tool": top, "top_tool_calls": topn,
               "severity": "high" if outcome == "loop_stopped" else ("medium" if outcome in ("escalated_to_human", "blocked:guardrail") else "low")}
        self.add("gen_ai:agent:run", ts, run)
        if not with_steps:
            return
        # steps: `calls` execute_tool rows (top tool x topn first, errors on the top tool), remaining rows are chat
        t0 = ts - duration / 1000.0
        tool_list = [top] * topn + [t for t in (tools_used[1:] * calls)][:calls - topn]
        err_left = errs
        chat_slots = set(pick_distinct(rng, range(steps), steps - calls)) if steps > calls else set()
        ti = 0
        for n in range(steps):
            st = t0 + duration / 1000.0 * (n + 1) / steps
            ev = {"gen_ai.agent.name": agent, "trace_id": tid, "step_no": n + 1, "duration_ms": rng.randint(400, 2600),
                  "tokens": max(50, int(tokens / steps * rng.uniform(0.6, 1.4))), "status": "ok", "error_type": None}
            if n in chat_slots or ti >= len(tool_list):
                ev["gen_ai.operation.name"] = "chat"
                ev["gen_ai.tool.name"] = None
            else:
                ev["gen_ai.operation.name"] = "execute_tool"
                ev["gen_ai.tool.name"] = tool_list[ti]
                ti += 1
                if err_left > 0 and ev["gen_ai.tool.name"] == top:
                    ev["status"] = "error"
                    ev["error_type"] = "http_503" if top == "claims_api" else rng.choice(["timeout", "schema_error"])
                    err_left -= 1
            ev["severity"] = "medium" if ev["status"] == "error" else "low"
            self.add("gen_ai:agent:step", st, ev)

    def scripted_step_errors(self):
        return sum(ev.get("tool_call_failures", 0) for _, ev in self.events.get("gen_ai:agent:run", []))

    # ---- cost rows (stamped 23:59:59 local) and UCS inventory (06:00) --------------------
    def _cost(self):
        ts = self.t(23, 59, 59)
        rng = self.rng("ai:cost")
        day = self.day.isoformat()
        for wl, (bu, cc, kind, pod, weekly, util7, util24) in T.WORKLOADS.items():
            gh = round(weekly / 7.0, 1)
            if wl == "ft-claims-v13" and self.offset == 1:
                gh = round(gh * 1.3, 1)   # rerun after the CHECKPOINT_IO_STALL failure (daily spend spike)
            self.add("ai:cost:daily", ts, {"day": day, "workload": wl, "business_unit": bu, "cost_center": cc, "kind": kind, "ai_pod": pod,
                                           "gpu_hours": gh, "idle_gpu_hours": 0.0, "avg_gpu_util": float(util7),
                                           "usd_per_gpu_hour": T.USD_PER_GPU_HOUR, "est_cost_usd": round(gh * T.USD_PER_GPU_HOUR, 2)})
        for pod in T.PODS:
            idle = sum(1 for n, g, w, k in T.GPU_ROWS if w == "unallocated" and T.pod_of(n) == pod) * 24.0
            self.add("ai:cost:daily", ts, {"day": day, "workload": "unallocated", "business_unit": "platform", "cost_center": "CC-0000",
                                           "kind": "unallocated", "ai_pod": pod, "gpu_hours": 0.0, "idle_gpu_hours": idle, "avg_gpu_util": 0.0,
                                           "usd_per_gpu_hour": T.USD_PER_GPU_HOUR, "est_cost_usd": 0.0})
        total_sh = 1200.0
        jit = {m: rng.uniform(0.85, 1.15) for m in T.SELF_HOSTED_TOKEN_MIX}
        raw = {m: total_sh * mix * 1e6 / 2140.0 * jit[m] for m, mix in T.SELF_HOSTED_TOKEN_MIX.items()}
        scale = (total_sh * 1e6 / 2140.0) / sum(raw.values())
        for m, mix in T.SELF_HOSTED_TOKEN_MIX.items():
            tm = round(total_sh * mix, 3)
            self.add("ai:cost:tokens", ts, {"day": day, "model": m, "gen_ai.system": "self-hosted", "tokens_millions": tm,
                                            "cost_per_1m_tokens": T.SELF_HOSTED_RATE[m], "cost_usd": round(tm * T.SELF_HOSTED_RATE[m], 2),
                                            "gpu_seconds": round(raw[m] * scale, 1)})
        self.add("ai:cost:tokens", ts, {"day": day, "model": "provider-api-large", "gen_ai.system": "provider", "tokens_millions": 10100.0,
                                        "cost_per_1m_tokens": T.PROVIDER_RATE, "cost_usd": 30300.0, "gpu_seconds": 0.0})
        ts = self.t(6, 0)
        for n in T.ALL_NODES:
            leaf, port = T.NODE_LEAF[n]
            gpu = n.split("-")[2] == "gpu"
            self.add("cisco:ucs:inventory", ts, {"server": n, "ai_pod": T.pod_of(n), "model": "UCS C885A M8" if gpu else "UCS C225 M8",
                                                 "gpu_model": "H100-SXM-80GB" if gpu else "none", "gpu_count": 8 if gpu else 0,
                                                 "firmware": "4.3(2b)", "leaf_switch": leaf, "leaf_port": port, "severity": "low"})


def technique_sequence(seed):
    seq = []
    for t, w in T.INJECTION_TECHNIQUES:
        seq += [t] * w
    rng_for(seed, "techniques").shuffle(seq)
    return seq


SINGLETONS_PER_DAY = (1906 - 3) + 896 + 7 + 1   # guardrail pairs + error rows + deck rows + loop-run request


def request_event(rng, ts, app, model, system, workload, tid, r, status="ok", request_count=1, row_kind="minute", tuned=None):
    """One gen_ai:request row (aggregate row or singleton). `r` is the incident ramp at `ts`."""
    from . import calib as C
    tuned = tuned or C.TUNED
    hot = (app == "medadvice-chat" and model != "provider-api-large")
    key = "provider" if system == "provider" else app
    if hot and r > 0:
        ttft = lognormal_(rng, 480.0 + 820.0 * r, 0.06)
    else:
        ttft = lognormal_(rng, C.TTFT_MEDIAN[key], tuned["ttft_sigma"])
    ttft = int(round(ttft))
    if app in ("medadvice-chat", "search-rag", "claims-agent"):
        h = _hour_of(ts)
        if hot and r > 0 and h >= 14.0 + 44.0 / 60 and rng.random() < 0.35:
            retrieval = "timeout"
        elif hot and r > 0:
            retrieval = int(round(lognormal_(rng, 1200 + 900 * r, 0.12)))
        else:
            retrieval = int(round(lognormal_(rng, 42.0, 0.25)))
    else:
        retrieval = None
    tin, tout = C.TOKENS_IN[model], C.TOKENS_OUT[model]
    in_tok = int(request_count * tin * rng.uniform(0.9, 1.1))
    out_tok = int(request_count * tout * rng.uniform(0.9, 1.1))
    if model == "med-advisor-v41":
        p = tuned["halluc_med"] * (1.0 + (40.0 / 15.0 - 1.0) * r)
    else:
        p = C.HALLUC_BASE[model]
    hcount = int(request_count * p + rng.random())
    if status != "ok":
        hcount = 0
    ground = C.GROUND_BASE[model] - (1.9 * r if model == "med-advisor-v41" else 0.0) + rng.gauss(0, 0.3)
    safety = (tuned["safety_med"] if model == "med-advisor-v41" else C.SAFETY_BASE[model]) - (0.35 * r if model == "med-advisor-v41" else 0.0) + rng.gauss(0, 0.08)
    bu, cc = T.APPS[app]
    if workload:
        nodes = [n for n, g, w, k in T.GPU_ROWS if w == workload]
        node = nodes[rng.randrange(len(nodes))] if nodes else None
    else:
        node = "provider-edge"
    cost = round((in_tok + out_tok) * C.PROVIDER_USD_PER_TOKEN, 4) if system == "provider" else 0.0
    return {
        "gen_ai.app": app, "gen_ai.request.model": model, "gen_ai.system": system,
        "gen_ai.usage.input_tokens": in_tok, "gen_ai.usage.output_tokens": out_tok,
        "trace_id": tid, "session_id": hex_id(rng, 16), "user_id": "u_" + hex_id(rng, 12),
        "ttft_ms": ttft, "latency_ms": ttft + int(tout * 9 * rng.uniform(0.8, 1.2)) + (2000 if retrieval == "timeout" else 0),
        "retrieval_ms": retrieval, "status": status, "guardrail": "pass", "cost_usd": cost,
        "quality.hallucination_flag": 1 if hcount > 0 else 0, "hallucination_count": hcount,
        "quality.groundedness": round(max(80.0, min(100.0, ground)), 2),
        "quality.safety_score": round(max(95.0, min(100.0, safety)), 2),
        "business_unit": bu, "cost_center": cc, "node": node, "request_count": request_count, "row_kind": row_kind,
        "prompt_hash": hex_id(rng, 16), "prompt_len": rng.randint(40, 900),
        "severity": "low" if status == "ok" else "medium",
    }


def lognormal_(rng, median, sigma):
    import math
    return median * math.exp(rng.gauss(0.0, sigma))


_HOUR_TZ = [None]


def _hour_of(ts):
    return local_hour(_HOUR_TZ[0], ts)
