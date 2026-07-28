# DataHub Agent Memory

Give an agent durable, per-asset memory on the DataHub graph: a resumable confidence belief that
survives between runs, plus a confidence-gated governance write (trusted vs. needs-review) instead
of a print statement nobody sees.

## What it does

1. Accumulates evidence about an asset into a log-odds confidence belief (`scripts/belief.py`) —
   Bayesian weight-of-evidence, bounded and cheap to persist
2. Persists that belief on the entity as `agent.*` structured properties, merge-safe against
   whatever else is already there (`scripts/agent_memory.py`)
3. Resumes the exact posterior on the next run instead of starting from a neutral prior
4. Applies exponential staleness decay when an asset hasn't been re-observed in a while
5. Gates a governance write by confidence AND evidence mass: `TRUSTED`, `NEEDS_REVIEW` (+ a
   visible `agent-needs-review` tag), or left alone — never touching the asset's own description
   or other owner-authored metadata
6. Reads its own writes back to verify they landed

## Usage

```
/datahub-agent-memory give this dataset a durable confidence score
/datahub-agent-memory flag orders_table for review if confidence drops below 0.7
/datahub-agent-memory persist what my agent just learned about this model
/datahub-agent-memory set up confidence-gated governance for these assets
```

Or run the scripts directly:

```bash
pip install acryl-datahub

python scripts/agent_memory.py define                                    # one-time setup
python scripts/agent_memory.py write --urn '<URN>' --source lineage --hops 0 --quality 0.9
python scripts/agent_memory.py read --urn '<URN>' --json
python scripts/agent_memory.py govern --urn '<URN>' --json

python scripts/belief.py                                                 # belief model, standalone
```

See `SKILL.md` for the full workflow and `references/` for the confidence model, the structured
property write-back pattern, and the governance policy.
