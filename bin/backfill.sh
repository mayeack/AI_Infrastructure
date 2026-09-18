#!/bin/sh
# backfill.sh - load the demo history for ai_infra_monitoring.
#
# Default path: HEC.  Reads HEC_URL and AI_DEMO_HEC_TOKEN (and optional SEED, BACKFILL_DAYS, GEN_PYTHON)
# from <app>/.env, runs the generator's --self-check, then `--backfill 30d --hec ... --token ...`, and
# prints the expected-count table.  Compare with:
#   | tstats count where host=ai-demo-generator by index sourcetype
#
# Alternative path (`--oneshot`): write NDJSON files with --out and load each file with
# `splunk add oneshot <file> -index <index> -sourcetype <sourcetype> -host ai-demo-generator -auth user:pass`
# (needs SPLUNK_USERNAME/SPLUNK_PASSWORD in .env; ai:gpu:metrics relies on the app's log-to-metrics props).
#
# Usage: bin/backfill.sh [--oneshot] [--days N] [--force] [--resume] [--dry-run]
#   --resume fills only the minutes not yet indexed (safe to run while the streaming inputs are on).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
APP=$(cd "$HERE/.." && pwd)
[ -f "$APP/.env" ] && { set -a; . "$APP/.env"; set +a; }
SPLUNK_HOME=${SPLUNK_HOME:-$(cd "$APP/../../.." && pwd)}
PY=${GEN_PYTHON:-}
if [ -z "$PY" ]; then
  if [ -x "$SPLUNK_HOME/bin/splunk" ]; then PY="$SPLUNK_HOME/bin/splunk cmd python3"; else PY=python3; fi
fi
DAYS=${BACKFILL_DAYS:-30}
SEED=${SEED:-20260916}
HEC_URL=${HEC_URL:-https://localhost:8088}
MODE=hec; FORCE=""; DRY=""; RESUME=""
while [ $# -gt 0 ]; do
  case "$1" in
    --oneshot) MODE=oneshot ;;
    --days) DAYS=$2; shift ;;
    --force) FORCE="--force" ;;
    --resume) RESUME="--resume" ;;
    --dry-run) DRY=1 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
GEN="$HERE/ai_demo_generator.py"
echo "== self-check (seed $SEED)"
$PY "$GEN" --self-check --no-tune --seed "$SEED" || { echo "self-check failed; not loading" >&2; exit 1; }
echo "== expected events for a ${DAYS}-day backfill"
$PY -c "
import sys; sys.path.insert(0, '$HERE')
import ai_demo_generator as G
from ai_demo_lib.catalog import SOURCETYPE_INDEX
rows = G.expected_table(int('$DAYS'))
print('%-26s %-18s %12s' % ('sourcetype', 'index', 'expected'))
tot = 0
for st, n in rows.items():
    tot += n
    print('%-26s %-18s %12s' % (st, SOURCETYPE_INDEX[st], '{:,}'.format(n)))
print('%-26s %-18s %12s' % ('total', '', '{:,}'.format(tot)))
print('(tier mix: last 24h at 1-min, days 2-7 at 5-min, days 8-%s at 15-min; the current day is partial so the 1-min tier straddles two calendar days; compare with | tstats count where host=ai-demo-generator by index sourcetype, tolerance +-2%% on full days)' % '$DAYS')
"
[ -n "$DRY" ] && exit 0
if [ "$MODE" = hec ]; then
  : "${AI_DEMO_HEC_TOKEN:?set AI_DEMO_HEC_TOKEN in $APP/.env (make hec-setup)}"
  echo "== backfill ${DAYS}d via HEC $HEC_URL"
  $PY "$GEN" --backfill "${DAYS}d" --hec "$HEC_URL" --token "$AI_DEMO_HEC_TOKEN" --seed "$SEED" $FORCE $RESUME
else
  OUT=${BACKFILL_OUT:-$APP/dist/backfill}
  echo "== backfill ${DAYS}d to $OUT then splunk add oneshot"
  mkdir -p "$OUT"; find "$OUT" -name "*.ndjson" -type f -delete   # generator appends per <index>__<sourcetype>.ndjson file
  $PY "$GEN" --backfill "${DAYS}d" --out "$OUT" --seed "$SEED"
  : "${SPLUNK_USERNAME:?set SPLUNK_USERNAME in .env}"; : "${SPLUNK_PASSWORD:?set SPLUNK_PASSWORD in .env}"
  for f in "$OUT"/*.ndjson; do
    base=$(basename "$f" .ndjson); idx=${base%%__*}; st=${base#*__}; st=$(echo "$st" | tr '_' ':')
    case "$st" in gen:ai:*) st=$(echo "$st" | sed 's/^gen:ai:/gen_ai:/') ;; esac
    echo "oneshot $f -> index=$idx sourcetype=$st"
    src=ai_demo_generator; [ "$st" = "ai:gpu:metrics" ] && src=ai_demo_generator_metrics   # source-scoped log-to-metrics props
    "$SPLUNK_HOME/bin/splunk" add oneshot "$f" -index "$idx" -sourcetype "$st" -host ai-demo-generator -rename-source "$src" -auth "$SPLUNK_USERNAME:$SPLUNK_PASSWORD"
  done
fi
echo "== done. Verify with: | tstats count where host=ai-demo-generator by index sourcetype"
