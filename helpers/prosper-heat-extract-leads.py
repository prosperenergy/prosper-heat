#!/usr/bin/env python3
"""Extract all unique Solar Exclusive leads to a JSON pool file (no Redis loop)."""
import sqlite3, re, json, time

DB = "/Users/craigstratton/Library/Messages/chat.db"
FEED_SENDER = "+17027897844"
OUT = "/Users/craigstratton/ClaudeCodexBridge/prosper-heat-lead-pool.json"

conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute(
    """SELECT m.ROWID, m.date, m.attributedBody
       FROM message m JOIN handle h ON m.handle_id=h.ROWID
       WHERE h.id=? AND is_from_me=0 AND m.attributedBody IS NOT NULL
       ORDER BY m.date ASC""",
    (FEED_SENDER,),
)

leads = []
for rowid, date, body in cur.fetchall():
    strs = re.findall(rb"[\x20-\x7e]{4,}", body)
    text = b" ".join(strs).decode("utf-8", errors="ignore")
    if "New Solar Exclusive Lead" not in text:
        continue
    section = text[text.find("New Solar"):text.find("NSDictionary")] if "NSDictionary" in text else text[text.find("New Solar"):]
    m = re.search(
        r"Name:\s*(.+?)\s+Email:\s*(\S+)\s+Phone:\s*(\+\d+)\s+Address:\s*(.+?)\s+Electric Bill:\s*(.+?)\s+Utility Company:\s*(.+?)\s+Shade:\s*(.+?)\s*$",
        section, re.DOTALL,
    )
    if not m:
        continue
    leads.append({
        "rowid": rowid,
        "received_at": date,
        "name": m.group(1).strip(),
        "email": m.group(2).strip(),
        "phone": m.group(3).strip(),
        "address": re.sub(r"\s+", " ", m.group(4).strip()),
        "bill": m.group(5).strip(),
        "utility": m.group(6).strip(),
        "shade": re.sub(r"\s+", " ", m.group(7).strip())[:30],
    })

# Dedupe by phone, keep oldest
seen = set()
unique = []
for L in leads:
    if L["phone"] in seen:
        continue
    seen.add(L["phone"])
    unique.append(L)

# Mark already-worked phones (from Redis state would require subprocess — skip for speed)
# We'll filter in the heat-engine when popping.

pool = {
    "generated_at": int(time.time()),
    "total_in_feed": len(leads),
    "unique_count": len(unique),
    "leads": unique,
}

with open(OUT, "w") as f:
    json.dump(pool, f, indent=2)

print(f"WROTE {OUT}")
print(f"  total in feed: {len(leads)}")
print(f"  unique by phone: {len(unique)}")
print(f"  first 5 by date:")
for L in unique[:5]:
    print(f"    - {L['name']} | {L['address'][:50]} | ${L['bill']}")
