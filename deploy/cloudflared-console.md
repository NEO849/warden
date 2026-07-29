# Exposing the Trust Console via Cloudflare Tunnel

Human step only — Claude does not run this. The goal: make `console/app.py` reachable at
`warden.<yourdomain>`, while `:8090` (GMS) and `:9002` (DataHub UI) stay bound to loopback forever.

## 1. Start the console (if not already running as a service)

```bash
sudo cp deploy/warden-console.service /etc/systemd/system/warden-console.service
sudo systemctl daemon-reload
sudo systemctl enable --now warden-console
curl -s http://127.0.0.1:8808/api/heartbeat   # sanity check, still on loopback
```

## 2. Create the tunnel (one-time)

```bash
cloudflared tunnel login
cloudflared tunnel create warden-console
cloudflared tunnel route dns warden-console warden.<yourdomain>
```

## 3. Ingress config — **only** the console, nothing else

`~/.cloudflared/config.yml`:

```yaml
tunnel: warden-console
credentials-file: /root/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: warden.<yourdomain>
    service: http://127.0.0.1:8808
  - service: http_status:404   # catch-all: everything else 404s, nothing else is routable
```

Run it:

```bash
cloudflared tunnel run warden-console
# or as a service: cloudflared service install
```

## 4. Put Cloudflare Access in front of it (recommended, not optional for anything sensitive)

Even though the console is read-only and has no secrets in its responses, gate it with
Cloudflare Access (Zero Trust → Access → Applications → add `warden.<yourdomain>`, policy =
your email / allowed list) so it isn't a fully anonymous public page. This costs nothing at
this scale and takes two minutes in the dashboard.

## Non-negotiable

- **Never** add an ingress rule pointing at `127.0.0.1:8090` (GMS) or `127.0.0.1:9002`
  (DataHub UI). Only `127.0.0.1:8808` (this console) is ever fronted by the tunnel.
- **Never** change the console's own bind address to `0.0.0.0` "to make the tunnel work" — a
  Cloudflare Tunnel connects outbound from the box to Cloudflare's edge; it needs the local
  service on loopback, not a public bind. If `cloudflared` can't reach `127.0.0.1:8808`, the fix
  is the tunnel config, never the app's `--host` flag.
- Double-check with `ss -tlnp | grep 8808` after starting the service: the listening address
  must read `127.0.0.1:8808`, never `0.0.0.0:8808` or `*:8808`.
