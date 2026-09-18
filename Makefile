# ai_infra_monitoring build, install and verification targets.
# Excluded from the package together with tools/, dist/ and .env*.
SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c
APP             := ai_infra_monitoring
VERSION         := $(shell sed -n 's/^version *= *//p' default/app.conf | head -1)
SPLUNK_HOME     ?= /opt/splunk104
SPLUNK          := $(SPLUNK_HOME)/bin/splunk
PY              := $(SPLUNK_HOME)/bin/splunk cmd python3
APPINSPECT      ?= $(HOME)/Library/Python/3.9/bin/splunk-appinspect
SPLUNK_MGMT_URL ?= https://127.0.0.1:8090
SPLUNK_WEB_URL  ?= http://localhost:8002
HEC_URL         ?= https://localhost:8088
SEED            ?= 20260916
BACKFILL_DAYS   ?= 30
BACKFILL_FLAGS  ?= --resume   # gap-fill by default; use BACKFILL_FLAGS=--force for a full reload into empty indexes
SMOKE_FLAGS     ?=
INDEXES := ai_infra_metrics,ai_infra,ai_network,ai_platform,ai_application,ai_model_eval,ai_cost,ai_security,ai_summary
TGZ     := dist/$(APP)-$(VERSION).tgz
MD_DOCS := README.md CHANGELOG.md docs/field_reference.md bin/hec_setup.md $(wildcard docs/testing/*.md)
-include .env
export

.PHONY: all package appinspect validate install hec-setup backfill fire-incident enable-es enable-stream clean smoke screenshots html docs icons

all: validate package appinspect

# ---------------------------------------------------------------- package
package: html
	rm -rf dist/$(APP)
	mkdir -p dist/$(APP)
	rsync -a --exclude='.*' --exclude='__pycache__' --exclude='*.pyc' \
	  --exclude='Makefile' --exclude='tools/' --exclude='dist/' --exclude='local/' --exclude='docs/testing/' \
	  --exclude='metadata/local.meta' --exclude='.env*' ./ dist/$(APP)/
	find dist/$(APP) -type d -exec chmod 755 {} +
	find dist/$(APP) -type f -exec chmod 644 {} +
	if ls dist/$(APP)/bin/*.py >/dev/null 2>&1; then chmod 755 dist/$(APP)/bin/*.py; fi
	if ls dist/$(APP)/bin/*.sh >/dev/null 2>&1; then chmod 755 dist/$(APP)/bin/*.sh; fi
	if find dist/$(APP) -name '* *' | grep -q .; then echo "ERROR: filenames with spaces"; find dist/$(APP) -name '* *'; exit 1; fi
	COPYFILE_DISABLE=1 tar --no-xattrs -C dist -czf $(TGZ) $(APP)
	rm -rf dist/$(APP)
	if tar tzf $(TGZ) | grep -E '(^|/)\.[^/]|__MACOSX' ; then echo "ERROR: hidden files in package"; exit 1; fi
	@echo "packaged $(TGZ) ($$(tar tzf $(TGZ) | wc -l | tr -d ' ') entries)"

# ------------------------------------------------------------- appinspect
appinspect: package
	test -x "$(APPINSPECT)" || { echo "splunk-appinspect not found at $(APPINSPECT)"; exit 1; }
	"$(APPINSPECT)" inspect $(TGZ) --mode precert --included-tags cloud \
	  --output-file dist/appinspect.json --log-level ERROR || true
	$(PY) tools/appinspect_gate.py dist/appinspect.json

# --------------------------------------------------------------- validate
validate:
	$(PY) tools/validate_views.py --app-dir . --views default/data/ui/views
	@if [ -x "$(SPLUNK)" ]; then \
	  out=$$($(SPLUNK) btool check 2>&1 | grep '/apps/$(APP)/' || true); \
	  if echo "$$out" | grep -qiE 'invalid key|invalid stanza|does not exist'; then echo "$$out"; echo "ERROR: btool check reported problems"; exit 1; fi; \
	  echo "btool check: OK"; \
	fi
	@for f in $(MD_DOCS); do \
	  h="$${f%.md}.html"; \
	  if [ -f "$$f" ] && { [ ! -f "$$h" ] || [ "$$f" -nt "$$h" ]; }; then echo "ERROR: $$h is missing or older than $$f (run make html)"; exit 1; fi; \
	done
	@echo "validate: OK"

# ---------------------------------------------------------------- install
install:
	if [ "$(CURDIR)" != "$(SPLUNK_HOME)/etc/apps/$(APP)" ]; then \
	  rsync -a --delete --exclude 'local/' --exclude '.env' --exclude 'dist/' ./ "$(SPLUNK_HOME)/etc/apps/$(APP)/"; \
	fi
	if [ -n "$${SPLUNK_TOKEN:-}" ]; then \
	  curl -sk -H "Authorization: Bearer $$SPLUNK_TOKEN" -X POST "$(SPLUNK_MGMT_URL)/services/server/control/restart" >/dev/null; \
	elif [ -n "$${SPLUNK_USERNAME:-}" ] && [ -n "$${SPLUNK_PASSWORD:-}" ]; then \
	  curl -sk -u "$$SPLUNK_USERNAME:$$SPLUNK_PASSWORD" -X POST "$(SPLUNK_MGMT_URL)/services/server/control/restart" >/dev/null; \
	else \
	  "$(SPLUNK)" restart; \
	fi
	sleep 5
	for i in $$(seq 1 60); do \
	  if curl -sk -o /dev/null -w '%{http_code}' "$(SPLUNK_MGMT_URL)/services/server/info" | grep -qE '^(200|401)$$'; then echo "splunkd is up"; break; fi; \
	  sleep 2; \
	  if [ "$$i" = "60" ]; then echo "ERROR: splunkd did not come back in 120 s"; exit 1; fi; \
	done
	$(PY) tools/_splunkrest.py --check-indexes $(INDEXES) --check-app $(APP)

# -------------------------------------------------------------- hec-setup
hec-setup:
	$(PY) tools/hec_setup.py --name ai_infra_demo --indexes $(INDEXES) --default-index ai_infra --env-file .env

# --------------------------------------------------------------- backfill
backfill:
	if [ -z "$${AI_DEMO_HEC_TOKEN:-}" ]; then $(MAKE) hec-setup; fi
	set -a; . ./.env; set +a
	$(PY) bin/ai_demo_generator.py --self-check --seed $(SEED)
	bin/backfill.sh $(BACKFILL_FLAGS) --days $(BACKFILL_DAYS) --hec "$${HEC_URL:-$(HEC_URL)}" --token "$$AI_DEMO_HEC_TOKEN" --seed $(SEED)

fire-incident:
	set -a; . ./.env; set +a
	$(PY) bin/ai_demo_generator.py --fire-incident --hec "$${HEC_URL:-$(HEC_URL)}" --token "$$AI_DEMO_HEC_TOKEN" --seed $(SEED)

# ------------------------------------------------------------- enable-es
enable-es:
	$(PY) tools/enable_es.py

enable-stream:   # ALL=1 enables all 25 feeds; default enables the metrics + four biggest event feeds
	mkdir -p local
	$(PY) - <<'PYEOF'
	import re
	feeds = ["ai:gpu:metrics", "gen_ai:request", "cisco:nexus:interface", "gen_ai:agent:run", "gen_ai:agent:step"]
	import os
	if os.environ.get("ALL") == "1":   # make enable-stream ALL=1 turns on every feed
	    feeds = ["--sourcetype "]
	src = open("default/inputs.conf").read()
	out = ["# written by make enable-stream: turns on the scripted generator feeds on Splunk Enterprise"]
	for m in re.finditer(r"^\[(script://[^\]]+)\]", src, re.M):
	    stanza = m.group(1)
	    if any(("--sourcetype " + f) in stanza for f in feeds):
	        out += ["", "[%s]" % stanza, "disabled = 0"]
	open("local/inputs.conf", "w").write("\n".join(out) + "\n")
	print("wrote local/inputs.conf with %d enabled feeds" % (len(out) // 3))
	PYEOF
	$(PY) tools/_splunkrest.py --reload-inputs

# ------------------------------------------------------------------ clean
clean:
	@echo "Deleting host=ai-demo-generator events from $(INDEXES) (the account needs the can_delete capability)"
	$(PY) tools/smoke.py --run 'search index IN ($(INDEXES)) host=ai-demo-generator earliest=0 latest=+1d | delete' --confirm
	rm -f dist/*.tgz dist/appinspect.json dist/smoke.txt dist/smoke.json

# ------------------------------------------------------------------ smoke
smoke:
	mkdir -p dist
	$(PY) tools/smoke.py --views default/data/ui/views --macros default/macros.conf --savedsearches default/savedsearches.conf --out dist/smoke.txt --json dist/smoke.json $(SMOKE_FLAGS)

screenshots:
	mkdir -p dist/screenshots
	$(PY) tools/screenshots.py --base $(SPLUNK_WEB_URL) --app $(APP) --out dist/screenshots

# ------------------------------------------------------------------- docs
html:
	$(PY) tools/md2html.py $(MD_DOCS)

docs: html

icons:
	$(PY) tools/make_icons.py static/
