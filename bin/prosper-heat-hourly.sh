#!/usr/bin/env bash
# Prosper Heat — Hourly digest to Craig via Telegram
# Authored by Hanna 2026-05-30.

set -uo pipefail
RP=/Users/craigstratton/bin/redis-prosper
TG_TOKEN="8799770266:AAGAy7j-QjQJv87t7QHwv4dTM8nKTeR7vEo"
TG_CHAT="7660965553"
POOL_JSON=/Users/craigstratton/ClaudeCodexBridge/prosper-heat-lead-pool.json
LOG=/tmp/prosper-heat-hourly.log

log() { echo "[$(date -Iseconds)] $*" >> "$LOG"; }

# Compute remaining leads in pool
POOL_TOTAL=$(/usr/bin/python3 -c "import json; print(json.load(open('$POOL_JSON'))['unique_count'])" 2>/dev/null || echo 0)

# Count worked (status set)
WORKED=$($RP KEYS 'prosper.lead.active.*' | wc -l | tr -d ' ')
REMAINING=$((POOL_TOTAL - WORKED))

# Build leaderboard
HEAD="🔥 PROSPER HEAT — Hourly Update ($(date '+%-I:%M %p'))"
LB=""
declare -a LINES

REP_KEYS=$($RP KEYS 'prosper.lead.rep.*' 2>/dev/null)
for K in $REP_KEYS; do
  PHONE="${K#prosper.lead.rep.}"
  NAME=$($RP HGET "$K" name)
  PTS=$($RP HGET "$K" points_today)
  STATUS=$($RP HGET "$K" status)
  CALLS=$($RP HGET "$K" calls_today)
  TEXTS=$($RP HGET "$K" texts_today)
  SETS=$($RP HGET "$K" sets_today)
  MISSES=$($RP HGET "$K" misses_today)
  LEADS=$($RP HGET "$K" leads_worked_today)
  CUR=$($RP HGET "$K" current_lead_id)
  [ -z "$PTS" ] && PTS=0
  STATE_EMOJI="⚪"
  [ "$STATUS" = "ACTIVE_DRAWING" ] && STATE_EMOJI="🟢"
  [ "$STATUS" = "PAUSED" ] && STATE_EMOJI="⏸"
  [ "$STATUS" = "PENDING_OPT_IN" ] && STATE_EMOJI="⏳"
  LINES+=("${PTS}|${STATE_EMOJI} ${NAME}: ${PTS} pts (${CALLS:-0} calls / ${TEXTS:-0} texts / ${SETS:-0} sets / ${LEADS:-0} worked / ${MISSES:-0} miss)")
done

# Sort by points desc
SORTED=$(printf '%s\n' "${LINES[@]}" | sort -rn -t'|' -k1 | cut -d'|' -f2-)

BODY="${HEAD}

🏆 LEADERBOARD:
${SORTED}

📦 Lead pool: ${REMAINING} / ${POOL_TOTAL} remaining

— Hanna, autopilot"

# Write to file for Cowork (Hanna) to surface in chat with Craig
# Telegram disabled per Craig directive 2026-05-30 — statuses stay in Cowork
echo "$BODY" > /Users/craigstratton/ClaudeCodexBridge/prosper-heat-digest-latest.txt

log "hourly digest written to file — pool ${REMAINING}/${POOL_TOTAL}"
