# Field reference

Every sourcetype the generator writes, with the fields it carries. Common to all events: `timestamp` (ISO-8601 with milliseconds and numeric offset, e.g. `2026-09-18T14:49:31.120-0700`, parsed by `TIME_PREFIX`/`TIME_FORMAT`; HEC uses the epoch `time` field instead), `host=ai-demo-generator`, `source=ai_demo_generator`. `layer` is never emitted; it is an `EVAL-layer` calculated field on every sourcetype (`compute`, `network`, `platform`, `application`, `model`, `agent`, `efficiency`, `security`, `summary`) and `ai_layer_map` adds `layer_no` and `dashboard` through an automatic lookup. Types: `str`, `int`, `float`, `bool`, `array`. "Used by" names the dashboard (D) and alert (A) that read the field; the KPI macros are listed in the README.

## Index `ai_infra_metrics` (metrics)

### `ai:gpu:metrics`

One multi-metric datapoint per GPU per interval (1 min in the last 24 h, 5 min days 2-7, 15 min days 8-30). Sent over HEC in the `fields`/`metric_name:` form; the stdout path emits plain JSON that `metric-schema:ai_gpu_metrics` converts (`METRIC-SCHEMA-MEASURES = DCGM_FI_DEV_*, storage_*`).

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `ai_pod` | dimension str | `aipod-dc1`, `aipod-dc2`, `aipod-lab` | D infrastructure (POD filter, utilization chart), A idle capacity |
| `node` | dimension str | `dc1-ucs-gpu-07` | D infrastructure (node filter), GPUs Monitored |
| `gpu` | dimension str | `GPU0` … `GPU7` | GPUs Monitored (`BY node gpu`) |
| `workload` | dimension str | `serve-med-advisor-v41`, `ft-claims-v13`, `unallocated` | Avg GPU Utilization (`NOT workload="unallocated"`), A idle capacity |
| `kind` | dimension str | `inference`, `evaluation`, `fine-tuning`, `unallocated` | breakdowns |
| `DCGM_FI_DEV_GPU_UTIL` | measure float % | 61.2 (0-3 on unallocated GPUs) | D infrastructure tiles and chart, D executive utilization, A idle capacity |
| `DCGM_FI_DEV_MEM_COPY_UTIL` | measure float % | 38.4 | drilldowns |
| `DCGM_FI_DEV_FB_USED` | measure int MiB | 61440 | drilldowns |
| `DCGM_FI_DEV_POWER_USAGE` | measure float W | 412.5 (60-70 unallocated) | drilldowns |
| `DCGM_FI_DEV_GPU_TEMP` | measure int C | 71; 91 on `dc1-ucs-gpu-07 GPU5` at 14:49 | node timeline |
| `DCGM_FI_DEV_SM_CLOCK` | measure int MHz | 1980 | drilldowns |
| `storage_read_mbps` / `storage_write_mbps` / `storage_latency_ms` | measure float | 1840.0 / 420.0 / 2.3, on `gpu=GPU0` only (per node) | storage drilldowns |

## Index `ai_infra`

### `ai:gpu:fault`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `node` | str | `dc1-ucs-gpu-07` | D infrastructure table, node timeline, A ECC/Xid, A thermal |
| `ai_pod` | str | `aipod-dc1` | POD filter |
| `gpu` | str | `GPU5` | table, A ECC/Xid |
| `fault` | str | `ecc_dbe_volatile`, `xid_79_fallen_off_bus`, `xid_48_dbe`, `ecc_sbe_rate_high`, `nvlink_crc_errors`, `thermal_throttle`, `power_cap_throttle` | ECC / Xid Errors tile, faults chart (`fault_type`), table colour, A ECC/Xid, A thermal |
| `gpu_temp_c` | int C | 91 | table colour (red >= 90, orange >= 85), A thermal |
| `severity` | str | `critical`, `high`, `medium`, `low` (background) | attention-first ordering, Degraded Nodes |
| `node_state` | str | `degraded` on the three degraded nodes, else `ok` | Degraded Nodes tile |
| `fabric_link` | str | `dc1-leaf-112:Eth1/14` | table (`fabric_link fabric_link_state`), joins `fabric_link_id` on Nexus events |
| `fabric_link_state` | str | `up`, `flapping` | table |
| `xid` | int | 79, 48 (Xid faults only) | drilldowns |
| `message` | str | free text | node timeline `detail` |

### `cisco:ucs:alarm`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `server` | str | `dc1-ucs-gpu-07` (aliased to `node`) | node timeline, landing-page counts |
| `ai_pod` | str | `aipod-dc1` | filters |
| `severity` | str | `critical`, `major`, `minor`, `warning`, `info` | node timeline |
| `code` | str | `F1236` | drilldowns |
| `description` | str | free text | drilldowns |

### `cisco:ucs:inventory`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `server` | str | aliased to `node` | landing-page counts |
| `ai_pod` | str | `aipod-lab` | filters |
| `model` | str | `UCS C885A M8`, `UCS C225 M8` (CPU nodes) | drilldowns |
| `gpu_model` | str | `H100-SXM-80GB` | drilldowns |
| `gpu_count` | int | 8 (0 on CPU nodes) | drilldowns |
| `firmware` | str | `4.3(2b)` | drilldowns |
| `leaf_switch` / `leaf_port` | str | `dc1-leaf-112` / `Eth1/14` | link plan |

### `cisco:ucs:audit`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `user` | str | `ucs-admin` | drilldowns |
| `action` | str | `firmware.update`, `power.cycle`, `bios.update` | drilldowns |
| `object` | str | `sys/chassis-1/blade-3` | drilldowns |
| `server` | str | aliased to `node` | node timeline |

## Index `ai_network`

### `cisco:nexus:interface`

One row per monitored link per interval (5 min, 1 min during 12:45-15:00 on the latest day; 15 min days 2-7; 60 min days 8-30). 1,152 links: dc1 4 leaves x 48 + 2 spines x 64, dc2 8 leaves x 48 + 2 spines x 64, lab 8 leaves x 40.

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `device` | str | `dc1-leaf-112` | D network (device filter, table), drilldowns |
| `interface` | str | `Eth1/14` | table, drilldowns |
| `peer` | str | `dc1-ucs-gpu-07` or a switch (`EVAL-node = coalesce(peer,null())` joins GPU servers) | node timeline |
| `fabric` | str | `aipod-dc1` | fabric filter (`ai_pod` is also computed from `device`) |
| `speed_gbps` | int | 400 | throughput chart |
| `in_util_pct` / `out_util_pct` | float % | 41.2 / 37.8 | throughput chart (`(in+out)/200 x speed_gbps`) |
| `in_gbps` / `out_gbps` | float | 164.8 / 151.2 | drilldowns |
| `ecn_marked_packets` | int | 0; up to 18K/min on `dc1-spine-02 Eth2/05` from 14:38 | drilldowns |
| `pfc_pause_rx` / `pfc_pause_tx` | int | storm on `dc1-leaf-112 Eth1/31` from 14:41 (day total 38.2K) | PFC Pause Frames tile |
| `crc_errors` | int | rising on `dc2-leaf-207 Eth1/03` | drilldowns |
| `link_state` | str | `up`, `down` (six down/up pairs on Eth1/14 14:40-14:49) | drilldowns |
| `optic_rx_power_dbm` | float | -2.1; low on `lab-leaf-158 Eth1/09` | drilldowns |

### `cisco:nexus:anomaly`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `device` / `interface` / `peer` / `fabric` | str | as above | D network table and chart, A congestion, A link flapping |
| `anomaly` | str | `congestion`, `pfc_pause_storm`, `link_flap`, `crc_errors`, `ecn_marked_packets high`, `optic rx power low` | Congested Links, Link Flaps, anomalies chart (`anomaly_type`), table |
| `utilization` | int % | 97 | table, A congestion (`>= 90`) |
| `severity` | str | `critical`, `high`, `medium`, `low` | attention-first ordering |
| `flap_count` | int | 6 on the scripted flap, 1 on singles | Link Flaps tile (`sum`), A link flapping |
| `source` | str | `nexus` | table |
| `detail` | str | `flaps=6 in 10m` | table label |

### `cisco:nexus:config`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `device` | str | `dc1-leaf-112` | D network table (`anomaly = "config change: ".change`), A configuration drift |
| `user` | str | `netops-jrivera` | table, alert |
| `change` | str | `qos policy` | table, alert |
| `diff_summary` | str | `policy-map QOS-AI-FABRIC: class AI-ROCE cs3 no-drop -> drop` | drilldown |
| `session_id` | str | 8 hex | drilldown |
| `source` | str | `nexus` | table |

### `ai:path:test`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `probe` | str | `probe-dc1`, `probe-dc2` (aliased to `device`) | table |
| `target` | str | `api.model-provider.example`, `users-west`, `cloud-east` (aliased to `peer`) | p95 Latency to Model APIs tile |
| `latency_ms` | float | 182.0 (322 on the 13:55 excursion) | tile, table |
| `loss_pct` | float | 0.0 | drilldowns |
| `hops` | int | 12 | drilldowns |
| `slow_hop` | int or null | 9 | table (`latency +140 ms at hop 9`) |
| `slow_hop_delta_ms` | int | 140 | table |
| `source` | str | `path_test` | table |

## Index `ai_platform`

### `kube:events`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `reason` | str | `OOMKilled`, `NodeNotReady`, `CrashLoopBackOff`, `Evicted`, `BackOff`, `Scheduled`, `Pulled`, `SlowQueries` | Pod Restarts tile, restarts chart, table, A restart storm |
| `namespace` | str | `inference`, `retrieval`, `mlops` | namespace filter |
| `pod` | str | `med-advisor-v41-7c9f4` | table, A restart storm |
| `workload` | str | `med-advisor-v41`, `vector-db-2` | workload filter, table |
| `kind` | str | `inference`, `data service`, `evaluation`, `fine-tuning` | table |
| `node` | str | `dc1-ucs-gpu-07`, `dc1-ucs-cpu-03` | table, node timeline |
| `message` | str | free text | node timeline |
| `impact` | str | `replica lost, 47 min degraded`, `restarted x3`, `retrieval timeouts` | table |
| `restart_count` | int | 3 on the OOMKilled row, 0 on informational events | Pod Restarts tile (`sum`) |
| `severity` | str | `high` on the 14:44-14:50 rows, `medium` on job rows, `low` | attention-first ordering |
| `type` | str | `Warning`, `Normal` | drilldowns |

### `ai:inference:server`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `model_server` | str | `med-advisor-v41`, `claims-v12`, `coder-v9` (aliased to `model`) | queue chart, Inference Replicas |
| `ai_pod` | str | `aipod-dc1` | filters |
| `replicas_running` | int | 96 / 56 / 32 (182 total for 47 min after 14:50) | Inference Replicas Running (`latest BY model_server`, sum) |
| `queue_depth` | int | 10 baseline, 40 at the peak | queue chart |
| `queue_time_p95_ms` | int | 400 to 2,600 | p95 Queue Time, A queue build-up (`> 1500`) |
| `batch_size` | int | 16 | drilldowns |
| `kv_cache_util_pct` | float | 71.4 | drilldowns |
| `pending_gpu_pods` | int | 8 / 3 / 1 at the peak | Pending GPU Pods |
| `requests_per_s` | float | 5.6 | drilldowns |

### `ai:job:lifecycle`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `job_id` | str | `eval-reasoning-v41-0089`, `ft-claims-v13-s002` | Failed Jobs (`dc`), table, evidence drilldown |
| `kind` | str | `fine-tuning`, `evaluation` | table |
| `state` | str | `queued`, `running`, `checkpointing`, `retrying`, `completed`, `failed`, `preempted` | Failed Jobs, table, A job failed |
| `node` | str | `lab-ucs-gpu-09` | table, node timeline |
| `ai_pod` | str | `aipod-lab` | filters |
| `gpu_hours` | float | 512 on the stalled fine-tune | alert key field |
| `gpus` | int | 8 | drilldowns |
| `reason` | str or null | `HARNESS_EXIT_1`, `CHECKPOINT_IO_STALL`, `CUDA_OOM`, `PREEMPTED` | table |
| `queue_wait_s` | int | 5400 | Velocity drilldowns |
| `workload` | str | `eval-suite-v41` | cost joins |
| `severity` | str | `medium` on scripted failures | ordering |

## Index `ai_application`

### `gen_ai:request`

Per-minute aggregate rows (28 streams per minute carrying `request_count`) plus singleton rows (`request_count=1`) for failed requests, guardrail hits and the detailed incident rows; the row kind field below tells them apart.

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `gen_ai.app` | str | `medadvice-chat`, `claims-agent`, `search-rag`, `code-assist` (aliased to `app`) | D applications (filter, chart, table), A apps |
| `gen_ai.request.model` | str | `med-advisor-v41`, `med-advisor-v40`, `claims-v12`, `rag-embed-v7`, `coder-v9`, `provider-api-large` (aliased to `model`) | D applications, D models (Safety, Groundedness, Hallucination) |
| `gen_ai.system` | str | `self-hosted`, `provider` | Token Spend (provider only carries cost) |
| `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` | int | 3,100 / 900 (provider ~40K) | Token Usage chart |
| `trace_id` | str 12 hex | `7f3a9c1e04b2` | table, cross-sourcetype drilldown |
| `session_id` | str 16 hex | | drilldowns |
| `user_id` | str | `u_` + 12 hex (hashed) | drilldowns |
| `ttft_ms` | int | 480 baseline, ~1,400 in 13:00-15:00 | p95 Time-to-First-Token, TTFT chart, A TTFT regression |
| `latency_ms` | int | 1,900 | drilldowns |
| `retrieval_ms` | int or `timeout` | 140; `timeout` on medadvice rows after 14:44 | table, A retrieval timeouts |
| `status` | str | `ok`, `error`, `timeout` | Availability, A error rate |
| `guardrail` | str | `pass`, `flagged:hallucination`, `blocked:prompt_injection`, `blocked:pii` | table |
| `cost_usd` | float | 0.12 on provider rows, 0 self-hosted | Token Spend (24h) |
| `quality.hallucination_flag` | int 0/1 | | Hallucination Rate, hallucination chart, A quality drift |
| `hallucination_count` | int | flagged responses inside the aggregate | hallucination chart (per 1,000) |
| `quality.groundedness` | float | 0.961 (stored as a fraction; tiles multiply where needed) | Groundedness |
| `quality.safety_score` | float | 0.992 | Safety Compliance, A safety compliance |
| `business_unit` | str | `customer-care`, `claims`, `engineering` | business-unit filters |
| `cost_center` | str | `CC-5102` | cost joins |
| `node` | str | serving node | node timeline |
| `request_count` | int | 61 at 14:00, 19 at 02:00, 1 on singletons | Requests, Availability, Hallucination Rate |
| `row_kind` | str | `minute` (aggregate), `detail` (incident rows) | table (`detail` rows only) |
| `prompt_hash` / `prompt_len` | str 16 hex / int | never the prompt itself | drilldowns |

### `gen_ai:agent:run`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `gen_ai.agent.name` | str | `claims-intake-agent`, `care-navigator`, `it-helpdesk-agent`, `policy-qa-agent`, `scheduling-agent` (aliased to `agent`) | D agents (filter, completion bar, table), A agents |
| `trace_id` | str | `c41e77a09b3d` | table, steps drilldown |
| `session_id` | str | | drilldowns |
| `steps` | int | 41 on the loop run, mean 6.4 | Avg Steps per Task, table, A runaway loop (`> 30`) |
| `tool_calls` | int | 38 | table |
| `tool_call_failures` | int | 31 | drilldowns |
| `top_tool` / `top_tool_calls` | str / int | `claims_api` / 31 (renders `38 (claims_api x31)`) | table |
| `outcome` | str | `completed`, `escalated_to_human`, `loop_stopped`, `blocked:guardrail`, `abandoned` | Task Completion, Runaway Loops Stopped, outcome filter, A task completion, A runaway loop |
| `tokens` | int | 212,480 | table, A runaway token spend |
| `cost_usd` | float | 3.12 | table, A runaway token spend (`> 2`) |
| `duration_ms` | int | | drilldowns |
| `gen_ai.request.model` | str | model used by the agent | drilldowns |
| `business_unit` | str | | filters |
| `tools_used` | array | `["search_kb","claims_api"]` | drilldowns |

### `gen_ai:agent:step`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `gen_ai.agent.name` | str | aliased to `agent` | Tool Call Failures |
| `trace_id` | str | joins the run | steps drilldown |
| `step_no` | int | 1 … 41 | steps drilldown |
| `gen_ai.operation.name` | str | `execute_tool`, `chat` (aliased to `operation`) | Tool Call Failures, tool-calls chart |
| `gen_ai.tool.name` | str or null | `search_kb`, `claims_api`, `ehr_lookup`, `send_notification` (aliased to `tool`) | tool-calls chart |
| `status` | str | `ok`, `error` | Tool Call Failures |
| `error_type` | str or null | `http_503`, `timeout`, `schema_error` | steps drilldown |
| `duration_ms` / `tokens` | int | | steps drilldown |

### `gen_ai:guardrail`

Only `flagged` and `blocked` verdicts are emitted (1,906 per day); `pass` is implied by the request rows.

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `trace_id` | str | matches the request | cross-sourcetype drilldown |
| `gen_ai.app` | str | aliased to `app` | Guardrails Triggered, A guardrail surge |
| `gen_ai.request.model` | str | | drilldowns |
| `verdict` | str | `flagged`, `blocked` | Guardrails Triggered, Prompt Injections Detected |
| `category` | str | `hallucination`, `prompt_injection`, `pii`, `toxicity`, `policy` | Prompt Injections Detected, A prompt-injection campaign |
| `technique` | str | `instruction_override`, `role_play_jailbreak`, `encoded_payload`, `indirect_via_document`, `system_prompt_leak` (prompt injection only) | injections-by-technique bar |
| `src` | str | `203.0.113.10` | A prompt-injection campaign, security drilldown |
| `user` | str | `probe@example.com` | security drilldown |
| `action_taken` | str | `blocked_response`, `flag_for_review` | drilldowns |

## Index `ai_model_eval`

### `ai:eval:run`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `job_id` | str | `eval-reasoning-v41-0089` | table `evidence`, drilldown |
| `model_version` | str | `med-advisor-v41` (model filter) | table, pass-rate chart |
| `model` | str | `med-advisor` (base name, not aliased) | filters |
| `version` | str | `v37` … `v41` (`version_tag` calculated as fallback) | version filter, pass-rate chart |
| `suite` | str | `safety`, `reasoning`, `coding`, `groundedness` | Score Drift (`suite=reasoning`), chart, table |
| `pass_rate` | float % | 91.9 | Evaluation pass rate, chart, table |
| `baseline_pass_rate` | float % | 94.0 | drilldown |
| `delta_vs_baseline` | float pts | -2.1 | Score Drift vs Baseline, table, A evaluation regression |
| `status` | str | `regression`, `within_band`, `improved`, `watch` | table ordering, A evaluation regression |
| `evidence` | str | = `job_id` | table drilldown |
| `cycle_time_h` | float | 4.2 | Evaluation Cycle Time |
| `queue_wait_h` | float | 1.5 | Velocity drilldowns |
| `cases` | int | 2400 | drilldown |
| `node` | str | `lab-ucs-gpu-04` | node timeline |

## Index `ai_cost`

### `ai:cost:daily`

One row per workload per day (the seven spec workloads plus the small dc2 workloads `serve-med-advisor-v40`, `serve-policy-qa-v3`, `dev-notebooks`) and one `workload=unallocated` row per AI POD carrying the idle hours.

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `day` | str | `2026-09-17` | daily chart |
| `workload` | str | `serve-med-advisor-v41`, `unallocated` | Top Workloads table, drilldown |
| `business_unit` | str | `customer-care`, `claims`, `engineering`, `data-science` | GPU-Hours by Business Unit, BU filter, A spend spike |
| `cost_center` | str | `CC-5102` | table |
| `kind` | str | `inference`, `evaluation`, `fine-tuning`, `unallocated` | table, Tokens per GPU-Second (`kind=inference`) |
| `ai_pod` | str | `aipod-dc1` | `gpu_rate_card` lookup, Idle GPU-Hours filter |
| `gpu_hours` | float | 3072.0 (0 on unallocated rows) | GPU-Hours Allocated (7d), table, A idle reservation |
| `idle_gpu_hours` | float | 0 on workload rows; unallocated GPUs x 24 on the idle rows | Idle GPU-Hours (7d), A idle reservation |
| `avg_gpu_util` | float % | 58.0 | table, A idle reservation |
| `usd_per_gpu_hour` | float | 2.40 (the lookup value wins when present) | est cost |
| `est_cost_usd` | float | 7372.8 | table, A spend spike |

### `ai:cost:tokens`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `day` | str | `2026-09-17` | 7-day sums |
| `model` | str | `provider-api-large`, `med-advisor-v41`, `claims-v12`, `coder-v9`, `rag-embed-v7` | Cost per 1M Tokens bar, Model API Spend |
| `gen_ai.system` | str | `provider`, `self-hosted` (`self_hosted` calculated 0/1) | Cost per 1M Tokens (self-hosted) |
| `tokens_millions` | float | 412.5 | Cost per 1M Tokens, Tokens per GPU-Second |
| `cost_usd` | float | 30,300 per day on the provider row | Model API Spend (7d), Cost per 1M Tokens |
| `cost_per_1m_tokens` | float | 3.00 / 1.32 / 0.71 / 0.64 / 0.12 | bar chart |
| `gpu_seconds` | float | serving compute attributed to the tokens (total = tokens / 2,140) | Tokens per GPU-Second |

## Index `ai_security`

### `aws:cloudtrail:sim`, `k8s:audit:sim`, `iam:sim` (raw events)

| Field | Type | Sourcetype | Values / example | Used by |
|---|---|---|---|---|
| `user` | str | all | `svc-mlops-ci`, `maya.okonkwo@buttercupgames.com` | user filter, security drilldown, A security (all) |
| `src` | str | all | `10.42.17.88`, `198.51.100.20` | drilldown |
| `action` | str | all | `s3:GetObject`, `egress`, `kubectl exec`, `assume_role`, `api_key.created` | A first-seen weights, A credential misuse, A data movement |
| `object` | str | all | `weights/med-advisor-v41/`, `bucket/rag-corpus-clinical`, `pod/med-advisor-v41-7c9f4`, `role/weights-reader`, `model-registry/prod` | alerts, findings |
| `environment` | str | all | `production` (aliased to `env`) | environment filter |
| `outcome` | str | all | `success`, `denied` | drilldown |
| `bytes_out` | int | cloudtrail | 44023414784 (41 GB; `bytes_out_gb` calculated) | A data movement (`> 10737418240`) |
| `asn` / `asn_new` | int / bool | cloudtrail | 16509 / true | A data movement |
| `first_seen` | bool | cloudtrail, iam | true on the scripted weights read and role assumption | A first-seen weights, A credential misuse |
| `region` | str | cloudtrail | `us-west-2` | drilldown |
| `namespace` | str | k8s | `inference` | drilldown |
| `off_hours` | bool | k8s | true on the 14:37 exec | A credential misuse |

### `ai:security:finding`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `finding_id` | str | `F-20260918-0007`; alerts derive the same id from `user.action.object.day` so reruns dedup | Open Findings (`latest(status) BY finding_id`), category tiles (`dc`) |
| `user` / `src` / `action` / `object` | str | as in the raw events; `action` is the display label (`s3:GetObject (first seen)`, `prompt_injection x38`) | Recent Findings table, drilldown |
| `risk_score` | int | 80, 75, 70, 65, 60, 40 | table colour (red >= 75, orange >= 60, yellow >= 40) |
| `rule` | str | the alert title, e.g. `AI Security - First-seen access to model weights` | findings-by-rule chart |
| `category` | str | `model_asset_access`, `credential_misuse`, `data_movement`, `off_hours_admin`, `prompt_injection` | Model Asset Access Anomalies, Credential Misuse, Data Movement Alerts, stacked chart |
| `mitre_technique` | str | `T1530`, `T1078`, `T1567`, `AML.T0051` | table drilldown, ES annotations |
| `status` | str | `open`, `closed` | Open Findings |
| `triage_disposition` | str | `true_positive`, `needs_review`, `benign` | table |
| `owner` | str | `soc-tier1`, `soc-tier2` | table |
| `environment` | str | `production` (aliased to `env`) | environment filter |
| `scoreboard` | str | `security` | Security scoreboard |
| `risk_object` / `risk_object_type` | str | = `user` / `user` (calculated for ES) | ES risk events |

## Index `ai_summary`

### `ai:scoreboard`

Written by the five `AI Scoreboard - *` rollups every 15 minutes, seeded with 60 days of daily history (plus a weekly GPU-utilization series 54.1 to 61.8).

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `scoreboard` | str | `reliability`, `velocity`, `efficiency`, `trust`, `security` | executive tiles, landing page |
| `metric` | str | `Availability`, `p95 time-to-first-token`, `Degraded nodes`, `Congested links`, `Pilot to production`, `Evaluation cycle time`, `Evaluation pass rate`, `GPU utilization`, `Idle GPU-hours`, `Token spend`, `Safety compliance`, `Hallucination rate`, `Guardrails triggered`, `Open findings`, `Model asset access anomalies`, `Prompt injections detected` | executive tiles |
| `value` | float | 99.93 | executive tiles, GPU utilization vs target chart, smoke equality check |
| `unit` | str | `pct`, `ms`, `count`, `days`, `h`, `usd`, `gpu_h` | tiles |
| `window` | str | `24h`, `7d`, `30d` | tiles |
| `business_unit` / `environment` | str | `all` / `production` | executive filters |

### `ai:incident`

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `week` | str | `2026-W37` | incidents chart |
| `week_start` | str | `2026-09-07` | incidents chart (`timechart span=1w`) |
| `root_cause_layer` | str | `compute`, `network`, `platform`, `application`, `model` | incidents chart |
| `count` | int | weekly totals 31, 29, 27, 24, 22, 20, 18 | incidents chart |

### `ai:alert`

Written by the `logevent` action of every alert (one event per result).

| Field | Type | Values / example | Used by |
|---|---|---|---|
| `search_name` | str | the alert title | smoke alert coverage, landing page |
| `severity` | str | `low`, `medium`, `high`, `critical` | drilldowns |
| `layer` | str | `compute` … `security`, `cost` | drilldowns |
| `dashboard` | str | owning dashboard id | drilldowns |
| key fields | mixed | `node`, `gpu`, `device`, `interface`, `pod`, `gen_ai.app`, `trace_id`, `user`, `src`, … per alert | drilldowns |

## Aliases and calculated fields (`default/props.conf`)

| Sourcetype | Field | Source | Definition |
|---|---|---|---|
| every sourcetype | `layer` | EVAL | constant per sourcetype (`compute`, `network`, `platform`, `application`, `model`, `agent`, `efficiency`, `security`, `summary`) |
| every sourcetype | `layer_no`, `dashboard` | LOOKUP | `ai_layer_map sourcetype OUTPUTNEW layer_no dashboard` |
| `ai:gpu:fault` | `fabric_link_id` | EVAL | `fabric_link` (joins Nexus events) |
| `ai:gpu:fault` | `fault_type` | EVAL | `ecc_dbe`, `ecc`, `xid`, `nvlink`, `thermal_throttle`, `power_cap_throttle`, `other` |
| `ai:gpu:fault`, `kube:events`, `ai:job:lifecycle`, `gen_ai:request`, UCS | `server_model`, `gpu_model`, `leaf_switch`, `leaf_port`, `cost_center` | LOOKUP | `ai_node_inventory node OUTPUTNEW …` |
| `cisco:ucs:*` | `node` | FIELDALIAS | `server AS node` |
| `cisco:nexus:interface`, `cisco:nexus:anomaly` | `node` | EVAL | `coalesce(peer, null())` (switch rows keep `device`) |
| `cisco:nexus:interface`, `cisco:nexus:anomaly` | `fabric_link_id` | EVAL | `device.":".interface` |
| `cisco:nexus:*` | `ai_pod`, `fabric` | EVAL | from the `device` prefix (`dc1-`, `dc2-`, `lab-`) |
| `cisco:nexus:interface` | `pfc_pause_total`, `throughput_gbps` | EVAL | `rx+tx`; `(in+out)/200 x speed_gbps` |
| `cisco:nexus:anomaly` | `anomaly_type` | EVAL | folds `ecn_marked_packets high` into `congestion`, `optic rx power low` into `optic` |
| `cisco:nexus:config` | `anomaly` | EVAL | `"config change: ".change` |
| `ai:path:test` | `device`, `peer`, `anomaly` | EVAL | `probe`; `target`; `"latency +<delta> ms at hop <n>"` |
| `ai:inference:server` | `model`, `workload` | FIELDALIAS / EVAL | `model_server AS model`; `"serve-".model_server` |
| `ai:job:lifecycle` | `workload` | EVAL | `job_id` |
| `gen_ai:request` | `app`, `model`, `input_tokens`, `output_tokens` | FIELDALIAS | from the `gen_ai.*` fields |
| `gen_ai:request` | `total_tokens`, `is_error`, `error_count`, `retrieval_timeout` | EVAL | token sum; `status IN (error,timeout)`; `error_count` weighted by `request_count` |
| `gen_ai:request`, `gen_ai:guardrail` | `owner`, `tier`, `in_customer_path` | LOOKUP | `ai_application_catalog gen_ai.app OUTPUTNEW …` |
| `ai:eval:run` | `version_tag` | EVAL | `coalesce(version, <suffix of model_version>)` |
| `gen_ai:agent:run` | `agent`, `completed`, `tool_calls_label` | FIELDALIAS / EVAL | `gen_ai.agent.name AS agent`; `outcome=="completed"`; `38 (claims_api x31)` |
| `gen_ai:agent:step` | `agent`, `tool`, `operation` | FIELDALIAS | `gen_ai.agent.name`, `gen_ai.tool.name`, `gen_ai.operation.name` |
| `ai:cost:daily` | `ai_pod`, `rate_card_usd_per_gpu_hour` | EVAL / LOOKUP | POD inferred from the workload when absent; `gpu_rate_card ai_pod OUTPUTNEW usd_per_gpu_hour` |
| `ai:cost:tokens` | `self_hosted` | EVAL | `model!="provider-api-large"` |
| security sourcetypes | `env` | FIELDALIAS | `environment AS env` |
| `aws:cloudtrail:sim` | `bytes_out_gb` | EVAL | `round(bytes_out/1073741824)` |
| `ai:security:finding` | `risk_object`, `risk_object_type` | EVAL | `user`; `"user"` |

Event types `ai_layer_compute` … `ai_layer_agent` (index + sourcetype searches, no pipes) carry tags `ai_layer` and the layer name (`compute`, `network`, `platform`, `application`, `model`, `agent`) through `tags.conf`.
