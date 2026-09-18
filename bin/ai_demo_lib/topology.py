"""Static estate: AI PODs, nodes, GPU allocation, fabric link plan, apps, agents."""

HOST = "ai-demo-generator"
SOURCE = "ai_demo_generator"
USD_PER_GPU_HOUR = 2.40

PODS = ["aipod-dc1", "aipod-dc2", "aipod-lab"]
POD_PREFIX = {"aipod-dc1": "dc1", "aipod-dc2": "dc2", "aipod-lab": "lab"}

# workload -> (business_unit, cost_center, kind, ai_pod, weekly_gpu_hours, avg_util_7d, avg_util_24h)
WORKLOADS = {
    "serve-med-advisor-v41": ("customer-care", "CC-5102", "inference", "aipod-dc1", 21504, 58, 62),
    "serve-claims-v12": ("claims", "CC-4523", "inference", "aipod-dc2", 13440, 63, 66),
    "serve-coder-v9": ("engineering", "CC-6010", "inference", "aipod-dc1", 8064, 44, 48),
    "ft-claims-v13": ("data-science", "CC-4490", "fine-tuning", "aipod-lab", 6720, 81, 84),
    "eval-suite-v41": ("data-science", "CC-4490", "evaluation", "aipod-lab", 3072, 38, 40),
    "serve-rag-embed-v7": ("customer-care", "CC-5102", "inference", "aipod-dc1", 2688, 71, 74),
    "eval-suite-c13": ("data-science", "CC-4490", "evaluation", "aipod-lab", 1024, 41, 43),
    # small dc2 workloads (12,432 GPU-h/week together)
    "serve-med-advisor-v40": ("customer-care", "CC-5102", "inference", "aipod-dc2", 5376, 55, 58),
    "serve-policy-qa-v3": ("claims", "CC-4523", "inference", "aipod-dc2", 4032, 55, 58),
    "dev-notebooks": ("engineering", "CC-6010", "inference", "aipod-dc2", 3024, 55, 58),
}
SPEC_WORKLOADS = list(WORKLOADS)[:7]


def _gpus(node, lo=0, hi=8):
    return [(node, "GPU%d" % g) for g in range(lo, hi)]


def _build_allocation():
    """Return {(node, gpu): workload} for all 512 GPUs; 410 allocated, 102 unallocated."""
    alloc = {}

    def put(nodes, wl, lo=0, hi=8):
        for n in nodes:
            for k in _gpus(n, lo, hi):
                alloc[k] = wl
    dc1 = ["dc1-ucs-gpu-%02d" % i for i in range(1, 25)]
    dc2 = ["dc2-ucs-gpu-%02d" % i for i in range(1, 25)]
    lab = ["lab-ucs-gpu-%02d" % i for i in range(1, 17)]
    put(dc1[0:16], "serve-med-advisor-v41")      # 128
    put(dc1[16:22], "serve-coder-v9")             # 48
    put(dc1[22:24], "serve-rag-embed-v7")         # 16
    put(dc2[0:10], "serve-claims-v12")            # 80
    put(dc2[10:14], "serve-med-advisor-v40")      # 32
    put(dc2[14:17], "serve-policy-qa-v3")         # 24
    put(dc2[17:19], "dev-notebooks")              # 16
    put(dc2[19:20], "dev-notebooks", 0, 2)        # +2 = 18
    put(dc2[19:20], "unallocated", 2, 8)
    put(dc2[20:24], "unallocated")                # 38 unallocated in dc2
    put(lab[0:5], "ft-claims-v13")                # 40
    put(lab[5:7], "eval-suite-v41")               # 16
    put(lab[7:8], "eval-suite-v41", 0, 2)         # +2 = 18
    put(lab[7:8], "eval-suite-c13", 2, 8)         # 6
    put(lab[8:16], "unallocated")                 # 64 unallocated in lab
    return alloc


ALLOCATION = _build_allocation()
GPU_NODES = sorted({n for n, _ in ALLOCATION})
CPU_NODES = ["dc1-ucs-cpu-%02d" % i for i in range(1, 5)] + ["dc2-ucs-cpu-%02d" % i for i in range(1, 5)]
ALL_NODES = GPU_NODES + CPU_NODES
WORKLOAD_KIND = {w: v[2] for w, v in WORKLOADS.items()}
WORKLOAD_KIND["unallocated"] = "unallocated"
WORKLOAD_UTIL_24H = {w: v[6] for w, v in WORKLOADS.items()}
# GPU rows grouped as (node, gpu, workload, kind) in emission order
GPU_ROWS = [(n, g, ALLOCATION[(n, g)], WORKLOAD_KIND[ALLOCATION[(n, g)]]) for n, g in sorted(ALLOCATION)]
GPUS_PER_WORKLOAD = {}
for _n, _g, _w, _k in GPU_ROWS:
    GPUS_PER_WORKLOAD[_w] = GPUS_PER_WORKLOAD.get(_w, 0) + 1


def pod_of(node):
    return "aipod-" + node[:3]


# ---- fabric link plan: 1,152 links ------------------------------------------------
# (device, interface, peer, fabric, kind)  kind: server|uplink|spine
PINNED_PORTS = {  # (device, interface) -> server
    ("dc1-leaf-112", "Eth1/14"): "dc1-ucs-gpu-07",
    ("dc1-leaf-112", "Eth1/31"): "dc1-ucs-gpu-21",
    ("dc1-leaf-113", "Eth1/22"): "dc1-ucs-gpu-11",
    ("dc2-leaf-207", "Eth1/03"): "dc2-ucs-gpu-19",
    ("dc2-leaf-203", "Eth1/17"): "dc2-ucs-gpu-02",
    ("lab-leaf-158", "Eth1/09"): "lab-ucs-gpu-04",
}
LEAVES = {
    "aipod-dc1": (["dc1-leaf-%d" % i for i in range(111, 115)], 48, ["dc1-spine-01", "dc1-spine-02"]),
    "aipod-dc2": (["dc2-leaf-%d" % i for i in range(201, 209)], 48, ["dc2-spine-01", "dc2-spine-02"]),
    "aipod-lab": (["lab-leaf-%d" % i for i in range(151, 159)], 40, []),
}
SPINE_PORTS = 64


def _build_links():
    links = []
    for pod in PODS:
        leaves, nports, spines = LEAVES[pod]
        pre = POD_PREFIX[pod]
        servers = [n for n in ALL_NODES if n.startswith(pre)]
        uplinks = 8 if spines else 0
        si = 0
        for leaf in leaves:
            for p in range(1, nports + 1):
                intf = "Eth1/%02d" % p
                if p > nports - uplinks:
                    peer = spines[(p - 1) % len(spines)]
                    kind = "uplink"
                else:
                    peer = PINNED_PORTS.get((leaf, intf))
                    if peer is None:
                        peer = servers[si % len(servers)]
                        si += 1
                    kind = "server"
                links.append((leaf, intf, peer, pod, kind))
        for spine in spines:
            for p in range(1, SPINE_PORTS + 1):
                intf = "Eth2/%02d" % p
                peer = leaves[(p - 1) % len(leaves)]
                links.append((spine, intf, peer, pod, "spine"))
    return links


LINKS = _build_links()
assert len(LINKS) == 1152, len(LINKS)
LINK_INDEX = {(d, i): k for k, (d, i, _p, _f, _k) in enumerate(LINKS)}
# per-node leaf attachment (first server-facing port found; pins win)
NODE_LEAF = {}
for _d, _i, _p, _f, _k in LINKS:
    if _k == "server" and (_p not in NODE_LEAF or (_d, _i) in PINNED_PORTS):
        NODE_LEAF[_p] = (_d, _i)


def node_fabric_link(node):
    d, i = NODE_LEAF[node]
    return "%s:%s" % (d, i)


# ---- applications, models, agents ---------------------------------------------------
# app -> (business_unit, cost_center)
APPS = {
    "medadvice-chat": ("customer-care", "CC-5102"),
    "claims-agent": ("claims", "CC-4523"),
    "search-rag": ("customer-care", "CC-5102"),
    "code-assist": ("engineering", "CC-6010"),
}
# request row streams: (app, model, system, streams_per_minute, serving_workload)
STREAMS = [
    ("medadvice-chat", "med-advisor-v41", "self-hosted", 8, "serve-med-advisor-v41"),
    ("claims-agent", "claims-v12", "self-hosted", 6, "serve-claims-v12"),
    ("search-rag", "rag-embed-v7", "self-hosted", 6, "serve-rag-embed-v7"),
    ("code-assist", "coder-v9", "self-hosted", 4, "serve-coder-v9"),
    ("medadvice-chat", "med-advisor-v40", "self-hosted", 1, "serve-med-advisor-v40"),
    ("medadvice-chat", "provider-api-large", "provider", 1, None),
    ("claims-agent", "provider-api-large", "provider", 1, None),
    ("code-assist", "provider-api-large", "provider", 1, None),
]
APP_SHARE = {"medadvice-chat": 0.38, "claims-agent": 0.22, "search-rag": 0.20, "code-assist": 0.14, "provider": 0.06}
MODEL_SERVERS = {"med-advisor-v41": ("aipod-dc1", 96), "claims-v12": ("aipod-dc2", 56), "coder-v9": ("aipod-dc1", 32)}
SELF_HOSTED_RATE = {"med-advisor-v41": 1.32, "claims-v12": 0.71, "coder-v9": 0.64, "rag-embed-v7": 0.12}
SELF_HOSTED_TOKEN_MIX = {"med-advisor-v41": 0.36, "claims-v12": 0.34, "coder-v9": 0.16, "rag-embed-v7": 0.14}
PROVIDER_RATE = 3.00
# agents: name -> (run share, completion pct, model, business_unit)
AGENTS = {
    "claims-intake-agent": (0.26, 88.4, "claims-v12", "claims"),
    "care-navigator": (0.28, 95.2, "med-advisor-v41", "customer-care"),
    "it-helpdesk-agent": (0.16, 96.8, "coder-v9", "engineering"),
    "policy-qa-agent": (0.15, 94.1, "claims-v12", "claims"),
    "scheduling-agent": (0.15, 97.3, "med-advisor-v41", "customer-care"),
}
TOOLS = ["search_kb", "claims_api", "ehr_lookup", "send_notification"]
TOOL_FAIL_WEIGHTS = [0.20, 0.45, 0.25, 0.10]
INJECTION_TECHNIQUES = [("instruction_override", 86), ("role_play_jailbreak", 57), ("encoded_payload", 34),
                        ("indirect_via_document", 25), ("system_prompt_leak", 12)]
PATH_PROBES = ["probe-dc1", "probe-dc2"]
PATH_TARGETS = {"api.model-provider.example": 154.0, "users-west": 42.0, "cloud-east": 68.0}
