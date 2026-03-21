# Multi-Cluster Proxmox MCP Specification

## Overview
Extend the existing single-cluster Proxmox MCP system to support management of multiple Proxmox clusters with intelligent credential routing and dynamic cluster selection based on context.

## Current State
- **Single Cluster**: Currently hardcoded to use one Proxmox cluster via environment variables
- **Credentials**: Read from `.env` file using `PROXMOX_API_URL`, `PROXMOX_TOKEN_ID`, `PROXMOX_TOKEN_SECRET`, etc.
- **Architecture**: Single `ProxmoxClient` instance handling all operations

## Goals
1. **Multi-Cluster Support**: Manage multiple Proxmox clusters (≥2) simultaneously
2. **Dynamic Credential Management**: Load credentials from `.env` file for all clusters
3. **Intelligent Cluster Selection**: Automatically determine which cluster to use based on:
   - Explicit cluster selector in tool parameters
   - Resource name patterns
   - VM/Container naming conventions
   - Default cluster fallback
4. **Backward Compatibility**: Maintain existing single-cluster behavior when only one cluster defined
5. **Transparent Integration**: Minimal changes to existing tools and client code

---

## Architecture Design

### 1. Cluster Configuration Structure

#### .env File Format
```env
# Primary cluster (default)
PROXMOX_CLUSTERS=cluster1,cluster2,cluster3

# Cluster 1 Configuration
PROXMOX_CLUSTER_cluster1_API_URL=https://proxmox1.example.com:8006
PROXMOX_CLUSTER_cluster1_TOKEN_ID=root@pam!mcp-token-1
PROXMOX_CLUSTER_cluster1_TOKEN_SECRET=secret1
PROXMOX_CLUSTER_cluster1_VERIFY=true
PROXMOX_CLUSTER_cluster1_DEFAULT_NODE=pve-node1
PROXMOX_CLUSTER_cluster1_DEFAULT_STORAGE=local-lvm-1
PROXMOX_CLUSTER_cluster1_DEFAULT_BRIDGE=vmbr0

# Cluster 2 Configuration
PROXMOX_CLUSTER_cluster2_API_URL=https://proxmox2.example.com:8006
PROXMOX_CLUSTER_cluster2_TOKEN_ID=root@pam!mcp-token-2
PROXMOX_CLUSTER_cluster2_TOKEN_SECRET=secret2
PROXMOX_CLUSTER_cluster2_VERIFY=true
PROXMOX_CLUSTER_cluster2_DEFAULT_NODE=pve-node2
PROXMOX_CLUSTER_cluster2_DEFAULT_STORAGE=local-lvm-2
PROXMOX_CLUSTER_cluster2_DEFAULT_BRIDGE=vmbr0

# Cluster 3 Configuration
PROXMOX_CLUSTER_cluster3_API_URL=https://proxmox3.example.com:8006
PROXMOX_CLUSTER_cluster3_TOKEN_ID=root@pam!mcp-token-3
PROXMOX_CLUSTER_cluster3_TOKEN_SECRET=secret3
PROXMOX_CLUSTER_cluster3_VERIFY=true
PROXMOX_CLUSTER_cluster3_DEFAULT_NODE=pve-node3
PROXMOX_CLUSTER_cluster3_DEFAULT_STORAGE=local-lvm-3
PROXMOX_CLUSTER_cluster3_DEFAULT_BRIDGE=vmbr0

# Backward compatibility: single cluster (no PROXMOX_CLUSTERS defined)
PROXMOX_API_URL=https://proxmox.example.com:8006
PROXMOX_TOKEN_ID=root@pam!mcp-proxmox
PROXMOX_TOKEN_SECRET=secret
PROXMOX_VERIFY=true
PROXMOX_DEFAULT_NODE=pve
PROXMOX_DEFAULT_STORAGE=local-lvm
PROXMOX_DEFAULT_BRIDGE=vmbr0
```

### 2. Core Components

#### A. ClusterConfig Dataclass
- Stores credentials and defaults for a single cluster
- Includes cluster name and metadata
- Supports cluster-specific settings

#### B. ClusterRegistry
- Central registry for managing all cluster configurations
- Lazy-loads credentials from environment
- Caches initialized ProxmoxClient instances
- Provides cluster discovery and validation

#### C. Multi-Cluster Client Wrapper
- Extends ProxmoxClient or creates wrapper
- Routes operations to appropriate cluster
- Implements intelligent cluster selection logic
- Maintains transparent API compatibility

#### D. Cluster Selector Strategy
Priority order for cluster selection:
1. **Explicit Parameter**: `cluster_name` in tool parameters
2. **Resource Pattern Match**: VM name contains cluster identifier
3. **VMId Mapping**: Lookup table for VM ID to cluster mapping (optional)
4. **Default Cluster**: First configured cluster or `PROXMOX_CLUSTERS` preference

---

## Implementation Details

### 1. Enhanced Utils Module (`utils.py`)

#### New Dataclasses
```python
@dataclass
class ClusterConfig:
    name: str
    base_url: str
    token_id: str
    token_secret: str
    verify: bool
    default_node: Optional[str] = None
    default_storage: Optional[str] = None
    default_bridge: Optional[str] = None
    region: Optional[str] = None  # For geographic tagging
    tier: Optional[str] = None    # Production, staging, etc.

@dataclass
class ClusterRegistryConfig:
    clusters: Dict[str, ClusterConfig]
    default_cluster: str
    enable_cluster_validation: bool = True
    cache_ttl: int = 3600  # Cache TTL in seconds
```

#### New Functions
```python
def read_multi_cluster_env() -> Dict[str, ClusterConfig]
    """Read multiple cluster configs from environment"""

def load_cluster_registry() -> ClusterRegistry
    """Initialize cluster registry from environment"""

def validate_cluster_connection(cluster: ClusterConfig) -> bool
    """Test connection to a cluster"""
```

### 2. New ClusterRegistry Class (`cluster_manager.py`)

**Responsibilities:**
- Load and cache cluster configurations
- Provide cluster lookup by name
- Support intelligent cluster selection
- Maintain ProxmoxClient instances per cluster
- Handle cluster validation and health checks

**Key Methods:**
```python
class ClusterRegistry:
    def get_client(self, cluster_name: Optional[str] = None) -> ProxmoxClient
    def list_clusters(self) -> List[ClusterConfig]
    def select_cluster_for_resource(self, resource_name: str) -> str
    def validate_all_clusters() -> Dict[str, bool]
    def get_cluster_by_pattern(self, pattern: str) -> Optional[str]
```

### 3. Modified Server Module (`server.py`)

#### Backward Compatibility
- Detect single vs. multi-cluster mode
- Initialize appropriate client strategy
- Add optional `cluster` parameter to all tools

#### New Helper
```python
def get_multi_cluster_client(
    cluster_name: Optional[str] = None,
    resource_name: Optional[str] = None
) -> ProxmoxClient:
    """Get appropriate client based on cluster selection strategy"""
```

#### Tool Parameter Changes
- Add optional `cluster` parameter to discovery and lifecycle tools
- Tool signature example:
```python
@server.tool("proxmox-list-nodes")
async def proxmox_list_nodes(cluster: Optional[str] = None) -> List[Dict[str, Any]]:
    client = get_multi_cluster_client(cluster)
    return client.list_nodes()
```

### 4. Client Extension Strategy

**Option A: Wrapper Class (Recommended)**
- Create `MultiClusterProxmoxClient` that wraps multiple `ProxmoxClient` instances
- Maintains exact same interface as `ProxmoxClient`
- Routes calls to appropriate cluster
- Minimal code duplication

**Option B: Enhanced Single Client**
- Modify `ProxmoxClient` to support cluster parameter
- Less disruptive but more complex

### 5. VM/Resource Naming Convention

#### Recommended Pattern
```
{cluster_prefix}-{resource_type}-{identifier}
Examples:
  prod-vm-web01        # Production cluster, VM
  staging-ct-db01      # Staging cluster, container
  dr-vm-backup01       # Disaster recovery cluster
```

#### Cluster Identifier Mapping
Optional mapping file or environment variable:
```python
PROXMOX_CLUSTER_PATTERNS={
  "prod-": "cluster1",
  "staging-": "cluster2",
  "dr-": "cluster3"
}
```

---

## Data Flow

### Single Cluster Mode (Backward Compatible)
```
.env (PROXMOX_*) → read_env() → ProxmoxClient → API Call
```

### Multi-Cluster Mode
```
.env (PROXMOX_CLUSTERS, PROXMOX_CLUSTER_*) 
  → read_multi_cluster_env() 
  → ClusterRegistry 
  → Tool Parameter + Cluster Selector 
  → Appropriate ProxmoxClient 
  → API Call
```

### Intelligent Selection Flow
```
1. Check for explicit `cluster` parameter in tool call
2. If not provided, check resource_name for pattern matching
3. If no match, check VMId mapping (if enabled)
4. Fall back to default cluster
5. Return appropriate ProxmoxClient instance
```

---

## Tool Updates Strategy

### Phase 1: Core Discovery Tools
- `proxmox-list-nodes`
- `proxmox-list-vms`
- `proxmox-list-storage`
- etc.

### Phase 2: VM Lifecycle Tools
- `proxmox-create-vm`
- `proxmox-delete-vm`
- `proxmox-clone-vm`
- etc.

### Phase 3: Advanced Tools
- Cloud-init deployment
- Windows VM management
- Docker Swarm orchestration
- OpenShift deployment

### Phase 4: New Multi-Cluster Tools
- `proxmox-list-all-clusters`
- `proxmox-cluster-status`
- `proxmox-migrate-vm-between-clusters`
- `proxmox-cross-cluster-backup`

---

## Error Handling

### Cluster-Specific Errors
```python
class ClusterError(Exception):
    """Base exception for cluster operations"""
    def __init__(self, cluster_name: str, message: str)

class ClusterNotFoundError(ClusterError):
    """Cluster not found in registry"""

class ClusterConnectionError(ClusterError):
    """Cannot connect to cluster"""

class AmbiguousClusterSelectionError(ClusterError):
    """Cannot determine target cluster"""
```

### Validation Strategy
1. **Startup**: Validate all configured clusters are reachable
2. **Per-Operation**: Validate selected cluster connectivity
3. **Graceful Degradation**: Retry with fallback cluster if primary unavailable
4. **Detailed Logging**: Log cluster selection decisions

---

## Configuration Validation

### Startup Checks
```python
def validate_cluster_configuration():
    1. Verify PROXMOX_CLUSTERS environment variable if multi-cluster mode
    2. For each cluster:
       - Verify required credentials present
       - Test API connectivity
       - Validate token permissions
    3. Verify default cluster exists
    4. Warn if clusters are unreachable
```

### Health Checks
```python
@server.tool("proxmox-cluster-health")
async def proxmox_cluster_health(cluster: Optional[str] = None) -> Dict[str, Any]:
    """Check health of all or specific cluster"""
```

---

## Testing Strategy

### Unit Tests
- Cluster configuration parsing
- Cluster selection logic
- Pattern matching
- Credential loading

### Integration Tests
- Multi-cluster client initialization
- Cross-cluster operations
- Fallback behavior
- Error handling

### Mock Tests
- Simulate multiple cluster APIs
- Test selection strategies
- Verify transparent routing

---

## Backward Compatibility

### Single Cluster Mode
```env
# Traditional .env format still works
PROXMOX_API_URL=...
PROXMOX_TOKEN_ID=...
PROXMOX_TOKEN_SECRET=...
```

### Feature Detection
```python
def is_multi_cluster_mode() -> bool:
    return "PROXMOX_CLUSTERS" in os.environ
```

### Fallback Logic
- If `PROXMOX_CLUSTERS` not defined, use legacy `PROXMOX_*` variables
- All tools work identically in single cluster mode
- Optional `cluster` parameter ignored in single cluster mode

---

## Documentation Updates

### README.md Changes
- Multi-cluster configuration examples
- Tool parameter documentation
- Cluster selection strategy explanation

### Configuration Guide
- .env setup for multiple clusters
- Naming conventions
- Pattern matching rules

### Migration Guide
- Steps to upgrade from single to multi-cluster
- No API breaking changes
- Gradual adoption possible

---

## Security Considerations

1. **Credential Isolation**: Each cluster has separate credentials
2. **Token Scoping**: Support per-cluster token with appropriate ACLs
3. **Encryption**: Support encrypted credential storage (future enhancement)
4. **Audit**: Log cluster operations with cluster identifier
5. **RBAC**: Support role-based access control per cluster

---

## Future Enhancements

1. **Cluster Failover**: Automatic failover to secondary cluster
2. **Load Balancing**: Distribute operations across clusters
3. **Replication**: Synchronize resources across clusters
4. **Cost Tracking**: Per-cluster billing/cost analysis
5. **Cluster Federation**: Shared cluster pool management
6. **Encryption**: AES encryption for stored credentials

---

## Success Criteria

1. ✅ Manage 3+ clusters simultaneously
2. ✅ Intelligent automatic cluster selection
3. ✅ 100% backward compatibility
4. ✅ All existing tools work with cluster parameter
5. ✅ Clear error messages for ambiguous selection
6. ✅ Comprehensive test coverage
7. ✅ Updated documentation
8. ✅ No performance degradation

---

## Files to Create/Modify

### Create New Files
1. `src/proxmox_mcp/cluster_manager.py` - ClusterRegistry and related classes
2. `src/proxmox_mcp/multi_cluster_client.py` - MultiClusterProxmoxClient wrapper
3. `.env.example.multi` - Multi-cluster example configuration
4. `tests/test_cluster_manager.py` - Cluster manager tests
5. `tests/test_multi_cluster.py` - Multi-cluster integration tests
6. `MULTI_CLUSTER_MIGRATION.md` - Migration guide

### Modify Existing Files
1. `src/proxmox_mcp/utils.py` - Add multi-cluster env parsing
2. `src/proxmox_mcp/server.py` - Add cluster parameter to tools
3. `src/proxmox_mcp/__init__.py` - Export new classes
4. `README.md` - Update with multi-cluster documentation
5. `requirements.txt` - No new dependencies required

---

## Implementation Phases

### Phase 1: Core Infrastructure (Days 1-2)
- Implement ClusterRegistry
- Add multi-cluster env parsing
- Create cluster configuration validation

### Phase 2: Client Integration (Days 2-3)
- Implement MultiClusterProxmoxClient
- Add cluster parameter to all tools
- Implement cluster selection strategies

### Phase 3: Testing & Documentation (Days 3-4)
- Comprehensive test coverage
- Update README and examples
- Create migration guide

### Phase 4: Validation & Optimization (Day 4)
- End-to-end testing
- Performance profiling
- Security review
