# Warden — Demo Video Storyboard (<3 min) — v2, klimax-first

> **Category:** Production ML Agents · **Scored under:** Submission Quality (judges' first impression).
> **v2 change from v1** (`DEMO_STORYBOARD_v1_backup.md`): the real, live, autonomous chain
> (`run_live_chain_demo.py`) was buried as "Optional Shot 11" at the very end. It is now the KLIMAX —
> the video builds to it and ends on its payoff, not to a scripted demo with an architecture diagram
> tacked on after. `run_ml_drift_demo.py` is demoted to a 20-second mechanic explainer in the middle,
> not the carrier of the story.
> **HERO:** a real Kafka event → autonomous reverse-lineage resolution → a Bayesian confidence drop →
> a governed graph write → a **different agent, reading only the graph, refusing the model**. Every
> line quoted below is copy-pasted from an actual passing run
> (`run_live_chain_demo_20260728_220100.log`, 17/17 gates green).
> **Honesty contract (do NOT narrate past this):** the demos really run; "wakes on event" is real —
> a systemd-hosted Kafka Actions consumer (`warden-wake.service`), not a poll loop, for this beat
> (polling remains the shipped default for the rest of the agent); insight/summary text is generated
> by **local Ollama**; confidence `0.901 → 0.600` is a real, live-written value — the *drop magnitude*
> is a principled Bayesian log-odds update (§ below), not a measured drift statistic on this demo's
> sample dataset pair, and the script says so on screen.
> **Recording kit:** one terminal (720p+, large font) + Chrome on DataHub UI `http://localhost:9002`
> + the Trust Console (`console/app.py`). No editing beyond cuts + the voiceover track.

---

## THE OPENING HOOK — 0:00–0:15 (voiceover, verbatim)

> **"This is how a production model dies. Not with an error — with silence.
> Someone re-points an upstream table. Same column names. Same feature. No alert fires.
> The model just quietly starts scoring on the wrong data — and nobody notices until the business does."**

On screen while this is spoken: **Beat 1** below.

---

## The 3 beats

| # | Time | On-screen (terminal / DataHub UI :9002 / Trust Console) | Voiceover (tight) | What it proves — the moat |
|---|------|-----------------------------------------------------------|--------------------|-----------------------------|
| **1 — COLD OPEN, the pain** | 0:00–0:18 | DataHub UI on the `scienceModel` (mlflow, PROD) entity page — the exact model the climax resolves — calm and green. Slowly zoom on the "PROD" badge and the lineage graph showing one clean upstream path. Nothing looks wrong. | *(the verbatim hook above)* | Sets the stakes: the failure is **invisible to the current UI** — a valid model, a valid lineage graph, no error. A one-shot schema-diff run right now would report "all clear." |
| **2 — MEMORY, THE MECHANIC (brief explainer)** | 0:18–0:55 | Cut to terminal, `python run_ml_drift_demo.py` — **only BEAT 1** of its output on screen (~10s): `model memory established: confidence 0.901, remembered sources [...]`. Freeze that line. Cut to DataHub UI → Properties tab → `warden.confidence 0.901`. | "Warden remembers — a Bayesian confidence, log-odds under the hood, written directly onto the entity as a structured property. But high confidence alone doesn't mean auto-trusted: Warden also tracks how much independent evidence backed that number, and gates any silent auto-write behind a minimum evidence bar. One clean observation reads 0.901 — high — but isn't enough mass yet to auto-write; it's watched, not blindly trusted. That discipline is what makes the next part safe to automate." | **Per-asset, principled memory that lives ON the graph** — not a re-derive-from-scratch score, and not a confidence number that auto-acts just because it's high. Sets up why the climax's write is a *governed* flag, not a silent mutation. |
| **3 — THE LIVE CHAIN (klimax)** | 0:55–2:15 | Split screen. **Left:** `python run_live_chain_demo.py` running live, real timestamps scrolling. **Right:** Trust Console on `scienceModel`. Sequence, each beat lingers ~1s: (a) baseline `confidence=0.901` (b) silent re-point `SampleHiveDataset → SampleHdfsDataset` — *"a schema-diff sees nothing"* line on screen (c) `Kafka wake trigger — fresh TAG-ADD` fires (d) the line *"scienceModel is NOT in the running service's static WARDEN_WATCH_MODELS ... reverse lineage"* — highlight this line, it's the autonomy proof (e) `GATE 3 ... confidence=0.6` — **the confidence-drop number lands** (f) Trust Console right pane flips `scienceModel` from green to red **NEEDS_REVIEW** (g) `GATE 5: interop_demo.py ... downstream agent REFUSED to recommend scienceModel` (h) `LIVE-CHAIN GREEN ✅ ALL 17 GATE CHECKS PASSED`. | "Watch this happen without me touching anything. A real Kafka event fires on the model's *new* source. Warden isn't told which model that feeds — it isn't even on its watch-list — it works that out itself, by walking the lineage graph backward. It wakes, re-reads the source, and finds the delta against what it remembered. Confidence drops — nine-tenths to six-tenths — below the line. Warden writes that verdict onto the model as a needs-review flag, never touching the model's own description. And now — a completely separate agent, that has never heard of Warden, reads that flag straight off the graph — and refuses to recommend this model for production. End to end. Live. Autonomous." | **BUILT & live-verified, 17/17 poll-until gates.** Autonomous reverse-lineage discovery (not a hardcoded watch-list) + a governed, non-destructive write + graph-native interop: any agent, zero shared code, can consult and act on Warden's verdict because it lives ON the entity. This is the single beat competitors' "remembers the conversation" pattern structurally cannot replicate — there is nothing on the graph for a foreign agent to read. |

**Title card, 2:15–2:25:** *Warden — compounding, governed memory for the data graph.
The reference agent suggests once. Warden remembers — and a stranger's agent can trust what it wrote.*

**Total runtime: ~2:25 (3 beats + hook + title).** Comfortable margin under 3:00 — and it leaves ~35s
of slack for the optional beats below if a cut wants to run closer to the ceiling.

---

## Optional extended-cut beats (only if time remains under 3:00 — otherwise cut)

These were full shots in v1; they're real, live-verified, and worth keeping in a longer director's
cut, but none of them is the climax anymore — insert between Beat 3 and the title card only if the
core 3-beat cut is comfortably under budget.

| # | On-screen | Voiceover | Note |
|---|-----------|-----------|------|
| **Architecture** | `ARCHITECTURE.md §4` diagram: GMS/UI/Kafka → Warden (reconcile → confidence → gate → reflect) → structured properties. | "Under the hood: Warden reads the graph through DataHub's own APIs, updates a Bayesian confidence model, gates every write on governance, and writes typed structured properties back." | Grounds the pitch in real plumbing for judges who want the architecture beat; cut first if time is tight since Beat 3 already shows the mechanism live. |
| **Reflection crown** | `run_reflection_demo.py` output: lineage-wide insight, `confidence 0.912`, citing 3 assets, written on the model. | "And it goes further — Warden reflects across the whole lineage path to a graph-level insight that lives on no single asset." | `warden/reflection.py` is BUILT & GREEN. |
| **Eval lift** | `examples/eval_lift.svg`: WITHOUT 0.52 → **WITH_RAW 0.91** → WITH 1.00, PLACEBO 0.33 (N=21). | "Measured: the memory lifts triage accuracy from 0.52 to 0.91 by reasoning — even on cases built to defeat a shortcut — and irrelevant memory hurts, so it's the relevant memory, not just more tokens." | **BUILT & run** — real chart from `eval/results.csv`. |
| **Honesty close (if Beat 3's ending feels too abrupt)** | Terminal: `LIVE-CHAIN GREEN ✅` full 17-gate summary held on screen 2s longer. | "Every check you just saw is a live assertion against a running DataHub, not a canned recording." | Use only if the title card feels rushed; Beat 3 already carries the honesty payload on screen. |

---

## Recording order (efficient for a solo builder)

1. **Beat 3 first** (it's the hardest to get clean): `systemctl status warden-wake.service` → confirm
   active, then screen-record `python run_live_chain_demo.py` end-to-end, Trust Console open in a
   second window/monitor so the red flip is capturable live. Do a second clean take for safety —
   this is the money shot.
2. **Beat 2**: run `python run_ml_drift_demo.py`, screen-record only its BEAT 1 output (cut the rest —
   it's not the carrier anymore). Capture the `warden.confidence 0.901` DataHub UI panel right after.
3. **Beat 1**: capture the calm `scienceModel` DataHub UI page (do this BEFORE step 1 corrupts its
   state, or reset via the demo's own idempotent `baseline_reset`).
4. Optional beats (architecture screenshot, `run_reflection_demo.py`, `examples/eval_lift.svg`) only
   if the core cut has slack.
5. Record the voiceover last against the assembled cut — see `DEMO_VOICEOVER.md` (updated to match
   this v2 beat structure). The hook (0:00–0:15) is verbatim above.
