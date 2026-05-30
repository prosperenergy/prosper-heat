# Contributing to Prosper Heat

This is intentionally simple. No CI / no linting rules / no test framework. The goal is to keep it readable by anyone who runs a sales team — not just engineers.

## How to help

1. **Fork it. Run it. Break it.** Tell us what blew up.
2. **PRs welcome** — small, focused, with a one-line "why" in the description.
3. **Issues encouraged** — even just "tried this on Twilio, here's what broke."

## Style

- bash + python + bun. No new languages without discussion.
- No frameworks. Plain HTTP, plain Redis, plain shell.
- Tight files (<300 lines each ideal). If a daemon needs more, split it.
- Comments explain *why*, not *what*. Code shows *what*.

## Adding a new rail (Twilio / Telnyx / GHL webhooks)

The chat.db read is iMessage-specific. To swap rails:
1. Replace `helpers/heat-read-since.ts` with a webhook receiver for your rail.
2. Replace `send_msg()` in `bin/prosper-heat-engine.py` with your rail's send API.
3. The Redis schema and engine logic don't change.

PR the rail as `helpers/heat-read-since.<rail>.ts` and `helpers/send-msg.<rail>.sh`.

## Adding a new lead source

`helpers/prosper-heat-extract-leads.py` parses Solar Exclusive iMessage format. For new sources:
1. Write a parser that outputs the same JSON shape (`name / phone / email / address / bill / utility / shade`).
2. Drop it as `helpers/extract-leads.<source>.py`.
3. PR a tiny `docs/lead-sources.md` entry describing the source.

## Adding LLM provider support

`prosper-heat-engine.py llm_classify()` posts to an OpenAI-compatible endpoint. To swap providers:
- Change `GATEWAY` to your provider URL
- Change `GATEWAY_KEY` to your auth header
- Change `LLM_MODEL` to the provider's model id

We've tested with Claude Haiku 4.5 via local CPAMC proxy. If you've tested with GPT-4 / Gemini / Llama, PR results in `docs/llm-providers.md`.

## Reporting from the field

If you run this with real reps, we want to know:
- What did your reps do that broke the classifier? (paste the rep's message)
- What template variants worked better than what's in `docs/opt-in-templates.md`?
- What point math worked for your team? (we use 1/2/5×N — your mileage will vary)
- Any voice-related stuff — your reps probably text differently than ours

Open an issue with the tag `field-report` and the team will fold it in.

## What we won't merge (yet)

- Heavy abstractions (factories, dependency injection, etc.)
- Adding more services (no Kafka, no Kubernetes, no microservices)
- Frontend frameworks (we'll add a plain-HTML dashboard later; that's it)
- Anything that requires SaaS lock-in
- Anything that hides the LLM prompt from view

Keep it visible. Keep it small. Ship it.
