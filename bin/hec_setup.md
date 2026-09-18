# HTTP Event Collector setup for Splunk Cloud Platform

On Splunk Cloud Platform the generator runs outside the stack and sends events to an HTTP Event Collector (HEC) token. Scripted inputs stay disabled in the app. On Splunk Enterprise `make hec-setup` does all of this through the management port; the steps below are the manual equivalent.

## 1. Install the app

Upload `dist/ai_infra_monitoring-1.0.0.tgz` (Apps > Manage Apps > Install app from file). The app passes `splunk-appinspect --mode precert --included-tags cloud`; on Splunk Cloud the indexes below are not created by the app and must be added by hand.

## 2. Create the nine indexes

Settings > Indexes > New Index. Names are lowercase and must match exactly.

| Index | Type | Holds |
|---|---|---|
| `ai_infra_metrics` | **Metrics** | `ai:gpu:metrics` (DCGM GPU and storage measures) |
| `ai_infra` | Events | GPU faults, Cisco UCS alarms, inventory and audit |
| `ai_network` | Events | Cisco Nexus interface, anomaly and config events, path tests |
| `ai_platform` | Events | Kubernetes events, inference servers, job lifecycle |
| `ai_application` | Events | application requests, agent runs and steps, guardrails |
| `ai_model_eval` | Events | evaluation runs |
| `ai_cost` | Events | daily GPU-hour and token cost rows |
| `ai_security` | Events | raw access, identity and egress events plus findings |
| `ai_summary` | Events | scoreboard rollups, incident history, alert events |

A 30-day backfill is about 2.1 GB raw across all indexes; a retention of 90 days (`frozenTimePeriodInSecs = 7776000`) is what the app declares on Splunk Enterprise.

## 3. Create the token

Settings > Data Inputs > HTTP Event Collector > New Token.

1. Name: `ai_infra_demo`. Leave source type blank (the generator sets it per event).
2. Allowed indexes: select all nine indexes above. Default index: `ai_infra`.
3. Do not enable indexer acknowledgement (the generator does not use channels).
4. Copy the token value. The endpoint is `https://<stack>.splunkcloud.com:8088` (or `https://http-inputs-<stack>.splunkcloud.com:443` on some stacks; check Settings > Data Inputs > HTTP Event Collector > Global Settings).

## 4. Probe the token

```bash
curl -k https://<stack>.splunkcloud.com:8088/services/collector/event \
  -H "Authorization: Splunk <token>" \
  -d '{"event":"hec_probe","index":"ai_summary","sourcetype":"ai:hec_probe","host":"ai-demo-generator"}'
```

Expected reply: `{"text":"Success","code":0}`. Then repeat with `--compressed -H "Content-Encoding: gzip"` and a gzip'd body if you want to confirm compression (the generator falls back to identity encoding when gzip is refused).

## 5. Backfill and stream from any host

```bash
export AI_DEMO_HEC_TOKEN=<token>
export HEC_URL=https://<stack>.splunkcloud.com:8088
bin/ai_demo_generator.py --backfill 30d --hec "$HEC_URL" --token "$AI_DEMO_HEC_TOKEN" --seed 20260916
bin/ai_demo_generator.py --stream --hec "$HEC_URL" --token "$AI_DEMO_HEC_TOKEN" --seed 20260916
```

The backfill takes 10-20 minutes over a fast link and prints the expected event counts per sourcetype. Run the stream command under `nohup` or a service manager to keep the last-minute feeds current; run `--fire-incident` from the same host for a live demo.

## 6. Troubleshooting

| Reply | Cause | Fix |
|---|---|---|
| `{"text":"Incorrect index","code":7}` | index not in the token's allowed list or not created | add the index in step 2 and to the token in step 3 |
| `{"text":"Invalid token","code":4}` | wrong token or HEC disabled | check Global Settings > All Tokens = Enabled |
| HTTP 400 `Invalid data format` | metrics event sent to `/services/collector/event` with a non-metric index | `ai_infra_metrics` must be a metrics index |
| HTTP 403 | token disabled | enable the token |
| `Server is busy` (code 9) | queue pressure during backfill | rerun with `--workers 2 --batch-bytes 1500000` |

Everything the generator sends carries `host=ai-demo-generator`, so `index IN (...) host=ai-demo-generator | delete` (with the `can_delete` capability) removes the demo data cleanly.
