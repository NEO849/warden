#!/usr/bin/env python3
"""
run_live_chain_demo.py — the deterministic, "runs like clockwork" LIVE-CHAIN orchestrator.

Everything else in this repo either (a) plays a scripted drift scenario on AUTHOR-SEEDED
synthetic entities (run_ml_drift_demo.py / demo_e2e.py: churn_model, fct_users_created, ...),
or (b) proves the core Reader -> Memory -> Bayesian-Confidence PLUMBING against REAL,
non-author-seeded assets but with NO real drift event and NO live wake (run_realdata_demo.py's
own honesty section says exactly this: "there is no real DRIFT EVENT here ... nobody but us
controls what happens to DataHub's official sample data").

This script closes both gaps at once, on ONE run: a real silent source-drift, on DataHub's own
official sample-data graph (SampleHiveDataset / SampleHdfsDataset / scienceModel — the exact
fixture every `datahub docker quickstart` ships), caught not by polling but by the ALWAYS-ON
`mnemo-wake` systemd service reacting to a genuine Kafka EntityChangeEvent_v1, which resolves
which model to re-check AUTONOMOUSLY via reverse lineage (G2, actions/mnemo_wake_action.py::
_reverse_lineage_models) rather than a hardcoded watch-list, and which now ACTUALLY WRITES real
governance onto the graph (G1, mnemo/agent.py::actuate_governance) instead of only logging it.

Every stage below is a READ-BACK GATE: poll the live graph/console/subprocess until the expected
state is durably true, with a timeout that aborts LOUDLY on failure — never a fixed `sleep`, and
never a silently-wrong "looks done" assumption. Two consecutive runs of this script must both
reach GREEN (idempotency is designed in at the baseline-reset step, not assumed).

What each stage proves:
  PREFLIGHT      GMS + the mnemo-wake service + the trust console are all actually up.
  BASELINE RESET Idempotent: (re)attach a bridge MLFeature(sources=[SampleHiveDataset]) onto
                 scienceModel (closing run_realdata_demo.py's documented missing edge) and
                 (re)establish a fresh Belief at exactly confidence=0.901 — regardless of what
                 state a PRIOR run of this script left behind.
  RE-POINT       The feature's source silently swaps to SampleHdfsDataset — same name/description,
                 the exact "a schema-diff sees nothing" shape the hero demo is built around.
  GATE 1 / 1b    Poll until the re-point is durably visible via BOTH the read path Mnemo's own
                 drift-detection uses (agent.model_input_sources) AND the read path G2's
                 reverse-lineage depends on (the GMS relationships index) — two different DataHub
                 subsystems that can lag independently; firing the Kafka trigger before either
                 catches up would make the next gate flaky for reasons that have nothing to do
                 with the mechanism being tested.
  KAFKA TRIGGER  A fresh (never-before-seen) tag lands on SampleHdfsDataset — the dataset that is
                 now scienceModel's current source. This is a category=TAG, entityType=dataset
                 event; the running wake service never had scienceModel in its static
                 MNEMO_WATCH_MODELS list, so if it still gets woken and governed, that is live
                 proof of G2 (reverse lineage), not the static fallback.
  GATE 3         Poll scienceModel's structured properties until the wake has actually written
                 governance_status=NEEDS_REVIEW + a finding + the mnemo-needs-review tag (async,
                 the wake service polls Kafka on its own schedule — budget ~30-60s).
  GATE 4         The read-only trust console (console/app.py) — started here if not already
                 running, stopped again at the end — independently confirms the same state
                 through its own HTTP API, never importing mnemo/agent.py.
  GATE 5         A DIFFERENT script, interop_demo.py, run as a subprocess with zero Mnemo
                 knowledge, reads the same structured property off the graph and REFUSES to
                 recommend the model for production — the moat, demonstrated live.

Untouched by this script: run_ml_drift_demo.py, demo_e2e.py, seed_demo_graph.py,
confidence_model.py, churn_model (kept OUT of this run entirely, for numeric purity of the
other scripts' invariants).

Run:  python run_live_chain_demo.py
Exit code 0 = LIVE-CHAIN GREEN. Exit code 1 = a gate failed — see the printed diagnosis.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import quote

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

GMS_URL = os.getenv("DATAHUB_GMS_URL", "http://localhost:8090")
CONSOLE_PORT = int(os.getenv("MNEMO_CONSOLE_PORT", "8808"))
CONSOLE_BASE = f"http://127.0.0.1:{CONSOLE_PORT}"
PY = sys.executable

# --- deterministic target numbers (same Bayesian math as run_ml_drift_demo.py's hero beat: two
# corroborating "lineage" events -> 0.901, one contradicting "schema" event -> 0.600) ---
BASELINE = 0.901
FINAL = 0.600
TOL = 0.003

# --- DataHub's OWN official bootstrap sample-data fixture (not author-seeded by this repo) ---
HIVE = "urn:li:dataset:(urn:li:dataPlatform:hive,SampleHiveDataset,PROD)"
HDFS = "urn:li:dataset:(urn:li:dataPlatform:hdfs,SampleHdfsDataset,PROD)"
SCIENCE_MODEL = "urn:li:mlModel:(urn:li:dataPlatform:science,scienceModel,PROD)"
NEEDS_REVIEW_TAG_URN = "urn:li:tag:mnemo-needs-review"

# The ONE author-added edge this script establishes (idempotently, every run): a bridge feature
# that closes scienceModel's missing feature-source link (see run_realdata_demo.py STEP 5's
# honesty note: the real bootstrap fixture ships no feature-store-shaped model). This is the
# only new entity this script introduces; everything else it touches is DataHub's own fixture.
BRIDGE_FEATURE = "urn:li:mlFeature:(science_features,mnemo_livechain_feature)"

LOG_PATH = os.path.join(ROOT, f"run_live_chain_demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
_log_fh = open(LOG_PATH, "w")
ASSERTIONS = []  # list of (description, passed: bool, detail: str)
_console_proc = None  # subprocess handle, set iff THIS run started the console


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


def poll_until(desc: str, fn, timeout_s: float, interval_s: float = 1.0):
    """Poll fn() -> (ok: bool, detail: str) on a short cadence until ok or timeout. This is the
    ONLY waiting mechanism this script uses — no fixed `sleep(N)` anywhere on the critical path;
    every stage either is durably true or the gate fails loudly with a diagnosis."""
    deadline = time.time() + timeout_s
    last_detail = "(never checked)"
    while time.time() < deadline:
        ok, last_detail = fn()
        if ok:
            return True, last_detail
        time.sleep(interval_s)
    return False, last_detail


def _stop_console_if_ours() -> None:
    global _console_proc
    if _console_proc is not None:
        log(f"   stopping test-uvicorn console instance we started (pid={_console_proc.pid})")
        _console_proc.terminate()
        try:
            _console_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _console_proc.kill()
        _console_proc = None


def finish(ok: bool) -> None:
    _stop_console_if_ours()
    log("")
    log("=" * 88)
    n_pass = sum(1 for _, p, _ in ASSERTIONS if p)
    n_total = len(ASSERTIONS)
    if ok and n_pass == n_total and n_total > 0:
        log(f"LIVE-CHAIN GREEN ✅  ALL {n_total} GATE CHECKS PASSED — the chain ran like clockwork")
    else:
        log(f"LIVE-CHAIN RED ❌  {n_total - n_pass}/{n_total} CHECKS FAILED")
        for desc, passed, detail in ASSERTIONS:
            if not passed:
                log(f"   ❌ {desc} — {detail}")
    log("=" * 88)
    log(f"Full log: {LOG_PATH}")
    _log_fh.close()
    sys.exit(0 if (ok and n_pass == n_total and n_total > 0) else 1)


def abort(msg: str) -> None:
    log(f"❌ ABORTED: {msg}")
    finish(ok=False)


# --------------------------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------------------------- #
def _http_get_json(url: str, timeout: float = 5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode())


def _console_alive() -> bool:
    try:
        status, _ = _http_get_json(f"{CONSOLE_BASE}/api/heartbeat")
        return status == 200
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, OSError):
        return False


def _start_console_if_needed() -> None:
    global _console_proc
    if _console_alive():
        log(f"   ✅ console already reachable at {CONSOLE_BASE} (not started by this run)")
        return
    log(f"   console not reachable at {CONSOLE_BASE} — starting a test uvicorn instance "
        f"(127.0.0.1 only, per console/app.py's hardcoded bind)")
    env = os.environ.copy()
    _console_proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "console.app:app", "--host", "127.0.0.1", "--port", str(CONSOLE_PORT)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    ok, detail = poll_until(
        "console test-uvicorn readiness",
        lambda: (_console_alive(), "waiting for GET /api/heartbeat -> 200"),
        timeout_s=20, interval_s=1.0,
    )
    if not ok:
        abort(f"console test-uvicorn (pid={_console_proc.pid}) did not become reachable within 20s ({detail})")
    log(f"   ✅ console test-uvicorn up (pid={_console_proc.pid})")


def preflight() -> None:
    log("=== PREFLIGHT ===")
    try:
        with urllib.request.urlopen(f"{GMS_URL}/health", timeout=5) as r:
            check("preflight: GMS healthy", r.status == 200, f"HTTP {r.status} at {GMS_URL}/health")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        abort(f"DataHub GMS not reachable at {GMS_URL} ({type(e).__name__}: {e}). "
              f"Start it (`datahub docker quickstart`) and re-run.")

    svc_status = subprocess.run(
        ["systemctl", "is-active", "mnemo-wake.service"], capture_output=True, text=True
    ).stdout.strip()
    if not check("preflight: mnemo-wake.service active", svc_status == "active",
                 f"systemctl is-active mnemo-wake.service -> {svc_status!r}"):
        abort("mnemo-wake.service is not active. Start it: `systemctl start mnemo-wake.service`, "
              "wait ~20-30s for the Kafka connect, then re-run.")

    _start_console_if_needed()
    check("preflight: console /api/heartbeat reachable", _console_alive(),
          f"GET {CONSOLE_BASE}/api/heartbeat")


# --------------------------------------------------------------------------------------------- #
# Graph client + agent
# --------------------------------------------------------------------------------------------- #
def _graph():
    from datahub.ingestion.graph.client import DataHubGraph, DataHubGraphConfig
    return DataHubGraph(DataHubGraphConfig(
        server=GMS_URL, token=os.getenv("DATAHUB_GMS_TOKEN") or None,
    ))


# --------------------------------------------------------------------------------------------- #
# Baseline reset (idempotent — safe to run this whole script back to back, N times)
# --------------------------------------------------------------------------------------------- #
def baseline_reset(g, agent) -> None:
    log("=== STEP: baseline reset (idempotent) — bridge feature -> SampleHiveDataset, belief -> 0.901 ===")
    from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
    from datahub.metadata.schema_classes import MLFeaturePropertiesClass, MLModelPropertiesClass

    # Force the bridge feature's source back to SampleHiveDataset regardless of where a prior run
    # (or the live wake) left it — this alone makes the reset idempotent w.r.t. the re-point step.
    g.emit(MCP(entityUrn=BRIDGE_FEATURE, aspect=MLFeaturePropertiesClass(
        description="Mnemo live-chain bridge feature (author-added edge; closes the missing "
                    "feature-source link on DataHub's own scienceModel sample fixture — see "
                    "run_realdata_demo.py STEP 5)",
        sources=[HIVE],
    )))

    # Attach the bridge feature to scienceModel WITHOUT clobbering the bootstrap pack's own
    # description/type/tags/etc — MLModelPropertiesClass is a full-replace aspect, so read the
    # current value first and only override mlFeatures.
    mp = g.get_aspect(SCIENCE_MODEL, MLModelPropertiesClass)
    kwargs = dict(mp._inner_dict) if mp is not None else {}
    kwargs["mlFeatures"] = [BRIDGE_FEATURE]
    g.emit(MCP(entityUrn=SCIENCE_MODEL, aspect=MLModelPropertiesClass(**kwargs)))
    log(f"   scienceModel.mlFeatures -> [{BRIDGE_FEATURE}] (description/type/tags preserved: "
        f"description={kwargs.get('description')!r})")

    from confidence_model import Belief
    from mnemo.memory import MnemoMemory
    mem = MnemoMemory(g)
    b = Belief()
    b.update("lineage", corroborates=True, hops=2, quality=0.9, event_id="chain_baseline1")
    b.update("lineage", corroborates=True, hops=0, quality=1.0, event_id="chain_baseline2")
    mem.save(SCIENCE_MODEL, json.dumps({"desc": "live-chain baseline: healthy input = SampleHiveDataset",
                                        "input_sources": [HIVE]}), b, "chain_baseline2")
    log(f"   fresh Belief established: confidence={b.confidence:.3f} (target {BASELINE})")
    check("baseline: confidence == 0.901", close(b.confidence, BASELINE), f"got {b.confidence:.3f}")

    now = agent.model_input_sources(SCIENCE_MODEL)
    check("baseline: model_input_sources reads back [SampleHiveDataset]", now == [HIVE], f"got {now}")


# --------------------------------------------------------------------------------------------- #
# Silent re-point + GATE 1 / 1b
# --------------------------------------------------------------------------------------------- #
def silent_repoint_and_gate1(g, agent) -> None:
    log("=== STEP: silent source re-point — SampleHiveDataset -> SampleHdfsDataset (name/desc unchanged) ===")
    from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
    from datahub.ingestion.graph.openapi import RelationshipDirection
    from datahub.metadata.schema_classes import MLFeaturePropertiesClass

    g.emit(MCP(entityUrn=BRIDGE_FEATURE, aspect=MLFeaturePropertiesClass(
        description="Mnemo live-chain bridge feature (author-added edge; closes the missing "
                    "feature-source link on DataHub's own scienceModel sample fixture — see "
                    "run_realdata_demo.py STEP 5)",
        sources=[HDFS],
    )))
    log("   feature re-pointed — a schema-diff sees nothing (name/description identical)")

    def _gate1():
        now = agent.model_input_sources(SCIENCE_MODEL)
        return now == [HDFS], f"model_input_sources={now}"

    ok, detail = poll_until("GATE 1", _gate1, timeout_s=20, interval_s=1.0)
    check("GATE 1: re-point durable via agent.model_input_sources (<=20s)", ok, detail)
    if not ok:
        abort("GATE 1 failed — the re-point never became visible via agent.model_input_sources; "
              "aborting BEFORE firing the Kafka trigger (would test against stale state).")

    # GATE 1b hardens GATE 3 against a real, independently-observed flakiness source: G2's
    # reverse-lineage read goes through GMS's relationships/graph index, a DIFFERENT subsystem
    # from the plain aspect read GATE 1 just confirmed. The two can lag independently. Poll the
    # relationship edge itself before firing the trigger, so a graph-index lag fails HERE with a
    # clear diagnosis instead of silently degrading GATE 3 into "fell back to the static list".
    def _gate1b():
        try:
            related = [r.urn for r in g.get_related_entities(
                HDFS, relationship_types=["DerivedFrom"], direction=RelationshipDirection.INCOMING,
            )]
        except Exception as e:  # noqa: BLE001 — this is itself the condition being polled
            return False, f"relationships query failed: {type(e).__name__}: {e}"
        return BRIDGE_FEATURE in related, f"DerivedFrom(SampleHdfsDataset) -> {related}"

    ok2, detail2 = poll_until("GATE 1b", _gate1b, timeout_s=20, interval_s=1.0)
    check("GATE 1b: relationship index shows SampleHdfsDataset -DerivedFrom-> bridge feature (<=20s)",
          ok2, detail2)
    if not ok2:
        abort("GATE 1b failed — the relationship index the wake's G2 reverse-lineage depends on "
              "never caught up; firing the trigger now would race it.")


# --------------------------------------------------------------------------------------------- #
# Kafka wake trigger — fires on the DATASET, not the model, so the running service's G2
# reverse-lineage (not its static watch_models list) is what has to resolve scienceModel.
# --------------------------------------------------------------------------------------------- #
def fire_kafka_trigger(g) -> None:
    log("=== STEP: Kafka wake trigger — fresh TAG-ADD on SampleHdfsDataset (scienceModel's NEW source) ===")
    from datahub.emitter.mcp import MetadataChangeProposalWrapper as MCP
    from datahub.metadata.schema_classes import GlobalTagsClass, TagAssociationClass

    # FRESH tag value every run — re-emitting an IDENTICAL GlobalTags aspect is a no-op diff and
    # does not generate a new EntityChangeEvent (empirically confirmed, see
    # actions/_verify_trigger2.py and this script's own dry-run history).
    fresh_tag = f"urn:li:tag:mnemo-livechain-wake-{int(time.time())}"
    g.emit(MCP(entityUrn=HDFS, aspect=GlobalTagsClass(tags=[TagAssociationClass(tag=fresh_tag)])))
    log(f"   tag-add fired on {HDFS} ({fresh_tag}) — entityType=dataset, category=TAG.")
    log("   scienceModel is NOT in the running service's static MNEMO_WATCH_MODELS (that still "
        "defaults to churn_model) — so the wake reacting at all is live proof of G2's reverse "
        "lineage (dataset -> bridge feature -> scienceModel), not the static fallback.")


# --------------------------------------------------------------------------------------------- #
# GATE 3 — the wake actually wrote real governance (G1)
# --------------------------------------------------------------------------------------------- #
def gate3_wait_for_governance(g) -> None:
    log("=== GATE 3: poll scienceModel until the wake writes NEEDS_REVIEW + finding + tag ===")
    from datahub.metadata.schema_classes import GlobalTagsClass, StructuredPropertiesClass

    def _check():
        sp = g.get_aspect(SCIENCE_MODEL, StructuredPropertiesClass)
        vals = {}
        if sp:
            for p in sp.properties:
                qn = p.propertyUrn.split(":")[-1]
                vals[qn] = p.values[0] if p.values else None
        status = vals.get("mnemo.governance_status")
        finding = vals.get("mnemo.finding")
        try:
            provenance = json.loads(vals.get("mnemo.provenance") or "[]")
        except (json.JSONDecodeError, TypeError):
            provenance = []
        last_prov = provenance[-1] if provenance else {}
        # IDEMPOTENCY FIX (flakiness found & fixed, not just found): baseline_reset() intentionally
        # resets the BELIEF to 0.901 but does NOT touch a PRIOR run's leftover
        # governance_status/tag/finding -- so on a 2nd+ run, `status == NEEDS_REVIEW` can already
        # be true from the LAST run before this run's own trigger has fired at all, and this gate
        # would pass instantly on stale state (live-reproduced: confidence read back as 0.901 with
        # last_event=chain_baseline2, i.e. the pre-drift baseline, not the post-drift write).
        # FIX: also require a fresh contradicting schema/input_delta evidence entry -- append-only,
        # so this can only become true once THIS run's wake event has actually been processed.
        # baseline_reset() itself never appends event_id="input_delta" (it only ever appends
        # "lineage" events, and it REPLACES mnemo.provenance wholesale via a fresh Belief -- see
        # MnemoMemory.save -- so the provenance list is guaranteed to start each run containing only
        # those 2 lineage entries). Checking the exact LAST entry (as opposed to: any input_delta
        # entry anywhere in the log) used to be required here -- BUT check_model_inputs() can also
        # append a SECOND, trailing "drift_stat"/input_delta entry right after "schema"/input_delta
        # (mnemo/agent.py ~line 168, whenever a DatasetProfile pair exists for the swapped sources)
        # -- so strict last-entry equality is fragile: it is only ever green today because the
        # sample fixtures happen to carry no DatasetProfile, not because the mechanism guarantees
        # it. FIX (robust, not weaker): accept ANY input_delta-tagged entry as long as at least one
        # of them is the "schema" evidence -- since provenance is reset to [lineage, lineage] every
        # run by baseline_reset(), an input_delta entry can ONLY exist here because THIS run's
        # check_model_inputs() actually fired; this still proves the same freshness the strict
        # last-entry check did, without going falsely red the moment a profile pair starts existing.
        input_delta_entries = [p for p in provenance if p.get("event") == "input_delta"]
        fresh_drift = any(p.get("source") == "schema" for p in input_delta_entries)
        # FIX A: the reverse-lineage resolution witness must be DURABLE on the graph, not provable
        # only by exclusion (no static watch-list configured) or by a wake_service.err.log line that
        # doesn't survive a log rotation/reset. actions/mnemo_wake_action.py now threads
        # resolution_source ("reverse-lineage" | "static-watchlist") into
        # MnemoAgent.check_model_inputs(..., via=...), which folds it onto the "schema" provenance
        # entry itself (confidence_model.py::Belief.update's `via` param) -- so it round-trips
        # through the exact same mnemo.provenance structured property GATE 3 already reads. Find
        # that schema entry among the fresh input_delta entries and assert via=="reverse-lineage":
        # scienceModel is never in the wake service's static MNEMO_WATCH_MODELS (see
        # fire_kafka_trigger's own comment), so this run can ONLY have gotten here via G2.
        schema_entry = next((p for p in input_delta_entries if p.get("source") == "schema"), {})
        witnessed_via = schema_entry.get("via")
        on_graph_reverse_lineage_witness = witnessed_via == "reverse-lineage"
        tags = g.get_aspect(SCIENCE_MODEL, GlobalTagsClass)
        tag_urns = [t.tag for t in tags.tags] if tags and tags.tags else []
        has_review_tag = NEEDS_REVIEW_TAG_URN in tag_urns
        ok = (fresh_drift and status == "NEEDS_REVIEW" and bool(finding) and has_review_tag
              and on_graph_reverse_lineage_witness)
        detail = (f"fresh_drift(input_delta_entries={input_delta_entries!r})={fresh_drift} "
                  f"on_graph_via={witnessed_via!r} status={status!r} "
                  f"finding={'<set>' if finding else None!r} needs_review_tag={has_review_tag} "
                  f"confidence={vals.get('mnemo.confidence')}")
        return ok, detail

    ok, detail = poll_until("GATE 3", _check, timeout_s=60, interval_s=2.0)
    check("GATE 3: wake wrote a FRESH governance_status=NEEDS_REVIEW + finding + tag, keyed off the "
          "append-only provenance log so stale state from a prior run cannot pass this gate, AND the "
          "on-graph provenance entry itself witnesses via=='reverse-lineage' (durable proof G2 "
          "resolved this, not just absence-of-static-watchlist) (<=60s, wake is ~30s async)",
          ok, detail)
    if not ok:
        abort("GATE 3 failed — the wake never wrote a fresh governance verdict for scienceModel "
              "(with an on-graph reverse-lineage witness) within 60s. Check "
              "actions/wake_service.err.log for 'MNEMO WAKE' lines and confirm G2's reverse-lineage "
              "resolved SampleHdfsDataset -> scienceModel (grep 'via=reverse-lineage').")
    # On-screen honesty (delivers the storyboard/README promise that the caveat is visible in the run,
    # not just in the docs): the DROP MAGNITUDE is a principled Bayesian log-odds update from the
    # structural source-delta term — it is NOT a measured drift statistic on this sample pair.
    log("   [honesty] confidence drop 0.901->0.600 is a principled Bayesian log-odds update from the "
        "structural source-delta term — NOT a measured drift statistic on this sample pair; the "
        "measured-PSI variant is run_measured_drift_demo.py (adds a drift_stat term when profiles exist).")


# --------------------------------------------------------------------------------------------- #
# GATE 4 — the read-only trust console independently confirms the same state
# --------------------------------------------------------------------------------------------- #
def gate4_console_api() -> None:
    log("=== GATE 4: console API (console/app.py, zero write path) reflects the drift + governance ===")
    urn_path = quote(SCIENCE_MODEL, safe="")
    try:
        status, data = _http_get_json(f"{CONSOLE_BASE}/api/model/{urn_path}")
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, OSError) as e:
        abort(f"GATE 4 failed — GET /api/model/{{urn}} unreachable: {type(e).__name__}: {e}")
        return
    check("GATE 4: /api/model/{urn} -> HTTP 200", status == 200, f"HTTP {status}")
    check("GATE 4: governance_status == NEEDS_REVIEW", data.get("governance_status") == "NEEDS_REVIEW",
          f"got {data.get('governance_status')!r}")

    # FLAKINESS FOUND & HANDLED, not silently papered over: console/app.py's `sources_drifted` is
    # `bool(current) and set(current) != set(remembered)`. But mnemo/agent.py::check_model_inputs
    # OVERWRITES the remembered summary to `input_sources: now` in the SAME write that detects the
    # delta (agent.py ~line 170) -- BEFORE actuate_governance ever runs. So by the time GATE 3 has
    # confirmed governance_status=NEEDS_REVIEW, remembered and current have ALREADY converged and
    # sources_drifted is structurally False -- live-verified: a real run of this exact script hit
    # `sources_drifted=False` here 100% of the time, not a transient failure to retry away. The
    # actually-durable evidence that a drift WAS caught and folded into governance is the
    # provenance chain's last entry (source=schema, event=input_delta) plus last_event itself --
    # append-only, never overwritten, so this assertion is stable instead of racing the write that
    # produced GATE 3's own success condition.
    log(f"   [informational] sources_drifted={data.get('sources_drifted')!r} remembered="
        f"{data.get('remembered_sources')} current={data.get('current_sources')} -- expected False "
        f"here (see comment above), NOT used as a gate condition")
    prov = data.get("provenance") or []
    last_prov = prov[-1] if prov else {}
    check("GATE 4: last_event == 'input_delta' (durable proof a drift was detected)",
          data.get("last_event") == "input_delta", f"got {data.get('last_event')!r}")
    check("GATE 4: provenance's last entry is the contradicting schema-delta evidence",
          last_prov.get("source") == "schema" and last_prov.get("event") == "input_delta",
          f"got {last_prov!r}")
    conf = data.get("confidence")
    check("GATE 4: confidence ≈ 0.600", conf is not None and close(conf, FINAL), f"got {conf!r}")

    try:
        hb_status, hb = _http_get_json(f"{CONSOLE_BASE}/api/heartbeat")
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, OSError) as e:
        abort(f"GATE 4 failed — GET /api/heartbeat unreachable: {type(e).__name__}: {e}")
        return
    check("GATE 4: /api/heartbeat -> HTTP 200", hb_status == 200, f"HTTP {hb_status}")
    check("GATE 4: /api/heartbeat awake == True", hb.get("awake") is True, f"got {hb}")


# --------------------------------------------------------------------------------------------- #
# GATE 5 — a DIFFERENT agent, zero Mnemo knowledge, reads the graph and refuses
# --------------------------------------------------------------------------------------------- #
def gate5_interop() -> None:
    log("=== GATE 5: interop_demo.py (different script, zero Mnemo code) refuses the flagged model ===")
    proc = subprocess.run(
        [PY, os.path.join(ROOT, "interop_demo.py"), "--server", GMS_URL, "--urn", SCIENCE_MODEL],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    for line in proc.stdout.splitlines():
        log(f"   [interop] {line}")
    if proc.stderr.strip():
        for line in proc.stderr.strip().splitlines():
            log(f"   [interop][stderr] {line}")
    check("GATE 5: interop_demo.py process exit code 0", proc.returncode == 0, f"returncode={proc.returncode}")
    check("GATE 5: downstream agent REFUSED (NEEDS_REVIEW read straight off the graph)",
          "REFUSED" in proc.stdout, "looked for 'REFUSED' in interop_demo.py stdout")


# --------------------------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------------------------- #
def main() -> None:
    log("Mnemo run_live_chain_demo — deterministic live-graph orchestrator "
        "(poll-until-condition, zero fixed sleeps on the critical path)")
    preflight()

    from mnemo.agent import MnemoAgent
    g = _graph()
    agent = MnemoAgent(g)
    agent.setup()  # idempotent: ensures mnemo.* structured properties + reflection prop + the
                   # mnemo-needs-review tag entity are all defined (no-op if already defined)

    baseline_reset(g, agent)
    silent_repoint_and_gate1(g, agent)
    fire_kafka_trigger(g)
    gate3_wait_for_governance(g)
    gate4_console_api()
    gate5_interop()

    finish(ok=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # any unhandled break must abort VISIBLY, never show silently-wrong state
        log(f"❌ UNHANDLED EXCEPTION: {type(e).__name__}: {e}")
        finish(ok=False)
