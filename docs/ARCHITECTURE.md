# Architecture

## Current Shape

The repository now ships a single MCP runtime:

- `proxmox-mcp`
  - stdio-first MCP server
  - focused on direct Proxmox management
  - intended for local operator use from MCP clients such as Claude Code, Codex, Cursor, and Opencode

Tool registration is composed through registrar modules under `src/proxmox_mcp/registrars/`.

## Current Package Boundary

The package is intentionally trimmed to Proxmox-native operations:

- cluster discovery and status
- VM and LXC lifecycle
- storage, snapshots, backups, templates, and uploads
- pools, users, and permission helpers
- cloud-init, Windows, and RHCOS provisioning helpers
- notes and guest-operation helpers

Removed from the MCP surface:

- embedded control-plane and API-gateway features
- monitoring/logging stack deployment
- secret-store and other bundled security-service features
- generic Terraform, Ansible, and GitOps runners
- bundled Swarm and OpenShift orchestration helpers

The intended boundary is now simple: other systems decide what to automate, and this server performs Proxmox operations.

## Runtime Guidance

Local use:

```bash
uv tool install .
proxmox-mcp
```

Repo-local development:

```bash
uv sync --dev
uv run proxmox-mcp
```

## Design Direction

Near-term work should keep improving the core operator workflow:

1. strengthen live Proxmox compatibility checks and smoke coverage
2. keep destructive actions clearly marked in MCP metadata
3. improve direct Proxmox ergonomics rather than adding adjacent platforms
4. let external systems call this MCP server instead of embedding them inside it
