# Reproducing Warden

Warden is a proof of concept: a compounding-memory governance agent that reads/writes DataHub's
own metadata graph (structured properties + tags), not a hosted service. Reproducing it means
running it against a DataHub instance you control — either the local quickstart or your own GMS.

## Prerequisites

- Python 3.11+
- A reachable DataHub GMS. Easiest path: the official quickstart —
  ```
  pip install acryl-datahub
  datahub docker quickstart
  ```
  (needs Docker, ~8 GB free RAM; see `DAY1_RUNBOOK.md` in this repo for the full bring-up +
  troubleshooting notes we hit standing this up). GMS defaults to `http://localhost:8090`.
- Optional, for the reflection step's natural-language synthesis: a local
  [Ollama](https://ollama.com) instance. Without it, `WardenAgent.reflect()` falls back to a
  deterministic stub synthesis — no external API key is required for anything in this repo.

## Install

```
pip install .
```

This installs the `warden` package and a `warden` console script (entry point `warden.cli:main`).
Dependencies are pinned exactly (`pyproject.toml`) to what this project was built and demoed
against — `acryl-datahub[datahub-rest,datahub-kafka]`, `acryl-datahub-actions`, `python-dotenv`,
`mcp`, `numpy`.

Verify:
```
warden --help
```

## Point it at your GMS

```
export DATAHUB_GMS_URL=http://localhost:8090   # default; override for a remote instance
export DATAHUB_GMS_TOKEN=...                    # optional, if your GMS requires auth
```

(Or drop both into a `.env` file in the project root — every entrypoint in this repo calls
`load_dotenv()` first.)

## Provision the warden.\* structured properties

Warden persists its belief/governance state as `warden.*` structured properties on DataHub
entities (`warden.summary`, `warden.confidence`, `warden.governance_status`, `warden.reflection`,
…). These are custom property **definitions** that must exist on GMS before Warden can write
values for them — they are not part of stock DataHub.

```
warden provision
```

This is idempotent: it checks each `warden.*` definition against GMS and only creates what's
missing. Run it as many times as you like — a property that already exists is reported as
skipped, never re-created or duplicated. This is what makes Warden reproducible against a fresh
DataHub instance instead of implicitly depending on properties one particular GMS happens to
already have registered.

## Run the demo

```
make demo
```

Runs `warden provision` followed by `run_live_chain_demo.py` — the deterministic, full
observe → detect → govern → reflect cycle against your live GMS (seeds a small lineage graph,
silently re-points an upstream source, and shows Warden catching the drift and opening a
governance review). See `README.md` / `DEMO_STORYBOARD.md` for what the demo narrates and why.

`make install` is the plain `pip install .` above, provided as a Makefile target for symmetry.

## Honesty notes

- This is a hackathon proof of concept, not a packaged product: no PyPI publish, no CI-built
  wheel, no version-compatibility matrix beyond what's pinned in `pyproject.toml`.
- The pinned `acryl-datahub`/`acryl-datahub-actions` versions are what this project was actually
  built and demoed against; a newer/older DataHub CLI or GMS may still work but hasn't been
  verified here.
- `warden provision` only defines the property *schemas*. It does not seed any lineage graph or
  demo data — `run_live_chain_demo.py` (via `make demo`) does that.
- Everything above was verified with definition-writes only against a live local GMS — the demo
  chain itself is exercised separately (see `DEMO_STORYBOARD.md`), not re-run as part of this
  reproducibility check.
