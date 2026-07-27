# Eval — honest reading (controlled ablation, not a production benchmark)

**Setup.** 15 hand-authored ML-risk-triage cases (5 each DRIFT / LEAKAGE / NO_RISK). One local Ollama
model (llama3.1-8b, temp 0), identical prompt across arms; only the memory block changes:

- **WITHOUT** — raw metadata only (schema, lineage, the change)
- **WITH** — raw metadata + Mnemo's memory of the asset
- **PLACEBO** — raw metadata + an *unrelated* asset's memory (equal token budget)

**Results** (`results.csv`, reproducible at temp 0):

| Arm | Accuracy | macro-F1 |
|---|---|---|
| WITHOUT | 0.53 | 0.50 |
| WITH | 1.00 | 1.00 |
| PLACEBO | 0.33 | 0.17 |

## What this DOES show
1. **Direction.** Relevant memory takes triage accuracy from 0.53 → 1.00. Without memory the agent
   labels every silent-DRIFT case "NO_RISK" — exactly the failure Mnemo exists to prevent.
2. **The placebo control is the real rigor result.** PLACEBO (0.33) is *worse* than WITHOUT (0.53):
   adding an *irrelevant* memory of equal length **hurts**. So the lift is NOT "more tokens" — it is the
   *relevant* memory. This is the control most hackathon entries omit.

## What this does NOT show (stated plainly)
- **WITH = 1.00 is a ceiling effect, not a production accuracy.** The cases are constructed to *isolate*
  the memory signal, and the memory text is explicit. This is a controlled ablation, not a benchmark.
  We deliberately did **not** tune the cases to manufacture a "credible" sub-100 number — that would be
  goalpost-moving. We report what the ablation actually produced and frame it honestly.
- A production-realistic number would need the memory to supply only *raw remembered facts* (prior
  source/type/confidence) and let the model do all inference over a large noisy set. That's future work.

**Bottom line for a judge:** the honest, defensible claim is the *direction + the placebo control*, not
the headline 100%.
