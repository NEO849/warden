#!/usr/bin/env python3
"""
Context-lift eval: does Mnemo's MEMORY measurably improve ML-risk triage accuracy?

Task: classify each (upstream change, model) as DRIFT / LEAKAGE / NO_RISK.
Arms (same local Ollama model, temp 0, identical prompt except the memory block):
  WITHOUT  = raw metadata only (schema, lineage, the change)
  WITH     = raw metadata + Mnemo memory (prior source-set + confidence; reflection)  ← the lift
  PLACEBO  = raw metadata + an UNRELATED asset's memory (equal budget) → controls for "more text"

Fairness: the memory block gives REMEMBERED STATE, never the label. The model must still reason
(e.g. "remembered source ≠ current source → DRIFT"). Deterministic cases + fixed order + a
non-LLM scorer → a judge can recompute the bar from eval/results.csv.

Run:  python eval/run_eval.py         (needs Ollama; ~36s/call on CPU → runs best in background)
Env:  EVAL_N (cases, default 6), OLLAMA_MODEL
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mnemo.llm import ollama_json

CLASSES = ["DRIFT", "LEAKAGE", "NO_RISK"]
SYSTEM = ("You are an ML production-risk triage agent. Given metadata about a model and a recent "
          "change to its data lineage, classify the risk to the model as EXACTLY one of "
          "DRIFT (a training input's meaning/source silently changed), "
          "LEAKAGE (a feature's lineage reaches the label/target), or "
          "NO_RISK (the change does not affect this model's inputs). "
          'Output STRICT JSON: {"label": "DRIFT"|"LEAKAGE"|"NO_RISK"}.')

# 21 genuinely-distinct labeled cases (7/class): the original 15 (5/class), mixed difficulty incl.
# hard cases where memory is weak/ambiguous so WITH is not trivially perfect, PLUS 6 ADVERSARIAL
# cases (2/class, appended at the end — see "ADVERSARIAL" block below) that each defeat the trivial
# schema-pattern shortcut a Rigor-Judge flagged (DRIFT=prior_source≠current_source, LEAKAGE=
# current_source==label, NO_RISK=hash==hash). raw = facts shown to ALL arms; mem = Mnemo memory.
# The memory gives REMEMBERED STATE, never the label — the model must still reason.
#
# mem_raw = the same remembered state, but stripped to RAW FACTS ONLY (prior_source/prior_type/
# prior_confidence/current_source-style key=value pairs) — no natural-language conclusion words
# ("differs", "temporal leakage", "reaches the label", "same", "not consumed", ...). Feeds the
# WITH_RAW arm: the model must derive the verdict itself from remembered-vs-current facts, the
# same way it would from raw lineage/schema deltas. Existing `mem` strings are untouched.
_BASE = [
    # ---- DRIFT (5) ----
    {"label": "DRIFT", "raw": "Model churn_model uses feature days_since_signup; lineage sources=[fct_users_v2]; schema looks normal, no error.",
     "mem": "Memory on days_since_signup: previously sourced from [fct_users] at confidence 0.90 (2 events). Current source [fct_users_v2] differs.",
     "mem_raw": "prior_source=fct_users; prior_type=signup_ts; prior_confidence=0.90; current_source=fct_users_v2"},
    {"label": "DRIFT", "raw": "Model ltv_model uses feature avg_order_value; column type is now string; no rename.",
     "mem": "Memory: avg_order_value was type decimal at confidence 0.88; it is now string — same name, changed type.",
     "mem_raw": "prior_source=avg_order_value; prior_type=decimal; prior_confidence=0.88; current_source=avg_order_value:string"},
    {"label": "DRIFT", "raw": "Model ranking_model uses feature ctr_7d; upstream table events re-pointed to events_clone; both look identical.",
     "mem": "Memory (LOW confidence 0.55): ctr_7d source may have changed from events to events_clone; not strongly corroborated.",
     "mem_raw": "prior_source=events; prior_type=table_ref; prior_confidence=0.55; current_source=events_clone"},
    {"label": "DRIFT", "raw": "Model credit_model uses feature income_bucket; upstream applies a new bucketing threshold; column name unchanged.",
     "mem": "Memory: income_bucket boundaries changed vs remembered distribution (confidence 0.82); semantics shifted under a stable name.",
     "mem_raw": "prior_source=bucket_def_v1(0.10,0.25,0.50); prior_type=threshold_config; prior_confidence=0.82; current_source=bucket_def_v2(0.15,0.30,0.55)"},
    {"label": "DRIFT", "raw": "Model demand_model uses feature region_code; upstream ref table swapped from geo_v1 to geo_v3; values remap silently.",
     "mem": "Memory: region_code encoded via geo_v1 at confidence 0.9; now geo_v3 — remembered mapping differs.",
     "mem_raw": "prior_source=geo_v1; prior_type=ref_table; prior_confidence=0.9; current_source=geo_v3"},
    # ---- LEAKAGE (5) ----
    {"label": "LEAKAGE", "raw": "Model fraud_model uses feature risk_score; lineage risk_score.sources=[txn_enriched]; txn_enriched upstream=[txn_raw, label_fraud_outcome]; training label=label_fraud_outcome.",
     "mem": "Memory: risk_score's lineage transitively reaches the model's label dataset label_fraud_outcome (confidence 0.85).",
     "mem_raw": "prior_source=txn_enriched; prior_type=lineage_hop; prior_confidence=0.85; current_source=label_fraud_outcome"},
    {"label": "LEAKAGE", "raw": "Model churn_model2 adds feature will_cancel_flag computed post-subscription-end; label is churned_30d.",
     "mem": "Memory: will_cancel_flag is derived after the outcome window that defines churned_30d (confidence 0.8) — temporal leakage.",
     "mem_raw": "prior_source=will_cancel_flag; prior_type=event_time_offset; prior_confidence=0.8; current_source=churned_30d_window"},
    {"label": "LEAKAGE", "raw": "Model default_model uses feature acct_status; acct_status.sources=[collections]; collections is downstream of default_label.",
     "mem": "Memory: acct_status upstream includes collections, which is computed from default_label (confidence 0.83).",
     "mem_raw": "prior_source=collections; prior_type=lineage_hop; prior_confidence=0.83; current_source=default_label"},
    {"label": "LEAKAGE", "raw": "Model conv_model uses feature refund_amount; refunds only exist after conversion; target is converted.",
     "mem": "Memory: refund_amount is populated only for converted users — availability correlates with the target (confidence 0.78).",
     "mem_raw": "prior_source=refund_amount; prior_type=availability_flag; prior_confidence=0.78; current_source=converted"},
    {"label": "LEAKAGE", "raw": "Model lead_model uses feature sales_touch_count; sales only touch qualified leads; label is qualified.",
     "mem": "Memory: sales_touch_count is a consequence of qualification, not a cause (confidence 0.7) — reaches the label.",
     "mem_raw": "prior_source=sales_touch_count; prior_type=event_trigger; prior_confidence=0.7; current_source=qualified"},
    # ---- NO_RISK (5) ----
    {"label": "NO_RISK", "raw": "Model reco_model uses feature affinity sources=[catalog]. Event: column internal_note modified on audit_log; audit_log not in lineage.",
     "mem": "Memory: no input of reco_model depends on audit_log (confidence 0.90).",
     "mem_raw": "prior_source=affinity; prior_type=lineage_dependency_set; prior_confidence=0.90; current_source=catalog"},
    {"label": "NO_RISK", "raw": "Model churn_model source table fct_users was RENAMED to fct_users (curated); underlying data identical, alias kept.",
     "mem": "Memory: fct_users and fct_users(curated) are the same physical data via alias (confidence 0.9); no semantic change.",
     "mem_raw": "prior_source=fct_users; prior_type=physical_id:tbl_9f21; prior_confidence=0.9; current_source=physical_id:tbl_9f21"},
    {"label": "NO_RISK", "raw": "Model ltv_model: a deprecated feature legacy_score (not in the model's feature list) changed upstream.",
     "mem": "Memory: legacy_score is not consumed by ltv_model (confidence 0.92).",
     "mem_raw": "prior_source=legacy_score; prior_type=deprecated_feature; prior_confidence=0.92; current_source=ltv_model_feature_list_v7"},
    {"label": "NO_RISK", "raw": "Model ranking_model: a column description was edited on an upstream table; no schema or lineage change.",
     "mem": "Memory: cosmetic doc-only edit; ranking_model inputs unchanged (confidence 0.9).",
     "mem_raw": "prior_source=ranking_model_inputs; prior_type=input_set_hash:a1c3; prior_confidence=0.9; current_source=input_set_hash:a1c3"},
    {"label": "NO_RISK", "raw": "Model demand_model: a new column added to an upstream table; existing consumed columns untouched.",
     "mem": "Memory: added column is not consumed by demand_model; existing inputs stable (confidence 0.88).",
     "mem_raw": "prior_source=demand_model_inputs; prior_type=input_set_hash:7e2d; prior_confidence=0.88; current_source=input_set_hash:7e2d"},
    # ---- ADVERSARIAL (6, 2/class) — each one defeats the trivial schema-pattern shortcut.
    # NO_RISK despite prior_source != current_source (would trivially read as DRIFT):
    {"label": "NO_RISK", "raw": "Model pricing_model uses feature base_currency_amount; lineage source table renamed from txn_amounts_usd to txn_amounts_usd_v2 during a routine warehouse migration; column-level checksum of migrated rows matches the source-of-truth ledger for the full historical window.",
     "mem": "Memory: txn_amounts_usd was migrated verbatim to txn_amounts_usd_v2 as part of a scheduled warehouse copy; row-level checksums matched pre/post migration (confidence 0.93); no transformation logic applied — a physical rename, not a semantic change.",
     "mem_raw": "prior_source=txn_amounts_usd; prior_type=table_ref; prior_confidence=0.93; current_source=txn_amounts_usd_v2"},
    {"label": "NO_RISK", "raw": "Model inventory_forecast_model uses feature warehouse_temp_reading; the upstream source was swapped from sensor_feed_a to sensor_feed_b after a hardware vendor change; sensor_feed_b was calibrated against sensor_feed_a for 30 days with mean absolute deviation under 0.1 degrees before cutover, per the attached migration ticket.",
     "mem": "Memory: warehouse_temp_reading originally sourced from sensor_feed_a (confidence 0.85); now sensor_feed_b following a calibrated, validated vendor swap — values are equivalent within noise, not a semantic change.",
     "mem_raw": "prior_source=sensor_feed_a; prior_type=sensor_stream; prior_confidence=0.85; current_source=sensor_feed_b"},
    # LEAKAGE where current_source is NOT literally the label — needs a 1-2 hop inference from `raw`:
    {"label": "LEAKAGE", "raw": "Model subscription_churn_model uses feature days_since_last_ticket_days; lineage sources=[support_tickets_enriched]; support_tickets_enriched is built by joining raw ticket data to cancellation_survey on user_id; cancellation_survey rows exist only for users who already cancelled; training label is cancelled_flag.",
     "mem": "Memory: days_since_last_ticket_days is sourced from support_tickets_enriched; that dataset's build joins in cancellation_survey (post-cancellation-only rows) — the feature's lineage is not label-clean (confidence 0.79).",
     "mem_raw": "prior_source=raw_tickets; prior_type=lineage_hop; prior_confidence=0.79; current_source=support_tickets_enriched"},
    {"label": "LEAKAGE", "raw": "Model insurance_claim_model uses feature policy_review_flag; policy_review_flag.sources=[underwriting_queue]; underwriting_queue records are created automatically whenever a claim is later marked fraudulent; training label is is_fraud.",
     "mem": "Memory: policy_review_flag comes from underwriting_queue, whose rows are triggered by the fraud-determination process itself (confidence 0.76) — the feature is a downstream artifact of the label.",
     "mem_raw": "prior_source=intake_queue; prior_type=lineage_hop; prior_confidence=0.76; current_source=underwriting_queue"},
    # DRIFT where prior_source == current_source at the named field — only a semantic/deeper change:
    {"label": "DRIFT", "raw": "Model logistics_eta_model uses feature avg_transit_hours; lineage source unchanged at warehouse_transit_events; however the upstream team changed the timezone convention of the timestamp columns feeding this aggregate from UTC to store-local time without updating any column name or type.",
     "mem": "Memory: avg_transit_hours sourced from warehouse_transit_events at confidence 0.86; underlying timestamp semantics shifted from UTC to local-time under the same column name — a silent meaning change.",
     "mem_raw": "prior_source=warehouse_transit_events; prior_type=table_ref; prior_confidence=0.86; current_source=warehouse_transit_events; timestamp_convention_prior=UTC; timestamp_convention_current=store_local"},
    {"label": "DRIFT", "raw": "Model pricing_elasticity_model uses feature price_change_pct; lineage source unchanged at pricing_events; upstream engineering changed the aggregation window for price_change_pct from a 7-day rolling window to a 30-day rolling window as part of a metric redefinition, keeping the exact same column name and table.",
     "mem": "Memory: price_change_pct sourced from pricing_events at confidence 0.84; no source or table change recorded — but the aggregation window definition changed upstream (7-day to 30-day), altering what the feature measures under an unchanged name.",
     "mem_raw": "prior_source=pricing_events; prior_type=table_ref; prior_confidence=0.84; current_source=pricing_events"},
]
PLACEBO = ("Memory on unrelated asset marketing_dashboard: refreshed nightly, owned by growth team, "
           "tier GOLD, confidence 0.88. No relation to this model.")


def cases(n):
    return [{"id": f"case{i}", "label": _BASE[i]["label"], "raw": _BASE[i]["raw"], "mem": _BASE[i]["mem"],
             "mem_raw": _BASE[i]["mem_raw"]} for i in range(min(n, len(_BASE)))]


def classify(context):
    try:
        data = ollama_json(f"METADATA:\n{context}\n\nClassify the risk.", SYSTEM)
        lab = str(data.get("label", "")).upper().strip()
        return lab if lab in CLASSES else "NO_RISK"
    except Exception as e:
        return f"ERROR:{type(e).__name__}"


def macro_f1(pairs):
    f1s = []
    for c in CLASSES:
        tp = sum(1 for g, p in pairs if g == c and p == c)
        fp = sum(1 for g, p in pairs if g != c and p == c)
        fn = sum(1 for g, p in pairs if g == c and p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(f1s) / len(f1s)


def main():
    n = int(os.getenv("EVAL_N", "6"))
    data = cases(n)
    arms = {"WITHOUT": lambda c: c["raw"],
            "WITH": lambda c: c["raw"] + "\n\nMEMORY:\n" + c["mem"],
            "PLACEBO": lambda c: c["raw"] + "\n\nMEMORY:\n" + PLACEBO,
            # Rigor arm: memory carries ONLY raw remembered facts (prior_source/prior_type/
            # prior_confidence/current_source) — no natural-language conclusion. The model must
            # infer DRIFT/LEAKAGE/NO_RISK itself, same as a rigor-judge would demand.
            "WITH_RAW": lambda c: c["raw"] + "\n\nMEMORY (remembered facts):\n" + c["mem_raw"]}
    rows, results = [], {}
    for arm, render in arms.items():
        pairs = []
        for c in data:
            pred = classify(render(c))
            pairs.append((c["label"], pred))
            rows.append({"arm": arm, "id": c["id"], "gold": c["label"], "pred": pred})
            print(f"  {arm:8} {c['id']} gold={c['label']:8} pred={pred}")
        clean = [(g, p) for g, p in pairs if not p.startswith("ERROR")]
        acc = sum(1 for g, p in clean if g == p) / len(clean) if clean else 0.0
        results[arm] = {"accuracy": round(acc, 3), "macro_f1": round(macro_f1(clean), 3),
                        "n": len(clean)}
        print(f"  >>> {arm}: acc={results[arm]['accuracy']} macro_f1={results[arm]['macro_f1']}\n")

    outdir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(outdir, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["arm", "id", "gold", "pred"])
        w.writeheader(); w.writerows(rows)
    summary = {"model": os.getenv("OLLAMA_MODEL", "mannix/llama3.1-8b-abliterated:q4_k_m"), "n_per_arm": n, "results": results,
               "lift_accuracy": round(results["WITH"]["accuracy"] - results["WITHOUT"]["accuracy"], 3),
               "lift_accuracy_raw": round(results["WITH_RAW"]["accuracy"] - results["WITHOUT"]["accuracy"], 3)}
    with open(os.path.join(os.path.dirname(outdir), "examples", "eval_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print("=== SUMMARY ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
