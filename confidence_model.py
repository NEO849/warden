#!/usr/bin/env python3
"""
Mnemo confidence model — Bayesian weight-of-evidence in log-odds.

Confidence is a POSTERIOR belief in H = "this memory record is correct", not a vibe label.
Bayes' theorem for a binary hypothesis is additive in log-odds, so evidence accumulation is
one addition and stays bounded. This is the principled-memory depth signal most entries omit.

Spec: scratchpad/confidence_model.md (mathematik-krypto-professor).
Pure stdlib. Defaults are chosen priors, tunable — the MECHANISM is the principled part.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# --- parameters (sane defaults; document on camera that authorities are priors, not learned) ---
GAMMA = 0.5                       # provenance proximity: each lineage hop halves evidence weight
AUTHORITY = {                     # a_e per evidence source
    "lineage": 1.8,
    "schema": 1.8,
    "usage": 0.7,
    "human": 4.0,                 # human confirmation counts most...
}
C_MIN, C_MAX = 0.02, 0.98         # Cromwell's rule — never absolute certainty
DW_MAX = 4.0                      # per-update weight cap (anti-flapping)
N_MIN = 3.0                       # evidence mass needed before a >0.85 auto-write is allowed
T_HALF_DAYS = 30.0               # staleness half-life (clamp 7..180 by change frequency)
TAU_PROPOSAL = 0.7                # below this after a contradiction → open a DataHub Proposal
PER_SOURCE_WCAP = 2.0             # cap cumulative weight from any single source (anti-double-count)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class Belief:
    log_odds: float = 0.0         # ℓ, neutral prior = 0 → c = 0.5
    mass: float = 0.0             # N, effective evidence mass
    provenance: list = field(default_factory=list)

    @property
    def confidence(self) -> float:
        return max(C_MIN, min(C_MAX, _sigmoid(self.log_odds)))

    @property
    def actionable_high(self) -> bool:
        """>0.85 auto-write allowed only once enough independent evidence accrued."""
        return self.confidence > 0.85 and self.mass >= N_MIN

    def decay(self, dt_days: float, t_half: float = T_HALF_DAYS) -> None:
        """Lazy staleness applied per revisit: pulls belief toward 0.5 (unsure)."""
        factor = math.exp(-math.log(2) / t_half * dt_days)
        self.log_odds *= factor
        self.mass *= factor

    def update(self, source: str, corroborates: bool, hops: int, quality: float,
               event_id: str | None = None) -> float:
        """Add one piece of evidence. Returns the applied weight w (nats)."""
        rho = 1.0 if source == "human" else GAMMA ** hops   # human = undiscounted (d=0)
        sign = 1.0 if corroborates else -1.0
        w = sign * AUTHORITY.get(source, 1.0) * rho * quality
        w = max(-DW_MAX, min(DW_MAX, w))                     # clamp (anti-flap)
        self.log_odds += w
        self.mass += rho * quality
        self.provenance.append(
            {"source": source, "event": event_id, "hops": hops,
             "delta": round(w, 3), "c_after": round(self.confidence, 3)}
        )
        return w

    def needs_proposal(self) -> bool:
        return self.confidence < TAU_PROPOSAL


if __name__ == "__main__":
    # Worked example — reproduces the demo hero shot 0.60 → 0.90 and the full arc.
    b = Belief()
    print(f"0. prior                         c={b.confidence:.3f}")
    b.update("lineage", corroborates=True, hops=2, quality=0.9, event_id="e1")
    print(f"1. indirect corroborating lineage c={b.confidence:.3f}   (→ cold-open state)")
    b.update("lineage", corroborates=True, hops=0, quality=1.0, event_id="e2")
    print(f"2. NEW direct corroborating lineage c={b.confidence:.3f} (→ second-run hero: 0.6→0.9)")
    b.decay(30.0)
    print(f"3. 30d staleness                  c={b.confidence:.3f}")
    b.update("schema", corroborates=False, hops=0, quality=1.0, event_id="e3")
    print(f"4. contradicting schema change    c={b.confidence:.3f}   needs_proposal={b.needs_proposal()}")
    b.update("human", corroborates=True, hops=0, quality=1.0, event_id="e4")
    print(f"5. human approves Proposal        c={b.confidence:.3f}   actionable_high={b.actionable_high}")
