#!/usr/bin/env python3
"""
demo_e2e.py — deterministic, CI-style orchestrator for the Mnemo demo-video capture.

One run = the entire recordable arc, in one shot, with a golden log at the end that says
GREEN or RED — never a silently-wrong number:

  preflight (GMS + Ollama reachable, else abort loudly)
    -> seed the graph (idempotent, fixed seeds)
    -> hero drift            (run_ml_drift_demo.py, subprocess, UNTOUCHED)          0.901 -> 0.600
    -> measured drift        (run_measured_drift_demo.py, subprocess, UNTOUCHED)    kill-shot vs measured
    -> lineage reflection    (mnemo.reflection.reflect, INLINE, llm=None/stub — forced deterministic,
                               so the recorded text never varies take-to-take; run_reflection_demo.py
                               itself is untouched and still available separately with real Ollama text)
    -> compounding proof     (a SECOND, independent MnemoMemory.load on the SAME asset resumes the
                               posterior the hero drift just wrote — proof memory lives ON the graph,
                               not in any one process, and continues instead of resetting to neutral 0.5)
    -> confidence-timeseries chart (examples/confidence_timeseries.svg, built from REAL Belief.provenance
                               read back from the graph, not fabricated)
    -> eval numbers cross-check (examples/eval_summary.json, read-only)
    -> GOLDEN-LOG verdict block with hard assertions on the DETERMINISTIC numbers only.

This script only ORCHESTRATES the existing, already-verified building blocks — it does not modify
run_ml_drift_demo.py, run_measured_drift_demo.py, seed_demo_graph.py, confidence_model.py,
eval/make_chart.py, or examples/eval_summary.json.

Run:  python demo_e2e.py
Exit code 0 = GOLDEN-LOG GREEN (safe to record). Exit code 1 = something is off — DO NOT record.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

GMS_HEALTH_URL = os.getenv("DATAHUB_GMS_URL", "http://localhost:8090") + "/health"
OLLAMA_TAGS_URL = os.getenv("OLLAMA_TAGS_URL", "http://localhost:11434/api/tags")
PY = sys.executable
STEP_TIMEOUT_S = 180  # a hanging take must abort visibly, never spin forever

# --- deterministic golden numbers (see run_ml_drift_demo.py / run_measured_drift_demo.py, live-verified) ---
HERO_BASELINE = 0.901
HERO_FINAL = 0.600
MEASURED_FINAL = 0.251
PSI_STABLE_MAX = 0.10      # mnemo/drift.py PSI_STABLE
PSI_SIGNIFICANT_MIN = 0.25  # mnemo/drift.py PSI_SIGNIFICANT
COMPOUND_RESUMED = 0.600    # what a SECOND, independent load of churn_model must resume at
COMPOUND_AFTER = 0.874      # after folding in one more corroborating "lineage" event on top
EVAL_EXPECT = {"WITHOUT": 0.53, "WITH_RAW": 0.93, "WITH": 1.00, "PLACEBO": 0.33}
TOL = 0.003


# --------------------------------------------------------------------------------------------- #
# Timestamped golden log (tee to console + file, pattern like the existing quickstart_*.log)
# --------------------------------------------------------------------------------------------- #
LOG_PATH = os.path.join(ROOT, f"demo_e2e_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
_log_fh = open(LOG_PATH, "w")
ASSERTIONS = []  # list of (description, passed: bool, detail: str)


def log(line: str = "") -> None:
    stamped = f"[{datetime.now().strftime('%H:%M:%S')}] {line}"
    print(stamped)
    _log_fh.write(stamped + "\n")
    _log_fh.flush()


def check(description: str, passed: bool, detail: str) -> bool:
    ASSERTIONS.append((description, passed, detail))
    mark = "✅ PASS" if passed else "❌ FAIL"
    log(f"   [{mark}] {description} — {detail}")
    return passed


def close(a: float, b: float, tol: float = TOL) -> bool:
    return abs(a - b) <= tol


def abort_preflight(msg: str) -> None:
    log(f"❌ PREFLIGHT ABORTED: {msg}")
    log("   Fix the above and re-run. Nothing was seeded or recorded.")
    _log_fh.close()
    sys.exit(1)


# --------------------------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------------------------- #
def preflight() -> None:
    log("=== PREFLIGHT ===")
    try:
        with urllib.request.urlopen(GMS_HEALTH_URL, timeout=5) as r:
            if r.status != 200:
                abort_preflight(f"DataHub GMS health returned HTTP {r.status} at {GMS_HEALTH_URL}")
        log(f"   ✅ GMS reachable ({GMS_HEALTH_URL})")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        abort_preflight(
            f"DataHub GMS not reachable at {GMS_HEALTH_URL} ({type(e).__name__}: {e}). "
            f"Start it (e.g. `datahub docker quickstart`) and re-run."
        )

    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=5) as r:
            if r.status != 200:
                abort_preflight(f"Ollama returned HTTP {r.status} at {OLLAMA_TAGS_URL}")
        log(f"   ✅ Ollama reachable ({OLLAMA_TAGS_URL})")
        log("      (note: the RECORDED reflection beat below forces the deterministic stub path, not "
            "Ollama, for take-to-take stability — this check only confirms the stack is live for the "
            "OPTIONAL manual `run_reflection_demo.py` with real LLM text; see examples/DEMO_CAPTURE_README.md)")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        abort_preflight(
            f"Ollama not reachable at {OLLAMA_TAGS_URL} ({type(e).__name__}: {e}). "
            f"Start it (e.g. `ollama serve`) and re-run."
        )


# --------------------------------------------------------------------------------------------- #
# Subprocess steps (orchestrate the existing, untouched scripts)
# --------------------------------------------------------------------------------------------- #
def run_step(label: str, script: str) -> str:
    log(f"=== STEP: {label} ({script}) ===")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = subprocess.run(
            [PY, os.path.join(ROOT, script)], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=STEP_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        log(f"   ❌ {script} did NOT finish within {STEP_TIMEOUT_S}s — aborting visibly, not hanging.")
        check(f"{label}: process completes", False, f"timed out after {STEP_TIMEOUT_S}s")
        finish(ok=False)
        raise SystemExit(1)  # unreachable (finish() exits), keeps linters happy

    for line in proc.stdout.splitlines():
        log(f"   [{label}] {line}")
    if proc.stderr.strip():
        for line in proc.stderr.strip().splitlines():
            log(f"   [{label}][stderr] {line}")

    check(f"{label}: process exit code 0", proc.returncode == 0, f"returncode={proc.returncode}")
    return proc.stdout


def seed_graph() -> None:
    out = run_step("seed", "seed_demo_graph.py")
    check("seed: graph seeded", "Demo graph seeded" in out, "looked for 'Demo graph seeded' in output")
    m = re.search(r"measured PSI=([\d.]+)", out)
    check("seed: fixed-seed profile PSI reproducible (seed=42/43)",
          bool(m) and close(float(m.group(1)), 0.0159, tol=0.001),
          f"parsed PSI={m.group(1) if m else 'NOT FOUND'} (expect ≈0.0159 — proves idempotent seeding)")


def hero_drift() -> None:
    out = run_step("hero-drift", "run_ml_drift_demo.py")
    m = re.search(r"confidence\s+([\d.]+)\s*→\s*([\d.]+)", out)
    if m:
        c0, c1 = float(m.group(1)), float(m.group(2))
    else:
        c0 = c1 = float("nan")
    check("hero: baseline confidence == 0.901", m is not None and close(c0, HERO_BASELINE),
          f"parsed {c0}")
    check("hero: post-drift confidence == 0.600", m is not None and close(c1, HERO_FINAL),
          f"parsed {c1}")
    check("hero: verdict line present (ML-DRIFT DEMO GREEN)",
          "ML-DRIFT DEMO GREEN" in out, "looked for 'ML-DRIFT DEMO GREEN' in output")


def measured_drift() -> None:
    out = run_step("measured-drift", "run_measured_drift_demo.py")
    m_a = re.search(r"\(a\) PSI schweigt:\s+PSI=([\d.]+)\s+confidence→([\d.]+)", out)
    m_b = re.search(r"\(b\) measured drift:\s+PSI=([\d.]+)\s+confidence→([\d.]+)", out)
    psi_a, conf_a = (float(m_a.group(1)), float(m_a.group(2))) if m_a else (float("nan"),) * 2
    psi_b, conf_b = (float(m_b.group(1)), float(m_b.group(2))) if m_b else (float("nan"),) * 2

    check("measured: kill-shot PSI stays stable (< 0.10)", m_a is not None and psi_a < PSI_STABLE_MAX,
          f"parsed PSI={psi_a}")
    check("measured: kill-shot confidence == 0.600 (structural term alone)",
          m_a is not None and close(conf_a, HERO_FINAL), f"parsed confidence={conf_a}")
    check("measured: measured-drift PSI is significant (> 0.25)",
          m_b is not None and psi_b > PSI_SIGNIFICANT_MIN, f"parsed PSI={psi_b}")
    check("measured: measured-drift confidence == 0.251 (structural + real PSI)",
          m_b is not None and close(conf_b, MEASURED_FINAL), f"parsed confidence={conf_b}")
    check("measured: verdict line present (MEASURED-DRIFT DEMO GREEN)",
          "MEASURED-DRIFT DEMO GREEN" in out, "looked for 'MEASURED-DRIFT DEMO GREEN' in output")


# --------------------------------------------------------------------------------------------- #
# In-process beats (reuse the mnemo library directly; never touch the demo script files)
# --------------------------------------------------------------------------------------------- #
def _graph():
    from dotenv import load_dotenv
    load_dotenv()
    from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
    return DataHubGraph(DataHubGraphConfig(
        server=os.getenv("DATAHUB_GMS_URL", "http://localhost:8090"),
        token=os.getenv("DATAHUB_GMS_TOKEN") or None,
    ))


def reflection_beat(g) -> dict:
    """Same seeding + call as run_reflection_demo.py, but llm=None (forced stub) so the recorded
    insight TEXT is deterministic take-to-take. run_reflection_demo.py itself is untouched and
    still available separately for a real-Ollama-text take (see examples/DEMO_CAPTURE_README.md)."""
    log("=== STEP: lineage reflection (inline, stub-forced for recording determinism) ===")
    from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
    from datahub.emitter.mce_builder import make_dataset_urn
    from datahub.metadata.schema_classes import (
        DatasetLineageTypeClass, MLFeaturePropertiesClass, MLModelPropertiesClass,
        UpstreamClass, UpstreamLineageClass,
    )
    from confidence_model import Belief
    from mnemo.memory import MnemoMemory
    from mnemo.reflection import reflect, define_reflection_property

    mem = MnemoMemory(g)
    dsA = make_dataset_urn("hive", "refl_dsA", "PROD")
    dsB = make_dataset_urn("hive", "refl_dsB", "PROD")
    dsC = make_dataset_urn("hive", "refl_dsC", "PROD")
    FEAT = "urn:li:mlFeature:(refl_features,f1)"
    MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,refl_model,PROD)"

    def seed_memory(urn, target_conf, note):
        b = Belief()
        while b.confidence < target_conf:
            b.update("lineage", corroborates=True, hops=0, quality=0.8, event_id="seed")
        mem.save(urn, note, b, "seed")

    mem.define_properties()
    define_reflection_property(g)
    time.sleep(2)
    g.emit(MCP(entityUrn=dsA, aspect=UpstreamLineageClass(
        upstreams=[UpstreamClass(dataset=dsB, type=DatasetLineageTypeClass.TRANSFORMED)])))
    g.emit(MCP(entityUrn=dsB, aspect=UpstreamLineageClass(
        upstreams=[UpstreamClass(dataset=dsC, type=DatasetLineageTypeClass.TRANSFORMED)])))
    g.emit(MCP(entityUrn=FEAT, aspect=MLFeaturePropertiesClass(description="f1", sources=[dsA])))
    g.emit(MCP(entityUrn=MODEL, aspect=MLModelPropertiesClass(
        description="reflection test model", mlFeatures=[FEAT])))
    time.sleep(1)
    seed_memory(dsA, 0.9, "dsA: clean signup facts")
    seed_memory(dsB, 0.85, "dsB: enriched events")
    seed_memory(dsC, 0.8, "dsC: raw ingest")
    time.sleep(1)

    rec = reflect(g, mem, MODEL, llm=None)  # llm=None => deterministic stub, never Ollama
    # reflect() returns either the written record, or {"skipped": "...", "record": <record>} when the
    # graph fingerprint is unchanged from a prior run (idempotent re-run) — both are success states.
    record = rec.get("record", rec) if isinstance(rec, dict) else None
    insights = (record or {}).get("insights") or []
    log(f"   reflect() -> {rec.get('skipped', 'written')} | insights={len(insights)}")
    if insights:
        ins = insights[0]
        log(f"   INSIGHT: \"{ins['statement']}\" confidence={ins['confidence']} "
            f"gate={ins['gate']} cites={len(ins['evidence_urns'])} assets")

    check("reflection: ran (not skipped-with-no-record)", record is not None,
          f"raw skip reason={rec.get('skipped') if isinstance(rec, dict) else 'n/a'}")
    check("reflection: >= 1 insight survived the guards", len(insights) >= 1,
          f"insight count={len(insights)}")
    if insights:
        ins = insights[0]
        check("reflection: insight cites >= 2 distinct assets (K_MIN guard)",
              len(set(ins["evidence_urns"])) >= 2, f"cites={ins['evidence_urns']}")
        check("reflection: statement is the deterministic stub text (forced llm=None)",
              ins["statement"] == "Model inputs are corroborated across lineage.",
              f"statement={ins['statement']!r}")
    return record or {}


def compounding_proof(g) -> None:
    """The compounding claim, proven with the mechanism that actually implements it
    (MnemoMemory.load/save persisting Belief.log_odds/mass on the graph):

      PASS 1 = the hero-drift subprocess that just ran: fresh Belief() -> 0.901 -> observes the
               silent re-point -> 0.600, saved onto churn_model.
      PASS 2 = THIS function, a wholly separate load (new Python process boundary already crossed:
               hero-drift was a subprocess that has since exited) that RESUMES the persisted 0.600
               instead of resetting to the neutral prior 0.500, then folds in one more corroborating
               event on top — proving the posterior compounds forward rather than restarting.
    """
    log("=== STEP: compounding proof (MnemoMemory.load resumes posterior across a fresh process) ===")
    from mnemo.memory import MnemoMemory
    MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)"
    mem = MnemoMemory(g)

    belief_resumed, summary = mem.load(MODEL)
    resumed_conf = belief_resumed.confidence  # snapshot BEFORE the update below mutates belief_resumed in place
    log(f"   PASS 2 load: resumed confidence={resumed_conf:.3f} "
        f"(PASS 1's final state — NOT reset to the neutral prior 0.500) | summary={summary}")
    check("compounding: PASS 2 resumes PASS 1's final posterior (0.600), not the neutral prior (0.500)",
          close(resumed_conf, COMPOUND_RESUMED), f"resumed={resumed_conf:.3f}")

    belief_resumed.update("lineage", corroborates=True, hops=0, quality=0.85, event_id="compounding_recheck")
    mem.save(MODEL, json.dumps({"desc": "compounding-recheck: later corroborating re-observation",
                                "input_sources": []}), belief_resumed, "compounding_recheck")
    belief_after, _ = mem.load(MODEL)  # a THIRD independent load proves the write actually persisted
    log(f"   after folding in one more corroborating event + re-loading a THIRD time: "
        f"confidence {COMPOUND_RESUMED:.3f} -> {belief_after.confidence:.3f} "
        f"(continues from the resumed posterior, does not restart at 0.500)")
    check("compounding: continuation lands at the expected posterior (0.874)",
          close(belief_after.confidence, COMPOUND_AFTER), f"after={belief_after.confidence:.3f}")
    check("compounding: confidence strictly increased (evidence folded onto the resumed posterior, "
          "not a reset-and-redo)",
          belief_after.confidence > resumed_conf + 0.05,
          f"{resumed_conf:.3f} -> {belief_after.confidence:.3f}")


# --------------------------------------------------------------------------------------------- #
# Confidence-timeseries chart (dependency-free SVG, pattern: eval/make_chart.py)
# --------------------------------------------------------------------------------------------- #
def build_confidence_chart(g, out_path: str) -> None:
    log("=== STEP: confidence-timeseries chart (examples/confidence_timeseries.svg) ===")
    from mnemo.memory import MnemoMemory
    mem = MnemoMemory(g)

    CHURN_MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)"
    KILL_SHOT_MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,kill_shot_model,PROD)"
    MEASURED_MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,measured_model,PROD)"

    def arc(urn, upto_event=None):
        """c_after values from the REAL persisted provenance, optionally truncated at (and
        including) the first occurrence of an event_id, so the chart reflects the hero/measured
        drift ARC itself — not any later compounding-proof events this script folds in afterwards."""
        belief, _ = mem.load(urn)
        vals = []
        for p in belief.provenance:
            vals.append(p["c_after"])
            if upto_event and p.get("event") == upto_event:
                break
        return vals

    hero = arc(CHURN_MODEL, upto_event="drift")          # 3 pts: 0.600, 0.901, 0.600 — no PSI term
    kill_shot = arc(KILL_SHOT_MODEL)                       # 4 pts: ..., 0.600, 0.600  (PSI silent)
    measured = arc(MEASURED_MODEL)                         # 4 pts: ..., 0.600, 0.251  (PSI fires)
    log(f"   hero arc (churn_model, pre-compounding):   {hero}")
    log(f"   kill-shot arc (structural + silent PSI):   {kill_shot}")
    log(f"   measured arc (structural + real PSI):      {measured}")

    check("chart: hero arc read back matches 0.901 baseline / 0.600 final",
          len(hero) >= 3 and close(hero[-2], HERO_BASELINE) and close(hero[-1], HERO_FINAL),
          f"hero={hero}")
    check("chart: measured arc read back matches 0.251 final",
          len(measured) >= 1 and close(measured[-1], MEASURED_FINAL), f"measured={measured}")

    # hero == the shared prefix exactly (all three arcs start identically: two corroborating lineage
    # events establish 0.901, then the structural source-delta drops to 0.600). They only FORK at the
    # 4th event, where a drift_stat (PSI) term is folded in — or, for hero, not at all (that demo has
    # no field-profile pair). Drawing it as shared-prefix + fork (instead of 3 fully overlapping lines)
    # avoids one color completely hiding another and tells the honest story: same start, different end.
    event_labels = ["corrob. lineage\n(indirect, hops=2)", "corrob. lineage\n(direct → 0.901)",
                    "− structural Δ\n(source re-point)", "− drift_stat Δ\n(measured PSI)"]
    GRAY, GOLD, RED, GREEN = "#9aa4b2", "#d9a441", "#e06c75", "#4c9f70"

    W, H = 820, 500
    pad_l, pad_r, pad_t, pad_b = 74, 40, 132, 90
    plot_w, plot_h = W - pad_l - pad_r, H - pad_t - pad_b
    max_x = max(len(kill_shot), len(measured)) - 1  # 3 (4 points, index 0..3)

    def X(i):
        return pad_l + (plot_w * i / max_x if max_x else 0)

    def Y(c):
        return pad_t + plot_h * (1 - c)

    parts = [f'<rect width="{W}" height="{H}" fill="#1b1f27" rx="8"/>',
             f'<text x="{pad_l}" y="26" font-size="17" font-weight="bold" fill="#e6e6e6">'
             f'Mnemo confidence timeseries — the silent drop, live from the graph</text>',
             f'<text x="{pad_l}" y="46" font-size="12" fill="#8a93a2">Belief.provenance (c_after per '
             f'update), read back via MnemoMemory.load — not simulated.</text>',
             f'<text x="{pad_l}" y="62" font-size="12" fill="#8a93a2">All three arcs share the same '
             f'start; they fork at the last event, where a measured PSI term is (or isn\'t) folded in.</text>']

    legend = [("shared baseline → hero stops here (no PSI profile in that demo)", GRAY),
              ("kill-shot: PSI stays silent (&lt; 0.10) → flat", GOLD),
              ("measured: real PSI=1.32 (&gt; 0.25) → drops harder", RED)]
    for i, (label, color) in enumerate(legend):
        ly = 84 + i * 16
        parts.append(f'<circle cx="{pad_l + 4}" cy="{ly - 4}" r="5" fill="{color}"/>')
        parts.append(f'<text x="{pad_l + 16}" y="{ly}" font-size="12" fill="#e6e6e6">{label}</text>')

    for gy in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = Y(gy)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{W - pad_r}" y2="{y:.1f}" '
                      f'stroke="#2c313c" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="11" '
                      f'fill="#8a93a2">{gy:.2f}</text>')
    gov_y = Y(0.7)
    parts.append(f'<line x1="{pad_l}" y1="{gov_y:.1f}" x2="{W - pad_r}" y2="{gov_y:.1f}" '
                 f'stroke="#e06c75" stroke-width="1.5" stroke-dasharray="6,4"/>')
    parts.append(f'<text x="{W - pad_r}" y="{gov_y - 8:.1f}" text-anchor="end" font-size="11" '
                 f'fill="#e06c75">governance τ=0.70 → opens a Proposal below this line</text>')

    for i, raw_label in enumerate(event_labels):
        for j, line in enumerate(raw_label.split("\n")):
            parts.append(f'<text x="{X(i):.1f}" y="{H - pad_b + 22 + j * 13:.1f}" text-anchor="middle" '
                         f'font-size="10" fill="#8a93a2">{line}</text>')

    # 1) shared prefix (indices 0..2) — one neutral line + labeled points, all three arcs agree here
    shared_pts = " ".join(f"{X(j):.1f},{Y(v):.1f}" for j, v in enumerate(hero))
    parts.append(f'<polyline points="{shared_pts}" fill="none" stroke="{GRAY}" stroke-width="3"/>')
    for j, v in enumerate(hero):
        parts.append(f'<circle cx="{X(j):.1f}" cy="{Y(v):.1f}" r="5" fill="{GRAY}"/>')
        parts.append(f'<text x="{X(j):.1f}" y="{Y(v) - 11:.1f}" text-anchor="middle" font-size="12" '
                     f'font-weight="bold" fill="#e6e6e6">{v:.3f}</text>')
    last_i = len(hero) - 1  # = 2: where hero stops and kill-shot/measured fork onward

    # 2) the fork: kill-shot (flat, PSI silent) vs measured (drops, PSI fires) — from the shared point on
    for values, color in ((kill_shot, GOLD), (measured, RED)):
        seg = " ".join(f"{X(j):.1f},{Y(v):.1f}" for j in range(last_i, len(values)) for v in [values[j]])
        parts.append(f'<polyline points="{seg}" fill="none" stroke="{color}" stroke-width="3"/>')
        fv = values[-1]
        parts.append(f'<circle cx="{X(len(values) - 1):.1f}" cy="{Y(fv):.1f}" r="5" fill="{color}"/>')
        parts.append(f'<text x="{X(len(values) - 1):.1f}" y="{Y(fv) - 11:.1f}" text-anchor="middle" '
                     f'font-size="12" font-weight="bold" fill="#e6e6e6">{fv:.3f}</text>')

    # 3) mark where hero (structural-only demo) ends — a small green ring around the shared fork point
    parts.append(f'<circle cx="{X(last_i):.1f}" cy="{Y(hero[last_i]):.1f}" r="9" fill="none" '
                 f'stroke="{GREEN}" stroke-width="2.5"/>')

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="sans-serif">'
           + "".join(parts) + "</svg>")
    with open(out_path, "w") as f:
        f.write(svg)
    log(f"   wrote {out_path}")

    with open(out_path) as f:
        content = f.read()
    check("chart: file written and non-empty", len(content) > 500, f"{len(content)} bytes")
    check("chart: contains the hero numbers (0.901 / 0.600)",
          "0.901" in content and "0.600" in content, "substring check on rendered SVG text")
    check("chart: contains the measured number (0.251)", "0.251" in content, "substring check")


# --------------------------------------------------------------------------------------------- #
# Eval numbers cross-check (read-only; eval/ itself is untouched)
# --------------------------------------------------------------------------------------------- #
def eval_crosscheck() -> None:
    log("=== STEP: eval numbers cross-check (examples/eval_summary.json, read-only) ===")
    path = os.path.join(ROOT, "examples", "eval_summary.json")
    with open(path) as f:
        summary = json.load(f)
    r = summary["results"]
    for arm, expected in EVAL_EXPECT.items():
        got = round(r[arm]["accuracy"], 2)
        check(f"eval: {arm} accuracy rounds to {expected:.2f}", close(got, expected, tol=0.005),
              f"got {got} (raw {r[arm]['accuracy']})")


# --------------------------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------------------------- #
def finish(ok: bool) -> None:
    log("")
    log("=" * 88)
    n_pass = sum(1 for _, p, _ in ASSERTIONS if p)
    n_total = len(ASSERTIONS)
    if ok and n_pass == n_total:
        log(f"GOLDEN-LOG ✅  ALL {n_total} ASSERTIONS PASSED — safe to record")
    else:
        log(f"GOLDEN-LOG ❌  {n_total - n_pass}/{n_total} ASSERTIONS FAILED — DO NOT RECORD, fix first")
        for desc, passed, detail in ASSERTIONS:
            if not passed:
                log(f"   ❌ {desc} — {detail}")
    log("=" * 88)
    log(f"Full log: {LOG_PATH}")
    _log_fh.close()
    sys.exit(0 if (ok and n_pass == n_total) else 1)


def main() -> None:
    log("Mnemo demo_e2e — deterministic CI-style capture run")
    preflight()

    seed_graph()
    hero_drift()
    measured_drift()

    g = _graph()
    reflection_beat(g)
    compounding_proof(g)
    build_confidence_chart(g, os.path.join(ROOT, "examples", "confidence_timeseries.svg"))
    eval_crosscheck()

    finish(ok=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # any unhandled break must abort VISIBLY, never show silently-wrong numbers
        log(f"❌ UNHANDLED EXCEPTION: {type(e).__name__}: {e}")
        finish(ok=False)
