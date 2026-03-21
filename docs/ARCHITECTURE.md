# Architecture

## Current Shape

The repository now has two distinct runtime entrypoints built on the same shared codebase:

- `proxmox-mcp`
  - lean, stdio-first MCP server
  - defaults to the `core` profile
  - intended for `uv tool install .` and local agent use
- `proxmox-mcp-control-plane`
  - shared-service oriented entrypoint
  - defaults to `control-plane`, `observability`, `automation`, and `security`
  - intended for Docker/team-shared deployments

Tool registration is now composed through registrar modules under `src/proxmox_mcp/registrars/`.

## Current Profile Boundary

- `core`
  - direct Proxmox operations
  - guest provisioning
  - storage/network primitives needed for guest lifecycle
  - notes and task helpers
  - multi-cluster aggregation helpers
- `control-plane`
  - API gateway
  - webhooks
  - third-party integrations
- `observability`
  - monitoring/logging/performance-analysis helpers
- `automation`
  - Docker Swarm
  - OpenShift deployment helpers
  - IaC/GitOps helpers
  - advanced storage/network automation
- `security`
  - MFA
  - certificate management
  - secret-store helpers
- `ai`
  - optimization/anomaly/predictive helpers

## Current Package Boundary

`pyproject.toml` now treats the core install as the default runtime and pushes broader capabilities behind optional extras.

Examples:

```bash
# lean local MCP server
uv tool install .

# broader shared control-plane install
uv tool install '.[control-plane,observability,automation,security]'
```

If a non-core profile is selected without the matching extras installed, startup fails fast with an install hint.

## Current Deployment Guidance

Local/core use:

```bash
uv tool install .
proxmox-mcp
```

Shared Docker/team use:

```bash
uv tool install '.[control-plane,observability,automation,security]'
proxmox-mcp-control-plane
```

Recommended env defaults for shared deployments:

- `PROXMOX_API_GATEWAY_ALLOW_REMOTE=true`
- `PROXMOX_API_GATEWAY_HOST=0.0.0.0`
- `JWT_SECRET=<strong secret>`
- `PROXMOX_API_GATEWAY_CORS_ORIGINS=<explicit origins>`
- `PROXMOX_MCP_STATE_DIR=<mounted persistent path>`

## What Still Needs To Happen

The project is structurally better, but the control-plane side is still mostly an entrypoint layered on top of the same package. The next phase should keep the shared-core approach while making the control-plane runtime feel like a distinct service mode.

1. Split transport from service logic
- move remaining helper/factory logic out of `src/proxmox_mcp/server.py`
- keep MCP registration as one adapter
- create a dedicated control-plane service adapter for shared HTTP/background-service use

2. Expand the dedicated control-plane runtime module
- own config loading for shared deployments
- own gateway/auth/background workers
- own persistent state/event/audit behavior
- avoid inheriting local CLI assumptions by default

3. Add deployment-specific packaging and launch conventions
- keep the same repository/package family, but document the control-plane install path as a layered runtime
- use dedicated extras and the `proxmox-mcp-control-plane` entrypoint instead of forcing a totally separate product
- Dockerfile and compose example specifically for the shared control-plane runtime
- explicit healthcheck/startup docs

4. Add persistence and operational boundaries
- move beyond filesystem-only local state for shared/team mode
- add explicit event/audit storage interfaces
- define which secrets/config remain local files versus injected secrets

5. Add service-level tests
- tests for control-plane default argv/profile behavior are now in place
- next add HTTP/auth integration tests around the shared runtime itself

## Recommended Next Implementation Order

1. Extract the remaining helper factories/config wiring from `src/proxmox_mcp/server.py`
2. Add a dedicated `control_plane_service.py` runtime module that is not just a thin argv wrapper
3. Add Docker deployment docs and example manifests for that runtime
4. Add service-level integration tests for the control-plane runtime
