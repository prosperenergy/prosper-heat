#!/usr/bin/env bash
# Prosper Heat — engine wrapper (bash)
# Calls bun helper to read chat.db (FDA-safe), pipes inbounds to the python core
# which handles strict + LLM-fallback classification, Redis updates, ack sends,
# and auto-distribute. Runs every 30s via launchd (io.prosper.heat-engine).
# Authored by Hanna 2026-05-30. Open-source at github.com/prosperenergy/prosper-heat.

set -uo pipefail

BUN=/Users/craigstratton/.local/bin/bun
HELPER=/Users/craigstratton/Projects/prosper/prosper-imessage-responder/src/heat-read-since.ts
ENGINE_PY=/Users/craigstratton/bin/prosper-heat-engine.py
LOG=/tmp/prosper-heat-engine.log
STATE_FILE=/tmp/prosper-heat-last-poll.ns
NOW=$(date +%s)

REPS_LIST="+13303293748,+14439004416,+15304489938,+13853350157,+18014006701,+18017873504,+18019955913,+16575468448"

# Compute Apple-epoch ns timestamp for last poll
if [ -f "$STATE_FILE" ]; then
  LAST_NS=$(cat "$STATE_FILE")
else
  LAST_NS=$(( ($NOW - 60 - 978307200) * 1000000000 ))
fi
NEW_LAST_NS=$(( ($NOW - 978307200) * 1000000000 ))
echo "$NEW_LAST_NS" > "$STATE_FILE"

# Pipeline: bun reads chat.db → python parses + acts
$BUN "$HELPER" "$LAST_NS" "$REPS_LIST" 2>>"$LOG" | /usr/bin/python3 "$ENGINE_PY" 2>>"$LOG"
