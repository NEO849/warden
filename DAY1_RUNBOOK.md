# Day-1 Runbook — Warden Infra Spike (the go/no-go gate)

> Goal by end of day 3: **PROOF A** (memory writes to the graph, no rebuild), **PROOF B** (an event wakes
> our Action), **PROOF C** (ML lineage stands up — we committed to the Production ML Agents track).
> A+B+C green → build the agent. C fails → drop to the "Agents That Do Real Work" fallback (same core).
> Everything below is source-verified against DataHub docs; the ONE unverified thing is whether the pulled
> quickstart image gates structured properties — Step 5 is exactly that check. Do it first.

---

## Step 0 — Pre-flight (do this before anything; 5 min)

DataHub quickstart is **heavy**. Confirm the host can take it:
- **Docker + Docker Compose** running (`docker info` succeeds).
- **RAM: ≥ 8 GB free for Docker** (quickstart runs ~10 containers). On the VPS check `free -g`.
  ⚠️ We have an OOM history here — if the box is tight, run DataHub on the Mac or a scratch host, not
  alongside memory-hungry services. Set a Docker memory cap if needed.
- **Disk: ≥ 15 GB free** (`df -h`).
- **Ports free:** 9002 (UI), 8080 (GMS), 9092 (Kafka), 8081 (schema registry). `ss -ltnp | grep -E '9002|8080|9092|8081'` should be empty.

Decision: **where do you run it?** Pick the host with the RAM headroom. All commands below run there.

---

## Step 1 — CLI + deps (5 min)
```bash
cd /root/hackathons/datahub-agent
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
datahub version          # note the version — recent (>=0.13) has structured properties GA
```

## Step 2 — Quickstart up (~10–20 min first run, pulls images)
```bash
datahub docker quickstart
```
Verify: open `http://<host>:9002` → login `datahub` / `datahub`. GMS health:
```bash
curl -s http://localhost:8080/health          # expect: {"status":"UP"} or similar 200
```
If it hangs/half-starts → `datahub docker quickstart --stop` then re-run; check `docker ps` for crash-looping
containers and `docker logs <container>` (usually RAM).

## Step 3 — Sample metadata (2 min)
```bash
datahub docker ingest-sample-data
```
In the UI, search `fct_users_created` → you should see a dataset with schema + some lineage. That's our
reasoning substrate for PROOF A/B.

## Step 4 — Auth: PAT + .env (5 min)
Local quickstart often accepts unauthenticated GMS calls, **but provision a token anyway** (the SDK write
path expects one):
- UI → top-right avatar → **Settings → Access Tokens → Generate** (if the menu is missing, token auth is off
  — that's fine locally; leave `DATAHUB_GMS_TOKEN` empty and the SDK will still reach GMS).
```bash
cp .env.example .env 2>/dev/null || true
cat > .env <<'EOF'
DATAHUB_GMS_URL=http://localhost:8080
DATAHUB_GMS_TOKEN=          # paste PAT if token auth is on; leave empty if not
ANTHROPIC_API_KEY=          # not needed until day 4 (agent logic)
EOF
```

## Step 5 — 🔑 PROOF A: memory round-trips to the graph (the critical gate)
This is the single most important check of the whole spike.
```bash
source .venv/bin/activate
python spike/01_write_read_memory.py
```
**GREEN** = it prints `warden.summary` + `warden.confidence = [0.6]` read back, then `PROOF A GREEN ✅`.
→ The custom-PDL-aspect GMS rebuild is off the critical path forever. Proceed.

**If RED — triage in this order:**
1. `StructuredProperties`/`DatasetPatchBuilder` import error → `datahub` too old. `pip install -U 'acryl-datahub>=0.13'`.
2. Define step 403/401 → token auth is on but PAT missing/rong → paste a valid PAT in `.env`.
3. Write succeeds, **read returns empty** → the value likely wrote but the **UI display** is flag-gated
   (`ENABLE_STRUCTURED_PROPERTIES`). That's OK — **we read via API, not the UI.** Re-run the read; if the API
   still returns nothing, set the flag on the GMS container env and `datahub docker quickstart` again.
4. Total dead-end → **fallback:** store memory as an **editable dataset property / documentation aspect**
   keyed by URN (lose "first-class" polish, keep the compounding loop). Note it in ARCHITECTURE.md §9 and move on.

## Step 6 — PROOF B: an event wakes the Action
Terminal 1:
```bash
source .venv/bin/activate
cd spike && datahub actions -c warden_action_config.yaml
```
Terminal 2 (or the UI): edit `fct_users_created`'s **description** or a **schema field**, save.
→ Terminal 1 should print `WARDEN WAKE ▶ ... DOCUMENTATION/... ` within a few seconds. **GREEN.**

**If RED:**
- Consumer can't reach Kafka (`localhost:9092` / schema-registry `8081`) → confirm those ports from Step 0;
  if Docker networking hides them, run the action **inside** the actions container or expose the ports.
- No event fires → the change may not emit an `EntityChangeEvent` (some edits only emit MCL) → try a
  clearer change (add a tag/term) OR widen the filter categories in `warden_action_config.yaml`.
- **Fallback:** the polling loop over `graph.get_urns_by_filter` + `lastModified` (noted in the config).
  Event-driven is nicer for the demo, but polling keeps us moving; revisit later.

## Step 7 — PROOF C: ML lineage stands up (ML-track commitment)
We picked Production ML Agents, so we need model↔feature↔dataset lineage to reason over.
```bash
# Option 1: check whether sample data already includes ML entities
#   UI search: filter entity type = "ML Models" / "ML Feature Tables"
# Option 2: ingest ML sample metadata via the SDK (MLModel, MLFeatureTable, MLModelGroup + lineage).
```
**GREEN** = at least one `MLModel` linked through features to an upstream dataset appears in the UI, so a
schema change upstream is reachable from the model via lineage.
**If RED by day 3** → this is the pivot point: **fall back to "Agents That Do Real Work"** (dataset
incident-triage demo). Same engine; only the scenario + submission track change. No time lost on the core.
> Note: exact ML-entity ingestion snippets are the first thing to nail on day 1–2 — flag me to generate a
> ready-to-run `spike/02_ml_lineage_seed.py` once you confirm the DataHub version from Step 1.

---

## Green-light gate (end of day 3)
Write one line at the top of ARCHITECTURE.md §9:
```
SPIKE: A=green/fallback · B=green/fallback · C=green→ML-track / red→flagship-fallback
```
Only after this do we write agent logic (day 4+). The gate exists so an undocumented infra fight cannot
silently eat the 17-day runway — every branch above has a fallback that keeps us building.

## Failure-mode quick matrix
| Symptom | Likely cause | Move |
|---|---|---|
| quickstart containers crash-loop | RAM | cap/other host; `docker logs` |
| import errors in spike scripts | old `acryl-datahub` | `pip install -U` |
| 401/403 on write | token auth on, no PAT | PAT in `.env` |
| write ok, read empty | UI flag gate only | read via API; set flag if needed |
| no event fires | edit didn't emit ECE | tag/term change; widen filter; polling fallback |
| no ML entities | sample lacks ML | `02_ml_lineage_seed.py` (ask me) or flagship fallback |
