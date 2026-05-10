# Remote access

`tmux-webui` ships with **no built-in tunnel**. By default the server binds to `127.0.0.1` and is only reachable from the local machine. Three patterns to expose it elsewhere — pick the one that matches your trust model.

## 1. LAN — same Wi-Fi / Ethernet

```sh
tmux-webui serve --lan
```

This:
- binds `0.0.0.0:9527`
- prints every non-loopback IPv4 (RFC1918 first)
- renders an ASCII QR code in the terminal — scan it from a phone

> ⚠️ There is no authentication. Anyone on the same LAN can drive your tmux. Use only on trusted networks (your home, your laptop's hotspot, etc.).

For Tailscale users: `tmux-webui` detects the `tailscale0` interface and surfaces its IP separately so you can pick "Tailnet only" without exposing to the LAN.

## 2. Tailscale (Tailnet-only access)

```sh
tmux-webui serve --host 100.x.y.z       # your tailscale IP
```

Only nodes on your tailnet can reach it. No LAN exposure, no public DNS, encrypted by WireGuard.

## 3. Cloudflare Tunnel (public URL with auth)

Best for "I want to drive my home server from anywhere".

```sh
brew install cloudflared
cloudflared tunnel --url http://127.0.0.1:9527
```

Cloudflare gives you a `*.trycloudflare.com` URL. For permanent setups, [authenticate cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) and put the tunnel behind Cloudflare Access (Google/GitHub SSO).

Run as a service:

```sh
cloudflared service install <token>
```

## 4. ngrok (public URL, simplest)

```sh
brew install ngrok
ngrok http 9527
```

Free tier rotates URLs; paid plans support reserved domains and IP allowlists.

## Hard rules

- **Never** bind `0.0.0.0` on a public-IP machine without a tunnel + auth in front.
- The WS layer trusts the network; treat it like an SSH session.
- For multi-user scenarios, use Cloudflare Access / Tailscale ACLs / nginx + basic-auth — `tmux-webui` does not implement RBAC.
