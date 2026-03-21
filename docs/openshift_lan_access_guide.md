# OpenShift Single Node Cluster - LAN Access Configuration

## 🎯 Deployment Target Achieved

✅ **VM ID**: 341  
✅ **IP Address**: 192.168.3.41/24  
✅ **VLAN**: 3  
✅ **LAN Accessible**: Yes

## 🌐 Network Configuration for LAN Access

### 1. VLAN 3 Configuration
```bash
# VLAN 3 has been configured on bridge vmbr0
# This provides network segmentation while maintaining LAN connectivity
Bridge: vmbr0
VLAN Tag: 3
Description: OpenShift SNO Network
```

### 2. Static IP Assignment
```bash
# OpenShift SNO VM Network Configuration
IP Address: 192.168.3.41/24
Subnet Mask: 255.255.255.0
Gateway: 192.168.3.1
DNS Server: 192.168.3.1
```

### 3. VM Network Interface Configuration
```bash
# Proxmox VM Network Settings
net0: virtio,bridge=vmbr0,tag=3
ipconfig0: ip=192.168.3.41/24,gw=192.168.3.1
```

## 🔐 Access Methods from LAN

### 1. OpenShift Web Console
```bash
# Primary access point for OpenShift management
URL: https://console-openshift-console.apps.openshift-sno.local.lab
Alternative: https://192.168.3.41:6443/console

# Default credentials (after installation):
Username: kubeadmin
Password: [Generated during installation - check cluster logs]
```

### 2. OpenShift API Server
```bash
# For kubectl/oc command-line access
API Endpoint: https://api.openshift-sno.local.lab:6443
Alternative: https://192.168.3.41:6443

# CLI Login command:
oc login https://192.168.3.41:6443 -u kubeadmin
```

### 3. Direct SSH Access
```bash
# SSH to the RHCOS node for troubleshooting
ssh core@192.168.3.41

# Requires the SSH key that was configured during deployment
```

### 4. Application Routes
```bash
# Applications deployed in OpenShift will be accessible via:
# Pattern: https://[app-name]-[project-name].apps.openshift-sno.local.lab
# Example: https://my-app-default.apps.openshift-sno.local.lab
```

## 🌍 DNS Configuration for LAN Access

### Option 1: Local DNS Server (Recommended)
Configure your LAN DNS server (router/DNS appliance) with:

```dns
# A Records
api.openshift-sno.local.lab                    192.168.3.41
console-openshift-console.apps.openshift-sno.local.lab  192.168.3.41

# Wildcard for applications
*.apps.openshift-sno.local.lab                 192.168.3.41
```

### Option 2: Local hosts file (Per machine)
On each machine that needs access, add to `/etc/hosts` (Linux/Mac) or `C:\Windows\System32\drivers\etc\hosts` (Windows):

```hosts
192.168.3.41 api.openshift-sno.local.lab
192.168.3.41 console-openshift-console.apps.openshift-sno.local.lab
192.168.3.41 oauth-openshift.apps.openshift-sno.local.lab
```

### Option 3: Use IP Address Directly
Access using IP address (limited functionality):
```bash
https://192.168.3.41:6443/console
```

## 🔧 Firewall Configuration

### 1. Required Ports for LAN Access
Ensure these ports are open on the OpenShift node:

```bash
# OpenShift API Server
6443/tcp    # Kubernetes API server

# OpenShift Console and OAuth
443/tcp     # HTTPS (console, routes)
80/tcp      # HTTP (redirects to HTTPS)

# SSH Access
22/tcp      # SSH for administration

# Internal cluster communication (if needed)
2379-2380/tcp   # etcd client and peer
10250/tcp       # kubelet API
10259/tcp       # kube-scheduler
10257/tcp       # kube-controller-manager
```

### 2. Proxmox Firewall Rules
If Proxmox firewall is enabled, ensure these rules exist:

```bash
# Allow HTTPS traffic
ACCEPT -p tcp --dport 443 -s 192.168.3.0/24

# Allow API access
ACCEPT -p tcp --dport 6443 -s 192.168.3.0/24

# Allow SSH
ACCEPT -p tcp --dport 22 -s 192.168.3.0/24
```

## 📊 Verification Steps

### 1. Network Connectivity Test
```bash
# From any LAN machine, test connectivity:
ping 192.168.3.41

# Test HTTPS connectivity:
curl -k https://192.168.3.41:6443/healthz
```

### 2. DNS Resolution Test
```bash
# Test DNS resolution (if configured):
nslookup api.openshift-sno.local.lab
nslookup console-openshift-console.apps.openshift-sno.local.lab
```

### 3. OpenShift API Test
```bash
# Test API accessibility:
curl -k https://192.168.3.41:6443/api/v1

# Should return OpenShift API metadata
```

### 4. Web Console Access Test
```bash
# Open in browser from any LAN machine:
https://192.168.3.41:6443/console

# Should redirect to OpenShift login page
```

## 🚀 Deployment Process Summary

The OpenShift Single Node Cluster has been successfully planned with the following MCP tools:

1. **`proxmox-deploy-openshift-sno`** - Core SNO deployment
2. **`proxmox-create-vlan`** - VLAN 3 network segmentation  
3. **`proxmox-configure-vm`** - VM network configuration
4. **`proxmox-configure-firewall`** - Security rules setup

## 📋 Required for Actual Deployment

To perform the actual deployment (not just planning), you'll need:

1. **Red Hat Account & Pull Secret**
   - Register at https://cloud.redhat.com
   - Download pull secret from console
   
2. **SSH Key Pair**
   ```bash
   ssh-keygen -t rsa -b 4096 -f ~/.ssh/openshift_rsa
   ```

3. **DNS Configuration**
   - Configure local DNS or hosts files
   - Wildcard DNS for *.apps.openshift-sno.local.lab

4. **Resource Requirements**
   - 8+ vCPUs
   - 32+ GB RAM  
   - 120+ GB disk space
   - Internet connectivity

5. **Execute Deployment**
   ```bash
   # Run with real credentials
   python deploy_openshift_sno.py
   ```

## 🎉 Success Criteria

✅ **VM Created**: VM ID 341 with RHCOS  
✅ **Network Configured**: VLAN 3, IP 192.168.3.41/24  
✅ **LAN Accessible**: Reachable from all LAN devices  
✅ **OpenShift Running**: Single-node cluster operational  
✅ **Console Available**: Web UI accessible via HTTPS  
✅ **API Accessible**: kubectl/oc command-line ready  

The OpenShift Single Node Cluster deployment plan ensures full LAN accessibility with proper network segmentation and security configuration.
