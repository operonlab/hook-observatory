# Komodo Deployment — Workshop Fleet

Multi-machine container management: Core (Mac hub) + Periphery (Windows GPU worker).

## Architecture

```
  Mac (mac-hub)                        Windows (win-gpu)
  ┌────────────────────┐               ┌────────────────────┐
  │  Komodo Core:9120  │──Tailscale──▶ │ Periphery:8120     │
  │  MongoDB:27018     │               │ Docker containers   │
  │  Nginx reverse     │               │ RTX 3090 workloads  │
  │  proxy (optional)  │               │                     │
  └────────────────────┘               └────────────────────┘
```

- Core: web dashboard + API, manages all registered Periphery agents
- Periphery: lightweight agent, reports stats, executes container operations
- Communication: Tailscale VPN (no public internet exposure)

## Prerequisites

- Docker + Docker Compose on both machines
- Tailscale installed and connected on both machines
- Know your Tailscale IPs: `tailscale ip -4`

## 1. Deploy Core (Mac)

```bash
cd infra/komodo

# Create .env from template
cp .env.example .env
# Edit .env — set KOMODO_PASSKEY, KOMODO_ADMIN_USER, KOMODO_ADMIN_PASS, MAC_TAILSCALE_IP

# Start Core + MongoDB
docker compose up -d

# Verify
docker compose logs -f komodo-core
# Should see "listening on 0.0.0.0:9120"
```

Access the dashboard at `http://127.0.0.1:9120` (local) or `http://<MAC_TAILSCALE_IP>:9120` (from other machines).

### Optional: Nginx Reverse Proxy

Add to `/opt/homebrew/etc/nginx/conf.d/workshop-apps.inc`:

```nginx
location /komodo/ {
    proxy_pass http://127.0.0.1:9120/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

## 2. Deploy Periphery (Windows)

Copy `infra/komodo/periphery/` to the Windows machine:

```bash
# From Mac — scp to Windows
scp -r infra/komodo/periphery/ win-gpu:~/komodo-periphery/
```

On Windows (WSL2 or Docker Desktop):

```bash
cd ~/komodo-periphery

# Create .env
cat > .env << 'EOF'
KOMODO_PASSKEY=<same-passkey-as-core>
EOF

# Start Periphery agent
docker compose up -d

# Verify
docker compose logs -f komodo-periphery
```

## 3. Register Periphery in Core

1. Open Core dashboard: `http://<MAC_TAILSCALE_IP>:9120`
2. Log in with admin credentials
3. Go to **Servers** > **Add Server**
4. Enter:
   - Name: `win-gpu`
   - Address: `http://<WIN_TAILSCALE_IP>:8120`
5. Core will connect to Periphery using the shared passkey
6. Verify: server status should show green with CPU/RAM/GPU stats

## 4. Deploy Stacks

Pre-configured stack definitions are in `infra/komodo/stacks/`:

- `paper.toml` — Paper service on win-gpu
- `remote-services.toml` — Remote service bundle on win-gpu

Import these via Core dashboard > **Stacks** > **Import**.

## Security Notes

- Core binds to `127.0.0.1:9120` — not exposed to network directly
- Periphery binds to `0.0.0.0:8120` — accessible only via Tailscale (no public route)
- Passkey is the shared secret — use a strong random string
- MongoDB binds to `127.0.0.1:27018` — local access only
- `.env` files are gitignored — never commit credentials

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Core can't reach Periphery | Check Tailscale: `tailscale ping win-gpu` |
| Periphery won't start | Ensure Docker socket is accessible: `ls -la /var/run/docker.sock` |
| Auth failure | Verify KOMODO_PASSKEY matches on both sides |
| MongoDB connection error | Check `docker compose logs komodo-mongo` for startup issues |
| Stats not reporting | Periphery needs Docker socket access for container stats |

## File Structure

```
infra/komodo/
  docker-compose.yml     # Core + MongoDB (Mac)
  core.config.toml       # Core config reference
  .env.example           # Template for credentials
  .env                   # Actual credentials (gitignored)
  stacks/                # Stack definitions for Komodo
    paper.toml
    remote-services.toml
  periphery/
    docker-compose.yml   # Periphery agent (Windows)
    config.toml          # Periphery config reference
```
