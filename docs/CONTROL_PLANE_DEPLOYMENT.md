# Control-Plane Deployment

## Purpose

Use `proxmox-mcp` for local, stdio-first agent workflows.

Use `proxmox-mcp-control-plane` when you want a broader shared runtime for a team, typically inside Docker or another supervised service environment.

This is a layered runtime, not a completely separate product. It uses the same shared core and enables broader profiles by default.

## What The Control-Plane Entrypoint Enables

By default, `proxmox-mcp-control-plane` activates:

- `control-plane`
- `observability`
- `automation`
- `security`

It still uses the same core MCP/provisioning capabilities underneath.

## Install

```bash
uv tool install '.[control-plane,observability,automation,security]'
```

## Run

```bash
proxmox-mcp-control-plane
```

You can still override profiles explicitly if needed:

```bash
proxmox-mcp-control-plane --profile core
proxmox-mcp-control-plane --profile control-plane --profile observability
```

## Recommended Environment For Shared Deployments

```bash
PROXMOX_API_URL="https://proxmox.example.com:8006"
PROXMOX_TOKEN_ID="root@pam!mcp-proxmox"
PROXMOX_TOKEN_SECRET="<secret>"
PROXMOX_VERIFY="true"

PROXMOX_API_GATEWAY_ALLOW_REMOTE="true"
PROXMOX_API_GATEWAY_HOST="0.0.0.0"
PROXMOX_API_GATEWAY_CORS_ORIGINS="https://your-ui.example.com"
JWT_SECRET="<strong-secret>"

PROXMOX_MCP_STATE_DIR="/var/lib/proxmox-mcp"
PROXMOX_ALLOWED_URLS=""
PROXMOX_ENABLE_EXTERNAL_INTEGRATIONS="false"
```

## Security Notes

- Shared deployments should set `JWT_SECRET` explicitly.
- Remote gateway exposure remains opt-in.
- Keep `PROXMOX_ENABLE_EXTERNAL_INTEGRATIONS=false` unless you need those features.
- If you enable third-party integrations, explicitly allowlist public hosts in `PROXMOX_ALLOWED_URLS`.
- Mount `PROXMOX_MCP_STATE_DIR` to persistent storage if the service should retain local state.

## Docker Direction

The current repo now has the runtime boundary needed for Docker deployment, but not yet a canonical Dockerfile/compose example.

The next implementation step should be:

1. add a dedicated Dockerfile for `proxmox-mcp-control-plane`
2. add a compose example with env file + persistent state volume
3. add a healthcheck/startup section for gateway-enabled service mode
