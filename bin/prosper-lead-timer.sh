#!/usr/bin/env bash
# Prosper Lead Distributor — Timer Loop
# Fires T+5 reminder and T+10 reassign for active leads.
# Run every 60s via launchd (io.prosper.lead-timer).
# Authored by Hanna 2026-05-30.

set -uo pipefail
RP=/Users/craigstratton/bin/redis-prosper
NOW=$(date +%s)
LOG=/tmp/prosper-lead-timer.log

REMINDER_THRESHOLD=300   # 5 min
REASSIGN_THRESHOLD=600   # 10 min

log() { echo "[$(date -Iseconds)] $*" >> "$LOG"; }

# Send iMessage via Messages app bridge
send_msg() {
  local phone="$1"
  local body="$2"
  local escaped=$(printf '%s' "$body" | sed 's/"/\\"/g')
  osascript -e "tell application \"Messages\" to send \"$escaped\" to participant \"$phone\" of (1st service whose service type is iMessage)" 2>>"$LOG"
}

# Get all active lead keys
LEAD_KEYS=$($RP KEYS 'prosper.lead.active.*' 2>/dev/null)

if [ -z "$LEAD_KEYS" ]; then
  log "no active leads — sleeping"
  exit 0
fi

for KEY in $LEAD_KEYS; do
  STATUS=$($RP HGET "$KEY" status)
  if [ "$STATUS" != "active" ]; then continue; fi

  ASSIGNED=$($RP HGET "$KEY" assigned_at)
  REMINDED=$($RP HGET "$KEY" reminded_at)
  REP_PHONE=$($RP HGET "$KEY" rep_phone)
  HOMEOWNER=$($RP HGET "$KEY" homeowner_name)
  FIRST_NAME=$(echo "$HOMEOWNER" | awk '{print $1}')
  ELAPSED=$((NOW - ASSIGNED))

  log "$KEY elapsed=${ELAPSED}s reminded=${REMINDED:-no} rep=$REP_PHONE"

  # T+10 → reassign
  if [ "$ELAPSED" -ge "$REASSIGN_THRESHOLD" ]; then
    BODY="PROSPER — ${FIRST_NAME} reassigned.

No contact confirmation within the 10-min window. Lead went to the next active rep. No penalty this time — but daily contact rate counts toward tomorrow's draw priority.

Stay sharp."
    send_msg "$REP_PHONE" "$BODY"
    $RP HSET "$KEY" status reassigned closed_at "$NOW"
    $RP HINCRBY "prosper.lead.rep.${REP_PHONE}" timeouts_today 1
    $RP HSET "prosper.lead.rep.${REP_PHONE}" current_lead_id ''
    log "REASSIGN fired for $KEY"
    continue
  fi

  # T+5 → reminder (only once)
  if [ "$ELAPSED" -ge "$REMINDER_THRESHOLD" ] && [ -z "$REMINDED" ]; then
    BODY="PROSPER — clock check.

${FIRST_NAME} was sent ${ELAPSED} sec ago (~5 min). Reply CONTACTED ${FIRST_NAME} or MISS so the lead doesn't sit. Other reps are warm and ready."
    send_msg "$REP_PHONE" "$BODY"
    $RP HSET "$KEY" reminded_at "$NOW"
    log "REMINDER fired for $KEY"
  fi
done
