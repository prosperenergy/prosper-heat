#!/usr/bin/env python3
"""Prosper Heat — engine core (python). Reads new inbounds from a JSON file
(written by bun helper), classifies each via strict regex + LLM fallback,
updates Redis, sends acks via osascript Messages, auto-distributes next leads.
Authored by Hanna 2026-05-30."""

import json, sys, subprocess, re, os, time, urllib.request

RP = "/Users/craigstratton/bin/redis-prosper"
POOL_JSON = "/Users/craigstratton/ClaudeCodexBridge/prosper-heat-lead-pool.json"
LOG = "/tmp/prosper-heat-engine.log"
GATEWAY = "http://127.0.0.1:8317/v1/chat/completions"
GATEWAY_KEY = "prosper-hanna-2026"
LLM_MODEL = "claude-haiku-4-5-20251001"

REP_NAMES = {
    "+13303293748": "Garett",
    "+14439004416": "Cole",
    "+15304489938": "Jeff",
    "+13853350157": "Monty",
    "+18014006701": "Scott Blackhurst",
    "+18017873504": "Mo",
    "+18019955913": "Chad",
    "+16575468448": "Scott",
}


def normalize_phone(value):
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    return f"+{digits}" if digits else ""


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}\n")


def rp(*args):
    return subprocess.run([RP] + list(args), capture_output=True, text=True).stdout.strip()


def send_msg(phone, body):
    if os.environ.get("PROSPER_HEAT_DRY_RUN") == "1":
        log(f"DRY send to {phone}: {body[:160]!r}")
        return True

    script = """
on run argv
  set targetPhone to item 1 of argv
  set messageBody to item 2 of argv
  tell application "Messages"
    send messageBody to participant targetPhone of (1st service whose service type is iMessage)
  end tell
end run
"""
    result = subprocess.run(["osascript", "-e", script, phone, body], capture_output=True, text=True)
    if result.returncode != 0:
        log(f"send_msg FAILED to {phone}: {result.stderr.strip()[:300]}")
        return False
    log(f"send_msg OK to {phone}: {body.splitlines()[0][:120] if body else ''}")
    return True


def extract_clean_text(raw):
    """Strip Apple chat.db typedstream noise; return just the user's message."""
    m = re.search(r"NSString\s+(.+?)(?:\s+NSDictionary|\s+__kIM|\s*$)", raw)
    if m:
        return m.group(1).strip()
    return raw.strip()


def is_imessage_reaction(text):
    """Ignore tapback/reaction artifacts like: Loved "message body"."""
    return bool(re.match(r"^\s*(Loved|Liked|Disliked|Emphasized|Laughed at|Questioned)\s+[\"“]", text or "", re.I))


def strict_classify(text):
    """Returns list of verbs detected by strict pattern. Fast path."""
    up = text.upper().strip()
    verbs = []

    # Rep notes often arrive as "Name: called, texted, miss" or
    # "called / texted / misd / next". Count every action in order.
    action_patterns = [
        ("READY", r"\bREADY\b"),
        ("YES", r"\bY(?:ES)?\b"),
        ("NO", r"\bNO\b"),
        ("PAUSE", r"\bPAUSE\b"),
        ("GO", r"\bGO\b"),
        ("CALL", r"\b(CALLED|CALL|CALLED\s+AND|LEFT\s+(A\s+)?VM|VOICEMAIL)\b"),
        ("TEXT", r"\b(TEXTED|TEXT|TXT|SENT\s+(A\s+)?TEXT)\b"),
        ("SET", r"\b(SET|BOOKED|APPOINTMENT|APPT|SCHEDULED|LOCKED)\b"),
        ("MISS", r"\b(MISSED|MISS|MISD|NO\s+ANSWER|NO\s+ANS|DIDN'?T\s+ANSWER|DISCONNECTED|STOP\s+CALLING|PLEASE\s+STOP|DNC)\b"),
        ("NEXT", r"\bNEXT\b"),
    ]

    matches = []
    for verb, pattern in action_patterns:
        match = re.search(pattern, up)
        if match:
            matches.append((match.start(), verb))

    for _, verb in sorted(matches, key=lambda item: item[0]):
        if verb not in verbs:
            verbs.append(verb)

    # Avoid treating a plain "yes/no/go" inside a longer lead note as a control
    # command. Those only count when they are the whole reply or the prefix.
    if len(verbs) > 1:
        control = {"READY", "YES", "NO", "PAUSE", "GO"}
        verbs = [verb for verb in verbs if verb not in control or re.match(rf"^\s*{verb}\b", up)]

    return verbs


def llm_classify(text, rep_name, current_lead_name):
    """LLM fallback when strict regex misses. Returns list of verbs."""
    sys_prompt = (
        "You are a strict parser for sales-rep replies in a lead-distribution contest. "
        "Read the rep's message and classify what ACTION they took. "
        "Return ONLY valid JSON in this exact shape: "
        '{"verbs": ["CALL"|"TEXT"|"SET"|"MISS"|"NEXT"|"READY"|"YES"|"NONE"], "reason": "short why"}\n\n'
        "Definitions:\n"
        "- CALL = they called the homeowner (even if no answer, voicemail, etc.)\n"
        "- TEXT = they sent a text to the homeowner\n"
        "- SET = they booked an appointment / locked the set\n"
        "- MISS = they couldn't reach / no answer / passing on the lead / releasing\n"
        "- NEXT = they want the next lead\n"
        "- READY / YES = opt-in or daily check-in confirmation\n"
        "- NONE = the message is a question, social chat, or unrelated\n\n"
        "Multiple verbs allowed: e.g. ['CALL','TEXT','MISS'] if they called, texted, and got no answer.\n"
        "Be generous — if rep says 'left a vm and sent text', that's CALL+TEXT+MISS (no live conversation).\n"
        "If rep says 'got a hold of them and they're set for Tuesday', that's CALL+SET.\n"
    )
    user = f"Rep '{rep_name}' working lead '{current_lead_name or 'unassigned'}' replied: {text!r}"
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ],
        "max_tokens": 200,
    }
    try:
        req = urllib.request.Request(
            GATEWAY,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {GATEWAY_KEY}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
            content = data["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
                verbs = [v for v in parsed.get("verbs", []) if v in ("CALL", "TEXT", "SET", "MISS", "NEXT", "READY", "YES")]
                log(f"LLM classify: {text!r} -> {verbs} ({parsed.get('reason', '')[:60]})")
                return verbs
    except Exception as e:
        log(f"LLM classify FAILED: {e}")
    return []


def assign_next_lead(rep_phone):
    """Pop next available lead from pool, assign to rep, send packet."""
    log(f"assign_next_lead start for {rep_phone}")
    try:
        with open(POOL_JSON) as f:
            pool = json.load(f)
    except Exception as e:
        log(f"pool read failed: {e}")
        return False

    # Worked phones = anything in Redis active.*
    worked = set()
    keys = rp("KEYS", "prosper.lead.active.*").split()
    for k in keys:
        if not k:
            continue
        ph = rp("HGET", k, "homeowner_phone")
        if ph:
            worked.add(ph)

    for L in pool["leads"]:
        if L["phone"] in worked:
            continue
        # Assign
        now = int(time.time())
        lid = f"{L['phone'].lstrip('+')}-{now}"
        rp("HSET", f"prosper.lead.active.{lid}",
           "homeowner_name", L["name"], "homeowner_phone", L["phone"],
           "homeowner_email", L["email"], "address", L["address"],
           "bill", L["bill"], "utility", L["utility"], "shade", L["shade"],
           "rep_phone", rep_phone, "assigned_at", str(now), "reminded_at", "",
           "status", "active", "source", "solar_exclusive")
        rp("HSET", f"prosper.lead.rep.{rep_phone}", "current_lead_id", lid)
        first = L["name"].split()[0]
        packet = (
            f"🎯 NEXT LEAD — Clock starts NOW:\n\n"
            f"{L['name']}\n{L['phone']}\n{L['email']}\n{L['address']}\n\n"
            f"Bill: ${L['bill']} / month\n"
            f"Utility: {L['utility']}\n"
            f"Shade: {L['shade']}\n\n"
            f"Move: CALL → TEXT → SET or MISS. Then NEXT."
        )
        sent = send_msg(rep_phone, packet)
        log(f"ASSIGNED {L['name']} ({L['phone']}) to {rep_phone}")
        if not sent:
            log(f"ASSIGNED but packet send failed for {rep_phone}; lead_id={lid}")
        return True

    send_msg(rep_phone, "Queue empty — no more fresh leads in the pool. You're at the front of the line when the next batch drops.")
    log(f"queue empty for {rep_phone}")
    return False


def process_inbound(phone, text):
    """Parse one inbound from a rep, update state, send acks."""
    clean = extract_clean_text(text)
    if not clean or len(clean) < 1:
        return
    if is_imessage_reaction(clean):
        log(f"skip iMessage reaction artifact from {phone}: {clean[:140]!r}")
        return

    rep_key = f"prosper.lead.rep.{phone}"
    rep_name = REP_NAMES.get(phone, "Rep")
    current_lead_id = rp("HGET", rep_key, "current_lead_id")
    current_lead_name = ""
    if current_lead_id:
        current_lead_name = rp("HGET", f"prosper.lead.active.{current_lead_id}", "homeowner_name")

    # Strict first
    verbs = strict_classify(clean)
    if not verbs:
        # Fallback to LLM — but only if message is plausibly contest-related
        # Skip pure greetings/short noise
        if len(clean) < 4 and clean.upper() not in ("HI", "OK", "YO", "Y", "N"):
            log(f"skip noise from {phone}: {clean!r}")
            return
        verbs = llm_classify(clean, rep_name, current_lead_name)

    if not verbs or verbs == ["NONE"]:
        log(f"no actionable verb in {phone}: {clean!r}")
        return

    log(f"VERBS for {phone}: {verbs} (text={clean!r})")

    point_delta = 0
    actions = []
    want_next = False
    released_or_set = False

    for v in verbs:
        if v in ("READY", "YES"):
            rp("HSET", rep_key, "status", "ACTIVE_DRAWING")
            pts = rp("HGET", rep_key, "points_today") or "0"
            send_msg(phone, f"🟢 {rep_name} — you're in. Current points: {pts}. Watch for your first lead.")
            actions.append("opted-in")
        elif v == "NO":
            rp("HSET", rep_key, "status", "SKIP_TODAY")
            send_msg(phone, "Got it — skipping you for the day. Reply YES or READY anytime to jump back in.")
            actions.append("skip-today")
        elif v == "PAUSE":
            rp("HSET", rep_key, "status", "PAUSED")
            send_msg(phone, "Paused. No leads coming your way until you reply GO.")
            actions.append("paused")
        elif v == "GO":
            rp("HSET", rep_key, "status", "ACTIVE_DRAWING")
            send_msg(phone, "Back in. Pulling your next lead now.")
            want_next = True
            actions.append("resumed")
        elif v == "CALL":
            rp("HINCRBY", rep_key, "calls_today", "1")
            rp("HINCRBY", rep_key, "points_today", "2")
            point_delta += 2
            if current_lead_id:
                rp("HSET", f"prosper.lead.active.{current_lead_id}", "called", "1")
            actions.append("CALL +2")
        elif v == "TEXT":
            rp("HINCRBY", rep_key, "texts_today", "1")
            rp("HINCRBY", rep_key, "points_today", "1")
            point_delta += 1
            if current_lead_id:
                rp("HSET", f"prosper.lead.active.{current_lead_id}", "texted", "1")
            actions.append("TEXT +1")
        elif v == "SET":
            if not current_lead_id:
                send_msg(phone, "SET not counted - no active lead is open for you. Reply NEXT to pull a lead first.")
                log(f"SET REJECTED for {phone} - no active lead: {clean!r}")
                continue
            lead_key = f"prosper.lead.active.{current_lead_id}"
            lead_status = rp("HGET", lead_key, "status")
            lead_rep = normalize_phone(rp("HGET", lead_key, "rep_phone"))
            if lead_status != "active" or lead_rep != normalize_phone(phone):
                stale_lead_id = current_lead_id
                rp("HSET", rep_key, "current_lead_id", "")
                current_lead_id = ""
                send_msg(phone, "SET not counted - that lead is no longer active for you. Reply NEXT for a fresh one.")
                log(
                    f"SET REJECTED for {phone} - stale lead {stale_lead_id} "
                    f"status={lead_status!r} rep={lead_rep!r}: {clean!r}"
                )
                continue
            rp("HSET", lead_key, "set", "1", "status", "closed_set", "closed_at", str(int(time.time())))
            if rp("HGET", lead_key, "status") != "closed_set":
                send_msg(phone, "SET not counted - I could not verify the lead status update. Send it again or ping Craig.")
                log(f"SET REJECTED for {phone} - closed_set verify failed for {current_lead_id}: {clean!r}")
                continue
            lw = int(rp("HINCRBY", rep_key, "leads_worked_today", "1"))
            set_pts = 5 * lw
            rp("HINCRBY", rep_key, "sets_today", "1")
            rp("HINCRBY", rep_key, "points_today", str(set_pts))
            point_delta += set_pts
            rp("HSET", rep_key, "current_lead_id", "")
            current_lead_id = ""
            actions.append(f"SET +{set_pts} (×{lw})")
            released_or_set = True
            want_next = True
        elif v == "MISS":
            rp("HINCRBY", rep_key, "misses_today", "1")
            rp("HINCRBY", rep_key, "leads_worked_today", "1")  # count it as worked even without set
            if current_lead_id:
                rp("HSET", f"prosper.lead.active.{current_lead_id}", "status", "released", "closed_at", str(int(time.time())))
            rp("HSET", rep_key, "current_lead_id", "")
            current_lead_id = ""
            actions.append("MISS (no penalty)")
            released_or_set = True
            want_next = True  # auto-serve next after MISS
        elif v == "NEXT":
            if rp("HGET", rep_key, "current_lead_id"):
                send_msg(phone, "Still have a lead open — close it (CALLED → TEXTED → SET or MISS) first.")
                actions.append("NEXT denied (lead open)")
            else:
                want_next = True
                actions.append("NEXT requested")

    # Composite ack message
    if point_delta > 0 or released_or_set:
        pts = rp("HGET", rep_key, "points_today") or "0"
        lw = rp("HGET", rep_key, "leads_worked_today") or "0"
        if released_or_set and not want_next:
            send_msg(phone, f"✅ Logged: {', '.join(actions)}. TOTAL: {pts} pts.")
        elif point_delta > 0 and not released_or_set:
            send_msg(phone, f"✅ {', '.join(actions)}. TOTAL: {pts} pts. Keep going.")

    if want_next:
        log(f"want_next for {phone}; actions={actions}")
        assigned = assign_next_lead(phone)
        if assigned:
            pts = rp("HGET", rep_key, "points_today") or "0"
            lw_after = rp("HGET", rep_key, "leads_worked_today") or "0"
            next_set_pts = 5 * (int(lw_after) + 1)
            send_msg(phone, f"📊 Score: {pts} pts • {lw_after} leads worked • next SET = {next_set_pts} pts.")


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        log("no stdin")
        return
    try:
        inbounds = json.loads(raw)
    except Exception as e:
        log(f"json parse fail: {e}")
        return
    if not inbounds:
        log("no new inbounds")
        return
    log(f"processing {len(inbounds)} inbound(s)")
    for row in inbounds:
        process_inbound(row["phone"], row["text"])


if __name__ == "__main__":
    main()
