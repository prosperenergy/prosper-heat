// heat-read-since.ts — bun helper for prosper-contest-tally daemon
// Reads chat.db (FDA via bun) for inbounds from opted-in rep phones since a given timestamp.
// Outputs JSON to stdout: [{phone, rowid, date, text}, ...]
// Usage: bun heat-read-since.ts <apple-epoch-ns> <phone1,phone2,...>

import { Database } from "bun:sqlite";
import { readFileSync } from "node:fs";

const sinceNs = BigInt(process.argv[2] || "0");
const phones = (process.argv[3] || "").split(",").filter(Boolean);

if (phones.length === 0) {
  process.stderr.write("ERROR: no phones provided\n");
  process.exit(1);
}

const db = new Database("/Users/craigstratton/Library/Messages/chat.db", { readonly: true });

const placeholders = phones.map(() => "?").join(",");
const q = db.query<
  { phone: string; rowid: number; date: number; text: string | null; attributedBody: Uint8Array | null },
  any[]
>(`
  SELECT h.id as phone, m.ROWID as rowid, m.date as date,
         m.text as text, m.attributedBody as attributedBody
  FROM message m
  JOIN handle h ON m.handle_id = h.ROWID
  WHERE m.date > ?
    AND m.is_from_me = 0
    AND h.id IN (${placeholders})
  ORDER BY m.date ASC
`);

const rows = q.all(sinceNs as any, ...phones);

const out = rows.map((r) => {
  let text = r.text || "";
  if (!text && r.attributedBody) {
    // Extract printable strings from typedstream blob
    const buf = r.attributedBody;
    let s = "";
    let current = "";
    for (let i = 0; i < buf.length; i++) {
      const c = buf[i];
      if (c >= 0x20 && c <= 0x7e) {
        current += String.fromCharCode(c);
      } else {
        if (current.length >= 4) s += current + " ";
        current = "";
      }
    }
    if (current.length >= 4) s += current;
    // Strip the streamtyped header + Apple metadata
    s = s.replace(/streamtyped.*?NSMutableString\s*/i, "");
    s = s.replace(/iI\s+NSDictionary.*$/s, "").trim();
    text = s;
  }
  return { phone: r.phone, rowid: r.rowid, date: String(r.date), text: text.slice(0, 500) };
});

process.stdout.write(JSON.stringify(out));
