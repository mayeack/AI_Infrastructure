# Changelog

All notable changes to `ai_infra_monitoring` are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `docs/testing/regression_2026-09-18_splunk-10.4.3.md`: smoke test and full regression run after the Splunk Enterprise 10.4.0 to 10.4.3 upgrade. No app regressions.
- `tools/smoke_pinned.py` reruns the smoke test read-only with every search pinned to one moment. `tools/replay_alerts.py` runs the 25 alert searches at chosen anchors without collecting or triggering actions.
- README section 12, "Regression testing".

### Changed

- `make package` leaves `docs/testing/` out of the package, and `make html` and `make validate` cover its Markdown files.
- `tools/smoke_pinned.py` passes its pin to `smoke.py --now`, so a pinned run anchors on the incident that was the last one at that moment.

### Fixed

- `make smoke SMOKE_FLAGS=--dispatch-alerts` no longer fails the four AI Security dispatch checks when it runs after 15:05. The scripted security storyline only exists on the day the backfill wrote as its latest day, so those alerts are now dispatched at 14:55 on the newest day, up to the last incident and within 7 days, whose data holds all four pieces they detect. The other 21 alerts still fire at the last incident (regression report 2026-09-18, F2).
- The `ai_applications` table check no longer depends on which application's attention row was indexed last. It reads the table over the 24 hours ending at the last incident's 15:00 and requires the three scripted `medadvice-chat` rows (`7f3a9c1e04b2`, `2c6e0b77d1f5`, `9d02b6f1c47a`) among its attention rows (F3).
- `smoke.py --now <epoch>` sets the clock that decides which incident is the last one.

## [1.0.0] - 2026-09-18

### Added

- Nine indexes (`ai_infra_metrics` as a metrics index; `ai_infra`, `ai_network`, `ai_platform`, `ai_application`, `ai_model_eval`, `ai_cost`, `ai_security`, `ai_summary`).
- 25 sourcetypes with search-time JSON extraction, per-layer `EVAL-layer` calculated fields, field aliases, the `metric-schema:ai_gpu_metrics` log-to-metrics transform, six `ai_layer_*` event types with matching tags.
- Five CSV lookups: `gpu_rate_card`, `ai_node_inventory` (68 nodes), `ai_application_catalog`, `ai_layer_map`, `ai_top_risks`.
- Ten Dashboard Studio views in dark theme: the `ai_stack_overview` landing page, the six layer dashboards, cost, security posture and the executive overview.
- 25 scheduled alerts (compute, network, platform, applications, models, agents, cost and security) writing `ai:alert` events to `ai_summary`, plus four Enterprise Security correlation-search twins shipped disabled.
- Five scoreboard rollups (`Reliability`, `Velocity`, `Efficiency`, `Trust`, `Security`) writing `ai:scoreboard` every 15 minutes.
- `bin/ai_demo_generator.py`, a deterministic stdlib-only generator with backfill, stream, `--fire-incident` and HEC modes, and `bin/backfill.sh`.
- Build and verification tooling outside the package: `Makefile`, `tools/hec_setup.py`, `tools/smoke.py`, `tools/validate_views.py`, `tools/make_icons.py`, `tools/md2html.py`, `tools/screenshots.py`, `tools/enable_es.py`.
- Documentation: `README.md`, `docs/field_reference.md`, `bin/hec_setup.md`, Apache-2.0 `LICENSE`, HTML twins of every Markdown file.
