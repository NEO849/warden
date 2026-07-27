#!/usr/bin/env python3
"""Render examples/eval_lift.svg from examples/eval_summary.json — no deps (pure SVG)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
summary = json.load(open(os.path.join(ROOT, "examples", "eval_summary.json")))
r = summary["results"]
arms = ["WITHOUT", "PLACEBO", "WITH"]
colors = {"WITHOUT": "#9aa4b2", "PLACEBO": "#e06c75", "WITH": "#4c9f70"}
W, H, pad, bw, gap = 520, 320, 60, 90, 40
maxv = 1.0


def bar(i, arm):
    acc = r[arm]["accuracy"]
    x = pad + i * (bw + gap)
    bh = (H - 2 * pad) * acc / maxv
    y = H - pad - bh
    return (f'<rect x="{x}" y="{y:.0f}" width="{bw}" height="{bh:.0f}" fill="{colors[arm]}" rx="4"/>'
            f'<text x="{x + bw/2:.0f}" y="{y - 8:.0f}" text-anchor="middle" font-size="18" '
            f'font-weight="bold" fill="#e6e6e6">{acc:.2f}</text>'
            f'<text x="{x + bw/2:.0f}" y="{H - pad + 22:.0f}" text-anchor="middle" font-size="14" '
            f'fill="#b8c0cc">{arm}</text>'
            f'<text x="{x + bw/2:.0f}" y="{H - pad + 40:.0f}" text-anchor="middle" font-size="11" '
            f'fill="#8a93a2">F1 {r[arm]["macro_f1"]:.2f}</text>')


bars = "".join(bar(i, a) for i, a in enumerate(arms))
lift = summary.get("lift_accuracy", 0)
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="sans-serif">
<rect width="{W}" height="{H}" fill="#1b1f27" rx="8"/>
<text x="{pad}" y="34" font-size="17" font-weight="bold" fill="#e6e6e6">ML-risk triage: memory-context ablation</text>
<text x="{pad}" y="54" font-size="12" fill="#8a93a2">Controlled ablation (not a prod benchmark). Key result: PLACEBO &lt; WITHOUT → lift is relevant memory, not tokens. N={summary.get("n_per_arm")}</text>
<line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="#3a414d"/>
{bars}
</svg>'''
open(os.path.join(ROOT, "examples", "eval_lift.svg"), "w").write(svg)
print("wrote examples/eval_lift.svg  (lift +%.2f, WITH %.2f vs WITHOUT %.2f, PLACEBO %.2f)"
      % (lift, r["WITH"]["accuracy"], r["WITHOUT"]["accuracy"], r["PLACEBO"]["accuracy"]))
