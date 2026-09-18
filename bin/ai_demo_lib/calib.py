"""Tuned free parameters. --self-check re-solves the marked ones and reports any drift."""

TUNED = {
    # unweighted perc95(ttft_ms) over 24h gen_ai:request rows -> 820 ms
    "ttft_sigma": 0.30,
    # ai:path:test api.model-provider.example perc95(latency_ms) -> 182 ms (log-normal sigma 0.10)
    "path_median": 154.0,
    # ai:inference:server perc95(queue_time_p95_ms) over all rows -> 1,800 ms (share of burst minutes on med-advisor-v41)
    "queue_burst": 0.154,
    # med-advisor-v41 baseline hallucination share (~15/1,000) so sum(hallucination_count)/sum(request_count)
    # over generative requests (embedding calls to rag-embed-v7 excluded) -> 1.8%
    "halluc_med": 0.01459,
    # med-advisor-v41 baseline safety score so avg(quality.safety_score) -> 99.2
    "safety_med": 99.25,
}
TUNABLE_BOUNDS = {
    "ttft_sigma": (0.05, 1.2),
    "path_median": (100.0, 200.0),
    "queue_burst": (0.0, 0.5),
    "halluc_med": (0.001, 0.12),
    "safety_med": (98.5, 99.9),
}
# fixed baselines
TTFT_MEDIAN = {"medadvice-chat": 480.0, "claims-agent": 230.0, "search-rag": 185.0, "code-assist": 300.0, "provider": 340.0}
HALLUC_BASE = {"claims-v12": 0.017, "coder-v9": 0.010, "rag-embed-v7": 0.0, "provider-api-large": 0.022, "med-advisor-v40": 0.018}
EMBEDDING_MODELS = {"rag-embed-v7"}  # excluded from the hallucination-rate denominator (no generated answer)
GROUND_BASE = {"med-advisor-v41": 96.8, "med-advisor-v40": 96.5, "claims-v12": 96.1, "coder-v9": 95.4, "rag-embed-v7": 95.9, "provider-api-large": 96.3}
SAFETY_BASE = {"med-advisor-v40": 99.2, "claims-v12": 99.4, "coder-v9": 99.0, "rag-embed-v7": 99.3, "provider-api-large": 99.3}
TOKENS_IN = {"med-advisor-v41": 780, "med-advisor-v40": 760, "claims-v12": 640, "coder-v9": 1100, "rag-embed-v7": 420, "provider-api-large": 118000}
TOKENS_OUT = {"med-advisor-v41": 210, "med-advisor-v40": 200, "claims-v12": 160, "coder-v9": 340, "rag-embed-v7": 24, "provider-api-large": 13800}
PROVIDER_USD_PER_TOKEN = 3.0e-6
REQUESTS_PER_DAY = 1280000
AGENT_RUNS_PER_DAY = 48320
AGENT_OUTCOMES = {"completed": 45324, "escalated_to_human": 1690, "abandoned": 966, "blocked:guardrail": 303, "loop_stopped": 37}
STEP_ERRORS_PER_DAY = 1204
STEPS_DIST = [(3, 0.06), (4, 0.12), (5, 0.18), (6, 0.22), (7, 0.16), (8, 0.10), (9, 0.06), (10, 0.04), (11, 0.03), (12, 0.03)]
