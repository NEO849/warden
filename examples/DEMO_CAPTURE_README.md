# Demo capture guide — v2 (matches `../DEMO_STORYBOARD.md` klimax-first)

> v2 supersedes the old `demo_e2e.py`/`churn_model` guide. The video's KLIMAX is the real,
> autonomous live chain (`run_live_chain_demo.py` on `scienceModel`), 17/17 poll-until gates.
> Every on-screen number is copy-paste from an actual passing run — never invented.

## 0. Before you record
```bash
cd /root/hackathons/datahub-agent
# stack must be up (systemd boot chain keeps it up across reboots):
systemctl is-active datahub-stack warden-console warden-wake   # → active / active / active
curl -s -m5 -o /dev/null -w '%{http_code}\n' http://localhost:8090/health   # → 200
```
Do ONE silent dry run of Beat 3 first (warm caches / confirm green), THEN the recorded take —
the live chain is idempotent (2× green by design).

## 1. Beat 3 FIRST — the klimax (hardest to get clean; the money shot)
Terminal, large font. The autonomous chain end-to-end:
```bash
DATAHUB_GMS_URL=http://localhost:8090 .venv/bin/python run_live_chain_demo.py
```
Keep the **Trust Console** open in a second window so the green→red `NEEDS_REVIEW` flip is
capturable live: `http://127.0.0.1:8808` (read-only). The lines that MUST land on screen
(from `run_live_chain_demo_*.log`):
- baseline `confidence=0.901`
- silent re-point `SampleHiveDataset → SampleHdfsDataset` (the "a schema-diff sees nothing" moment)
- `Kafka wake trigger — fresh TAG-ADD`
- **the autonomy proof:** `on_graph_via='reverse-lineage'` — scienceModel is NOT in the running
  service's static `WARDEN_WATCH_MODELS`; reverse-lineage resolved it
- `GATE 3 ... confidence=0.6` (the drop lands)
- Trust Console flips `scienceModel` → red `NEEDS_REVIEW`
- `GATE 5 ... downstream agent REFUSED to recommend scienceModel` (the interop moat)
- `LIVE-CHAIN GREEN ✅  ALL 17 GATE CHECKS PASSED`

A terminal-only screencast of this run is captured programmatically via
`work/capture_livechain.sh` (asciinema → agg → mp4) — see `/root/handoff/video/work/`.

## 2. Beat 2 — the mechanic (brief, ~10s of one command)
```bash
.venv/bin/python run_ml_drift_demo.py    # show ONLY beat-1 output: "confidence 0.901, remembered sources [...]"
```
Then DataHub UI → Properties tab → `warden.confidence 0.901` (`http://localhost:9002`).

## 3. Beat 1 — the calm "before" (capture BEFORE step 1 mutates state, or reset)
DataHub UI on the `scienceModel` (mlflow, PROD) entity page — calm/green, one clean upstream path.
Reset to a clean baseline anytime with the demo's own idempotent `baseline_reset` (runs inside
`run_live_chain_demo.py`) or `python seed_demo_graph.py`.

## 4. Voiceover
`../DEMO_VOICEOVER.md` (v2, Kokoro `am_michael` @0.95). Generate:
`/root/handoff/video/kokoroenv/bin/python /root/handoff/video/gen_kokoro_warden.py am_michael 0.95`
→ clips in `/root/handoff/video/audio/warden/`. Record/lay the VO against the assembled cut last.

## 5. Honesty (keep on screen, never narrate past it)
- "wakes on event" = real systemd Kafka Actions consumer (`warden-wake.service`) for this beat;
  polling remains the shipped default elsewhere. Events are demo-injected, not organic prod traffic.
- confidence `0.901 → 0.600` is a real, live-written value; the *drop magnitude* is a principled
  Bayesian log-odds update, NOT a measured drift statistic on this sample pair — the script says so.
- insight/summary text = local Ollama; never claim it is deterministic.

## 6. If a take goes wrong
Re-run — the live chain aborts LOUDLY on any gate (non-zero exit + the exact failing gate), so a
broken number never reaches the terminal you're filming. Read the tail of the new
`run_live_chain_demo_<ts>.log`.
