#!/usr/bin/env bash
# Prosper Lead Contest — 9 PM Winner Tally
# Reads all rep states, computes winner, broadcasts to all reps + Craig.
# Authored by Hanna 2026-05-30 — fires once at 9 PM ET today.

set -uo pipefail
RP=/Users/craigstratton/bin/redis-prosper
LOG=/tmp/prosper-contest-winner.log
TG_TOKEN="8799770266:AAGAy7j-QjQJv87t7QHwv4dTM8nKTeR7vEo"
TG_CHAT="7660965553"

log() { echo "[$(date -Iseconds)] $*" >> "$LOG"; }

send_msg() {
  local phone="$1"
  local body="$2"
  local escaped=$(printf '%s' "$body" | sed 's/"/\\"/g')
  osascript -e "tell application \"Messages\" to send \"$escaped\" to participant \"$phone\" of (1st service whose service type is iMessage)" 2>>"$LOG"
}

# Compute leaderboard
REP_KEYS=$($RP KEYS 'prosper.lead.rep.*' 2>/dev/null)
[ -z "$REP_KEYS" ] && { log "no reps registered"; exit 0; }

declare -A BOARD
for K in $REP_KEYS; do
  PHONE="${K#prosper.lead.rep.}"
  NAME=$($RP HGET "$K" name)
  PTS=$($RP HGET "$K" points_today)
  CALLS=$($RP HGET "$K" calls_today)
  TEXTS=$($RP HGET "$K" texts_today)
  SETS=$($RP HGET "$K" sets_today)
  [ -z "$PTS" ] && PTS=0
  BOARD["$PHONE"]="${PTS}|${NAME}|${CALLS:-0}|${TEXTS:-0}|${SETS:-0}"
  log "rep $NAME ($PHONE): $PTS pts (calls=$CALLS texts=$TEXTS sets=$SETS)"
done

# Sort by points desc
WINNER_LINE=""
WINNER_PTS=-1
WINNER_NAME=""
WINNER_PHONE=""
LEADERBOARD=""

for PHONE in "${!BOARD[@]}"; do
  IFS='|' read -r PTS NAME CALLS TEXTS SETS <<< "${BOARD[$PHONE]}"
  LEADERBOARD="${LEADERBOARD}${NAME}: ${PTS} pts (${CALLS} calls / ${TEXTS} texts / ${SETS} sets)\n"
  if [ "$PTS" -gt "$WINNER_PTS" ]; then
    WINNER_PTS=$PTS
    WINNER_NAME=$NAME
    WINNER_PHONE=$PHONE
  fi
done

# Sort leaderboard string by points
SORTED_LB=$(echo -e "$LEADERBOARD" | sort -t: -k2 -rn | head -10)

# Build announcement
if [ "$WINNER_PTS" -le "0" ]; then
  ANNOUNCEMENT="🏆 PROSPER CONTEST — END OF DAY.

No points scored today. Better moves tomorrow.

— Craig"
else
  ANNOUNCEMENT="🏆 PROSPER CONTEST — WINNER LOCKED.

🥇 ${WINNER_NAME} — ${WINNER_PTS} pts — \$300 cash incoming.

Final board:
${SORTED_LB}

Appreciate every one of you who played. Tomorrow we run it back.

— Craig"
fi

# Broadcast to all reps
for PHONE in "${!BOARD[@]}"; do
  send_msg "$PHONE" "$ANNOUNCEMENT"
  log "winner-announce sent to $PHONE"
  sleep 1
done

# Write winner announcement to file for Cowork (Hanna) to surface in chat
# Telegram disabled per Craig directive 2026-05-30 — statuses stay in Cowork
echo "$ANNOUNCEMENT" > /Users/craigstratton/ClaudeCodexBridge/prosper-heat-winner-announcement.txt

log "DONE — winner: $WINNER_NAME ($WINNER_PTS pts) — file written for Cowork relay"
