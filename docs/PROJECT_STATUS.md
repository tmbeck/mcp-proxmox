# Proxmox MCP Server - Project Status

🎉 **Status**: Production Ready  
📅 **Last Updated**: 2026-03-22  
🔧 **Product Boundary**: Core Proxmox MCP server only  
✅ **Latest Focus**: Version compatibility, destructive-action hints, and live smoke validation

---

## Overview

The server is now trimmed to direct Proxmox management.

Current scope includes:

- VM and LXC lifecycle management
- storage, snapshots, backups, templates, and uploads
- pools, users, permissions, and task helpers
- cloud-init, Windows, and RHCOS provisioning helpers
- guest exec/shell helpers and notes management
- multi-cluster status aggregation and version compatibility reporting

Removed from the MCP surface:

- embedded control-plane and API-gateway features
- bundled monitoring/logging stack deployment
- secret-store and adjacent security-service features
- generic Terraform, Ansible, and GitOps runners
- bundled Docker Swarm and OpenShift orchestration helpers
- AI/optimization helpers

## Validation Snapshot

Automated checks:

- ✅ package metadata/version checks
- ✅ compatibility and tool-metadata coverage
- ✅ safety regression coverage for destructive operations
- ✅ packaging and entrypoint behavior

Live validation:

- ✅ tested against Proxmox VE `9.1.6`
- ✅ disposable smoke workflow covers clone, SSH readiness, disk add/detach/delete-volume, snapshot create/rollback/delete, stop/start, shutdown, and final cleanup

## Notes

- Patch releases within `9.1.x` are treated as expected-compatible.
- Other Proxmox major/minor lines are unverified and produce a warning plus MCP-visible compatibility data.
- The project is intentionally biased toward being called by other systems rather than embedding those systems inside the MCP server.
