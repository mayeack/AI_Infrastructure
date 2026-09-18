"""Sourcetype -> index map, tiers and cadences."""

SOURCETYPE_INDEX = {
    "ai:gpu:metrics": "ai_infra_metrics",
    "ai:gpu:fault": "ai_infra",
    "cisco:ucs:alarm": "ai_infra",
    "cisco:ucs:inventory": "ai_infra",
    "cisco:ucs:audit": "ai_infra",
    "cisco:nexus:interface": "ai_network",
    "cisco:nexus:anomaly": "ai_network",
    "cisco:nexus:config": "ai_network",
    "ai:path:test": "ai_network",
    "kube:events": "ai_platform",
    "ai:inference:server": "ai_platform",
    "ai:job:lifecycle": "ai_platform",
    "gen_ai:request": "ai_application",
    "gen_ai:agent:run": "ai_application",
    "gen_ai:agent:step": "ai_application",
    "gen_ai:guardrail": "ai_application",
    "ai:eval:run": "ai_model_eval",
    "ai:cost:daily": "ai_cost",
    "ai:cost:tokens": "ai_cost",
    "aws:cloudtrail:sim": "ai_security",
    "k8s:audit:sim": "ai_security",
    "iam:sim": "ai_security",
    "ai:security:finding": "ai_security",
    "ai:scoreboard": "ai_summary",
    "ai:incident": "ai_summary",
}
ALL_SOURCETYPES = list(SOURCETYPE_INDEX)
# Per-minute formula feeds (high volume); everything else comes from the day schedule.
MINUTE_FEEDS = ["ai:gpu:metrics", "cisco:nexus:interface", "ai:path:test", "ai:inference:server",
                "gen_ai:request", "gen_ai:agent:run", "gen_ai:agent:step"]
SCHEDULE_FEEDS = [s for s in ALL_SOURCETYPES if s not in MINUTE_FEEDS and s not in ("ai:scoreboard", "ai:incident")]
HISTORY_FEEDS = ["ai:scoreboard", "ai:incident", "ai:eval:run", "cisco:ucs:inventory"]

# tier -> cadence in minutes for the interval feeds
TIER_CADENCE = {
    1: {"ai:gpu:metrics": 1, "cisco:nexus:interface": 5, "ai:path:test": 1, "ai:inference:server": 1, "gen_ai:request": 1},
    2: {"ai:gpu:metrics": 5, "cisco:nexus:interface": 15, "ai:path:test": 5, "ai:inference:server": 5, "gen_ai:request": 5},
    3: {"ai:gpu:metrics": 15, "cisco:nexus:interface": 60, "ai:path:test": 15, "ai:inference:server": 15, "gen_ai:request": 15},
}
INTERFACE_WINDOW_CADENCE = 1  # cisco:nexus:interface inside 12:45-15:00 in tier 1


def tier_for(minute_epoch, now_epoch):
    age = now_epoch - minute_epoch
    if age <= 86400:
        return 1
    if age <= 7 * 86400:
        return 2
    return 3
