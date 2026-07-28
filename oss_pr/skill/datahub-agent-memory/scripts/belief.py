#!/usr/bin/env python3
"""
belief.py — Bayesian weight-of-evidence confidence model, in log-odds.

Confidence here is a POSTERIOR belief in a hypothesis H ("this agent's current understanding of
an asset is still correct"), not a vibe label. Bayes' theorem for a binary hypothesis is additive
in log-odds, so folding in one more piece of evidence is a single addition and the running belief
stays bounded and cheap to persist. `scripts/agent_memory.py` stores exactly this state
(`log_odds`, `mass`, `provenance`) as structured properties on a DataHub entity, so the next run
resumes the same posterior instead of starting over from a neutral prior.

Pure stdlib, no dependencies. The AUTHORITY weights and thresholds below are chosen priors — tune
them for your domain. The MECHANISM (log-odds accumulation, Cromwell's-rule clamp, evidence-mass
gating before high-confidence actions, exponential staleness decay) is the part worth reusing
as-is.

Usage:
    python belief.py            # run the worked example as narration
    python belief.py --json     # same run, emit the step-by-step trace as JSON

Examples:
    $ python belief.py
    0. prior                                     confidence=0.500
    1. indirect corroborating lineage (2 hops)    confidence=0.601
    ...

    $ python belief.py --json | python -m json.tool
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field

# --- parameters: sane defaults, documented as chosen priors, not learned ---------------------
# provenance proximity: each lineage/derivation hop halves an evidence item's weight
GAMMA = 0.5
# a_e per evidence source: how much one unit of evidence from this source is worth
AUTHORITY = {
    "lineage": 1.8,
    "schema": 1.8,
    # a measured statistical signal (e.g. PSI/KS drift) corroborating, not identical to, a
    # structural delta — weighted below lineage/schema for that reason
    "drift_stat": 1.5,
    "usage": 0.7,
    "human": 4.0,  # human confirmation counts most and is never provenance-discounted
}
# Cromwell's rule: never let confidence reach absolute certainty
C_MIN, C_MAX = 0.02, 0.98
# per-update weight cap (anti-flapping: no single event can swing belief too far)
DW_MAX = 4.0
# evidence mass needed before a high-confidence (>0.85) auto-write is allowed
N_MIN = 3.0
# staleness half-life in days (tune 7..180 by how fast your domain changes)
T_HALF_DAYS = 30.0
# below this, after a contradiction, governance should flag for human review
TAU_PROPOSAL = 0.7


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class Belief:
    """A resumable posterior belief, expressed in log-odds (`log_odds`), plus the accumulated
    evidence mass and a provenance trail of every update applied. Round-trips cleanly to/from
    structured properties: `log_odds` and `mass` are the two numbers that let a later run pick up
    exactly where this one left off, instead of resetting to a neutral prior every time."""

    log_odds: float = 0.0  # l, neutral prior l=0 -> confidence=0.5
    mass: float = 0.0  # N, effective evidence mass accumulated so far
    provenance: list = field(default_factory=list)

    @property
    def confidence(self) -> float:
        return max(C_MIN, min(C_MAX, _sigmoid(self.log_odds)))

    @property
    def actionable_high(self) -> bool:
        """High enough, and backed by enough independent evidence, to act on without a human."""
        return self.confidence > 0.85 and self.mass >= N_MIN

    def decay(self, dt_days: float, t_half: float = T_HALF_DAYS) -> None:
        """Apply staleness lazily — call this when the asset is revisited, not on a timer. Pulls
        both the belief and its accumulated mass back toward the neutral prior as time passes
        without new confirming evidence."""
        factor = math.exp(-math.log(2) / t_half * dt_days)
        self.log_odds *= factor
        self.mass *= factor

    def update(
        self,
        source: str,
        corroborates: bool,
        hops: int,
        quality: float,
        event_id: str | None = None,
    ) -> float:
        """Fold one piece of evidence into the belief. Returns the applied weight `w`, in nats.

        source        -- which evidence channel this came from (a key in AUTHORITY, or any other
                          string — unknown sources default to weight 1.0)
        corroborates  -- True if this evidence supports the current belief, False if it contradicts it
        hops          -- provenance distance (e.g. lineage hops). Each hop halves the weight via
                          GAMMA, except "human" evidence, which is never discounted (hops ignored)
        quality       -- 0..1 confidence in this particular piece of evidence itself
        event_id      -- optional identifier recorded in the provenance trail, for audit/replay
        """
        rho = 1.0 if source == "human" else GAMMA**hops
        sign = 1.0 if corroborates else -1.0
        w = sign * AUTHORITY.get(source, 1.0) * rho * quality
        w = max(-DW_MAX, min(DW_MAX, w))  # clamp: anti-flap
        self.log_odds += w
        self.mass += rho * quality
        self.provenance.append(
            {
                "source": source,
                "event": event_id,
                "hops": hops,
                "delta": round(w, 3),
                "c_after": round(self.confidence, 3),
            }
        )
        return w

    def needs_proposal(self) -> bool:
        """True once a contradiction has pulled confidence below the review threshold."""
        return self.confidence < TAU_PROPOSAL

    def to_dict(self) -> dict:
        """Serializable snapshot — the exact fields `agent_memory.py` persists as structured
        properties (`agent.confidence` is derived, not stored directly; `agent.logodds` /
        `agent.mass` / `agent.provenance` are)."""
        return {
            "log_odds": round(self.log_odds, 4),
            "mass": round(self.mass, 4),
            "confidence": round(self.confidence, 3),
            "provenance": self.provenance,
        }


def _worked_example() -> list[dict]:
    """Runs the full arc once and returns a step-by-step trace: neutral prior -> two corroborating
    lineage observations -> 30 days of staleness decay -> a contradicting schema change -> a human
    override. Shared by the narration and --json output modes below, so both report the exact
    same run."""
    steps = []
    b = Belief()
    steps.append({"step": "0. prior", "confidence": round(b.confidence, 3)})

    b.update("lineage", corroborates=True, hops=2, quality=0.9, event_id="e1")
    steps.append(
        {
            "step": "1. indirect corroborating lineage (2 hops)",
            "confidence": round(b.confidence, 3),
        }
    )

    b.update("lineage", corroborates=True, hops=0, quality=1.0, event_id="e2")
    steps.append(
        {
            "step": "2. new direct corroborating lineage (0 hops)",
            "confidence": round(b.confidence, 3),
        }
    )

    b.decay(30.0)
    steps.append(
        {
            "step": "3. after 30 days of staleness decay",
            "confidence": round(b.confidence, 3),
        }
    )

    b.update("schema", corroborates=False, hops=0, quality=1.0, event_id="e3")
    steps.append(
        {
            "step": "4. contradicting schema change",
            "confidence": round(b.confidence, 3),
            "needs_proposal": b.needs_proposal(),
        }
    )

    b.update("human", corroborates=True, hops=0, quality=1.0, event_id="e4")
    steps.append(
        {
            "step": "5. human confirms",
            "confidence": round(b.confidence, 3),
            "actionable_high": b.actionable_high,
        }
    )

    steps.append({"final": b.to_dict()})
    return steps


def _print_narration(steps: list[dict]) -> None:
    for s in steps:
        if "step" not in s:
            final = s["final"]
            print(f"final state: log_odds={final['log_odds']}  mass={final['mass']}")
            continue
        extras = {k: v for k, v in s.items() if k not in ("step", "confidence")}
        suffix = "".join(f"  {k}={v}" for k, v in extras.items())
        print(f"{s['step']:<48} confidence={s['confidence']:.3f}{suffix}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the belief model's worked example (prior -> evidence -> decay -> "
        "contradiction -> human override)."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the step-by-step trace as JSON instead of narration",
    )
    args = parser.parse_args()

    steps = _worked_example()
    if args.json:
        print(json.dumps(steps, indent=2))
    else:
        _print_narration(steps)


if __name__ == "__main__":
    main()
