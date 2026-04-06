# Mini PC Setup Guide

**Host:** mini | **OS:** Ubuntu Server 24.04 | **User:** russellp
**Tailscale IP:** 100.120.154.111

---

## Tailscale Mesh

| Hostname | Tailscale IP | Role |
|---|---|---|
| mini | 100.120.154.111 | Headless automation box |
| russ-dell-laptop | 100.70.235.124 | Daily driver (Windows) |
| russells-macbook-pro | 100.119.83.49 | Dev machine (macOS) |
| origin-core (srv334254) | 100.89.175.30 | VPS — exit node, dev server (Ubuntu 24.04, Docker) |
| bossdev | 100.78.245.17 | Fedora — persistent services (Docker, Postgres, LiteLLM) |
| iphone172 | 100.120.114.62 | Phone |

---

## Standard Connection Procedure

### Quick Connect (daily use)

```bash
# 1. SSH into Mini from any mesh machine
ssh russellp@mini

# 2. Attach to your tmux session (or create one)
tmux attach -t work || tmux new -s work
```

### If You Need Unrestricted Internet (apt, downloads, etc.)

```bash
# On the Mini (inside tmux):
sudo tailscale set --exit-node=srv334254

# Do your installs...
sudo apt install <whatever>

# Turn it off when done:
sudo tailscale set --exit-node=
```

### If SSH Drops (network switch, laptop sleep, etc.)

```bash
# Just reconnect and reattach — tmux kept everything alive
ssh russellp@mini
tmux attach -t work
```

### Running Claude Code on Mini (over SSH)

Claude Code is a CLI tool — it runs great on headless Linux over SSH.
Install on the Mini using the native installer:

```bash
# With exit node ON for unrestricted internet:
sudo tailscale set --exit-node=srv334254
claude install
# Turn exit node off when done:
sudo tailscale set --exit-node=
```

Then from any SSH session into the Mini:

```bash
claude
```

### Connecting Cowork (Dell) to Mini via MCP

Cowork runs on the Dell (GUI). To let Cowork interact with services
running on the Mini (Postgres, Docker containers, etc.), you'd set up
MCP servers on the Mini and connect to them from the Dell over Tailscale.
This is a future setup — not needed yet.

---

## Bypass Corporate Firewall (Exit Node)

The corporate network blocks apt and some sites. Route traffic through the VPS to get unrestricted internet.

**Turn on** (run on whichever machine needs unrestricted internet):

```bash
sudo tailscale set --exit-node=srv334254
```

**Verify it's working:**

```bash
curl -s ifconfig.me
# Should return the VPS public IP, not the corporate IP
```

**Turn off** (go back to normal corporate routing):

```bash
sudo tailscale set --exit-node=
```

This works on any machine on the mesh — Mini, Dell, MBP, Fedora.

---

## tmux (Survive Network Switches)

Always work inside tmux on the Mini. If SSH drops when switching networks, just reconnect and reattach.

**Start a session:**

```bash
tmux new -s work
```

**Detach (leave running):** `Ctrl+B` then `D`

**Reattach after SSH reconnect:**

```bash
ssh russellp@mini
tmux attach -t work
```

**List sessions:**

```bash
tmux ls
```

---

## Installed Packages

Installed during setup (over hotspot):

- docker.io, docker-compose
- python3, python3-pip, python3-venv
- git, curl, wget
- net-tools, htop, tmux, ufw
- openssh-server (installed during OS setup)
- tailscale

---

## Network Notes

- **Corporate ethernet:** Internet works but firewall blocks apt, npm, Ubuntu repos, and random sites
- **Hotspot:** Unrestricted but requires phone tethering
- **Exit node via VPS:** Best option — unrestricted internet through Tailscale mesh, no phone needed
- **Tailscale:** Reconnects automatically when switching networks — SSH over Tailscale IPs is network-agnostic

---

## TODO

- [ ] Set static IP or DHCP reservation for Mini on corporate network
- [ ] Harden SSH — disable password auth after setting up key-based auth
- [x] Add Fedora workstation to Tailscale mesh (bossdev — 100.78.245.17)
- [ ] Install Claude Code on Mini (needs Node.js — use exit node for install)
- [ ] Set up MCP servers on Mini for Cowork (Dell) to connect to (future)
