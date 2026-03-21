# Proxmox MCP Server - Startup & Usage Guide

## 🚀 Server Status

**✅ Status**: RUNNING AND OPERATIONAL

### Running Processes:
- Multiple instances of `proxmox-mcp` server are active
- All servers successfully configured with multi-cluster support
- Both Production and Staging clusters are accessible

---

## 📋 Quick Start Commands

### 1. Activate Virtual Environment
```bash
source venv/bin/activate
```

### 2. Start the MCP Server (Stdio Mode)
```bash
# Option A: Using module form
python -m proxmox_mcp.server

# Option B: Using console script (if installed)
proxmox-mcp
```

### 3. Run Tests/Diagnostics
```bash
# List all resources from both clusters
python test_resources.py

# Simple cluster connection test
python simple_test.py
```

---

## 🔗 Integration with Cursor

### Configuration
The MCP server can be configured in Cursor's MCP settings:

**File**: `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "proxmox-mcp": {
      "command": "python",
      "args": ["-m", "proxmox_mcp.server"],
      "cwd": "/Users/bsahane/Developer/cursor/mcp-proxmox",
      "env": {
        "PYTHONPATH": "/Users/bsahane/Developer/cursor/mcp-proxmox/src"
      }
    }
  }
}
```

---

## 🎯 Available Tools

### Discovery Tools
- **proxmox-list-nodes** - List all nodes in a cluster
- **proxmox-node-status** - Get detailed node status
- **proxmox-list-vms** - List virtual machines
- **proxmox-vm-info** - Get VM configuration details
- **proxmox-list-lxc** - List LXC containers
- **proxmox-lxc-info** - Get container configuration
- **proxmox-list-storage** - List storage backends

### Lifecycle Tools
- **proxmox-create-vm** - Create a new VM
- **proxmox-start-vm** - Start a VM
- **proxmox-stop-vm** - Stop a VM
- **proxmox-delete-vm** - Delete a VM
- **proxmox-migrate-vm** - Live migrate a VM

### Cluster-Specific Features
All tools support `cluster` parameter for explicit cluster selection:
```
proxmox-list-vms(cluster="production")
proxmox-list-vms(cluster="staging")
```

---

## 📊 Multi-Cluster Configuration

### Current Setup
```
PROXMOX_CLUSTERS=production,staging

Production Cluster:
├─ URL: https://192.168.10.7:8006
├─ Token: root@pam!mcp-proxmox-server
├─ Tier: production
└─ Region: primary

Staging Cluster:
├─ URL: https://192.168.10.7:8006
├─ Token: root@pam!mcp-proxmox-server
├─ Tier: staging
└─ Region: primary
```

### Cluster Selection Priority
1. **Explicit**: `cluster="production"` parameter
2. **Pattern**: VM name prefix (e.g., `prod-vm-*` → production)
3. **Default**: First configured cluster (production)

---

## 🛠️ Troubleshooting

### Issue: Module not found error
**Solution**: Ensure the venv is activated and package is installed
```bash
source venv/bin/activate
pip install -e .
```

### Issue: Connection refused
**Solution**: Verify Proxmox API is accessible
```bash
curl -k https://192.168.10.7:8006/api2/json/nodes
```

### Issue: Authentication failed
**Solution**: Check .env file for correct credentials
```bash
cat .env | grep PROXMOX_TOKEN
```

---

## 📝 Environment Variables

### Multi-Cluster Configuration (.env)
```env
# Enable multi-cluster mode
PROXMOX_CLUSTERS=production,staging

# Production cluster
PROXMOX_CLUSTER_production_API_URL=...
PROXMOX_CLUSTER_production_TOKEN_ID=...
PROXMOX_CLUSTER_production_TOKEN_SECRET=...

# Staging cluster
PROXMOX_CLUSTER_staging_API_URL=...
PROXMOX_CLUSTER_staging_TOKEN_ID=...
PROXMOX_CLUSTER_staging_TOKEN_SECRET=...

# Backward compatibility (single cluster)
PROXMOX_API_URL=...
PROXMOX_TOKEN_ID=...
PROXMOX_TOKEN_SECRET=...
```

---

## 🔐 Security Notes

- ✅ SSL verification is currently disabled (PROXMOX_VERIFY="false")
- ⚠️ For production, enable SSL verification: `PROXMOX_VERIFY="true"`
- ✅ Token secrets stored securely in `.env` (not in git)
- ⚠️ Never commit `.env` file to version control

---

## 📚 Next Steps

1. **Configure in Claude Desktop**: Update `claude_desktop_config.json`
2. **Configure in Cursor**: Update `~/.cursor/mcp.json`
3. **Test connectivity**: Run `python test_resources.py`
4. **Explore tools**: Use the MCP tools to manage your Proxmox clusters

---

**Last Updated**: 2025-10-16 19:35 UTC
**Status**: ✅ All systems operational
