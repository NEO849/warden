# Warden Trust Console

A read-only, hosted window onto the live DataHub graph — the "it's running right now" proof.
It reads only the `warden.*` structured properties and the `warden-needs-review` tag that
`warden/agent.py` (a separate part of this project) already writes to GMS, and renders them as a
small dark dashboard: a live heartbeat ticker, a confidence timeseries per watched model (built
from `warden.provenance`), and a governance queue of models currently `NEEDS_REVIEW`.

This app does not run the agent. It has no mutation endpoints, no write path to GMS, and no
dependency on `ANTHROPIC_API_KEY` or any GMS token appearing in a browser response.

## Run it

```bash
source .venv/bin/activate   # project venv; pip install -r console/requirements.txt if fastapi/uvicorn aren't there yet
uvicorn console.app:app --host 127.0.0.1 --port 8808
```

Then open `http://127.0.0.1:8808/` locally, or tunnel it (see `../deploy/cloudflared-console.md`).

Env vars (all optional, sane defaults):

| var | default | meaning |
|---|---|---|
| `DATAHUB_GMS_URL` | `http://localhost:8090` | where the app reads `warden.*` from |
| `DATAHUB_GMS_TOKEN` | (unset) | optional GMS bearer token, used only server-side for the outbound read request — never echoed to the browser |
| `WARDEN_CONSOLE_PORT` | `8808` | port for the `python console/app.py` convenience runner (the recommended `uvicorn ... --port` flag overrides this) |
| `WARDEN_HEARTBEAT_AWAKE_WINDOW_S` | `3600` | how many seconds since the last observed wake before the heartbeat flips from "awake" to "quiet" |

## Security (non-negotiable)

- **Binds to `127.0.0.1` only.** Never pass `--host 0.0.0.0` — there is deliberately no env
  var that can push the bind address anywhere else; see the guard note in `console/app.py`.
- **Read-only.** Every route is a `GET`. No route builds or emits a
  `MetadataChangeProposal`, no route calls `graph.emit(...)`. The only writes to GMS this
  project makes at all happen in `warden/agent.py`, a different file this console never imports.
- **No secrets in the web tier.** `DATAHUB_GMS_TOKEN` (if set) is attached only to this
  server process's outbound requests to GMS; it is never present in any HTTP response this app
  sends. `ANTHROPIC_API_KEY` is not read here at all.
- **GMS (`:8090`) and the DataHub UI (`:9002`) are never proxied or exposed by this app.** It
  only republishes the small `warden.*` fields as JSON/HTML — nothing else on the graph is
  reachable through it.
- Going public (Cloudflare Tunnel) is a human step, done later, only for this app — see
  `../deploy/cloudflared-console.md`. `:8090`/`:9002` must never be tunneled.

## API

- `GET /` — the UI.
- `GET /api/models` — every `mlModel` Warden has observed: `{urn, confidence, verdict, governance_status, last_wake_ts}`.
- `GET /api/model/{urn}` — full snapshot for one URN: confidence, verdict, remembered-vs-current
  input sources, governance_status, the full `warden.provenance` chain, last-wake timestamp.
- `GET /api/heartbeat` — `{awake, last_event_seconds_ago, watching_count}`.
