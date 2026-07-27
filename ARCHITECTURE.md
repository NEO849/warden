# DataHub Agent Hackathon — Winning Architecture (v3, working-group synthesis)

> Working title: **Mnemo — Compounding, Governed Memory for the Data Graph**
> Deadline: **2026-08-10 17:00 EDT** · Judging 08-17→08-31 · Winners ~09-08 · Pool $20,500
> v3 changelog: source-verified differentiation (analytics-agent audited at code level); added the
> **eval-harness** and **governance-native** pillars (real judges); crown feature = **lineage-wide reflection**;
> confidence model formalized (`confidence_model.py`, runs, hits 0.6→0.9); category decision = **late-bind**.

---

> ⚠️ **BUILT vs PLANNED (read before any judge-facing claim).** This document is the DESIGN. What is
> actually built + live-verified is the table in **§10** — trust that, not the prose below. As of
> 2026-07-27: **BUILT & REAL** = compounding belief-on-graph, live source-delta drift detection,
> reflection traversal/pooling/guards/write-back, insight/summary TEXT via **local Ollama** (deterministic
> stub only on Ollama error), and the **eval harness** (built & run — WITHOUT 0.53 / WITH 1.00 / PLACEBO 0.33,
> lift +0.467; see §10). **NOT USED (by design)** = LangGraph + Claude — the agent is a direct Python pipeline
> (observe→detect→govern→reflect), not a graph orchestration. **event-driven wake** is now **LIVE-VERIFIED as an
> opt-in path** — a DataHub Actions consumer woke the detection on a real Kafka `EntityChangeEvent_v1`
> (TAG event, confidence 0.901→0.600, zero polling; root cause was a wrong `schema_registry_url`, see
> `EVENT_WAKE_STATUS.md`). **Polling remains the shipped default.** Sections §1/§2/§4/§7 describe the target design, not the current state.

---

## 0. The moat, stated precisely (source-verified)

The reference `datahub-project/analytics-agent` was audited **at code level**. What it actually is:
a request/response FastAPI chat agent with **conversation-history memory in a local DB** and free-text
description write-back. It has **no** Actions/Kafka code, **no** per-asset memory on the graph, **no**
confidence/provenance, **no** re-scoring across events. (The "self-scores context 1–5" claim is **refuted** —
the only score is `quality_score:Int` on a *conversations* telemetry table, never on the graph.)

So the moat is **not** "we have memory" (table stakes). It is the precise combination the reference and the
shipped classifier structurally cannot do:

> **Per-asset memory that lives ON the graph, revisits on metadata changes, and COMPOUNDS — each memory
> carries a principled Bayesian confidence + provenance chain, re-scores itself as evidence arrives,
> and periodically REFLECTS across lineage to emit graph-level insights that live on no single asset —
> all gated on GOVERNANCE signals, with an EVAL HARNESS proving the context lift.**

Five load-bearing pillars, each mapped to a judge value (see §2). This is the builder's proven
memory-agent moat (markmem / A-MEM / MemoryAgent) imported into a governance tool — a combination
no data-engineer in the field will assemble.

---

## 1. Concept

**Mnemo** is a **memory agent** for DataHub (event-driven by design; a polling reconcile loop today). It:

1. **Wakes on events** — Actions Framework on `EntityChangeEvent_v1` (schema/doc/lineage/tag/owner).
2. **Reads the graph** — lineage, schema, ownership, usage via the MCP server + SDK.
3. **Reconciles memory** — loads its own prior `mnemo.*` record, treats the new event as evidence,
   **Bayesian-updates confidence** (`confidence_model.py`), extends the provenance chain.
4. **Writes back** — typed structured properties (`mnemo.summary/confidence/provenance/...`), no GMS rebuild.
5. **Reflects** (crown feature) — on accrued importance, traverses a lineage path, gathers its own
   per-asset memories, and synthesizes a **confidence-scored insight onto the Data Product** citing the
   evidence URNs — a conclusion on no single asset.
6. **Governs** — ranks/gates every action on tier/owner/certification signals; low-confidence or
   ungoverned → opens a **DataHub Proposal** (human gate) instead of auto-writing.
7. **Proves lift** — an eval harness reports task accuracy **WITH vs WITHOUT** Mnemo's memory context.

Auto-documentation / PII tagging are **incidental side-effects**, never the pitch (both ship already).

---

## 2. Why it wins — pillars mapped to the REAL judges

Judges (verified): Maggie Hays (DataHub PM), Alyssa Lee, Nick Adams, **Aman Gairola (Pinterest EM,
governance-enforced text-to-SQL)**, **Wenjia You (OpenAI TPM, rigor)**, Tim Bossenmaier, Mike Burke.
Their gospel: *"not an LLM problem, a context problem"* · agents must **improve the graph each run** ·
**governance enforced at creation** · they love the **50%→90% context-lift proof**.

| Pillar | Judge value it hits | Beats reference because |
|---|---|---|
| Event-driven autonomy | "improve the graph each run" (compounding) | reference is request/response, no event code |
| Bayesian confidence + provenance | OpenAI-TPM rigor; auditable belief | reference has no graph confidence at all |
| **Lineage-wide reflection** | "context problem"; graph-level value | impossible without persisted, compounded memory |
| **Governance-native gating** | Pinterest "no tier/owner → no table" | reference does not gate on governance |
| **Eval harness (with/without)** | the 50%→90% proof they cite constantly | almost no entry will measure lift |

### Source-verified differentiation (from code audit)
| Dimension | analytics-agent (verified) | Mnemo |
|---|---|---|
| Trigger | request/response chat | event-driven (`EntityChangeEvent_v1`) |
| Memory | conversation history, local DB | per-asset, **on the graph** |
| Write-back | free-text descriptions + KB docs | typed structured properties |
| Confidence/provenance | none on graph | Bayesian log-odds + provenance chain |
| Compounding / re-score | none | re-visit → reconcile → re-score |
| Reflection | none | lineage-wide graph-level insights |

---

## 3. Category decision — COMMITTED: Production ML Agents (user call 2026-07-24)

**Target category: Production ML Agents** — thinnest field, and its stated value ("prevent expensive prod
failure") is exactly what the OpenAI-TPM + Pinterest-EM judges reward. Best odds-adjusted play.

**Demo scenario:** Mnemo watches **end-to-end ML lineage** (training data → feature → model → deployment).
On an upstream schema/distribution change, it wakes, reconciles its memory of the affected model's inputs,
re-scores confidence, and **flags silent model-drift / target-leakage risk before degradation** — writing a
governed, provenance-carrying warning back onto the model entity, gated through a Proposal.

**Infra risk & safety net:** the barrier that thins this field — standing up **ML lineage** in DataHub
(`MLModel`/`MLFeatureTable`/`MLModelGroup` + training-run lineage) — is also our risk. So ML-lineage sample
data is a **day-1 parallel track** (see DAY1_RUNBOOK.md §7). **Fallback:** if ML lineage cannot be stood up by
the day-3 gate, drop to **Agents That Do Real Work** (dataset incident-triage demo) — the core engine is
identical, only the demo scenario + track change. Aim ML; keep the flagship as the escape hatch.

---

## 4. Technical architecture

```
        ┌──────────────── DataHub (local Docker) ────────────────┐
        │  GMS :8080 · UI :9002 · Kafka MCL/EntityChangeEvent     │
        └──────┬──────────────────────────────────────┬──────────┘
     reads (MCP)│                                      │ EntityChangeEvent_v1
   lineage/schema                                      ▼ (wake)
               ▼                          ┌──────────────────────────┐
   ┌───────────────────────┐   wakes      │  Actions Framework        │
   │  Mnemo Agent          │◄─────────────│  MnemoAction (verified)   │
   │  LangGraph ReAct + Claude            └──────────────────────────┘
   │  1 reconcile prior memory (confidence_model.py Bayesian update)
   │  2 governance gate (tier/owner/certification)
   │  3 reflect over lineage path (crown)
   └───────────┬───────────────────────────────────────────────────┘
    write typed structured properties  ·  low-conf/ungoverned → DataHub Proposal (human gate)
               │
        eval harness: task accuracy WITH vs WITHOUT mnemo.* context (the 50%→90% echo)
```

### Verified APIs (source-confirmed; see `spike/` + `scratchpad/audit_source.md`)
- **Write memory (no rebuild):** `StructuredProperties(...).generate_mcps()` to define →
  `DatasetPatchBuilder(urn).add_structured_property("urn:li:structuredProperty:mnemo.confidence", 0.6)` → `g.emit()`.
- **Read:** `g.get_aspect(urn, StructuredPropertiesClass)`.
- **Event Action:** subclass `datahub_actions.action.action.Action`; `act(event)`; `event.event` is
  `EntityChangeEvent` with `.entityUrn/.category/.operation/.modifier`. Config filters on
  `EntityChangeEvent_v1` categories `TECHNICAL_SCHEMA` / `DOCUMENTATION`.
- **Confidence:** `confidence_model.py` — pure stdlib, runs, reproduces 0.6→0.9.

### Stack
Python 3.11 · `acryl-datahub[datahub-rest,datahub-kafka]` · `acryl-datahub-actions` ·
`acryldata/mcp-server-datahub` (read) · LangGraph · Claude (`LLM_PROVIDER` swappable) · Docker quickstart.

---

## 5. Build plan (17 days, today = 2026-07-24)

| Days | Milestone |
|---|---|
| **1–3 — INFRA SPIKE (gate)** | Quickstart up; PROOF A structured-property round-trip; PROOF B one real `EntityChangeEvent` fires; **PROOF C ML-lineage stands up** (MLModel/MLFeatureTable + training lineage). A+B+C green → ML-track confirmed. If C fails → flagship fallback. Fallbacks in `spike/00_SPIKE_RUNBOOK.md` |
| 4–6 | Read layer (MCP + SDK lineage/schema loader); LangGraph ReAct forms first memory; wire `confidence_model.py` |
| 7–9 | Write-back + the **re-visit/reconcile/re-score loop** (the compounding core); Proposal human-gate; governance gating on tier/owner |
| 10 | Event Action end-to-end: event → wake → reconcile → write |
| 11 — scenario freeze | Confirm ML-drift/target-leakage demo scenario end-to-end (or flagship fallback if C failed) |
| 12–13 | **Lineage-wide reflection** (crown) → insight on Data Product with evidence chain |
| 14 | **Eval harness**: accuracy WITH vs WITHOUT mnemo context; `examples/` folder (provenance chain + reflection card) |
| 15 | **OSS PR** upstream (§6) |
| 16 | Demo video (<3 min, §7) + README + Apache-2.0 license file (visible in About) |
| 17 (08-10) | Buffer + submit before 17:00 EDT |

**Depth ladder (add in this order if ahead of schedule):** reconcile/re-score → reflection → decay/staleness
(memory visibly ages) → consolidation (merge column-notes) → A-MEM retro-edit (rewrites a prior belief).

---

## 6. OSS contribution (Bonus + Criterion-1 proof)
Reusable core = the contribution. Ranked: (1) a DataHub **Skill** PR to `datahub-project/datahub-skills`
that Mnemo invokes; (2) an **RFC/docs PR** proposing "agent memory + confidence via structured properties";
(3) a small connector if a needed source is missing. A **merged/review-ready PR before 08-10** is the
strongest depth proof. Do this regardless of category.

## 7. Demo strategy (<3 min — make the invisible visible)
Open on the **second run**: asset memory already on screen (conf 0.6, provenance 1 event) → new lineage
arrives → Mnemo wakes on the event → **confidence rises to 0.9 on screen, provenance grows to 2** → then
the **reflection card** appears on the Data Product citing 4 upstream URNs → 20-sec architecture + the
eval bar chart (with/without) → OSS PR. Close: *"No single table says this. Mnemo concluded it by
remembering — and here's the evidence chain that made it 90% sure."*

## 8. Hard requirements (Stage-1 pass/fail)
- [ ] Public repo, **Apache-2.0** visible in About · [ ] uses MCP Server · [ ] working demo + setup
- [ ] description leads with *compounding/governed memory*, not "documents your data"
- [ ] video <3 min, built around the second run · [ ] `examples/` folder · [ ] English · [ ] new build, disclose reused code

## 9. Open risks (45%-cap honesty)

**SPIKE RESULT 2026-07-24 (run live on VPS, DataHub v1.5 / CLI 1.6):**
`A=GREEN ✅ (memory writes+persists on graph; structured properties NOT gated, no rebuild — via direct
StructuredPropertiesClass emit, not DatasetPatchBuilder) · C=GREEN ✅ (dataset→feature→model lineage
buildable via SDK; ML-track feasible) · B=AMBER (actions framework loads/connects/runs cleanly, but
EntityChangeEvent didn't reach the custom action in quick tests — needs day-4 GMS ECE-hook tuning) →
POLLING FALLBACK GREEN ✅ (change detection via get_urns_by_filter works). **Verdict: GREEN LIGHT to build.**`

- **Source-confirmed:** structured-property no-rebuild; `EntityChangeEvent` payload; confidence model runs.
- **Hypothesis until day-1 live round-trip:** the pulled **quickstart image may gate structured properties**
  (`ENABLE_STRUCTURED_PROPERTIES`) and needs both auth paths (Actions system creds + SDK PAT). Verify snippet A
  round-trips BEFORE the day-3 gate — this is the single most important early check.
- ML lineage setup is the day-11 pivot's risk; that's why we build the core category-agnostic.
- Reflection quality depends on accumulated memory — seed 2–3 events before demoing it.

## 10. Build status (live-verified 2026-07-24, DataHub v1.5 on VPS)

| Piece | File | Status |
|---|---|---|
| Bayesian confidence | `confidence_model.py` | ✅ runs, worked example 0.6→0.9→proposal→0.96 |
| Per-asset memory on graph | `mnemo/memory.py`, `mnemo/reader.py` | ✅ persists + resumes belief (log-odds/mass) |
| Compounding loop | `run_reconcile.py` | ✅ GREEN — 0.6→0.9 across runs, on graph |
| **ML-drift hero** (silent source re-point) | `run_ml_drift_demo.py` | ✅ GREEN — 0.901→0.600 → governance Proposal |
| **Lineage-wide reflection** (crown) | `mnemo/reflection.py`, `run_reflection_demo.py` | ✅ GREEN — insight conf 0.912 citing 3 assets, on model |
| **Unified agent** (one coherent object) | `mnemo/agent.py`, `run_agent.py` | ✅ GREEN — observe→remember→detect-drift→re-score→govern→reflect through one MnemoAgent (answers "demos are linear scripts") |
| Eval harness (with/without lift) | `eval/run_eval.py`, `examples/EVAL_NOTES.md` | ✅ BUILT + RUN (N=15): WITHOUT 0.53 · WITH 1.00 · PLACEBO 0.33. Honest framing = **controlled ablation**; headline = placebo<without (lift is relevant memory, not tokens), NOT the 100% |
| LLM synthesis (insights) | `mnemo/llm.py` | ✅ wired to **local Ollama** (free, no key); stub fallback |
| Apache-2.0 LICENSE | `LICENSE` | ✅ added (Stage-1 requirement) |
| README + Devpost writeup | `README.md`, `DEVPOST_DESCRIPTION.md` | ✅ drafted (honest status table) |
| Demo video storyboard | `DEMO_STORYBOARD.md` | ✅ 8 shots, ~2:35, hook written |
| OSS-bonus PR plan | `OSS_PR_PLAN.md` | ✅ scoped (docs PR to datahub-skills, mergeable) |

**Honest line (2026-07-24, post-adversarial-review):** REAL + live = belief math, on-graph memory,
compounding loop, live source-delta drift detection, reflection traversal/pooling/guards/write-back, and
now local-Ollama LLM synthesis + a running eval harness. WIP/aspirational (labeled, not narrated as done):
event-driven wake runs via **polling** (ECE hook AMBER); eval numbers are a small-N pilot (~36s/CPU call,
no GPU) pending the full run; `examples/` to be populated from eval + demo outputs.
