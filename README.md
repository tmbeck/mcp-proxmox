# MCP Proxmox Server

Advanced Proxmox Model Context Protocol (MCP) server in Python exposing rich Proxmox utilities for discovery, lifecycle, networking, snapshots/backups, metrics, pools/permissions, and orchestration.

- Guide reference: [MCP Quickstart (Python)](https://modelcontextprotocol.io/quickstart/server#python)
- Structure mirrors: [`bsahane/mcp-ansible`](https://github.com/bsahane/mcp-ansible/tree/main)
- Architecture overview: `docs/ARCHITECTURE.md`
- Shared deployment guide: `docs/CONTROL_PLANE_DEPLOYMENT.md`
- Disposable VM workflow recipe: `docs/DISPOSABLE_VM_TEST_RECIPE.md`

## Quick start

```bash
git clone https://github.com/tmbeck/mcp-proxmox.git
cd mcp-proxmox

uv sync --dev
```

Run commands in the project environment with `uv run ...` (no manual activation required).

Install modes:

- `uv tool install .` installs the lean core MCP server surface.
- `uv tool install '.[control-plane,observability,automation,security]'` lets you run broader shared/team modes when you actually need them.
- `uv tool install '.[control-plane]'` adds the shared API/integration feature set.
- `uv tool install '.[observability]'` adds monitoring/logging helpers.
- `uv tool install '.[automation]'` adds IaC/orchestration helpers.
- `uv tool install '.[security]'` adds MFA/certificate/secret-store helpers.
- `uv tool install '.[ai]'` adds AI/optimization helpers.
- `uv tool install '.[full]'` installs every optional feature group.
- If you select a non-core profile without its matching extra installed, the server now fails fast with a clear install hint.

For a local tool-style install, you can also use:

```bash
uv tool install .
```

## Configuration Strategy

There are two good ways to configure the server:

1. Repo-local development
- keep a `.env` file in the repository root
- use `uv run ...` from that repo

2. Installed local MCP tool use (`uv tool install ...`)
- do **not** rely on an implicit repo `.env`
- instead, either:
  - pass the Proxmox environment variables directly from the MCP client config, or
  - point the server at a dedicated env file with `PROXMOX_ENV_FILE=/absolute/path/to/proxmox.env`, or
  - pass `--env-file /absolute/path/to/proxmox.env`

For installed tools, the most reliable default is a dedicated env file outside the repo, for example:

```bash
mkdir -p ~/.config/proxmox-mcp
cp .env.example ~/.config/proxmox-mcp/proxmox.env
chmod 600 ~/.config/proxmox-mcp/proxmox.env
```

Then launch the server with either:

```bash
proxmox-mcp --env-file "$HOME/.config/proxmox-mcp/proxmox.env"
```

or by setting:

```bash
PROXMOX_ENV_FILE="$HOME/.config/proxmox-mcp/proxmox.env"
```

If neither is set, the server searches for `.env` from the current working directory upward.

## Env File Contents

- Copy `.env.example` to `.env` and edit values:

```bash
cp .env.example .env
```

`.env` keys:

```bash
PROXMOX_API_URL="https://proxmox.example.com:8006"
PROXMOX_TOKEN_ID="root@pam!mcp-proxmox"
PROXMOX_TOKEN_SECRET="<secret>"
PROXMOX_VERIFY="true"
PROXMOX_DEFAULT_NODE="pve"
PROXMOX_DEFAULT_STORAGE="local-lvm"
PROXMOX_DEFAULT_BRIDGE="vmbr0"
PROXMOX_DEFAULT_LXC_PASSWORD=""
PROXMOX_MCP_PROFILES="core"
```

Notes:
- Use an API token with appropriate ACLs; for discovery, `PVEAuditor` at `/` is sufficient; for lifecycle, grant narrower roles (e.g., `PVEVMAdmin`) on a pool.
- Using `.env` avoids zsh history expansion issues with `!` in token IDs.
- For installed MCP client workflows, prefer `PROXMOX_ENV_FILE` or explicit client `env` blocks over relying on implicit `.env` discovery.
- Outbound URL policy is strict by default: only private/local hosts are allowed unless explicitly listed in `PROXMOX_ALLOWED_URLS`.
- Third-party integrations are disabled by default (`PROXMOX_ENABLE_EXTERNAL_INTEGRATIONS=false`).
- The optional API gateway is local-first by default (`PROXMOX_API_GATEWAY_HOST=127.0.0.1`), keeps `/health` unauthenticated, and requires `JWT_SECRET` for management routes.
- To share the API gateway from a Docker/container deployment, explicitly set `PROXMOX_API_GATEWAY_ALLOW_REMOTE=true`, choose a non-local host such as `0.0.0.0`, and set explicit `PROXMOX_API_GATEWAY_CORS_ORIGINS` values.
- `PROXMOX_DEFAULT_LXC_PASSWORD` must be set before using `proxmox-create-lxc`; the server no longer falls back to a predictable default password.
- Generated monitoring/logging stacks are now local-first by default (`PROXMOX_MONITORING_BIND_HOST=127.0.0.1`) and expect operator-supplied secrets via `PROXMOX_GRAFANA_ADMIN_PASSWORD` and `PROXMOX_ELASTIC_PASSWORD`.
- `PROXMOX_MCP_PROFILES` can preselect optional tool surfaces for a deployment; the CLI `--profile` flag overrides it.
- `PROXMOX_MCP_STATE_DIR` can relocate local state/config artifacts if you do not want them under `~/.proxmox_mcp`.

## Run the MCP server (stdio)

Preferred (module form):

```bash
uv run python -m proxmox_mcp.server
```

Or installed console script:

```bash
uv run proxmox-mcp
```

Profiles:

- Default behavior is `core`, which includes direct Proxmox management and guest provisioning.
- Optional profiles layer on broader control-plane features without changing the default surface.

```bash
# Show available profiles
uv run proxmox-mcp --list-profiles

# Run the default core profile (same as omitting --profile)
uv run proxmox-mcp --profile core

# Add shared control-plane features such as webhooks and the optional API gateway
uv run proxmox-mcp --profile control-plane

# Compose multiple profiles
uv run proxmox-mcp --profile observability --profile automation

# Enable every optional profile
uv run proxmox-mcp --profile full

# Optional convenience wrapper for the broader shared profile set
uv run proxmox-mcp-control-plane
```

## Local MCP Client Setup

For local client tools, the easiest stable pattern is:

1. install the CLI once with `uv tool install .`
2. create `~/.config/proxmox-mcp/proxmox.env`
3. point the MCP client at `proxmox-mcp --profile core`
4. pass `PROXMOX_ENV_FILE` in the client's environment block

### Opencode

Example `opencode.json` snippet:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "proxmox-mcp": {
      "type": "local",
      "command": ["proxmox-mcp", "--profile", "core"],
      "enabled": true,
      "environment": {
        "PROXMOX_ENV_FILE": "/Users/you/.config/proxmox-mcp/proxmox.env"
      }
    }
  }
}
```

### Codex

Example `~/.codex/config.toml` snippet:

```toml
[mcp_servers.proxmox-mcp]
command = "proxmox-mcp"
args = ["--profile", "core"]

[mcp_servers.proxmox-mcp.env]
PROXMOX_ENV_FILE = "/Users/you/.config/proxmox-mcp/proxmox.env"
```

If you prefer not to use an env file, Codex can also pass the individual Proxmox variables directly with `env` or forward them from your shell with `env_vars`.

### Claude Code

Project-local `.mcp.json` example:

```json
{
  "mcpServers": {
    "proxmox-mcp": {
      "type": "stdio",
      "command": "proxmox-mcp",
      "args": ["--profile", "core"],
      "env": {
        "PROXMOX_ENV_FILE": "/Users/you/.config/proxmox-mcp/proxmox.env"
      }
    }
  }
}
```

Equivalent CLI form:

```bash
claude mcp add --transport stdio --scope project --env PROXMOX_ENV_FILE="$HOME/.config/proxmox-mcp/proxmox.env" proxmox-mcp -- proxmox-mcp --profile core
```

### Why this differs from repo-local `.env`

When you run `uv run ...` from the repository, a repo-root `.env` is a natural fit.

When you run an installed tool from an MCP client, the process is no longer tied to the repo checkout, so configuration should be passed explicitly:

- use a dedicated env file via `PROXMOX_ENV_FILE`, or
- use the client's own environment block

That makes the setup more predictable for Opencode, Codex, Claude Code, and similar local MCP clients.

For a deeper explanation of the core-vs-control-plane split and the next package/service boundary work, see `docs/ARCHITECTURE.md`.
For layered shared deployment guidance, see `docs/CONTROL_PLANE_DEPLOYMENT.md`.

If your main goal is direct VM/LXC management, template cloning, provisioning, snapshots/backups, and related guest operations, stay on the default `core` profile.
For product validation workflows, prefer external SSH for in-guest install/test steps; see `docs/DISPOSABLE_VM_TEST_RECIPE.md`.
For clone-based SSH access, the core server already supports injecting an externally generated public key with `proxmox-cloudinit-set` before first boot.

Profile guide:

- `core`: default; direct Proxmox operations, provisioning, and guest lifecycle
- `control-plane`: optional API gateway, webhooks, and external integrations
- `observability`: monitoring, logging, and performance-analysis helpers
- `automation`: Docker Swarm, OpenShift, IaC/GitOps, and advanced storage/network automation
- `security`: MFA, certificates, and secret-store helpers
- `ai`: AI/optimization helpers

## Compatibility

- Python: automated CI currently runs on Python `3.11`.
- Client library: the project targets `proxmoxer>=2.0.1`.
- Proxmox VE: live validation has been performed against Proxmox VE `9.1.6`.
- Patch releases within `9.1.x` are expected to be compatible; other major/minor releases are treated as unverified.
- The MCP server prints a stderr warning when a connected cluster reports a Proxmox VE version outside the tested `9.1.x` series.
- Current automated coverage: code-level tests, profile composition, security regressions, and packaging/entrypoint behavior.
- Not yet covered by CI: live integration tests against specific Proxmox VE versions or cluster topologies.

## Configure in Cursor

Edit `~/.cursor/mcp.json` (portable example):

```json
{
    "mcpServers": {
      "proxmox-mcp": {
        "command": "uv",
        "args": ["run", "python", "-m", "proxmox_mcp.server"]
      }
    }
}
```

## Configure in Claude for Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
    "mcpServers": {
      "proxmox-mcp": {
        "command": "uv",
        "args": ["run", "python", "-m", "proxmox_mcp.server"]
      }
    }
}
```

## Tools reference

All tools are available via MCP. Most write operations support `dry_run`, `wait`, `timeout`, and `poll_interval`. Tool descriptions call out operations that can permanently delete data.

Format below per tool:
- Description
- Example question → Possible answer (shape)

### Core discovery
- `proxmox-list-nodes`
  - List cluster nodes (name, status, CPU/RAM/disk summary)
  - Example: "List cluster nodes"
  - Answer: `[ { "node": "pve", "status": "online", ... } ]`
- `proxmox-node-status`
  - Detailed node health (load, uptime, versions)
  - Example: `{ "node": "pve" }`
  - Answer: `{ "kversion": "...", "uptime": 123456, ... }`
- `proxmox-list-vms`
  - List VMs (filter by node, status, name substring)
  - Example: `{ "node": "pve", "status": "running" }`
  - Answer: `[ { "vmid": 100, "name": "web01", ... } ]`
- `proxmox-vm-info`
  - Get VM details by `vmid` or `name` (+optional node), includes config
  - Example: `{ "name": "web01" }`
  - Answer: `{ "selector": {...}, "config": {...} }`
- `proxmox-list-lxc`
  - List LXC containers (filterable)
  - Example: `{ "node": "pve" }`
  - Answer: `[ { "vmid": 50001, "name": "ct01", ... } ]`
- `proxmox-lxc-info`
  - Get LXC details by `vmid` or `name` (+optional node)
  - Example: `{ "vmid": 50001 }`
  - Answer: `{ "selector": {...}, "config": {...} }`
- `proxmox-list-storage`
  - List storages (types, free/used)
  - Example: `{}`
  - Answer: `[ { "storage": "local-lvm", "type": "lvmthin", ... } ]`
- `proxmox-storage-content`
  - List storage content (ISOs, templates, images)
  - Example: `{ "node": "pve", "storage": "local" }`
  - Answer: `[ { "volid": "local:iso/foo.iso", ... } ]`
- `proxmox-list-bridges`
  - List node bridges (vmbr...)
  - Example: `{ "node": "pve" }`
  - Answer: `[ { "iface": "vmbr0", ... } ]`
- `proxmox-list-tasks`
  - Recent tasks (filter by node, user)
  - Example: `{ "node": "pve", "limit": 20 }`
  - Answer: `[ { "upid": "UPID:...", "status": "OK" }, ... ]`
- `proxmox-task-status`
  - Check a task status
  - Example: `{ "upid": "UPID:..." }`
  - Answer: `{ "status": "stopped", "exitstatus": "OK" }`

### VM lifecycle
- `proxmox-clone-vm`
  - Clone template VM to new VMID/name (supports target node, storage)
  - Example: `{ "source_vmid": 101, "new_vmid": 50009, "name": "web01", "storage": "local-lvm", "wait": true }`
  - Answer: `{ "upid": "UPID:...", "status": {...} }`
- `proxmox-create-vm`
  - Create new VM from ISO/template (minimal config)
  - Example: `{ "node": "pve", "vmid": 200, "name": "web02", "iso": "debian.iso" }`
  - Answer: `{ "upid": "UPID:..." }`
- `proxmox-delete-vm`
  - Permanently delete a VM; `purge` also removes owned resources
  - Example: `{ "name": "web01", "purge": true }`
  - Answer: `{ "upid": "UPID:..." }`
- `proxmox-start-vm` / `proxmox-stop-vm` / `proxmox-reboot-vm` / `proxmox-shutdown-vm`
  - Manage power state; `shutdown` requests a clean guest shutdown, while `stop` is immediate and `overrule_shutdown=true` cancels an in-progress shutdown task first (`hard` remains as a deprecated alias)
  - Example: `{ "name": "web01", "wait": true }`
  - Answer: `{ "upid": "UPID:...", "status": {...} }`
- `proxmox-migrate-vm`
  - Live/offline migrate to another node
  - Example: `{ "name": "web01", "target_node": "pve2", "live": true }`
  - Answer: `{ "upid": "UPID:..." }`
- `proxmox-resize-vm-disk`
  - Grow disk (GB) on target disk (e.g., scsi0)
  - Example: `{ "name": "web01", "disk": "scsi0", "grow_gb": 10, "wait": true }`
  - Answer: `{ "upid": "UPID:...", "status": {...} }`
- `proxmox-vm-disk-list` / `proxmox-vm-disk-add` / `proxmox-vm-disk-remove`
  - Inspect attached and unused disks, add a new disk or volume, and remove a disk in explicit `detach` or `delete-volume` mode; `delete-volume` permanently deletes the backing volume
  - Example: `{ "name": "web01", "size_gb": 100, "storage": "local-lvm" }`
  - Answer: `{ "upid": "UPID:...", "device": "scsi1", ... }`
  - Removal example: `{ "name": "web01", "device": "scsi1", "mode": "detach", "wait": true }`
  - Destructive removal example: `{ "name": "web01", "device": "scsi1", "mode": "delete-volume", "wait": true }`
- `proxmox-configure-vm`
  - Set whitelisted params (cores, memory, balloon, netX, agent, etc.)
  - Example: `{ "name": "web01", "params": { "memory": 4096, "cores": 4 } }`
  - Answer: `{ "upid": "UPID:..." }` or `{ "result": null }`

### LXC lifecycle
- `proxmox-create-lxc`
  - Create container from template (CPU/mem, rootfs size, net, storage)
  - Example: `{ "node": "pve", "vmid": 50050, "hostname": "ct01", "ostemplate": "debian-12.tar.zst" }`
  - Answer: `{ "upid": "UPID:..." }`
- `proxmox-delete-lxc` / `proxmox-start-lxc` / `proxmox-stop-lxc` / `proxmox-configure-lxc`
  - Manage container lifecycle and config; `proxmox-delete-lxc` permanently deletes container data

### Cloud-init & networking
- `proxmox-cloudinit-set`
  - Set CI params (ipconfig0, sshkeys, ciuser/cipassword)
  - Example: `{ "name": "web01", "ipconfig0": "ip=192.168.1.50/24,gw=192.168.1.1" }`
  - Answer: `{ "upid": "UPID:..." }` or `{ "result": null }`
- `proxmox-vm-nic-add` / `proxmox-vm-nic-remove`
  - Add/remove NICs (bridge, model, VLAN)
- `proxmox-vm-firewall-get` / `proxmox-vm-firewall-set`
  - Get/set per-VM firewall state and rules

### Images, templates, snapshots, backups
- `proxmox-upload-iso` / `proxmox-upload-template`
  - Upload ISO or LXC template to storage
- `proxmox-template-vm`
  - Convert VM to template
- `proxmox-list-snapshots` / `proxmox-create-snapshot` / `proxmox-delete-snapshot` / `proxmox-rollback-snapshot`
  - Manage snapshots; deleting a snapshot permanently removes that recovery point, and rollback discards newer guest state
- `proxmox-backup-vm` / `proxmox-restore-vm`
  - Run vzdump and restore archives; `force=true` on restore can overwrite existing VM state

### Metrics and monitoring
- `proxmox-vm-metrics`
  - RRD metrics for VM (timeframe, cf)
- `proxmox-node-metrics`
  - RRD metrics for node

### Pools, users, permissions
- `proxmox-list-pools` / `proxmox-create-pool` / `proxmox-delete-pool` / `proxmox-pool-add` / `proxmox-pool-remove`
- `proxmox-list-users` / `proxmox-list-roles` / `proxmox-assign-permission`

### Orchestration helpers
- `proxmox-wait-task`
  - Poll a task until done/timeout
- `proxmox-register-vm-as-host`
  - Emit JSON/INI snippet for Ansible inventory (hostname, IP, SSH user/key)
- `proxmox-guest-exec`
  - Run a command via QEMU Guest Agent; can optionally wait for exit status/output
- `proxmox-guest-shell`
  - Run a Linux shell snippet via guest agent (`bash -lc` or `sh -lc`) for install/test workflows

## Examples

- List nodes: `{}` for `proxmox-list-nodes`
- VMs on node `pve`: `{ "node": "pve" }` for `proxmox-list-vms`
- Clone a template: `{ "source_vmid": 101, "new_vmid": 50009, "name": "web01", "storage": "local-lvm", "wait": true }`
- Configure Cloud-init IP: `{ "name": "web01", "ipconfig0": "ip=192.168.1.50/24,gw=192.168.1.1" }`
- Run an install/test command in a Linux guest: `{ "name": "web01", "script": "sudo ./install.sh && ./run-tests.sh", "wait": true }` for `proxmox-guest-shell`

## Notes

- Server uses stdio transport; prints only MCP protocol to stdout. Logs go to stderr.
- Authentication uses your environment variables and/or `.env` file.
- Name collisions across nodes return clear errors unless you specify `node`.

## Development

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

Notes:
- `uv run pytest` runs the stable automated suite.
- Stable automated tests live under `tests/`.
- `uv run proxmox-mcp-release-patch` bumps the next patch version, refreshes `uv.lock`, runs the automated tests, creates a release commit, and tags it.
- The release helper requires a clean git worktree and only expects version-file changes in `pyproject.toml`, `src/proxmox_mcp/__init__.py`, and `uv.lock`.
- Successful release helper runs finish by creating `chore: release vX.Y.Z` and annotated tag `vX.Y.Z`; push them with `git push origin main --tags` when you are ready to publish.
- Manual/integration-oriented scripts such as `scripts/test_resources.py` and `scripts/test_multi_cluster_server.py` are intentionally excluded from pytest collection; run them directly when you want live-environment checks.
- Legacy/one-off maintenance helpers now live under `scripts/dev/` and `scripts/legacy/` instead of the repo root.

## License

MIT
