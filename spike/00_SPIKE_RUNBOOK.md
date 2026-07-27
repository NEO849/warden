# Infra Spike Runbook — Days 1–3 (GREEN-LIGHT GATE)

> Goal: prove the two hardest, least-documented things work **before** writing any agent logic.
> If either fails, take the fallback — do NOT burn days fighting it.
> ⚠️ All scripts below are grounded in DataHub docs but are **starter scaffolds** — verify exact
> API signatures against `scratchpad/audit_source.md` (whitebox source-auditor output) on day 1.

## The gate (must both be GREEN by end of day 3)
- [ ] **PROOF A** — write a `mnemo.memory` **structured property** onto a sample dataset via SDK, read it back. (No GMS rebuild.)
- [ ] **PROOF B** — a minimal custom **Action** fires on a real `EntityChangeEvent_v1` when you change a dataset in the UI.

If A fails → fallback: store memory as a **glossary/documentation aspect** or an external sidecar keyed by URN (lose "first-class" polish, keep the loop).
If B fails → fallback: **polling loop** over `search` + `lastModified` instead of the Kafka event stream.

---

## Step 0 — stand up DataHub (day 1, ~30 min)
```bash
cd /root/hackathons/datahub-agent/spike
bash setup.sh          # installs CLI, runs quickstart, ingests sample data
# UI: http://localhost:9002  (login datahub / datahub)
# GMS API: http://localhost:8080
```
Get a personal access token: UI → Settings → Access Tokens → generate.
Put it in `.env`:
```
DATAHUB_GMS_URL=http://localhost:8080
DATAHUB_GMS_TOKEN=<token>
ANTHROPIC_API_KEY=<key>   # only needed once agent logic starts (day 4+)
```

## Step 1 — PROOF A: structured-property memory (day 1–2)
```bash
# 1. define the property (no rebuild — this is the whole feasibility bet)
datahub properties upsert -f mnemo_memory_property.yaml

# 2. write a memory value onto a sample dataset + read it back
python 01_write_read_memory.py
```
Expect: script prints the memory record it wrote, then reads it back identical.
✅ If this works, the custom-PDL-aspect rebuild is OFF the critical path forever.

## Step 2 — PROOF B: event-driven Action (day 2–3)
```bash
# run the action listener
datahub actions -c mnemo_action_config.yaml
# then in the UI: edit a sample dataset's description or schema
# → watch the terminal print the EntityChangeEvent
```
✅ If the event prints, the event-driven differentiator is real.
❌ If Kafka/schema-registry access fights you, switch to the polling fallback (note it, move on).

## Step 3 — decision (end of day 3)
Write one line in `../ARCHITECTURE.md §5`: `SPIKE: A=green/fallback, B=green/fallback`.
Only after this gate do we write agent logic (day 4+).
