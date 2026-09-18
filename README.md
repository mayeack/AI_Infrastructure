# AI Infrastructure Monitoring

`ai_infra_monitoring` is a self-contained Splunk app that demonstrates full-stack monitoring for enterprise AI: Cisco UCS servers, Cisco AI PODs and Cisco Nexus fabrics at the base, Kubernetes and inference serving in the middle, applications, models and agents on top, with cost and security cutting across every layer. It ships its own deterministic data generator, ten Dashboard Studio dashboards, 25 alerts, five scoreboards and one incident that recurs every day from 12:45 to 15:00 local time so "Last 24 hours" always tells the story.

Version 1.0.0. Apache-2.0. Works on Splunk Enterprise 9.x/10.x and Splunk Cloud Platform (HEC mode); last regression-tested on Splunk Enterprise 10.4.3 on 2026-09-18 (section 12). Requires no other app; Splunk Enterprise Security and the AI Toolkit are optional.

## Before the demo

- The 7-day security tiles (Model Asset Access Anomalies, Credential Misuse, Data Movement Alerts, Prompt Injections Detected) count the last seven complete days (`latest=@d` inside their macros), so they read the same all day.

- Run `make backfill` the morning of the demo (2 to 3 minutes over HEC). It runs the generator with `--resume`, which asks Splunk which five-minute buckets already exist per sourcetype and generates only the missing ones, so it is safe with the streaming inputs on; `make backfill BACKFILL_FLAGS=--force` reloads everything into empty indexes. The last 24 hours are generated at
  1-minute resolution and every tile is calibrated for the "Last 24 hours" window; after a day without
  the streaming inputs the window slides into the 5-minute tier and the tiles drift by a few percent.
- `make smoke` proves every dashboard search, the 14 headline KPIs and the alert coverage
  (`make smoke SMOKE_FLAGS=--dispatch-alerts` re-fires the 25 alerts at the last incident).
- `make enable-es` turns on the four Enterprise Security rules; risk events carry the incident-day
  timestamps, so check `index=risk` with a window that covers that day (for example Last 7 days).
- Dashboard PNG exports made with Dashboard Studio's Download > PNG live in `dist/screenshots/`.

## 1. What it shows

Six layers, drawn bottom-up on the landing page (`ai_stack_overview`), each with its own dashboard:

| Layer | Dashboard | What the audience sees |
|---|---|---|
| 01 Compute and storage (Cisco UCS servers, Cisco AI PODs) | `ai_infrastructure_health` | 512 GPUs, utilization, idle GPU-hours, degraded nodes, ECC/Xid faults |
| 02 Network (Cisco Nexus switches) | `ai_network_fabric` | 1,152 fabric links, congestion, PFC storms, link flaps, path latency to model APIs |
| 03 Platform | `ai_platform_workloads` | inference replicas, pod restarts, pending GPU pods, queue time, failed jobs |
| 04 Applications | `ai_applications` | requests, availability, time-to-first-token, token spend, guardrails |
| 05 Models | `model_performance_quality` | safety compliance, groundedness, hallucination rate, evaluation evidence |
| 06 Agents | `ai_agents` | agent runs, task completion, steps, tool-call failures, runaway loops |
| Cost | `ai_cost_unit_economics` | GPU-hours by business unit, cost per 1M tokens, model API spend |
| Security | `ai_security_posture` | open findings, model asset access, credential misuse, data movement, prompt injection |
| Executive | `ai_operations_executive_overview` | five scoreboards, incidents by root-cause layer, GPU utilization vs target, top risks |

Layers 01 and 02 are Cisco hardware, tightly integrated with Splunk. Every event the generator writes carries `host=ai-demo-generator` so the demo data can be removed with one search.

## 2. The estate the data describes

Three Cisco AI PODs, 512 GPUs, 1,152 monitored fabric links, 86,016 GPU-hours per week of which about 68.9K are allocated and 17.1K idle, at a blended $2.40 per GPU-hour (`gpu_rate_card.csv`, editable).

| AI POD | Role | Nodes | GPUs | Node names | Leaf switches |
|---|---|---|---|---|---|
| `aipod-dc1` | production inference | 24 x 8 GPUs | 192 | `dc1-ucs-gpu-01` … `dc1-ucs-gpu-24`, plus `dc1-ucs-cpu-01..04` (data services) | `dc1-leaf-111` … `dc1-leaf-114`, spines `dc1-spine-01`, `dc1-spine-02` |
| `aipod-dc2` | production inference | 24 x 8 GPUs | 192 | `dc2-ucs-gpu-01` … `dc2-ucs-gpu-24`, `dc2-ucs-cpu-01..04` | `dc2-leaf-201` … `dc2-leaf-208`, spines `dc2-spine-01/02` |
| `aipod-lab` | evaluation and fine-tuning | 16 x 8 GPUs | 128 | `lab-ucs-gpu-01` … `lab-ucs-gpu-16` | `lab-leaf-151` … `lab-leaf-158` |

Applications and models: `medadvice-chat` (`med-advisor-v41`, prior `med-advisor-v40`, customer-care, CC-5102, uses retrieval from `vector-db-2`), `claims-agent` (`claims-v12`, claims, CC-4523), `search-rag` (`rag-embed-v7`, customer-care, CC-5102), `code-assist` (`coder-v9`, engineering, CC-6010) and an intelligence provider's API (`provider-api-large`, $3.00 per 1M tokens). Agents: `claims-intake-agent`, `care-navigator`, `it-helpdesk-agent`, `policy-qa-agent`, `scheduling-agent` with tools `search_kb`, `claims_api`, `ehr_lookup`, `send_notification`.

Workloads for cost attribution (7-day GPU-hours at $2.40): `serve-med-advisor-v41` 21,504 ($51,610, 58%), `serve-claims-v12` 13,440 ($32,256, 63%), `serve-coder-v9` 8,064 ($19,354, 44%), `ft-claims-v13` 6,720 ($16,128, 81%), `eval-suite-v41` 3,072 ($7,373, 38%), `serve-rag-embed-v7` 2,688 ($6,451, 71%), `eval-suite-c13` 1,024 ($2,458, 41%). Job taxonomy, always in this order: training and fine-tuning, model evaluation, inference.

## 3. The incident that threads through every dashboard

Cause at the bottom of the stack, symptom at the top. Times are local (`America/Los_Angeles` on the reference box); the generator replays the same script every day and `--fire-incident` compresses it into 20 minutes.

| Time | Layer | Where | What | Sourcetype |
|---|---|---|---|---|
| 14:12 | 02 Network | `dc1-leaf-112` | configuration change: QoS policy edit by `netops-jrivera` (AI-ROCE class no-drop to drop) | `cisco:nexus:config` |
| 14:38 | 02 Network | `dc1-spine-02 Eth2/05` toward `dc1-leaf-112` | ECN-marked packets high, utilization 94% | `cisco:nexus:anomaly` |
| 14:41 | 02 Network | `dc1-leaf-112 Eth1/31` (peer `dc1-ucs-gpu-21`) | PFC pause storm, utilization 97%; PFC pause frames for the day about 38.2K | `cisco:nexus:anomaly`, `cisco:nexus:interface` |
| 14:49 | 02 Network | `dc1-leaf-112 Eth1/14` (peer `dc1-ucs-gpu-07`) | link flaps x6 in 10 minutes | `cisco:nexus:anomaly` |
| 14:49 / 14:52 | 01 Compute | `dc1-ucs-gpu-07 GPU5` | `xid_79_fallen_off_bus` at 91 C, then `ecc_dbe_volatile` at 88 C; node marked degraded (3 degraded nodes with `dc2-ucs-gpu-19` thermal throttle at 14:31 and `lab-ucs-gpu-04` xid_48 at 13:40); about 41 ECC/Xid errors for the day | `ai:gpu:fault`, `ai:gpu:metrics` |
| 14:49-14:50 | 03 Platform | `med-advisor-v41-5b21d`, `med-advisor-v41-7c9f4` | OOMKilled (restarted x3); NodeNotReady on `dc1-ucs-gpu-07` (replica lost, 47 minutes degraded); 37 restarts, 12 pending GPU pods, p95 queue time 1.8 s, 184 replicas | `kube:events`, `ai:inference:server` |
| 14:44 | 03 Platform | `vector-db-2` (`retrieval`, `dc1-ucs-cpu-03`) | slow queries p95 2.4 s, retrieval timeouts begin | `kube:events` |
| 13:00-15:00 | 04 Applications | `medadvice-chat` | p95 time-to-first-token climbs from ~500 ms to ~1,400 ms (24 h p95 820 ms), `retrieval_ms=timeout`, availability dips but stays 99.93% over 24 h; 1.28M requests, $30.3K token spend, 1,906 guardrails triggered | `gen_ai:request`, `gen_ai:guardrail` |
| 13:00-15:00 | 05 Models | `med-advisor-v41` | hallucination flags per 1,000 responses rise from ~15 to ~40, groundedness dips; 24 h hallucination rate 1.8%, groundedness 96.1%, safety compliance 99.2% | `gen_ai:request` |
| 13:40 | 05 Models | `eval-reasoning-v41-0089` | reasoning suite 91.9% pass, -2.1 points vs baseline, status `regression`; safety 99.2 (within_band), coding 92.6 (improved), groundedness 96.1 (watch); cycle time 4.2 h | `ai:eval:run` |
| 13:00-14:57 | 06 Agents | `claims-intake-agent` run `c41e77a09b3d` | loops on `claims_api` failures: 41 steps, 38 tool calls (claims_api x31), 212,480 tokens, $3.12, `loop_stopped`; 48,320 runs, 93.8% completion, 1,204 tool-call failures, 37 loops stopped | `gen_ai:agent:run`, `gen_ai:agent:step` |
| 08:49-14:41 | Security | seven findings, newest first | `svc-mlops-ci` first-seen `s3:GetObject` on `weights/med-advisor-v41/` (80); `maya.okonkwo@buttercupgames.com` off-hours `kubectl exec` (65); `probe@example.com` from `203.0.113.10` prompt_injection x38 (80) and x21 (70); `svc-eval-runner` egress 41 GB to a new ASN (75); `j.alvarez@buttercupgames.com` `api_key.created` (40); `svc-mlops-ci` `assume_role` new principal (60). Seven-day totals: 22 open, 7 model asset access, 3 credential misuse, 12 data movement, 214 prompt injections | `ai:security:finding`, `aws:cloudtrail:sim`, `k8s:audit:sim`, `iam:sim`, `gen_ai:guardrail` |

Everything outside the window is calm and diurnal (peak around 14:00, trough around 02:00). The same `trace_id` joins an application request, its retrieval call, the agent run that made it and any guardrail event it produced.

## 4. Install

### Splunk Enterprise (single instance, default)

```bash
cd $SPLUNK_HOME/etc/apps/ai_infra_monitoring
cp .env.example .env        # add SPLUNK_USERNAME/SPLUNK_PASSWORD or SPLUNK_TOKEN (git-ignored, never packaged)
make install                # restart, wait for splunkd, check the nine indexes exist
make hec-setup              # create the ai_infra_demo HEC token, record it in .env, probe it
make backfill               # 30 days of history over HEC (10-20 min), then the generator self-check
make smoke                  # every dashboard query, the 14 headline KPIs, alerts, scoreboards, tables
```

The app creates the indexes (`default/indexes.conf`). The scripted-input stanzas in `default/inputs.conf` are all disabled so the package passes AppInspect for Splunk Cloud; on Splunk Enterprise run `make enable-stream` to switch on the metrics feed and the four biggest event feeds (`ai:gpu:metrics`, `gen_ai:request`, `cisco:nexus:interface`, `gen_ai:agent:run`, `gen_ai:agent:step`) through `local/inputs.conf`, or `make enable-stream ALL=1` to switch on all 25 feeds so every rolling window stays complete after the backfill ages (recommended on a demo instance). Alternatively keep everything off and run `bin/ai_demo_generator.py --stream --hec ... --token ...` from a shell.

Without `.env` credentials `make install` restarts through the CLI, `make hec-setup --file-provision` (or `tools/hec_setup.py --file-provision`) writes the token into `splunk_httpinput/local/inputs.conf` between `# BEGIN ai-infra-monitoring` / `# END ai-infra-monitoring` markers, and smoke and alert verification are left for you.

If the app directory is somewhere else, `make install` rsyncs it into `$SPLUNK_HOME/etc/apps/ai_infra_monitoring` first (excluding `local/`, `.env` and `dist/`).

### Splunk Cloud Platform

Scripted inputs in a private app need vetting, so the generator runs on any host and sends to an HEC token. `bin/hec_setup.md` walks through the nine indexes, the `ai_infra_demo` token, the probe, then:

```bash
bin/ai_demo_generator.py --backfill 30d --hec https://<stack>.splunkcloud.com:8088 --token $AI_DEMO_HEC_TOKEN --seed 20260916
bin/ai_demo_generator.py --stream   --hec https://<stack>.splunkcloud.com:8088 --token $AI_DEMO_HEC_TOKEN --seed 20260916
```

`make package && make appinspect` produce `dist/ai_infra_monitoring-1.0.0.tgz` and `dist/appinspect.json` (`--mode precert --included-tags cloud`, zero errors).

## 5. Fire the incident live

```bash
make fire-incident          # = bin/ai_demo_generator.py --fire-incident --hec $HEC_URL --token $AI_DEMO_HEC_TOKEN --seed 20260916
```

The generator maps every scripted timestamp `t` to `now + (t - 12:45) x 20/135` and streams the ramped feeds at a 10-second cadence for 20 minutes, so `span=1m` charts show the ramp, the link flaps, the GPU faults and the pod restarts arriving in order. Keep the dashboards on "Last 60 minutes" while it runs; the seven security findings and the looping agent run appear with their real ids so the drilldowns below still work.

## 6. How the numbers are made

Every KPI tile is a macro in `default/macros.conf` that returns one row with a single field `value`. The dashboards, the five scoreboard rollups and `tools/smoke.py` call the same macro, which is why the executive scoreboards equal the layer tiles. Base macros pin the index, sourcetype and `host=ai-demo-generator`: `ai_gpu_metrics`, `ai_gpu_fault`, `ai_nexus_interface`, `ai_nexus_anomaly`, `ai_nexus_config`, `ai_path_test`, `ai_kube_events`, `ai_inference_server`, `ai_job_lifecycle`, `ai_requests`, `ai_agent_runs`, `ai_agent_steps`, `ai_guardrails`, `ai_eval_runs`, `ai_cost_daily`, `ai_cost_tokens`, `ai_security_findings`, `ai_security_raw`, `ai_scoreboard`, `ai_incidents`, `ai_alerts`. Filter arguments default to `*`; the time window comes from the caller.

| Dashboard | KPI | Target | Window | Macro | SPL |
|---|---|---|---|---|---|
| AI Infrastructure Health | GPUs Monitored | 512 | -24h | `ai_kpi_gpus_monitored(pod,node)` | `\| mstats latest(DCGM_FI_DEV_GPU_UTIL) AS u WHERE \`ai_gpu_metrics\` ai_pod IN ($pod$) node="$node$" BY node gpu \| stats count AS value` |
| AI Infrastructure Health | Avg GPU Utilization | 61.8% | -24h | `ai_kpi_gpu_util_avg(pod,node)` | `\| mstats avg(DCGM_FI_DEV_GPU_UTIL) AS value WHERE \`ai_gpu_metrics\` ai_pod IN ($pod$) node="$node$" NOT workload="unallocated" \| eval value=round(value,1)` |
| AI Infrastructure Health | Idle GPU-Hours (7d) | 17.1K | -7d@d | `ai_kpi_idle_gpu_hours_7d(pod)` | `\`ai_cost_daily\` ai_pod IN ($pod$) \| stats sum(idle_gpu_hours) AS value` |
| AI Infrastructure Health | Degraded Nodes | 3 | -24h | `ai_kpi_degraded_nodes(pod,node)` | `\`ai_gpu_fault\` ai_pod IN ($pod$) node="$node$" severity IN (high,critical) \| stats latest(node_state) AS s BY node \| where s="degraded" \| stats count AS value` |
| AI Infrastructure Health | ECC / Xid Errors (24h) | 41 | -24h | `ai_kpi_ecc_xid_errors(pod,node)` | `\`ai_gpu_fault\` ai_pod IN ($pod$) node="$node$" fault IN (ecc_dbe_volatile,ecc_sbe_rate_high,xid_79_fallen_off_bus,xid_48_dbe) \| stats count AS value` |
| AI Network Fabric | Fabric Links Monitored | 1,152 | -30m | `ai_kpi_fabric_links(fabric)` | `\`ai_nexus_interface\` ai_pod IN ($fabric$) \| stats dc(fabric_link_id) AS value` |
| AI Network Fabric | Congested Links | 14 | -24h | `ai_kpi_congested_links(fabric)` | `\`ai_nexus_anomaly\` ai_pod IN ($fabric$) anomaly IN (congestion,pfc_pause_storm,"ecn_marked_packets high") \| stats dc(fabric_link_id) AS value` |
| AI Network Fabric | PFC Pause Frames (24h) | 38.2K | -24h | `ai_kpi_pfc_pause_frames(fabric)` | `\`ai_nexus_interface\` ai_pod IN ($fabric$) \| stats sum(pfc_pause_rx) AS rx sum(pfc_pause_tx) AS tx \| eval value=rx+tx` |
| AI Network Fabric | Link Flaps | 9 | -24h | `ai_kpi_link_flaps(fabric)` | `\`ai_nexus_anomaly\` ai_pod IN ($fabric$) anomaly=link_flap \| stats sum(flap_count) AS value` |
| AI Network Fabric | p95 Latency to Model APIs | 182 ms | -24h | `ai_kpi_p95_model_api_latency` | `\`ai_path_test\` target=api.model-provider.example \| stats perc95(latency_ms) AS value` |
| AI Platform and Workloads | Inference Replicas Running | 184 | -24h | `ai_kpi_inference_replicas(ns)` | `\`ai_inference_server\` \| stats latest(replicas_running) AS r BY model_server \| stats sum(r) AS value` |
| AI Platform and Workloads | Pod Restarts (24h) | 37 | -24h | `ai_kpi_pod_restarts(ns,workload)` | `\`ai_kube_events\` namespace IN ($ns$) workload="$workload$" reason IN (OOMKilled,NodeNotReady,CrashLoopBackOff,Evicted) \| stats sum(restart_count) AS value` |
| AI Platform and Workloads | Pending GPU Pods | 12 | -24h | `ai_kpi_pending_gpu_pods` | `\`ai_inference_server\` \| stats latest(pending_gpu_pods) AS value` |
| AI Platform and Workloads | p95 Queue Time | 1.8 s | -24h | `ai_kpi_p95_queue_time` | `\`ai_inference_server\` \| stats perc95(queue_time_p95_ms) AS ms \| eval value=round(ms/1000,1)` |
| AI Platform and Workloads | Failed Jobs (7d) | 9 | -7d@d | `ai_kpi_failed_jobs_7d` | `\`ai_job_lifecycle\` state=failed \| stats dc(job_id) AS value` |
| AI Applications | Requests | 1.28M | -24h | `ai_kpi_requests(app,model)` | `\`ai_requests\` gen_ai.app IN ($app$) gen_ai.request.model IN ($model$) \| stats sum(request_count) AS value` |
| AI Applications | Availability | 99.93% | -24h | `ai_kpi_availability(app,model)` | `\`ai_requests\` gen_ai.app IN ($app$) gen_ai.request.model IN ($model$) \| stats sum(request_count) AS t sum(eval(if(status="ok",request_count,0))) AS ok \| eval value=round(100*ok/t,2)` |
| AI Applications | p95 Time-to-First-Token | 820 ms | -24h | `ai_kpi_p95_ttft(app,model)` | `\`ai_requests\` gen_ai.app IN ($app$) gen_ai.request.model IN ($model$) \| stats perc95(ttft_ms) AS value \| eval value=round(value,0)` |
| AI Applications | Token Spend (24h) | $30.3K | -24h | `ai_kpi_token_spend(app,model)` | `\`ai_requests\` gen_ai.app IN ($app$) gen_ai.request.model IN ($model$) \| stats sum(cost_usd) AS value` |
| AI Applications | Guardrails Triggered | 1,906 | -24h | `ai_kpi_guardrails_triggered(app)` | `\`ai_guardrails\` gen_ai.app IN ($app$) verdict IN (flagged,blocked) \| stats count AS value` |
| Model Performance and Quality | Safety Compliance | 99.2% | -24h | `ai_kpi_safety_compliance(model)` | `\`ai_requests\` gen_ai.request.model IN ($model$) \| stats avg(quality.safety_score) AS value \| eval value=round(value,1)` |
| Model Performance and Quality | Groundedness | 96.1% | -24h | `ai_kpi_groundedness(model)` | `\`ai_requests\` gen_ai.request.model IN ($model$) \| stats avg(quality.groundedness) AS value \| eval value=round(value,1)` |
| Model Performance and Quality | Hallucination Rate | 1.8% | -24h | `ai_kpi_hallucination_rate(model)` | `\`ai_requests\` gen_ai.request.model IN ($model$) gen_ai.request.model!="rag-embed-v7" \| eval h=coalesce(hallucination_count, 'quality.hallucination_flag'*request_count) \| stats sum(h) AS h sum(request_count) AS n \| eval value=round(100*h/n,1)` (embedding calls carry no generated answer, so `rag-embed-v7` is excluded from the denominator) |
| Model Performance and Quality | Score Drift vs Baseline | -2.1 pts | -24h | `ai_kpi_score_drift` | `\`ai_eval_runs\` suite=reasoning \| sort - _time \| head 1 \| eval value=delta_vs_baseline` |
| Model Performance and Quality | Evaluation Cycle Time | 4.2 h | -7d@d | `ai_kpi_eval_cycle_time` | `\`ai_eval_runs\` \| stats avg(cycle_time_h) AS value \| eval value=round(value,1)` |
| AI Agents | Agent Runs (24h) | 48,320 | -24h | `ai_kpi_agent_runs(agent,outcome)` | `\`ai_agent_runs\` gen_ai.agent.name IN ($agent$) outcome IN ($outcome$) \| stats count AS value` |
| AI Agents | Task Completion | 93.8% | -24h | `ai_kpi_task_completion(agent)` | `\`ai_agent_runs\` gen_ai.agent.name IN ($agent$) \| stats count AS t count(eval(outcome="completed")) AS c \| eval value=round(100*c/t,1)` |
| AI Agents | Avg Steps per Task | 6.4 | -24h | `ai_kpi_avg_steps(agent)` | `\`ai_agent_runs\` gen_ai.agent.name IN ($agent$) outcome=completed \| stats avg(steps) AS value \| eval value=round(value,1)` |
| AI Agents | Tool Call Failures | 1,204 | -24h | `ai_kpi_tool_call_failures(agent)` | `\`ai_agent_steps\` gen_ai.agent.name IN ($agent$) gen_ai.operation.name=execute_tool status=error \| stats count AS value` |
| AI Agents | Runaway Loops Stopped | 37 | -24h | `ai_kpi_runaway_loops(agent)` | `\`ai_agent_runs\` gen_ai.agent.name IN ($agent$) outcome=loop_stopped \| stats count AS value` |
| AI Cost and Unit Economics | GPU-Hours Allocated (7d) | 68.9K | -7d@d | `ai_kpi_gpu_hours_allocated_7d(bu)` | `\`ai_cost_daily\` business_unit IN ($bu$) \| stats sum(gpu_hours) AS value` |
| AI Cost and Unit Economics | Idle GPU-Hours (7d) | 17.1K | -7d@d | `ai_kpi_idle_gpu_hours_7d(pod)` | as above |
| AI Cost and Unit Economics | Cost per 1M Tokens (self-hosted) | $0.84 | -7d@d | `ai_kpi_cost_per_1m_tokens_selfhosted` | `\`ai_cost_tokens\` model!=provider-api-large \| stats sum(cost_usd) AS c sum(tokens_millions) AS m \| eval value=round(c/m,2)` |
| AI Cost and Unit Economics | Model API Spend (7d) | $212K | -7d@d | `ai_kpi_model_api_spend_7d` | `\`ai_cost_tokens\` model=provider-api-large \| stats sum(cost_usd) AS value` |
| AI Cost and Unit Economics | Tokens per GPU-Second | 2,140 | -7d@d | `ai_kpi_tokens_per_gpu_second` | `\`ai_cost_tokens\` model!=provider-api-large \| stats sum(tokens_millions) AS m \| appendcols [\`ai_cost_daily\` kind=inference \| stats sum(gpu_hours) AS h] \| eval value=round(m*1000000/(h*3600),0)` |
| AI Security Posture | Open Findings | 22 | -7d@d | `ai_kpi_open_findings(env,user)` | `\`ai_security_findings\` environment IN ($env$) user="$user$" \| stats latest(status) AS s BY finding_id \| where s="open" \| stats count AS value` |
| AI Security Posture | Model Asset Access Anomalies | 7 | -7d@d | `ai_kpi_model_asset_anomalies(env,user)` | `\`ai_security_findings\` environment IN ($env$) user="$user$" rule=model_asset_access \| stats dc(finding_id) AS value` |
| AI Security Posture | Credential Misuse | 3 | -7d@d | `ai_kpi_credential_misuse(env,user)` | `\`ai_security_findings\` environment IN ($env$) user="$user$" rule=credential_misuse \| stats dc(finding_id) AS value` |
| AI Security Posture | Data Movement Alerts | 12 | -7d@d | `ai_kpi_data_movement_alerts(env,user)` | `\`ai_security_findings\` environment IN ($env$) user="$user$" rule=data_movement \| stats dc(finding_id) AS value` |
| AI Security Posture | Prompt Injections Detected | 214 | -7d@d | `ai_kpi_prompt_injections(env)` | `\`ai_guardrails\` category=prompt_injection verdict=blocked \| stats count AS value` |
| Executive Overview | Reliability: AI Service Availability | 99.93% | -30d@d | `ai_scoreboard_latest(board,metric)` | `\`ai_scoreboard\` scoreboard="$board$" metric="$metric$" \| timechart span=1d latest(value) AS value \| filldown value` (tile shows the last point, sparkline the series) |
| Executive Overview | Velocity: Pilot to Production | 38 d | -30d@d | `ai_kpi_pilot_to_production` | `\| inputlookup ai_application_catalog \| eval d=round((strptime(production_date,"%Y-%m-%d")-strptime(pilot_start_date,"%Y-%m-%d"))/86400) \| stats median(d) AS value` |
| Executive Overview | Efficiency: GPU Utilization | 61.8% | weekly | `ai_scoreboard_latest("efficiency","GPU utilization")` | rollup of `ai_kpi_gpu_util_avg` |
| Executive Overview | Trust: Safety Compliance | 99.2% | -24h | `ai_scoreboard_latest("trust","Safety compliance")` | rollup of `ai_kpi_safety_compliance` |
| Executive Overview | Security: Open Findings | 22 | -7d@d | `ai_scoreboard_latest("security","Open findings")` | rollup of `ai_kpi_open_findings` |

Conventions worth knowing when you read the tiles:

- **Idle vs allocated GPU-hours.** `ai:cost:daily` has one row per workload per day with `gpu_hours` (allocated) and one `workload=unallocated` row per AI POD carrying `idle_gpu_hours`. Allocated = 68.9K/7d, idle = 102 unallocated GPUs x 24 h x 7 d = 17.1K, and the two add up to the 86,016 GPU-hours the fleet has in a week. Utilization is always shown as recovered or idle GPU-hours, never as a fleet-size claim.
- **Avg GPU Utilization** averages the allocated GPUs only (`NOT workload="unallocated"`); unallocated GPUs report 0-3%.
- **Availability and requests** come from per-minute aggregate rows carrying `request_count`; failed requests are singleton rows, so `sum(request_count)` is 1.28M a day and `100 x (1 - errors / requests)` is 99.93%.
- **Token spend** is charged only on `gen_ai.system=provider` requests ($3.00 per 1M tokens), which is why `Token Spend (24h)` ($30.3K) and `Model API Spend (7d)` ($212K) agree. Self-hosted unit economics live in `ai:cost:tokens`.
- **Degraded Nodes** counts nodes whose latest fault carries `node_state=degraded` (the generator sets it on `dc1-ucs-gpu-07`, `dc2-ucs-gpu-19` and `lab-ucs-gpu-04`).
- **Attention-first tables.** Every "needing attention" table ranks rows by severity tier and then newest first (`sort - sev_rank - _time`); models rank `status=regression` first, agents rank `outcome=loop_stopped` first, applications rank guardrail hits and retrieval timeouts first, security is newest first. That is what puts the incident rows at the top even when "Last 24 hours" spans two days.
- **Scoreboards.** `AI Scoreboard - Reliability | Velocity | Efficiency | Trust | Security` run every 15 minutes, call the same macros and `collect` into `index=ai_summary sourcetype=ai:scoreboard` (`scoreboard, metric, value, unit, window`); the executive tiles read `latest(value)` per metric, so tile and rollup can only differ by the 15-minute schedule.

## 7. Demo script

Follow the deck bottom-up: six layer dashboards, then security in three beats, then the executive overview. Each stop has the takeaway to say, the row to click, the drilldown search the click opens (values filled in), and what the audience sees. Default ranges ("Last 24 hours", 7 or 30 days) already contain the incident; if you fired it live, switch to "Last 60 minutes".

### 7.1 AI Infrastructure Health (`ai_infrastructure_health`)

- **Takeaway.** "512 GPUs, 61.8% utilized, 17.1K idle GPU-hours this week, and three degraded nodes: your AI is only as reliable as the hardware it runs on."
- **Row to click.** `dc1-ucs-gpu-07 | aipod-dc1 | GPU5 | xid_79_fallen_off_bus | 91 | dc1-leaf-112:Eth1/14 flapping` (first row of "Nodes Needing Attention").
- **Drilldown SPL.** `` `ai_node_timeline("dc1-ucs-gpu-07")` `` which expands to `(index=ai_infra OR index=ai_network OR index=ai_platform) host=ai-demo-generator "dc1-ucs-gpu-07" | eval layer=case(index=="ai_infra","01 compute",index=="ai_network","02 network",true(),"03 platform"), element=coalesce(fabric_link,pod,gpu,interface), detail=coalesce(fault,anomaly,reason,message) | table _time layer sourcetype node element detail severity | sort 0 _time`.
- **What the audience sees.** One timeline: the six link flaps on `dc1-leaf-112 Eth1/14` (02 network), the Xid 79 and ECC double-bit faults on GPU5 (01 compute), then `med-advisor-v41-7c9f4` NodeNotReady and the OOMKilled restarts (03 platform), all inside twelve minutes.

### 7.2 AI Network Fabric (`ai_network_fabric`)

- **Takeaway.** "The fabric told us first: a QoS change at 14:12 turned into ECN marking, a PFC pause storm and a flapping GPU-facing port before any application alert."
- **Row to click.** `dc1-leaf-112 | Eth1/14 | dc1-ucs-gpu-07 | link_flap x6 in 10 min | 12 | nexus`, then scroll to `dc1-leaf-112 | - | netops-jrivera | config change: qos policy`.
- **Drilldown SPL.** `` `ai_nexus_interface` device="dc1-leaf-112" interface="Eth1/14" | timechart span=1m latest(link_state) AS link_state sum(pfc_pause_rx) AS pfc_rx max(in_util_pct) AS in_util `` (the config row opens `` `ai_nexus_config` device="dc1-leaf-112" | table _time user change diff_summary ``).
- **What the audience sees.** The per-minute interface counters with `link_state` toggling down/up six times between 14:40 and 14:49, and the QoS diff (`AI-ROCE class cs3 no-drop -> drop`) authored 37 minutes earlier by `netops-jrivera`.

### 7.3 AI Platform and Workloads (`ai_platform_workloads`)

- **Takeaway.** "Kubernetes did its job: 184 replicas, 37 restarts, 12 pending GPU pods, but the medadvice deployment ran degraded for 47 minutes while capacity was rebalanced."
- **Row to click.** `med-advisor-v41-7c9f4 | inference | inference | dc1-ucs-gpu-07 | NodeNotReady | replica lost, 47 min degraded`.
- **Drilldown SPL.** `` (`ai_kube_events` OR `ai_job_lifecycle`) ("med-advisor-v41" OR "dc1-ucs-gpu-07") | table _time sourcetype workload pod node reason impact restart_count | sort 0 _time ``.
- **What the audience sees.** The OOMKilled x3 restarts of `med-advisor-v41-5b21d`, the NodeNotReady on the degraded node, and the morning job failures (`ft-claims-v13-s002` CHECKPOINT_IO_STALL, 512 GPU-hours lost) that explain the day's spend spike.

### 7.4 AI Applications (`ai_applications`)

- **Takeaway.** "Users felt it as latency: p95 time-to-first-token went from 500 ms to 1.4 s between 13:00 and 15:00 while availability stayed at 99.93% for the day."
- **Row to click.** `medadvice-chat | med-advisor-v41 | 7f3a9c1e04b2 | 1412 | timeout | flagged:hallucination` (top of "Recent AI Requests").
- **Drilldown SPL.** `index=ai_application host=ai-demo-generator trace_id="7f3a9c1e04b2" | table _time sourcetype gen_ai.app gen_ai.request.model ttft_ms retrieval_ms status guardrail verdict category gen_ai.agent.name`.
- **What the audience sees.** The request, its guardrail event and (where applicable) the agent run joined on one `trace_id`: retrieval timed out against `vector-db-2`, the answer was flagged for hallucination, and nothing but hashes and lengths of the prompt was indexed.

### 7.5 Model Performance and Quality (`model_performance_quality`)

- **Takeaway.** "Quality moved with the infrastructure: hallucination flags per 1,000 responses went from 15 to 40, and the v41 release candidate posted a -2.1 point reasoning regression. That is evidence for a release decision, not the decision."
- **Row to click.** `med-advisor-v41 | reasoning | 91.9 | -2.1 | regression | eval-reasoning-v41-0089`.
- **Drilldown SPL.** `` (`ai_eval_runs` OR `ai_job_lifecycle`) job_id="eval-reasoning-v41-0089" | table _time sourcetype model_version suite pass_rate baseline_pass_rate delta_vs_baseline status state node cycle_time_h queue_wait_h ``.
- **What the audience sees.** The evaluation run next to the job lifecycle that produced it (4.2 h cycle, 1.5 h queue wait on `aipod-lab`), with the safety, coding and groundedness suites of the same version for context.

### 7.6 AI Agents (`ai_agents`)

- **Takeaway.** "One agent looped on a failing tool 31 times before the guardrail stopped it: 41 steps, 212K tokens, $3.12. Multiply by 37 runs and this is why agents need infrastructure monitoring."
- **Row to click.** `claims-intake-agent | c41e77a09b3d | 41 | 38 (claims_api x31) | loop_stopped | 212480 | 3.12` (first row of "Recent Agent Runs").
- **Drilldown SPL.** `` `ai_agent_steps` trace_id="c41e77a09b3d" | table _time step_no gen_ai.operation.name gen_ai.tool.name status error_type duration_ms tokens | sort 0 step_no ``.
- **What the audience sees.** The 41 steps in order: `claims_api` returning `http_503` again and again, the token count climbing, and the run ending in `loop_stopped`.

### 7.7 AI Security Posture (`ai_security_posture`)

Three beats on one dashboard.

**Monitor.** Takeaway: "Model weights, AI data stores, cluster credentials and the prompt surface are assets. 22 open findings this week, 214 prompt injections blocked." Point at the five tiles and the stacked chart by day (`model_asset_access`, `credential_misuse`, `data_movement`, `off_hours_admin`) and the bar of injection techniques (instruction_override 86, role_play_jailbreak 57, encoded_payload 34, indirect_via_document 25, system_prompt_leak 12).

**Detect compromise with detection engineering.** Takeaway: "Each finding is a rule: first-seen access to weights (T1530), credential misuse (T1078), anomalous data movement (T1567), prompt-injection campaign (ATLAS AML.T0051). The same rules ship as Enterprise Security correlation searches." Row to click: `svc-mlops-ci | 10.42.17.88 | s3:GetObject (first seen) | weights/med-advisor-v41/ | 80 | true_positive` (first row of "Recent Findings (Enterprise Security)"). Drilldown SPL: `` `ai_security_raw` user="svc-mlops-ci" src="10.42.17.88" | table _time sourcetype action object first_seen bytes_out asn outcome | sort 0 _time ``. What the audience sees: the `iam:sim` `assume_role` of `role/weights-reader` at 09:12 (new principal) followed by the `aws:cloudtrail:sim` `s3:GetObject` on the weights bucket at 14:41, both `first_seen=true`, in one timeline.

**Triage and respond.** Takeaway: "Findings carry a risk score, an owner and a disposition, so the SOC works a queue, not a feed." Row to click: `probe@example.com | 203.0.113.10 | prompt_injection x38 | app/medadvice-chat | 80 | true_positive`. Drilldown SPL: `` `ai_guardrails` src="203.0.113.10" category=prompt_injection | stats count BY technique gen_ai.app verdict ``. What the audience sees: 59 blocked attempts from one source across two applications, split by technique, and the matching alert `AI Security - Prompt-injection campaign from a single source` in `index=ai_summary sourcetype=ai:alert`.

### 7.8 AI Operations Executive Overview (`ai_operations_executive_overview`)

- **Takeaway.** "Five scoreboards, one story: availability 99.93% (up 0.21 pts), pilot to production 38 days (down 12), GPU utilization 61.8% against a 65% target, safety 99.2% within band, 22 open findings all owned. Incidents by root-cause layer are down from 31 to 18 a week."
- **Row to click.** `reliability | dc1-ucs-gpu-07 repeat ECC faults behind a flapping fabric link | 2 replicas lost, 47 min degraded | infra-oncall | node drained` in "Top Risks This Week".
- **Drilldown.** Every row links to the dashboard that owns it (`/app/ai_infra_monitoring/<dashboard_id>` from `ai_top_risks.csv`); this one reopens `ai_infrastructure_health`, closing the loop from the board room back to the GPU.
- **What the audience sees.** The same 99.93%, 61.8% and 22 they saw on the layer dashboards, because the scoreboards roll up from the same macros.

## 8. AI Toolkit fallback

The hallucination chart on `model_performance_quality` highlights the anomaly window through the `ai_hallucination_band` macro. The shipped definition is static (an `eventstats` mean +/- 2 sigma band per model):

```
eventstats avg(rate) AS band_mean stdev(rate) AS band_sd BY model
| eval band_upper=round(band_mean+2*band_sd,1), band_lower=round(max(band_mean-2*band_sd,0),1), anomaly=if(rate>band_upper,rate,null())
```

If the AI Toolkit (MLTK with the Python for Scientific Computing add-on) is installed, replace the macro definition with the density-function version (Settings > Advanced search > Search macros > `ai_hallucination_band`):

```
fit DensityFunction rate by "model" threshold=0.01 into app:ai_infra_hallucination_df
| eval anomaly=if(IsOutlier(rate)=1,rate,null()) | rename BoundaryRanges AS band
```

Both variants return `rate`, `anomaly` and a band, so the dashboard JSON does not change. `fit` needs at least 50 points per group (15-minute bins over 24 hours give 96) and is a risky command, so the role running the dashboard needs `run_risky_commands` or an administrator must run it once to create the model. The executive GPU-utilization chart works the same way: the shipped view plots the weekly series against a static `target=65` line; with the AI Toolkit you can add `| fit StateSpaceForecast utilization holdback=0 forecast_k=4 output_fit=t` before the `timechart`. Without the toolkit the dashboards say nothing about it and use the static thresholds above.

## 9. Enterprise Security

The four security alerts write `ai:security:finding` events on their own. When Splunk Enterprise Security is installed, each one also ships as a correlation search (`<title> - Rule`, disabled by default) with `action.risk` (risk object `user`, or `src` for the prompt-injection rule; scores 80/65/75/80), `action.notable` (security domain, severity, drilldown on `index=ai_security user=$user$`) and MITRE ATT&CK / ATLAS annotations. `make enable-es` confirms `/services/apps/local/SplunkEnterpriseSecuritySuite` exists, then writes `local/savedsearches.conf` with `disabled = 0` for the four rules and reloads the app; risk events land in `index=risk` and the notables appear in Mission Control. Without ES the `ai:security:finding` events stand in and the dashboard says nothing about ES beyond its table title.

## 10. Alerts and scoreboards

25 alerts in `default/savedsearches.conf`, all scheduled (every 5 minutes; every 15 minutes for the 7-day ones), email off, `alert.track=1`, each writing one `ai:alert` event per result to `index=ai_summary` through the built-in `logevent` action with `search_name`, `severity`, `layer`, `dashboard` and the key fields. Titles: `AI Infra - ECC or Xid faults on a GPU node` (high), `AI Infra - Thermal throttling sustained 15 min` (medium), `AI Infra - Idle GPU capacity above 30% for 24h` (low); `AI Network - Fabric congestion (ECN/PFC) on an AI POD link` (high), `AI Network - Link flapping on a GPU-facing port` (high), `AI Network - Configuration drift on an AI fabric switch` (medium); `AI Platform - Restart storm on an inference deployment` (high), `AI Platform - Inference queue build-up` (medium), `AI Platform - Evaluation or fine-tuning job failed` (medium); `AI Apps - p95 time-to-first-token regression` (high), `AI Apps - Error rate spike` (high), `AI Apps - Retrieval timeouts` (medium); `AI Models - Quality drift vs baseline` (medium), `AI Models - Safety compliance below policy band` (high), `AI Models - Evaluation regression on a release candidate` (medium); `AI Agents - Task completion drop` (medium), `AI Agents - Runaway loop detected` (high), `AI Agents - Guardrail surge` (high); `AI Cost - Daily spend spike by business unit` (medium), `AI Cost - Idle reservation above threshold` (low), `AI Cost - Runaway agent token spend` (medium); `AI Security - First-seen access to model weights` (critical), `AI Security - Credential misuse on an AI cluster` (high), `AI Security - Anomalous data movement from an AI data store` (high), `AI Security - Prompt-injection campaign from a single source` (high).

Every window is anchored so the 14:55 scheduled run sees the daily incident; `make smoke SMOKE_FLAGS=--dispatch-alerts` force-dispatches each alert at the last incident's 14:55 with `trigger_actions=1` and then checks `index=ai_summary sourcetype=ai:alert | stats count by search_name` for all 25 names.

## 11. Makefile reference

| Target | What it does |
|---|---|
| `make all` | `validate`, `package`, `appinspect` |
| `make package` | renders the HTML twins, rsyncs the app into `dist/` without `Makefile`, `tools/`, `dist/`, `local/`, `docs/testing/`, `.env*` and dotfiles, sets 644/755, builds `dist/ai_infra_monitoring-1.0.0.tgz` with `COPYFILE_DISABLE=1`, fails if any hidden file is in the tarball |
| `make appinspect` | `splunk-appinspect inspect ... --mode precert --included-tags cloud`, writes `dist/appinspect.json`, fails on errors or failures, prints warnings |
| `make validate` | `tools/validate_views.py` (view structure, tokens, nav order, wording, palette) plus `splunk btool check`, and confirms every `.md` has a fresh `.html` |
| `make install` | rsync into `$SPLUNK_HOME/etc/apps` if needed, restart (REST with `.env` credentials, else the CLI), wait for `/services/server/info`, check the nine indexes |
| `make hec-setup` | `tools/hec_setup.py`: creates/updates the `ai_infra_demo` token scoped to the nine indexes, records `AI_DEMO_HEC_TOKEN` and `HEC_URL` in `.env`, probes with gzip and identity (`--file-provision` as the no-credentials fallback) |
| `make backfill` | generator self-check, then `bin/backfill.sh --days 30 --hec ... --token ... --seed 20260916` |
| `make fire-incident` | replays the incident compressed into 20 minutes over HEC |
| `make enable-es` | enables the four ES correlation searches when ES is installed |
| `make enable-stream` | writes `local/inputs.conf` enabling the metrics and the four biggest event feeds (`ALL=1` enables all 25), reloads scripted inputs |
| `make smoke` | `tools/smoke.py`; add `SMOKE_FLAGS=--dispatch-alerts` to force the 25 alerts; writes `dist/smoke.txt` and `dist/smoke.json` |
| `make screenshots` | prints the ten dashboard URLs (`?theme=dark`) and captures PNGs when `playwright` is importable |
| `make html` / `make icons` | regenerate the HTML twins / the app icons |
| `make clean` | deletes the demo data (`host=ai-demo-generator`, needs `can_delete`) and the build outputs |

`.env` keys: `SPLUNK_MGMT_URL` (default `https://127.0.0.1:8090`), `SPLUNK_TOKEN` or `SPLUNK_USERNAME`/`SPLUNK_PASSWORD`, `HEC_URL`, `AI_DEMO_HEC_TOKEN`. Overridable make variables: `SPLUNK_HOME`, `APPINSPECT`, `HEC_URL`, `SEED`, `BACKFILL_DAYS`, `SMOKE_FLAGS`.

## 12. Regression testing

Run the whole suite after any change to the app and after every Splunk upgrade, in this order:

| Step | Command | Passes when |
|---|---|---|
| Static checks, package, AppInspect | `make all` | `validate: OK`, `btool check: OK`, AppInspect reports 0 errors and 0 failures |
| Generator self-check | `$SPLUNK_HOME/bin/splunk cmd python3 bin/ai_demo_generator.py --self-check --seed 20260916` | `39 KPIs, 0 failures` |
| Live smoke with alert dispatch | `make smoke SMOKE_FLAGS=--dispatch-alerts` | `PASS 144/144` |
| Platform checks after an upgrade | REST and SPL, listed in the latest report | the nine indexes and 25 feeds current, the 34 searches running, HEC healthy, no app errors in `splunkd.log` |
| Dashboards in Splunk Web | open the ten views after logging in | every panel loads with no error state; `_audit` shows no failed `UI:dashboard:*` searches |

Keep a copy of `dist/smoke.txt`, `dist/smoke.json` and `dist/appinspect.json` from before an upgrade as the baseline. To compare a new Splunk version with that baseline over the same data, `tools/smoke_pinned.py <epoch>` reruns `smoke.py` read-only with every search pinned to one moment, and `tools/replay_alerts.py <anchor> ...` runs the 25 alert searches at chosen times without writing anything.

The dispatch step anchors on the last incident's 14:55. The four AI Security alerts only have data on the generator's latest backfilled day, and the `ai_applications` table check depends on which row arrived last, so those checks can fail for reasons unrelated to a change (see the 2026-09-18 report).

Write each run up as `docs/testing/regression_<date>_<change>.md`; `make html` renders its HTML twin, and `docs/testing/` is not packaged. Raw logs go to `dist/regression/`. Reports so far:

- `docs/testing/regression_2026-09-18_splunk-10.4.3.md`: Splunk Enterprise 10.4.0 to 10.4.3, no regressions.

## 13. Cleanup

```
index IN (ai_infra_metrics,ai_infra,ai_network,ai_platform,ai_application,ai_model_eval,ai_cost,ai_security,ai_summary) host=ai-demo-generator | delete
```

`make clean` runs that search (the account needs the `can_delete` capability; metrics indexes accept `delete` on Splunk Enterprise 9.1 and later) and removes `dist/`. Disable the scripted inputs (`local/inputs.conf`) and the `ai_infra_demo` HEC token if you no longer want new data. The `ai_application` index name is shared with other GenAI content on purpose; the `host=ai-demo-generator` filter keeps this app's events separable.

## Files

`default/` (app, indexes, inputs, props, transforms, eventtypes, tags, macros, savedsearches, nav, ten views), `metadata/default.meta`, `lookups/` (five CSVs), `bin/` (`ai_demo_generator.py`, `backfill.sh`, `hec_setup.md`), `static/` (icons), `docs/field_reference.md` (every sourcetype and field), `CHANGELOG.md`, `LICENSE`. Build-only, not packaged: `Makefile`, `tools/`, `docs/testing/` (regression reports), `dist/`, `.env`.
