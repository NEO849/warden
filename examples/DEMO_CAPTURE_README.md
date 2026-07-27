# Demo capture guide — what to record, in what order

`demo_e2e.py` (repo root) is a deterministic, CI-style orchestrator: **one run produces every
number and every graph state the video needs.** Your job after running it is purely mechanical —
point the recorder at a terminal and at Chrome, in the order below. No manual seeding, no
guessing whether a number is right: the run ends with a `GOLDEN-LOG ✅` block, and if anything is
off it ends `❌` with a non-zero exit code instead of showing a silently-wrong number.

This maps the run's output onto the 8 shots in `../DEMO_STORYBOARD.md` (read that file for the
verbatim voiceover — this file only tells you WHEN to press record / screenshot).

## 0. Before you record

```bash
cd /root/hackathons/datahub-agent
source .venv/bin/activate
python demo_e2e.py
```

- Preflight aborts immediately (clear message, no partial recording wasted) if DataHub GMS or
  Ollama isn't up. Fix that first — don't start the recorder until you've seen `GOLDEN-LOG ✅`
  from a dry run.
- The run takes well under a minute (no Ollama inference in the recorded path — see note below).
  Do one **silent dry run first** to warm caches / confirm green, THEN do your **actual recorded
  take** as a second run — it's idempotent, the numbers are identical either time.
- `examples/confidence_timeseries.svg` is (re)written every run — open it in a browser tab ahead
  of time so it's ready to alt-tab to for the optional Shot 9.5 below.

## 1. Terminal recording (covers Shots 2, 3, 4, 5, 8 in one continuous take)

Screen-record the **whole terminal**, large font, then run:

```bash
python demo_e2e.py
```

| Storyboard shot | What appears on screen | Say (from `DEMO_STORYBOARD.md`) |
|---|---|---|
| **Shot 2** (0:15–0:35) | `=== STEP: hero-drift ===` block: `model memory established: confidence 0.901, remembered sources [...]` | "Mnemo has already watched this model's inputs... confidence 0.90..." |
| **Shot 3** (0:35–1:00) | `feature 'days_since_signup' silently re-pointed fct_users_created → fct_users_created_v2` / `(name unchanged, description unchanged...)` | "A data engineer swaps the feature's upstream..." |
| **Shot 4** (1:00–1:20) | `remembered: [...]` / `now: [...]` / `source delta detected: True` | "Mnemo's reconcile pass runs... sees the delta." |
| **Shot 5** (1:20–1:45) | `confidence 0.901 → 0.600` then `⚠️ below governance threshold (0.7) → OPEN DATAHUB PROPOSAL` | "The contradicting evidence drops confidence from 0.90 to 0.60..." |
| **Shot 8** (2:20–2:35) | Final `GOLDEN-LOG ✅ ALL 29 ASSERTIONS PASSED` block | "...and we say so. Mnemo: memory that compounds, governed at the graph." |

Bonus material the storyboard didn't have a slot for yet (use if you extend past 2:35, or as
B-roll / a LinkedIn cut):

- **Head-to-head (kill-shot vs. measured)** — `=== STEP: measured-drift ===`: the SAME structural
  swap, once where a PSI/KS monitor would stay silent (`PSI=0.0250 ... confidence→0.600`) and once
  where it's genuinely measured (`PSI=1.3229 ... confidence→0.251`). Good "we're a superset of a
  stats-only drift monitor" beat.
- **Compounding proof** — `=== STEP: compounding proof ===`: `PASS 2 load: resumed confidence=0.600
  (... NOT reset to the neutral prior 0.500)` then `confidence 0.600 -> 0.874`. This is the
  concrete, on-camera proof that memory lives ON the graph across process boundaries, not in one
  script's local variables — the strongest answer to "why not just re-run a one-shot check?".

## 2. Chrome recording on `:9002` (covers Shots 1, 2, 3, 5, 6 — do these AFTER step 1, graph is now populated)

Recording order from `DEMO_STORYBOARD.md`, unchanged:

1. **Shot 1** — `churn_model` (mlflow, PROD) entity page, calm/green, before anything runs (capture
   this ahead of time, or re-seed with `python seed_demo_graph.py` and reload if you need a clean
   "before" state — it's idempotent).
2. **Shot 2** — Properties tab → `mnemo.*` structured properties: `mnemo.confidence 0.901`.
3. **Shot 3** — the two source datasets (`fct_users_created` vs `_v2`) side by side, same feature
   name/description, different upstream column (`signup_ts` vs `ingest_ts`).
4. **Shot 5/6** — the Proposal/warning card + reflection/summary card on `churn_model` after the run.

## 3. Optional Shot 9.5 — the new confidence-timeseries chart (`examples/confidence_timeseries.svg`)

Not in the original 8-shot storyboard — this is the new visual "wow" asset from this block. Open
the SVG in a browser tab (or embed as a title-card cutaway) right after Shot 5/6 or during the
architecture beat (Shot 7):

> "Here's that same arc, read straight back off the graph — not simulated. Same shared start,
> then the fork: PSI silent and flat, or genuinely measured and falling harder. This is the
> confidence curve a schema-diff has no equivalent of."

## 4. Reflection text — stub vs. real Ollama (a deliberate choice, say why if asked)

`demo_e2e.py`'s reflection beat **forces the deterministic stub** (`llm=None`), not Ollama — so
the printed insight text is byte-identical take-to-take, and a flaky/slow local model never
derails a recording. If you want the **real LLM-synthesized** reflection text on camera instead
(more impressive, but non-deterministic wording — don't script the voiceover around it), run
`python run_reflection_demo.py` **separately** (it is untouched, still wired to real Ollama via
`make_reflection_llm()`) and capture that as its own short clip. Either way, per the storyboard's
honesty contract: never claim the insight TEXT is deterministic when it came from Ollama, and
never assert automated checks against Ollama's free text (only against confidence numbers/gates —
that's exactly what `demo_e2e.py`'s golden-log assertions do).

## 5. If a take goes wrong

Don't eyeball it — re-run `python demo_e2e.py` and read the tail of the new
`demo_e2e_<timestamp>.log`. `GOLDEN-LOG ❌` lists exactly which assertion failed and the parsed
vs. expected number; fix that before re-recording. The script never lets a broken number pass
silently through to the terminal you're filming.
