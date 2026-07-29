# Mnemo — Demo Voiceover Script (Kokoro `am_michael`, <3:00) — v2, matches `DEMO_STORYBOARD.md`

Production-ready voiceover, one block per storyboard beat, timed to what `run_ml_drift_demo.py` /
`run_live_chain_demo.py` actually print on screen. **Same voice as the prior hackathon video:**
Kokoro `am_michael` at speed **0.95** (chosen human-over-edge-tts in the earlier A/B).

**Generate:** in `/root/handoff/video/`, one line per block →
`kokoroenv/bin/python gen_kokoro.py am_michael 0.95` → master with the existing ffmpeg chain
(highpass 90 · de-ess · acompressor · loudnorm I=-16:TP=-1.5:LRA=11 · adelay 130 · afade 0.14).

**Voice rules (baked into the writing below):** short single-thought sentences; punctuation is the
only pause control (commas = short beat, em-dash = harder beat, period = full stop); no head-silence
trim; nothing over-processed. Total target ~2:20, hard ceiling 3:00.

> **Truth check (every line is backed by a live, passing run — no claim the code doesn't make):**
> confidence `0.901 → 0.600` is real and written on the graph; the governance write is a real
> `mnemo.governance_status=NEEDS_REVIEW` + `mnemo-needs-review` tag (NOT a Cloud "Proposal", which
> OSS lacks); the Kafka wake, the reverse-lineage resolution, and the downstream refusal are all
> **live-verified**, not scripted narration over a recording (`run_live_chain_demo_20260728_220100.log`,
> 17/17 gates green); the eval bar (optional beat) is the real N=21 result.

> **Usefulness anchor (say this — it's the "why does this matter" line a value-monitor demo can't say):**
> A value- or PSI-drift monitor watches the *data flowing through* the model — it can only alarm
> **after** bad data has already been ingested and scored. Mnemo watches the *structure of what feeds
> the model* — it catches the source swap **before** the next training run ever touches it.

---

## 01 — HOOK (0:00–0:15) · on screen: `scienceModel` page, calm/green (Beat 1)

> This is how a production model dies. Not with an error — with silence.
> Someone re-points an upstream table. Same column names. Same feature. No alert fires.
> The model just quietly starts scoring on the wrong data. And nobody notices, until the business does.

## 02 — MEMORY, THE MECHANIC (0:15–0:50) · terminal BEAT 1 of `run_ml_drift_demo.py` + `mnemo.confidence` in the UI (Beat 2)

> This is Mnemo. It doesn't re-derive from scratch — it remembers. A Bayesian confidence,
> written directly onto the entity as a structured property. Right now: nine-tenths.
> But high confidence alone isn't the same as trusted. Mnemo also tracks how much independent
> evidence backed that number — and it won't auto-act on a high score built from just one
> observation. One clean read is watched, not blindly trusted. That discipline is what makes
> what happens next safe to automate.

## 03 — THE LIVE CHAIN, the klimax (0:50–2:10) · `run_live_chain_demo.py` + Trust Console flip (Beat 3)

> Watch this happen without me touching anything.
> A real Kafka event fires — on the model's new upstream source.
> Mnemo isn't told which model that feeds. It isn't even on its watch-list.
> It works that out itself, by walking the lineage graph backward.
> It wakes. It re-reads the source. And it finds the delta against what it remembered —
> a source that changed, under a schema that didn't.
> Confidence drops — nine-tenths to six-tenths — below the governance line.
> Mnemo writes that verdict onto the model itself, as a needs-review flag —
> and it never touches the model's own description.
> And now — a completely separate agent, that has never heard of Mnemo,
> reads that flag straight off the graph, and refuses to recommend this model for production.
> End to end. Live. Autonomous.

## 04 — TITLE CARD (2:10–2:20)

> Mnemo. Compounding, governed memory for the data graph.
> The reference agent suggests once. Mnemo remembers — and a stranger's agent can trust what it wrote.

---

## OPTIONAL 05 — EVAL BAR (+0:00–0:15, only if it stays under 3:00) · `examples/eval_lift.svg`

> One more, measured. Stripped to bare facts — and on cases built to fool a shortcut —
> the memory lifts triage accuracy from one-half to nine-tenths, by reasoning.
> And irrelevant memory hurts. So the lift is the relevant memory, not just more words.

## OPTIONAL 06 — ARCHITECTURE (+0:00–0:15, only if it stays under 3:00) · `ARCHITECTURE.md §4` diagram

> Under the hood: Mnemo reads the graph through DataHub's own APIs, updates a Bayesian confidence
> model, gates every write on governance, and writes typed structured properties back.

---

### Recording notes (for the human)

- Capture one screen clip per block (browser fullscreen, mic off) into `handoff/video/incoming/01..04`
  (+ optional 05, 06). Let any wait-clips run fully; Claude speed-ramps them at assembly.
- Numbers are spoken as words on purpose ("nine-tenths", "six-tenths") — cleaner in TTS than "0.9 / 0.6";
  the *screen* shows the exact figures (0.901 → 0.600), so precision is preserved visually.
- Money-shot = block 03 (the live chain, especially the reverse-lineage line and the console flip).
  Give it a beat of air before the confidence-drop sentence lands in the cut.
- Block 02's mechanic sentence ("one clean read is watched, not blindly trusted") is the honesty
  nuance — do not cut it even under time pressure; it's what keeps the 0.9→0.6 story from reading as
  "the system was fooled," when it was in fact never auto-trusting in the first place.
