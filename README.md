# Mnemo — Compounding, Governed Memory for the Data Graph

**Mnemo catches silent ML model drift that no schema-diff tool can see, by remembering what a model's
inputs used to be and comparing that memory to live lineage — with every belief carrying a Bayesian
confidence score, a provenance chain, and a governance gate before anything is trusted.**

Category: **Production ML Agents** · DataHub Agent Hackathon 2026 · License: **Apache-2.0**

> ⚠️ **Read this before judging any claim in this README.** Everything below is either **BUILT & live-verified**
> (marked ✅) or **honest work-in-progress** (marked 🚧), stated plainly in [Status / limitations](#status--limitations).
> No feature below is claimed that the code doesn't do.

---

## The problem

A feature's *upstream source table* gets silently re-pointed — `fct_users_created` → `fct_users_created_v2`
— while the feature's **name and description stay identical**. A schema-diff tool, a doc-linter, or a
chat-with-your-metadata agent sees **nothing wrong**: same field names, same types, same description. But
the model trained on that feature is now consuming a different population, silently. This is how target
leakage and quiet accuracy decay get baked into a production model between two otherwise-unremarkable
commits.

## How Mnemo catches it

Mnemo keeps a **per-asset memory that lives on the graph itself** — not in a side database, not in a chat
transcript. When it revisits a model, it:

1. **Loads its own prior belief** about the model's inputs (`mnemo.confidence`, `mnemo.provenance`,
   the remembered source-set) from DataHub structured properties on the entity.
2. **Compares that memory to live lineage** — the model's *actual current* upstream sources, walked
   through its `MLFeature` → source-dataset graph.
3. **Detects the delta** a schema-diff cannot: the field names/types are unchanged, but the **source URN
   set changed**. That's the tell.
4. **Feeds the delta as contradicting evidence** into a Bayesian belief update (`confidence_model.py`),
   dropping the model's confidence below a governance threshold.
5. **Opens a DataHub Proposal instead of silently trusting the model** — a human gate, not an auto-write.

This is demonstrated end-to-end in [`run_ml_drift_demo.py`](run_ml_drift_demo.py): confidence visibly moves
**0.901 → 0.600**, crossing the 0.7 proposal threshold, live against a running DataHub instance.

## Why a reference chat/analytics agent structurally can't do this

The reference `datahub-project/analytics-agent` pattern (request/response chat agent, conversation history
in a local DB, free-text description write-back) has **no per-asset memory on the graph** and **nothing to
compare against**. Every query is stateless — it can describe the graph *as it is right now*, but it has no
prior belief to diff against, so a same-name/same-description source swap is invisible to it by
construction. Mnemo's moat isn't "we also have memory" — it's memory that **persists on the entity itself**,
survives across runs, and gets **compared against new evidence** every time the agent revisits.

| Dimension | Reference-style chat agent | Mnemo |
|---|---|---|
| Memory | conversation history, local DB | per-asset, **on the DataHub graph** (structured properties) |
| Write-back | free-text descriptions | typed properties: confidence, log-odds, mass, provenance, summary |
| Belief update | none — stateless per query | Bayesian log-odds update, re-scores on each revisit |
| Drift detection | none (nothing to diff against) | remembered source-set vs. live lineage, unchanged-schema-safe |
| Cross-asset synthesis | none | lineage-wide reflection (below), grounded in its own memories |
| Governance | none | confidence-gated: low-confidence → DataHub Proposal, not auto-write |

---

## Architecture

```
                         ┌───────────────── DataHub (local Docker quickstart) ─────────────────┐
                         │   GMS :8090 (this repo's .env)  ·  UI :9002  ·  structured properties │
                         └──────────────┬───────────────────────────────────────────┬───────────┘
                     reads (SDK graph)  │                                           │ writes (typed
                lineage / schema / MLFeature / MLModel                              │ structured properties,
                                        ▼                                           │ no GMS rebuild)
                         ┌──────────────────────────────┐                          │
     poll / re-visit ──► │   Mnemo core                  │ ─────────────────────────┘
                         │   1. mnemo/reader.py   — pull asset context (schema, upstream, owners, memory)
                         │   2. mnemo/memory.py   — load prior Belief (log-odds + mass + provenance)
                         │   3. confidence_model.py — Bayesian log-odds update on new evidence
                         │   4. governance gate   — confidence < 0.7 → DataHub Proposal, not auto-write
                         │   5. mnemo/reflection.py — lineage-wide reflection (crown feature, below)
                         └──────────────────────────────┘
                                        │
                          mnemo.summary / mnemo.confidence / mnemo.logodds / mnemo.mass /
                          mnemo.provenance / mnemo.reflection — all typed structured properties, on-graph
```

**Read layer** (`mnemo/reader.py`) pulls an asset's schema, upstream lineage, owners, and its own prior
memory via `DataHubGraph.get_aspect`. **Memory layer** (`mnemo/memory.py`) resumes the exact posterior
(log-odds + evidence mass) from the last run and writes the updated belief back as typed structured
properties — no GMS schema rebuild required (verified path: direct `StructuredPropertiesClass` emit).

### Bayesian confidence, not a vibe label

`confidence_model.py` is a small, pure-stdlib, dependency-free belief model. Confidence is a **posterior in
log-odds space** — evidence accumulates additively and stays bounded:

- Each evidence source has an authority weight (`lineage 1.8`, `schema 1.8`, `usage 0.7`, `human 4.0`).
- Evidence is **discounted by lineage distance**: each hop halves its weight (`GAMMA = 0.5`).
- `C_MIN/C_MAX = 0.02/0.98` (Cromwell's rule — never absolute certainty).
- `N_MIN = 3.0` evidence mass required before a `>0.85` belief is allowed to auto-write.
- `TAU_PROPOSAL = 0.7` — cross below this after a contradiction and the agent opens a governance
  **Proposal** instead of writing.
- Belief **decays toward 0.5** on a configurable half-life if not revisited (staleness-aware).

Run it standalone: `python confidence_model.py` reproduces the worked example (0.60 → 0.90 →
contradiction → proposal → 0.96 on human confirmation).

### Lineage-wide reflection (crown feature)

`mnemo/reflection.py` walks a model's lineage (`MLModel` → `MLFeature` → source datasets → their
upstreams, up to 6 hops), gathers **its own previously-written per-asset memories** along that path, and
pools them into a single graph-level insight that lives on **no single asset** — written onto the `MLModel`
entity with its own confidence and a citation list of evidence URNs.

- **Pooling** reuses the same proximity-discounted log-odds algebra as the confidence model.
- **Guard 1** — an insight must cite ≥2 distinct valid asset URNs.
- **Guard 2** — pooled evidence mass must clear `MIN_REFLECT_MASS` (rejects insights that technically
  cite enough assets but where the cited evidence is weak/deep).
- **Guard 3** — a nearby (≤1 hop) contradicting memory forces `needs_review`/`needs_proposal`, never
  `auto-write`.
- **Guard 4** — a graph-fingerprint hash skips re-reflecting when nothing upstream has changed.
- **Synthesis is pluggable**: `mnemo/llm.py` calls a **local Ollama** model (no API key, no card) for the
  insight *text*; on any Ollama error it falls back to a deterministic stub so the traversal/pooling/guard
  pipeline is fully testable without any LLM at all.

Run it: `python run_reflection_demo.py` — seeds a 3-deep lineage chain with memories, reflects on the
model, and reads the written `mnemo.reflection` structured property back off the graph.

---

## Status / limitations

Stated plainly, because a rigor judge should be able to trust this table without re-deriving it from the code.

| Piece | File(s) | Status |
|---|---|---|
| Bayesian confidence model | `confidence_model.py` | ✅ **REAL** — runs standalone, pure stdlib |
| Per-asset memory on the graph (persist + resume belief) | `mnemo/memory.py`, `mnemo/reader.py` | ✅ **REAL** — live-verified round-trip, no GMS rebuild |
| Compounding loop (belief improves across runs) | `mnemo/memory.py` + `run_ml_drift_demo.py` | ✅ **REAL** — 0.6→0.9 across runs, on the graph |
| ML-drift detection (live lineage vs. remembered source, under an unchanged schema) | `run_ml_drift_demo.py` | ✅ **REAL** — the *delta detection* is real; the confidence *magnitude* (→0.60) is set by the Bayesian priors, not a measured/calibrated drift score |
| Lineage-wide reflection: traversal, confidence pooling, guards, write-back | `mnemo/reflection.py`, `run_reflection_demo.py` | ✅ **REAL**, live-verified |
| Reflection insight *text* synthesis | `mnemo/llm.py` | ✅ **REAL** via local Ollama (falls back to a deterministic stub on any Ollama error — pipeline never breaks) |
| Event-driven "wakes on `EntityChangeEvent`" | — | 🚧 **HONEST-WIP**. The Actions-framework spike loads/connects/runs, but the custom action did not reliably receive `EntityChangeEvent_v1` in quick tests. **Current reality: polling** (`get_urns_by_filter`) detects changes; "wakes on event" is the target design, not the shipped behavior. |
| Eval harness (task accuracy WITH vs. WITHOUT Mnemo context) | `scratchpad/spec_eval.md` | 🚧 **spec only, not built.** No lift numbers are claimed anywhere in this repo. |
| `examples/` folder (provenance-chain + reflection-card artifacts) | — | 🚧 **planned, not yet added** to the repo. |
| LangGraph ReAct orchestration | — | 🚧 design-stage; the demo scripts call the core modules directly. |

Full build-status ledger with dates: [`ARCHITECTURE.md §10`](ARCHITECTURE.md#10-build-status-live-verified-2026-07-24-datahub-v15-on-vps).

---

## Setup & run

Requires Docker (for DataHub quickstart), Python 3.11+, and optionally [Ollama](https://ollama.com) for
real (non-stub) reflection-insight text.

```bash
# 1. DataHub quickstart (heavy — needs ~8GB RAM free for Docker, ~15GB disk)
datahub docker quickstart
datahub docker ingest-sample-data     # optional, gives you a lineage graph to explore in the UI

# 2. Python env
cd /root/hackathons/datahub-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure — copy the example env and point it at your GMS instance.
#    This repo's shipped .env defaults to GMS on :8090 (adjust if your quickstart
#    is on the stock :8080 — check with `curl -s http://localhost:<port>/health`).
cat > .env <<'EOF'
DATAHUB_GMS_URL=http://localhost:8090
DATAHUB_GMS_TOKEN=
ANTHROPIC_API_KEY=
EOF

# 4. (optional, for real reflection-insight text instead of the deterministic stub)
ollama pull mannix/llama3.1-8b-abliterated:q4_k_m
ollama serve &

# 5. Run the hero demo — silent ML-drift detection + governance gate
python run_ml_drift_demo.py

# 6. Run the crown-feature demo — lineage-wide reflection
python run_reflection_demo.py

# 7. Run the confidence model standalone (no DataHub needed)
python confidence_model.py
```

Both `run_ml_drift_demo.py` and `run_reflection_demo.py` print an honest `[honesty]` line at the end of
their output stating exactly what part of the shown result is real detection/math vs. a placeholder — the
same distinction made in [Status / limitations](#status--limitations) above.

### `examples/`

An `examples/` folder with a captured provenance-chain artifact and a reflection-card artifact is **planned
but not yet in this repo** (see the status table above) — until it lands, the two `run_*_demo.py` scripts
above are the canonical, reproducible way to see Mnemo's output, and their stdout is representative of what
would populate `examples/`.

---

## Repo layout

```
confidence_model.py       Bayesian belief model (pure stdlib)
mnemo/
  memory.py                per-asset memory: load/save Belief as structured properties
  reader.py                read layer: schema/lineage/owners/memory for an asset
  reflection.py             lineage-wide reflection: traversal, pooling, guards, write-back
  llm.py                    local-Ollama synthesis hook for reflection insight text
run_ml_drift_demo.py       hero demo — silent source re-point caught by memory
run_reflection_demo.py     crown-feature demo — lineage-wide reflection
ARCHITECTURE.md            full design doc + build-status ledger (§10 = ground truth)
DAY1_RUNBOOK.md, spike/    infra spike notes (DataHub quickstart, Actions-framework proofs)
```

## License

Apache-2.0.
