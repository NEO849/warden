# Mnemo — Demo Voiceover Script (Kokoro `am_michael`, <3:00)

Production-ready voiceover, one block per storyboard shot, timed to what `demo_e2e.py` /
`run_ml_drift_demo.py` actually print on screen. **Same voice as the prior hackathon video:**
Kokoro `am_michael` at speed **0.95** (chosen human-over-edge-tts in the earlier A/B).

**Generate:** in `/root/handoff/video/`, one line per block →
`kokoroenv/bin/python gen_kokoro.py am_michael 0.95` → master with the existing ffmpeg chain
(highpass 90 · de-ess · acompressor · loudnorm I=-16:TP=-1.5:LRA=11 · adelay 130 · afade 0.14).

**Voice rules (baked into the writing below):** short single-thought sentences; punctuation is the
only pause control (commas = short beat, em-dash = harder beat, period = full stop); no head-silence
trim; nothing over-processed. Total target ~2:40, hard ceiling 3:00.

> **Truth check (every line is backed by the live demo — no claim the code doesn't make):**
> confidence `0.901 → 0.600` is real; the governance write is a real `agent`/`mnemo.governance_status
> =NEEDS_REVIEW` + `mnemo-needs-review` tag on the graph (NOT a Cloud "Proposal", which OSS lacks);
> event-wake is live-verified; the eval bar is the real N=21 result.

---

## 01 — HOOK (0:00–0:15) · on screen: churn_model page, calm/green (Shot 1)

> This is how a production model dies. Not with an error — with silence.
> Someone re-points an upstream table. Same column names. Same feature. No alert fires.
> The model just quietly starts scoring on the wrong data. And nobody notices, until the business does.

## 02 — ESTABLISHED MEMORY (0:15–0:35) · terminal BEAT 1 + `mnemo.*` in the UI (Shot 2)

> This is Mnemo. It has already watched this model's inputs, across earlier events.
> It doesn't re-derive from scratch — it remembers. A Bayesian confidence of nine-tenths,
> and the exact source its feature is fed from, written on the graph itself.

## 03 — THE SILENT RE-POINT (0:35–1:00) · terminal BEAT 2 + two source schemas (Shot 3)

> Now a data engineer swaps the feature's upstream source.
> The new table's timestamp means ingest time — not signup time. Same feature name. Same description.
> No error is thrown. Every one-shot schema-diff sees a valid model. This is exactly how models die silently.

## 04 — MNEMO COMPARES TO MEMORY (1:00–1:20) · terminal BEAT 3-4, source delta (Shot 4)

> Mnemo's reconcile pass runs. It loads the source it remembered, re-reads the feature's live lineage —
> and sees the delta. Not a broken schema. A source that changed, relative to what it knew before.

## 05 — RE-SCORE → GOVERNED NEEDS-REVIEW (1:20–1:45) · confidence drop + real UI tag/property (Shot 5)

> The contradicting evidence drops its confidence, from nine-tenths to six-tenths — below the governance line.
> On a production model, Mnemo does not auto-trust, and it does not rewrite the model.
> It flags it for a human. A needs-review tag, and a governance-status property, written right on the entity —
> with the confidence and the evidence attached.

## 06 — PAYOFF + THE KILL (1:45–2:05) · reflection / summary card (Shot 6)

> Caught before the next training run baked the drift into production.
> The reference agent remembers the conversation. Mnemo remembers the asset —
> and catches what a schema-diff, and a plain drift monitor, cannot.

## 07 — ARCHITECTURE BEAT (2:05–2:20) · ASCII diagram, name the reconcile loop (Shot 7)

> Under the hood: Mnemo reads the graph through DataHub's own APIs.
> It reconciles its prior memory with a Bayesian confidence model, gates every write on governance,
> and writes typed structured properties back. A polling loop today — and, live-verified, it also wakes on a real DataHub event.

## 08 — HONESTY + CLOSE (2:20–2:40) · terminal GREEN + honesty line + title card (Shot 8)

> Everything you just saw runs live, against a real DataHub. The source-delta detection is real.
> When the sources carry profiles, the drop is a measured drift score — not just a prior. And we say so, on screen.
> Mnemo. Compounding, governed memory for the data graph.

---

## OPTIONAL 09 — EVAL BAR (+0:00–0:15, only if it stays under 3:00) · `examples/eval_lift.svg` (Shot 10)

> One more, measured. Stripped to bare facts — and on cases built to fool a shortcut —
> the memory lifts triage accuracy from one-half to nine-tenths, by reasoning.
> And irrelevant memory hurts. So the lift is the relevant memory, not just more words.

---

### Recording notes (for the human)
- Capture one screen clip per block (browser fullscreen, mic off) into `handoff/video/incoming/01..08`
  (+ optional 09). Let any wait-clips run fully; Claude speed-ramps them at assembly.
- Numbers are spoken as words on purpose ("nine-tenths", "six-tenths") — cleaner in TTS than "0.9 / 0.6";
  the *screen* shows the exact figures (0.901 → 0.600), so precision is preserved visually.
- Money-shot = block 05 (the governed needs-review). Give it ~1 s of air before it in the cut.
