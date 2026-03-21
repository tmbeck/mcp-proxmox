# Multi-Cluster Proxmox MCP - Quick Start Guide

## Overview
This guide walks you through setting up and using the multi-cluster Proxmox MCP system with credentials stored centrally in `.env`.

## ✅ Phase 1-2 Implementation Complete

The following components have been successfully implemented:

### Core Infrastructure (Phase 1) ✓
- **`utils.py`** - Enhanced with multi-cluster environment parsing
  - `ClusterConfig` dataclass for single cluster configuration
  - `ClusterRegistryConfig` for registry-level configuration
  - `read_multi_cluster_env()` - Parse multiple clusters from .env
  - `load_cluster_registry_config()` - Load config with fallback to legacy mode
  - `is_multi_cluster_mode()` - Detect multi-cluster operation
  
- **`cluster_manager.py`** - Complete ClusterRegistry implementation
  - `ClusterRegistry` class - Manages all clusters
  - `get_cluster_registry()` - Global registry accessor
  - Intelligent cluster selection logic
  - Client caching with TTL
  - Cluster validation and health checks
  - Custom exception classes for error handling

### Client Integration (Phase 2) ✓
- **`multi_cluster_client.py`** - MultiClusterProxmoxClient wrapper
  - Transparent API compatible with ProxmoxClient
  - All discovery methods support cluster parameter
  - All lifecycle methods support cluster parameter
  - Cluster-specific info methods
  
- **`.env.example.multi`** - Complete configuration example
  - 3-cluster example (production, staging, DR)
  - Pattern-based cluster selection
  - All required environment variables documented

- **`__init__.py`** - All classes exported for public use

## Setup Instructions

### 1. Configure Your Clusters in .env

Copy the example and update with your credentials:

```bash
cp .env.example.multi .env
```

Edit `.env` and replace values:

```env
# Enable multi-cluster mode by listing cluster names
PROXMOX_CLUSTERS=production,staging,disaster-recovery

# Configure each cluster with credentials from .env as PRIMARY source
PROXMOX_CLUSTER_production_API_URL=https://proxmox-prod.example.com:8006
PROXMOX_CLUSTER_production_TOKEN_ID=root@pam!mcp-prod-token
PROXMOX_CLUSTER_production_TOKEN_SECRET=your_token_here

# ... repeat for other clusters
```

### 2. Intelligent Cluster Selection (3 Priority Levels)

The system automatically selects the right cluster:

#### Priority 1: Explicit Selection
```python
# Specify cluster explicitly
client.list_vms(cluster="production")
```

#### Priority 2: Resource Name Pattern
```python
# Name pattern automatically routes to cluster
client.create_vm(name="prod-vm-web01", ...)  # → production cluster
client.create_vm(name="stg-ct-db01", ...)    # → staging cluster
client.create_vm(name="dr-backup-01", ...)   # → dr cluster
```

#### Priority 3: Default Cluster
```python
# No cluster specified, no pattern match → uses first configured cluster
client.list_nodes()  # → uses "production" (first in PROXMOX_CLUSTERS)
```

### 3. Usage Examples

#### List All Clusters
```python
from proxmox_mcp import MultiClusterProxmoxClient

client = MultiClusterProxmoxClient()
clusters = client.list_all_clusters()
print(f"Available clusters: {clusters}")
```

#### Get Cluster Information
```python
# Get info about specific cluster
prod_info = client.get_cluster_info("production")
print(f"Production: {prod_info['nodes_count']} nodes")

# Get info about all clusters
all_info = client.list_all_clusters_info()
for cluster_info in all_info:
    print(f"{cluster_info['cluster_name']}: {cluster_info['status']}")
```

#### Validate All Clusters
```python
results = client.validate_all_clusters()
for cluster, (is_valid, message) in results.items():
    status = "✓" if is_valid else "✗"
    print(f"{status} {cluster}: {message}")
```

#### Cluster-Specific Operations
```python
# List VMs from production cluster
prod_vms = client.list_vms(cluster="production")

# Create VM with automatic cluster detection
client.create_vm(
    name="prod-vm-web01",  # Pattern matches production
    vmid=100,
    cores=4,
    memory_mb=8192
)

# Create container in staging
client.create_lxc(
    hostname="stg-ct-database",  # Pattern matches staging
    vmid=200,
    ostemplate="debian-12.tar.zst"
)
```

## Environment Variables Reference

### Multi-Cluster Mode Variables
| Variable | Description | Required |
|----------|-------------|----------|
| `PROXMOX_CLUSTERS` | Comma-separated cluster names | Yes (for multi-cluster) |
| `PROXMOX_CLUSTER_PATTERNS` | Pattern to cluster mapping | No |
| `PROXMOX_CLUSTER_VALIDATION` | Validate clusters at startup | No (default: true) |
| `PROXMOX_CLUSTER_CACHE_TTL` | Client cache TTL in seconds | No (default: 3600) |

### Per-Cluster Configuration (for cluster named `{name}`)
| Variable | Description | Required |
|----------|-------------|----------|
| `PROXMOX_CLUSTER_{name}_API_URL` | Proxmox API endpoint | Yes |
| `PROXMOX_CLUSTER_{name}_TOKEN_ID` | API token ID | Yes |
| `PROXMOX_CLUSTER_{name}_TOKEN_SECRET` | API token secret | Yes |
| `PROXMOX_CLUSTER_{name}_VERIFY` | Verify SSL certificates | No (default: true) |
| `PROXMOX_CLUSTER_{name}_DEFAULT_NODE` | Default node name | No |
| `PROXMOX_CLUSTER_{name}_DEFAULT_STORAGE` | Default storage | No |
| `PROXMOX_CLUSTER_{name}_DEFAULT_BRIDGE` | Default network bridge | No |
| `PROXMOX_CLUSTER_{name}_REGION` | Cluster region/location | No |
| `PROXMOX_CLUSTER_{name}_TIER` | Cluster tier (prod/staging/dr) | No |

### Backward Compatibility (Single-Cluster)
If `PROXMOX_CLUSTERS` is NOT defined, these legacy variables are used:

```env
PROXMOX_API_URL=https://proxmox.example.com:8006
PROXMOX_TOKEN_ID=root@pam!mcp-token
PROXMOX_TOKEN_SECRET=secret
PROXMOX_VERIFY=true
PROXMOX_DEFAULT_NODE=pve
PROXMOX_DEFAULT_STORAGE=local-lvm
PROXMOX_DEFAULT_BRIDGE=vmbr0
```

## Key Features

✅ **All Credentials in .env**
- Single source of truth for all cluster credentials
- Secure, centralized configuration
- No hardcoded credentials in code

✅ **Intelligent Cluster Selection**
- Multiple selection methods work together
- Clear error messages for ambiguous cases
- Automatic pattern-based routing

✅ **100% Backward Compatible**
- Existing single-cluster configs still work
- Optional `cluster` parameter on all methods
- No breaking changes to API

✅ **Enterprise-Ready**
- Client caching with configurable TTL
- Cluster validation and health checks
- Comprehensive error handling

## Cluster Selection Examples

### Example 1: Pattern-Based Selection
```env
PROXMOX_CLUSTER_PATTERNS=prod-:production,stg-:staging
```

```python
# Resource names with patterns automatically route to correct cluster
client.create_vm(name="prod-web-01", ...)     # → production
client.create_vm(name="stg-database-01", ...) # → staging
client.create_vm(name="myvm", ...)            # → default cluster
```

### Example 2: Explicit Selection
```python
# Explicitly specify cluster
client.list_vms(cluster="production")
client.list_vms(cluster="staging")
client.list_vms(cluster="disaster-recovery")
```

### Example 3: Naming Convention
```env
PROXMOX_CLUSTERS=production,staging,dr
```

```python
# Naming convention: {cluster-name}-{type}-{identifier}
client.create_vm(name="production-web-01", ...)  # → production
client.create_vm(name="staging-web-01", ...)     # → staging
client.create_vm(name="dr-backup-01", ...)       # → dr
```

## Error Handling

The system provides clear error messages:

```python
from proxmox_mcp import (
    ClusterNotFoundError,
    AmbiguousClusterSelectionError,
    ClusterConnectionError
)

try:
    client.list_vms(cluster="nonexistent")
except ClusterNotFoundError as e:
    print(f"Error: {e}")  # Cluster not found: nonexistent

try:
    client.create_vm(name="ambiguous-vm", ...)
except AmbiguousClusterSelectionError as e:
    print(f"Error: {e}")  # Multiple clusters match, specify explicitly

try:
    client.list_nodes(cluster="offline-cluster")
except ClusterConnectionError as e:
    print(f"Error: {e}")  # Cannot connect to cluster
```

## Testing Your Setup

```python
from proxmox_mcp import MultiClusterProxmoxClient

# Initialize
client = MultiClusterProxmoxClient()

# Check configured clusters
print(f"Clusters: {client.list_all_clusters()}")

# Validate connectivity
results = client.validate_all_clusters()
for cluster, (valid, msg) in results.items():
    print(f"{cluster}: {'✓' if valid else '✗'} {msg}")

# Get cluster details
for info in client.list_all_clusters_info():
    print(f"\n{info['cluster_name']}:")
    print(f"  Status: {info['status']}")
    print(f"  Nodes: {info['nodes_count']}")
    print(f"  VMs: {info['vms_count']}")
    print(f"  Containers: {info['lxc_count']}")
```

## What's Implemented

### ✓ Core Components
- Multi-cluster environment parsing from .env
- ClusterRegistry with client caching
- Intelligent cluster selection
- Transparent API wrapper
- Custom exception classes

### ✓ Features
- All 3 clusters simultaneously managed
- Automatic pattern-based routing
- Explicit cluster selection
- Client caching with TTL
- Cluster validation and health checks
- Backward compatibility with single-cluster

### ⏳ Still to Come (Phase 2+)
- Server integration with cluster parameter to all tools
- Unit and integration tests
- Documentation updates
- Performance optimization
- Cross-cluster backup/migration tools

## Next Steps

1. **Update `.env`** with your cluster credentials
2. **Test connectivity** using the validation commands above
3. **Use the client** in your applications
4. **Monitor cluster health** with validation tools

---

**Version**: 0.2.0  
**Status**: Phase 1-2 Complete ✓  
**Created**: October 2025
