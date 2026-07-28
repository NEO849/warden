# The Confidence Model: Log-Odds Weight-of-Evidence

Implemented in `scripts/belief.py`. This reference explains the math and the parameters; run
`python scripts/belief.py` for a live, narrated worked example.

## Why log-odds, not a 0-1 score directly

A naive agent might track confidence as a 0-1 number and nudge it up or down by some ad-hoc amount
per event. That has two problems: nudges don't compose predictably (is +0.1 twice the same as
+0.2 once?), and there's no principled way to combine evidence of different strengths.

Bayes' theorem for a binary hypothesis H ("this asset's current belief is correct") is **additive
in log-odds**:

```text
log( P(H|e) / P(¬H|e) )  =  log( P(H) / P(¬H) )  +  log( P(e|H) / P(e|¬H) )
        posterior                   prior                  evidence weight
```

So accumulating N pieces of evidence is just N additions to a running log-odds total `log_odds`
(called `ℓ` below), and the confidence at any point is one `sigmoid` call away:

```text
confidence = sigmoid(ℓ) = 1 / (1 + e^-ℓ)
```

`ℓ = 0` is the neutral prior (`confidence = 0.5`). Positive evidence pushes `ℓ` up (confidence
toward 1); contradicting evidence pushes it down (confidence toward 0). This is exactly
`Belief.log_odds` and `Belief.confidence` in `belief.py`.

## The weight of one piece of evidence

`Belief.update(source, corroborates, hops, quality, event_id)` computes the weight `w` folded into
`log_odds`:

```text
w = sign · AUTHORITY[source] · GAMMA^hops · quality
```

- **`sign`** — `+1` if the evidence corroborates the current belief, `-1` if it contradicts it.
- **`AUTHORITY[source]`** — how much one unit of evidence from this channel is worth. The defaults
  (`lineage`/`schema` = 1.8, `drift_stat` = 1.5, `usage` = 0.7, `human` = 4.0) encode a simple
  ordering: a human confirmation counts for more than a structural signal, which counts for more
  than a soft usage signal. These are **priors** — tune them for your domain; the mechanism is the
  reusable part.
- **`GAMMA^hops`** — provenance-distance discount. Each derivation/lineage hop between the
  evidence and the asset halves its weight (`GAMMA = 0.5`). Evidence about the asset itself
  (`hops=0`) is undiscounted; evidence two hops upstream carries a quarter of its nominal weight.
  `human` evidence is exempt from this discount (a human reviewing the asset directly always
  counts fully).
- **`quality`** — a 0..1 confidence in the evidence item itself, independent of its source or
  distance (e.g. a noisy usage signal vs. a clean one).

The resulting `w` is clamped to `±DW_MAX` (default 4.0) before being added — this is the
**anti-flapping** guard: no single event, however extreme, can swing the belief further than one
bounded step.

## Cromwell's rule: never certain

`confidence` is clamped to `[C_MIN, C_MAX] = [0.02, 0.98]`. This is Cromwell's rule applied to
software: if you ever let a model's stated confidence reach exactly 0 or 1, no future evidence —
however strong — can move it, because the math (`sigmoid` of ±∞) makes it immovable. Leaving room
at both ends keeps the belief always revisable.

## Evidence mass: gating high-confidence actions

`Belief.mass` accumulates `GAMMA^hops · quality` on every update (the same discount factor as the
weight, without the sign). It answers a different question than confidence: not "how sure are we"
but "how much _independent_ evidence has actually been seen". A single very-high-quality event can
push confidence above 0.85 without much corroborating volume behind it.

`Belief.actionable_high` requires **both** `confidence > 0.85` **and** `mass >= N_MIN` (default
3.0) — a high-confidence action (see `references/governance-gating.md`) is only auto-approved once
enough independent evidence has accumulated, not on the strength of one lucky signal. This is the
gate that keeps a single human override, for instance, from being enough on its own to flip an
asset straight to `TRUSTED` (`human` is weighted `4.0`, easily enough to push `confidence` above
0.85 by itself — but the mass gate still requires corroboration to actually reach it).

## Staleness decay

`Belief.decay(dt_days)` should be called lazily, when an asset is revisited (not on a fixed timer):

```text
factor = exp(-ln(2) / T_HALF_DAYS · dt_days)
log_odds *= factor
mass     *= factor
```

Both the belief and its accumulated mass exponentially decay toward the neutral prior with a
configurable half-life (`T_HALF_DAYS`, default 30). An asset nobody has looked at in months
shouldn't keep the same confidence it earned from evidence collected a year ago — decay pulls it
back toward "unsure" until it's re-observed.

## When to flag for review

`Belief.needs_proposal()` returns `confidence < TAU_PROPOSAL` (default 0.7). This is the trigger a
governance layer (see `references/governance-gating.md`) uses to decide an asset needs a human's
attention — typically right after a contradicting piece of evidence has pulled confidence down.

## Persistence

Everything above is derived from exactly two numbers plus a list: `log_odds`, `mass`, and
`provenance` (the append-only audit trail `update()` builds, one entry per call). Those three
fields — and only those three — are what `scripts/agent_memory.py` needs to persist as structured
properties for the belief to be fully resumable across runs (see
`references/structured-property-writeback.md`).
