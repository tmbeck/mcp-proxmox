# MCP Proxmox Server

Advanced Proxmox Model Context Protocol (MCP) server in Python exposing rich Proxmox utilities for discovery, lifecycle, networking, snapshots/backups, metrics, pools/permissions, and orchestration.

- Guide reference: [MCP Quickstart (Python)](https://modelcontextprotocol.io/quickstart/server#python)
- Structure mirrors: [`bsahane/mcp-ansible`](https://github.com/bsahane/mcp-ansible/tree/main)

## Quick start

```bash
git clone https://github.com/tmbeck/mcp-proxmox.git
cd mcp-proxmox

uv sync --dev
```

Run commands in the project environment with `uv run ...` (no manual activation required).

Install modes:

- `uv tool install .` installs the lean core MCP server surface.
- `uv tool install '.[control-plane]'` adds the shared API/integration feature set.
- `uv tool install '.[observability]'` adds monitoring/logging helpers.
- `uv tool install '.[automation]'` adds IaC/orchestration helpers.
- `uv tool install '.[security]'` adds MFA/certificate/secret-store helpers.
- `uv tool install '.[ai]'` adds AI/optimization helpers.
- `uv tool install '.[full]'` installs every optional feature group.

For a local tool-style install, you can also use:

```bash
uv tool install .
```

## .env configuration

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
```

Profile guide:

- `core`: default; direct Proxmox operations, provisioning, and guest lifecycle
- `control-plane`: optional API gateway, webhooks, and external integrations
- `observability`: monitoring, logging, and performance-analysis helpers
- `automation`: Docker Swarm, OpenShift, IaC/GitOps, and advanced storage/network automation
- `security`: MFA, certificates, and secret-store helpers
- `ai`: AI/optimization helpers

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

All tools are available via MCP. Destructive tools accept `confirm`, and most write operations support `dry_run`, `wait`, `timeout`, `poll_interval`.

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
  - Example: `{ "source_vmid": 101, "new_vmid": 50009, "name": "web01", "storage": "local-lvm", "confirm": true, "wait": true }`
  - Answer: `{ "upid": "UPID:...", "status": {...} }`
- `proxmox-create-vm`
  - Create new VM from ISO/template (minimal config)
  - Example: `{ "node": "pve", "vmid": 200, "name": "web02", "iso": "debian.iso", "confirm": true }`
  - Answer: `{ "upid": "UPID:..." }`
- `proxmox-delete-vm`
  - Delete VM (confirm, purge)
  - Example: `{ "name": "web01", "purge": true, "confirm": true }`
  - Answer: `{ "upid": "UPID:..." }`
- `proxmox-start-vm` / `proxmox-stop-vm` / `proxmox-reboot-vm` / `proxmox-shutdown-vm`
  - Manage power state (stop supports hard and timeout)
  - Example: `{ "name": "web01", "wait": true }`
  - Answer: `{ "upid": "UPID:...", "status": {...} }`
- `proxmox-migrate-vm`
  - Live/offline migrate to another node
  - Example: `{ "name": "web01", "target_node": "pve2", "live": true }`
  - Answer: `{ "upid": "UPID:..." }`
- `proxmox-resize-vm-disk`
  - Grow disk (GB) on target disk (e.g., scsi0)
  - Example: `{ "name": "web01", "disk": "scsi0", "grow_gb": 10, "confirm": true, "wait": true }`
  - Answer: `{ "upid": "UPID:...", "status": {...} }`
- `proxmox-configure-vm`
  - Set whitelisted params (cores, memory, balloon, netX, agent, etc.)
  - Example: `{ "name": "web01", "params": { "memory": 4096, "cores": 4 }, "confirm": true }`
  - Answer: `{ "upid": "UPID:..." }` or `{ "result": null }`

### LXC lifecycle
- `proxmox-create-lxc`
  - Create container from template (CPU/mem, rootfs size, net, storage)
  - Example: `{ "node": "pve", "vmid": 50050, "hostname": "ct01", "ostemplate": "debian-12.tar.zst", "confirm": true }`
  - Answer: `{ "upid": "UPID:..." }`
- `proxmox-delete-lxc` / `proxmox-start-lxc` / `proxmox-stop-lxc` / `proxmox-configure-lxc`
  - Manage container lifecycle and config

### Cloud-init & networking
- `proxmox-cloudinit-set`
  - Set CI params (ipconfig0, sshkeys, ciuser/cipassword)
  - Example: `{ "name": "web01", "ipconfig0": "ip=192.168.1.50/24,gw=192.168.1.1", "confirm": true }`
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
  - Manage snapshots; rollback supports `wait`
- `proxmox-backup-vm` / `proxmox-restore-vm`
  - Run vzdump and restore archives

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
- `proxmox-guest-exec` (optional)
  - Run a command via QEMU Guest Agent (requires agent in guest)

## Examples

- List nodes: `{}` for `proxmox-list-nodes`
- VMs on node `pve`: `{ "node": "pve" }` for `proxmox-list-vms`
- Clone a template: `{ "source_vmid": 101, "new_vmid": 50009, "name": "web01", "storage": "local-lvm", "confirm": true, "wait": true }`
- Configure Cloud-init IP: `{ "name": "web01", "ipconfig0": "ip=192.168.1.50/24,gw=192.168.1.1", "confirm": true }`

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

## License

MIT
