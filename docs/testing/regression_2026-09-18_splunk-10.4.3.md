# Regression test report: ai_infra_monitoring on Splunk Enterprise 10.4.3

This is the smoke test and full regression run of `ai_infra_monitoring` 1.0.0 after the Splunk Enterprise upgrade from 10.4.0 to 10.4.3 on the demo instance, on 2026-09-18. All times are Pacific (PDT).

## Summary

**Verdict: pass. The upgrade caused no regressions.** Every static check, the package, AppInspect and the generator self-check pass with the same results as before the upgrade. Every knowledge object loads, and the 25 feeds, the scheduler, HEC and the app's alert actions all work on 10.4.3. All ten dashboards render in Splunk Web 10.4.3 without errors. On the same data window as the last pre-upgrade run, 10.4.3 reproduces the 10.4.0 result check for check (119/119).

The live suite (`make smoke SMOKE_FLAGS=--dispatch-alerts`) scored **139/144**. None of the five failures comes from the upgrade. They are time-of-day effects in the demo data, and this was the first smoke run ever made after 15:05 (findings F2 and F3). The upgrade outage also left a 5-minute hole in today's data (F1).

| Suite | Command | 10.4.0 baseline | 10.4.3 result | Status |
|---|---|---|---|---|
| Static validation | `make validate` | OK | 10/10 views OK (2 palette warnings), `btool check` OK, HTML twins fresh | Pass |
| Package | `make package` | 1.0.0 tarball | 63 entries, no hidden files | Pass |
| AppInspect (precert, cloud tags) | `make appinspect` | 0 errors, 0 failures, 4 warnings, 131 successes | identical, no check changed result | Pass |
| Generator self-check | `bin/ai_demo_generator.py --self-check` | not recorded | 39/39 KPIs within tolerance on Python 3.13.11 | Pass |
| Live smoke with alert dispatch | `make smoke SMOKE_FLAGS=--dispatch-alerts` | 143/144 (13:44) | 139/144 (15:19) | 5 failures, none from the upgrade (F2, F3) |
| Same data window as the baseline | `tools/smoke_pinned.py`, clock pinned to 13:46:00 | 119/119 (13:47) | 119/119 | Pass |
| Alert logic, read-only replay | `tools/replay_alerts.py` at 2026-09-17 14:55 | 25/25 fired (13:44) | 25/25 return results | Pass |
| Post-upgrade platform checks | REST and SPL, section 3.5 | n/a | all pass; scheduler-delay health was already red before the upgrade (F4) | Pass |
| Dashboards in Splunk Web | the ten views in a browser, section 3.6 | n/a | all ten render; 103 dashboard searches, 0 failed, all returned rows | Pass |
| Enterprise Security risk and notable actions | forced rule dispatch | verified at 09:37 | not run: the rules are suppressed until about 09:35 on 2026-09-19 (F5) | Not run |

## 1. Test environment

| Item | Value |
|---|---|
| Instance | Splunk Enterprise single instance on macOS arm64 at `/opt/splunk104`; management port 8090, Splunk Web 8002, HEC 8088 |
| Upgrade | 10.4.0 (build `f798d4d49089`) to 10.4.3 (build `4174a2deda5d`) |
| Upgrade timeline | splunkd stopped 13:56:26; migration ran 14:00:58 and all upgrade prechecks passed (KV store 8.0.20); splunkd started 14:01:26 |
| Bundled Python | 3.13.11 |
| App under test | `ai_infra_monitoring` 1.0.0, commit `4481b4f` on `main`, same as `origin/main`, working tree clean while the tests ran |
| Instance state | all 25 generator feeds enabled (`local/inputs.conf`); the four Enterprise Security rules enabled (`local/savedsearches.conf`); Enterprise Security 8.5.1 installed; seed 20260916 |
| Baseline | the same day on 10.4.0: `make smoke` 119/119 at 13:47, `make smoke SMOKE_FLAGS=--dispatch-alerts` 143/144 at 13:44, AppInspect at 13:47 |
| Run | 15:16 to 15:31 (suites), 15:36 to 15:48 (dashboards), by a Claude Code session for Michael Yeack |

## 2. What ran

1. `make all`: `tools/validate_views.py`, `splunk btool check`, the HTML-twin freshness check, `make package`, then `splunk-appinspect` 4.2.0 (`--mode precert --included-tags cloud`) with the gate script.
2. `splunk cmd python3 bin/ai_demo_generator.py --self-check --seed 20260916`, the offline recomputation of 39 dashboard KPIs.
3. `make smoke SMOKE_FLAGS=--dispatch-alerts`: every dashboard query, the 14 headline KPIs, alert coverage, the 25 alerts force-dispatched at the last incident's 14:55, scoreboards, the node timeline and the attention-table ordering.
4. Read-only post-upgrade platform checks over REST and SPL (section 3.5).
5. Triage of the failures:
   - `tools/replay_alerts.py` ran the 25 alert searches at 2026-09-17 14:55 and 2026-09-18 14:55, with the `collect` stages removed and no actions.
   - `tools/smoke_pinned.py` reran `smoke.py` unchanged with every search pinned to 13:47:00 and then 13:46:00. That repeats the baseline's data window on 10.4.3.
6. After you logged in to Splunk Web: the ten dashboards were opened in a browser at 1600×1000 (section 3.6). Each page got a screenshot review and a DOM check for error states, undrawn charts and empty panels. The `_audit` index then gave the outcome of every search job those page loads started.

What the run wrote: step 3 dispatched the 25 alerts with `trigger_actions=1`, so the 21 alerts that returned results wrote their usual `ai:alert` events to `ai_summary`, the same action the scheduler runs every 5 minutes. The four security alerts had no results, so nothing was collected into `ai_security`. Every other step was read-only. There was no restart, backfill or `make clean`.

Raw evidence lives in `dist/regression/2026-09-18_splunk-10.4.3/`, which is git-ignored and exists only on the demo instance:

| File | Content |
|---|---|
| `baseline_pre_upgrade/` | 10.4.0 results: `smoke.txt`/`smoke.json` (13:47), `smoke_run13.log`, `smoke_run14.log`, `appinspect_pre_upgrade.json` |
| `01_make_all.log`, `01_appinspect.json` | step 1 |
| `02_generator_selfcheck.log` | step 2 |
| `03_smoke_dispatch.log`, `.txt`, `.json` | step 3 |
| `04_alert_replay.*`, `08_replay_alerts_tool.*` | alert replays (ad hoc script, then `tools/replay_alerts.py`) |
| `05_smoke_pinned_1347.*`, `06_smoke_pinned_1346.*`, `09_smoke_pinned_tool_1346.*` | pinned-clock reruns |
| `07_platform_checks.log` | step 4, with the exact SPL of every check |
| `10_final_make_all.log`, `10_appinspect.json` | `make all` after these documentation changes |
| `11_dashboard_jobs_audit.log` | step 6: outcome of every dashboard search job, from `_audit` |
| `12_dashboard_ui_check.log` | step 6: per-dashboard DOM check results and the secondary-tile comparison |

## 3. Results

### 3.1 Static suite

- `validate_views`: all ten views OK, 0 errors. Two warnings for colours outside the palette: `#C3CBD4` in `ai_operations_executive_overview` and `#31373E` in `ai_stack_overview`. The check is static and the view files have not changed since 13:45, so the warnings predate the upgrade.
- `splunk btool check` on 10.4.3 reports no invalid keys or stanzas in the app.
- The four HTML twins were regenerated with byte-identical content (`git status` stayed clean).
- Package `dist/ai_infra_monitoring-1.0.0.tgz` has 63 entries and no hidden files.
- AppInspect on 10.4.3 reports 0 errors, 0 failures, 4 warnings, 131 successes, 106 not applicable and 1 skipped. That matches the 13:47 pre-upgrade report exactly, and no check changed result. The four warnings are unchanged: Python files present, scripted inputs present, `threading.Thread.start` in a loop in `bin/ai_demo_lib/transport.py`, and the documentation IP 203.0.113.10 in `README.html`.

### 3.2 Generator self-check

All 39 KPIs pass (latest day 2026-09-18), 15 of them headline KPIs, running on the Python 3.13.11 that ships with 10.4.3. The tuner re-solved `ttft_sigma` to 0.307 against the stored 0.3. That is informational: the resulting p95 TTFT of 819 ms is within tolerance of 820 ms.

### 3.3 Live smoke suite

Ran 15:16 to 15:19 with alerts anchored at 2026-09-18 14:55.

| Check | What it proves | Pass | Fail |
|---|---|---|---|
| datasource | every dataSource query of the ten dashboards returns rows with no ERROR message | 91 | 0 |
| kpi | the 14 headline KPI macros land within tolerance of their targets | 14 | 0 |
| alerts | all 25 alert names have written `ai:alert` events in the last 30 days | 1 | 0 |
| dispatch | each alert returns results when force-dispatched at the last incident's 14:55 | 21 | 4 |
| scoreboard | the five scoreboard rollups equal their tiles | 5 | 0 |
| node_timeline | the `dc1-ucs-gpu-07` drilldown spans at least 3 sourcetypes (6 found) | 1 | 0 |
| table_order | the seven attention tables lead with the scripted incident rows | 6 | 1 |
| **Total** | | **139** | **5** |

The failures are the four AI Security alerts (0 results at 2026-09-18 14:55, finding F2) and the `ai_applications` request table leading with `search-rag` instead of `medadvice-chat` (finding F3).

The KPI values on 10.4.3 match 10.4.0. The last two columns are the pinned rerun on the baseline's data window and the live run.

| KPI | Target | Tolerance | 10.4.0 at 13:47 | 10.4.3 pinned 13:46 | 10.4.3 live 15:19 |
|---|---|---|---|---|---|
| GPUs Monitored | 512 | 5% | 512 | 512 | 512 |
| Avg GPU Utilization | 61.8 | 5% | 61.6 | 61.7 | 61.6 |
| Idle GPU-Hours (7d) | 17,100 | 5% | 17,136 | 17,136 | 17,136 |
| Fabric Links Monitored | 1,152 | 5% | 1,152 | 1,152 | 1,152 |
| Pod Restarts (24h) | 37 | 5% | 37 | 37 | 37 |
| Requests (24h) | 1,280,000 | 5% | 1,276,225 | 1,278,331 | 1,269,477 |
| Availability | 99.93 | 0.05 | 99.93 | 99.93 | 99.93 |
| p95 Time-to-First-Token | 820 | 5% | 804 | 805 | 802 |
| Safety Compliance | 99.2 | 0.05 | 99.2 | 99.2 | 99.2 |
| Hallucination Rate | 1.8 | 5% | 1.8 | 1.8 | 1.8 |
| Agent Runs (24h) | 48,320 | 5% | 48,163 | 48,258 | 47,913 |
| GPU-Hours Allocated (7d) | 68,900 | 5% | 69,232 | 69,232 | 69,232 |
| Open Findings | 22 | 5% | 22 | 22 | 22 |
| Prompt Injections Detected | 214 | 5% | 214 | 214 | 214 |

All five scoreboards equal their tiles in every run: Availability 99.93, Pilot to production 38, GPU utilization 61.6, Safety compliance 99.2 and Open findings 22. The live Requests and Agent Runs totals are 0.5 to 0.7% below the baseline and pinned runs because the live 24-hour window contains the upgrade outage (F1).

Alert results by run. The first column is the live forced dispatch. The next two are the read-only replay at two anchors. The last is the first `ai:alert` event the scheduler wrote after the upgrade, before any forced dispatch.

| Alert | Dispatch at 09-18 14:55 | Replay at 09-18 14:55 | Replay at 09-17 14:55 | Scheduler fired after upgrade |
|---|---|---|---|---|
| AI Infra - ECC or Xid faults on a GPU node | 1 | 1 | 1 | 14:55:10 |
| AI Infra - Thermal throttling sustained 15 min | 1 | 1 | 1 | 14:45:18 |
| AI Infra - Idle GPU capacity above 30% for 24h | 1 | 1 | 1 | 14:03:18 |
| AI Network - Fabric congestion (ECN/PFC) on an AI POD link | 3 | 3 | 3 | 14:03:13 |
| AI Network - Link flapping on a GPU-facing port | 1 | 1 | 1 | 14:55:09 |
| AI Network - Configuration drift on an AI fabric switch | 1 | 1 | 1 | 14:15:13 |
| AI Platform - Restart storm on an inference deployment | 1 | 1 | 1 | 14:55:08 |
| AI Platform - Inference queue build-up | 1 | 1 | 1 | 14:03:12 |
| AI Platform - Evaluation or fine-tuning job failed | 3 | 3 | 3 | 14:03:19 |
| AI Apps - p95 time-to-first-token regression | 1 | 1 | 1 | 14:15:15 |
| AI Apps - Error rate spike | 4 | 4 | 4 | 14:03:13 |
| AI Apps - Retrieval timeouts | 1 | 1 | 1 | 14:50:13 |
| AI Models - Quality drift vs baseline | 1 | 1 | 1 | 14:03:18 |
| AI Models - Safety compliance below policy band | 1 | 1 | 1 | 14:03:15 |
| AI Models - Evaluation regression on a release candidate | 1 | 1 | 1 | 14:03:13 |
| AI Agents - Task completion drop | 1 | 1 | 1 | 14:03:15 |
| AI Agents - Runaway loop detected | 2 | 2 | 2 | 14:03:18 |
| AI Agents - Guardrail surge | 2 | 2 | 3 | 14:03:18 |
| AI Cost - Daily spend spike by business unit | 1 | 1 | 1 | 14:03:19 |
| AI Cost - Idle reservation above threshold | 4 | 4 | 4 | 14:03:19 |
| AI Cost - Runaway agent token spend | 2 | 2 | 2 | 14:03:15 |
| AI Security - First-seen access to model weights | **0** | 0 | 1 | none (0 results in 15 runs) |
| AI Security - Credential misuse on an AI cluster | **0** | 0 | 1 | none (0 results in 15 runs) |
| AI Security - Anomalous data movement from an AI data store | **0** | 0 | 1 | none (0 results in 15 runs) |
| AI Security - Prompt-injection campaign from a single source | **0** | 0 | 1 | none (0 results in 15 runs) |

### 3.4 Same data window as the baseline

`tools/smoke_pinned.py` runs `smoke.py` unchanged but sets the search-job `now` parameter. That parameter fixes both the relative time range and SPL's `now()`; a check with `| makeresults | eval now()` confirmed both. The dispatch checks are left out, so the run is read-only.

- Pinned to **13:46:00**, the last minute that was fully indexed when the 10.4.0 baseline ran its table checks, 10.4.3 scores **119/119**, the same as the baseline.
- Pinned to **13:47:00**, it scores 118/119. Only `ai_applications/ds_requests_table` differs, because this window contains the 13:46 minute: it was indexed at 13:47:42, after the baseline's table check (F3).
- Across the 119 checks the runs share, the live run differs from the baseline only in that same table check.

### 3.5 Post-upgrade platform checks

| Check | Result |
|---|---|
| Server | 10.4.3, build `4174a2deda5d`, KV store ready; REST authentication with the `.env` credentials works |
| App | enabled, visible, version 1.0.0 |
| Views | 10 of 10 loaded, all Dashboard Studio `version="2"` |
| Saved searches | 34 of 34 loaded, all scheduled, none disabled (25 alerts, 5 scoreboards, 4 ES rules) |
| Other knowledge objects | macros 74/74, event types 6/6, props stanzas 27/27, lookup files 5/5, lookup definitions 5 |
| Scripted inputs | 25 of 25 enabled and running under Python 3.13.11 |
| Indexes | all nine present and enabled (`ai_infra_metrics` is a metrics index), all receiving data |
| HEC | `/services/collector/health` answers "HEC is healthy"; token `ai_infra_demo` enabled and scoped to the nine indexes |
| Feed freshness | every event feed and all 9 GPU metrics current. The high-rate feeds lag 1 to 2 minutes because the generator emits the previous minute. Sparse feeds (`cisco:ucs:alarm`, `ai:eval:run`, `cisco:nexus:config`) and the 5-minute interface counters outside the incident window follow their normal cadence. |
| Scheduler, first hour after the upgrade (14:01 to 15:01) | 366 successful runs of the app's 34 searches, 0 skipped, 0 failed, average dispatch delay 31.7 s. The hour before the upgrade: 336 successful, 0 skipped. |
| Alert actions | 21 of 25 alerts wrote `ai:alert` events through `logevent` from 14:03 on, including the incident alerts at 14:55. The other four had no results (F2). |
| Scoreboards | all five rollups written every 15 minutes since the upgrade (last at 15:15) |
| Enterprise Security | ES 8.5.1 enabled. The four rules are enabled and scheduled, and ran after the upgrade with 0 results for the same reason as F2. Their risk and notable actions have not run on 10.4.3 (F5). |
| Alert action framework | `logevent` ran 932 times between the upgrade and 15:45, all with exit code 0 |
| splunkd.log | no WARN, ERROR or FATAL lines mention the app or the generator since 14:01:26 |
| splunkd health | red on "Search Scheduler: Searches Delayed" (F4) |

### 3.6 Dashboards in Splunk Web

Each dashboard was opened on 10.4.3 and left until every panel had finished loading, then checked in two ways: a screenshot review, and a DOM check of every Dashboard Studio panel for error states (search errors, "no results", waiting for input, timeouts), undrawn charts and empty tables. The `_audit` index recorded every search job these page loads started.

| Dashboard | Panels (data) | Charts drawn | Table rows | Error states | Searches (failed) | Values shown |
|---|---|---|---|---|---|---|
| `ai_stack_overview` | 25 (11) | n/a | n/a | 0 | 18 (0), loaded twice | 1.62M, 211, 292.86K, 39.61K, 1.89M, 5.78K; scoreboards 99.93, 38, 61.6, 99.2, 22 |
| `ai_infrastructure_health` | 8 (8) | 2/2 | 25 | 0 | 9 (0) | 512, 61.6%, 17.14K, 3, 41 |
| `ai_network_fabric` | 8 (8) | 2/2 | 25 | 0 | 9 (0) | 1,152, 13, 38K, 9, 183 ms |
| `ai_platform_workloads` | 8 (8) | 2/2 | 25 | 0 | 9 (0) | 184, 37, 12, 1.8 s, 10 |
| `ai_applications` | 8 (8) | 2/2 | 50 | 0 | 11 (0) | 1.27M, 99.93%, 798 ms, $30.2K, 1,856 |
| `model_performance_quality` | 8 (8) | 2/2 | 7 | 0 | 10 (0) | 99.2%, 96.1%, 1.8%, -2.1 pts, 4.2 h |
| `ai_agents` | 8 (8) | 2/2 | 50 | 0 | 10 (0) | 47,934, 93.8%, 6.4, 1,189, 36 |
| `ai_security_posture` | 8 (8) | 2/2 | 25 | 0 | 9 (0) | 22, 7, 3, 12, 214 |
| `ai_cost_unit_economics` | 8 (8) | 2/2 | 7 | 0 | 9 (0) | 69.23K, 17.14K, $0.84, $212.1K, 2,140 |
| `ai_operations_executive_overview` | 8 (8) | 2/2 | 7 | 0 | 9 (0) | 99.93%, 38 d, 61.6%, 99.2%, 22 |

All 103 dashboard searches returned rows and none failed; the slowest took 1.38 s. The only HTTP errors on any page were three 404s from Splunk Web's own probes (SPL2 orchestrator, SCS tenant info, `splunk-visual-exporter`), none from the app. The headline values match the smoke run.

A few tiles that the smoke test doesn't cover read slightly off the generator model: Congested Links 13 (model 14), Failed Jobs 10 (9), Guardrails Triggered 1,856 (1,906). The same searches pinned to the baseline window (13:46:00) return 14, 9 and 1,892 on 10.4.3, so the live difference comes from the F1 gap and from data written after 13:46, not from the platform.

## 4. Findings

### F1. Five-minute data gap from the upgrade outage

- **What:** splunkd was down from 13:56:26 to 14:01:26. The scripted inputs only ever emit the previous minute, so minutes 13:56 to 14:00 are missing from all 25 feeds and the 9 GPU metrics. Before and after the gap the five busiest feeds carry about 1,260 events a minute and the metrics 3,264 points a minute; during it, nothing.
- **Impact:** low. The gap sits inside today's incident window, so the incident charts show a 5-minute hole. The live "Last 24 hours" totals read 0.5 to 0.7% lower than on the baseline and pinned windows (Requests 1,269,477 and Agent Runs 47,913 are within 1% of target), and every tile stays within tolerance.
- **Action:** none needed. The gap leaves "Last 24 hours" at 14:01 on 2026-09-19. `make backfill` cannot fill it: `--resume` skips any 5-minute bucket that already holds data, and the 13:55 and 14:00 buckets do. Plan future upgrades outside 12:45 to 15:00, the daily incident window.

### F2. The security alerts fail dispatch after 15:05 (existed before the upgrade)

- **What:** the four AI Security alerts return 0 results when dispatched at 2026-09-18 14:55.
- **Cause:** the generator writes the scripted security storyline only on its "latest day". That storyline is the seven findings (first-seen access to model weights, off-hours `kubectl exec`, egress to a new ASN, and the prompt-injection campaign with 59 blocked attempts). `latest_day_for()` in `bin/ai_demo_generator.py` returns yesterday until 15:00, and `DaySchedule` in `bin/ai_demo_lib/schedule.py` emits `FINDINGS` only when `offset == 0`. The streaming inputs therefore never write today's copy, and after 15:00 it is too late to stream it. Meanwhile `incident_anchor()` in `tools/smoke.py` switches to today's 14:55 at 15:05. Every earlier smoke run happened before 14:00, so this run is the first to hit the combination. The code involved has not changed since before the upgrade.
- **Evidence:**
  - The storyline rows exist on 2026-09-17 (users svc-mlops-ci, maya.okonkwo@buttercupgames.com and svc-eval-runner) and not on 2026-09-18.
  - The top blocked-injection source reached 59 attempts on 2026-09-17 and 30 on 2026-09-18, spread over the day, so no 90-minute window reaches the alert's threshold of 20.
  - The read-only replay on 10.4.3 returns results for all 25 alerts at 2026-09-17 14:55 and for 21 at 2026-09-18 14:55, missing exactly these four.
- **Impact:** limited to tests and demos; the alert logic works on 10.4.3. From 2026-09-19 the anchor day never carries the storyline, so the four dispatch checks keep failing and the security story ages out of "Last 24 hours".
- **Action:** follow-up 1 in section 5.

### F3. The `ai_applications` table-order check depends on timing (existed before the upgrade)

- **What:** `ai_applications/ds_requests_table` should start with `medadvice-chat`; the live run started with `search-rag`.
- **Cause:** the table puts attention rows first (guardrail not `pass`, retrieval timeout, or status not `ok`), newest first. During the incident, `medadvice-chat`, `search-rag`, `claims-agent` and `code-assist` all produce attention rows every minute. Of the 20 newest before 13:47, nine were `medadvice-chat`, five `search-rag`, four `claims-agent` and two `code-assist`. So the first row depends on which app's row arrived last. The 13:46 minute, whose newest attention row is `search-rag` at 13:46:54.917, was indexed at 13:47:42. The 10.4.0 baseline run finished at 13:47:43 with the table checks last, so it read the table before that minute arrived. At that point the newest attention row was `medadvice-chat` at 13:45:43.904.
- **Evidence:** on 10.4.3 the check passes with the clock pinned to 13:46:00 and fails pinned to 13:47:00, exactly as the data predicts. After the incident ends at 15:00, the newest attention rows are ordinary background rows from any app.
- **Action:** follow-up 1 in section 5.

### F4. splunkd health is red on "Searches Delayed" (existed before the upgrade, affects the whole instance)

- The indicator has been red since at least 2026-09-15 15:55: 3,600 red reports before the upgrade, and green only briefly after restarts. It measured 964% against a threshold of 20% for non-high-priority scheduled searches over 24 hours.
- The instance also runs Enterprise Security 8.5.1, MLTK and about 150 scheduled searches. This app's searches still meet their schedules on 10.4.3: 0 skipped, 31.7 s average delay.
- **Action:** none for the app. Tune scheduler concurrency on the instance or disable unused scheduled content if the red status matters.

### F5. Enterprise Security risk and notable actions not exercised on 10.4.3

- **What:** no ES rule has returned results since the upgrade (F2), so `action.risk` and `action.notable` have not run on 10.4.3. No risk or notable event from any source has been indexed since 14:01:26.
- **Why a forced dispatch wouldn't help today:** all four rules carry `alert.suppress = 1` on `user,object` for 86,300 s. The pre-upgrade verification at 09:37 set that suppression, and at 15:45 it had 64,194 s left (until about 09:35 on 2026-09-19). A dispatch at the 2026-09-17 14:55 anchor would return the same user and object and be suppressed.
- **What is known:** the rule searches run on schedule on 10.4.3 without errors, the app's `logevent` action ran 932 times with exit code 0, and both ES actions produced one risk event and one notable per rule on 10.4.0 this morning.
- **Action:** follow-up 2 in section 5.

## 5. Follow-ups

1. **Make the smoke test independent of the time of day (F2, F3).** Option one: have the generator write the latest day's scripted rows (security `FINDINGS`, the deck request rows and the 59 blocked injections) when `latest_day` rolls over at 15:00. Option two: anchor `incident_anchor()` on the newest day that actually holds the storyline. Then change the `ai_applications` table check to require the scripted incident rows among the attention rows, rather than one exact newest row.
2. **Exercise the Enterprise Security actions on 10.4.3 (F5).** After about 09:35 on 2026-09-19, when the suppression expires (or sooner, after clearing it), dispatch one rule at 2026-09-17 14:55 with `trigger_actions=1` and check `index=risk` and `index=notable` with a window that covers 2026-09-17. This adds one duplicate risk event and one duplicate notable to the demo's ES queue.

## 6. Rerunning the suite

From the app directory, with `.env` holding working credentials:

```bash
make all
$SPLUNK_HOME/bin/splunk cmd python3 bin/ai_demo_generator.py --self-check --seed 20260916
make smoke SMOKE_FLAGS=--dispatch-alerts
```

To compare against a baseline over the same data, pin the clock to the last minute that was fully indexed when the baseline ran, and replay the alerts at a day that holds the scripted storyline:

```bash
$SPLUNK_HOME/bin/splunk cmd python3 tools/smoke_pinned.py 1789764360 --json dist/smoke_pinned.json
$SPLUNK_HOME/bin/splunk cmd python3 tools/replay_alerts.py 2026-09-17T14:55 2026-09-18T14:55
```

The platform checks in section 3.5 are REST calls and SPL searches; `07_platform_checks.log` in the evidence folder records each query with its time range.
