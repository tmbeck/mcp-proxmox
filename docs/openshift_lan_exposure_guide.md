# OpenShift Single Node Cluster - LAN Exposure Guide

This guide explains how to expose an OpenShift Single Node (SNO) cluster deployed on Proxmox to the Local Area Network (LAN) for access from other devices.

## 🌐 Network Architecture Overview

```
Internet/WAN
     |
[Router/Gateway] (192.168.1.1)
     |
[LAN Network] (192.168.1.0/24)
     |
├── [Proxmox Host] (192.168.1.10)
│   └── [OpenShift SNO VM] (192.168.1.100)
├── [Client 1] (192.168.1.50)
├── [Client 2] (192.168.1.51)
└── [Developer Workstation] (192.168.1.60)
```

## 📋 Prerequisites

1. **OpenShift SNO VM** deployed with our MCP Proxmox tools
2. **Static IP** assigned to the SNO VM (e.g., 192.168.1.100)
3. **DNS access** (either local DNS server or router DNS configuration)
4. **Firewall configuration** on Proxmox host and network

## 🔧 Step 1: VM Network Configuration

### Proxmox Bridge Configuration
```bash
# Ensure VM is connected to the correct bridge
# In Proxmox web interface:
# VM → Hardware → Network Device → Bridge: vmbr0
# Model: VirtIO (paravirtualized)
# Firewall: No (for LAN access)
```

### OpenShift VM Network Setup
```bash
# Configure static IP in RHCOS (via Ignition or post-install)
nmcli connection modify ens18 ipv4.addresses 192.168.1.100/24
nmcli connection modify ens18 ipv4.gateway 192.168.1.1
nmcli connection modify ens18 ipv4.dns "192.168.1.1,8.8.8.8"
nmcli connection modify ens18 ipv4.method manual
nmcli connection up ens18
```

## 🌐 Step 2: DNS Configuration

### Option A: Router/Modem DNS (Recommended)
Configure your home router to resolve OpenShift domains:

```bash
# Add these DNS entries to your router's DNS settings:
api.openshift-sno.lab.local      → 192.168.1.100
oauth-openshift.apps.openshift-sno.lab.local → 192.168.1.100
console-openshift-console.apps.openshift-sno.lab.local → 192.168.1.100
*.apps.openshift-sno.lab.local  → 192.168.1.100
```

### Option B: Pi-hole/Bind DNS Server
If you have a local DNS server:

```bash
# /etc/hosts or DNS zone file
192.168.1.100 api.openshift-sno.lab.local
192.168.1.100 oauth-openshift.apps.openshift-sno.lab.local
192.168.1.100 console-openshift-console.apps.openshift-sno.lab.local
# Wildcard for all apps
*.apps.openshift-sno.lab.local → 192.168.1.100
```

### Option C: Individual Client Configuration
On each client device, modify `/etc/hosts` (Linux/Mac) or `C:\Windows\System32\drivers\etc\hosts` (Windows):

```bash
192.168.1.100 api.openshift-sno.lab.local
192.168.1.100 oauth-openshift.apps.openshift-sno.lab.local
192.168.1.100 console-openshift-console.apps.openshift-sno.lab.local
192.168.1.100 grafana-openshift-monitoring.apps.openshift-sno.lab.local
192.168.1.100 prometheus-k8s-openshift-monitoring.apps.openshift-sno.lab.local
```

## 🔥 Step 3: Firewall Configuration

### Proxmox Host Firewall
```bash
# Allow traffic to OpenShift ports
iptables -A FORWARD -d 192.168.1.100 -p tcp --dport 6443 -j ACCEPT  # API Server
iptables -A FORWARD -d 192.168.1.100 -p tcp --dport 443 -j ACCEPT   # HTTPS
iptables -A FORWARD -d 192.168.1.100 -p tcp --dport 80 -j ACCEPT    # HTTP
iptables -A FORWARD -d 192.168.1.100 -p tcp --dport 22623 -j ACCEPT # Machine Config Server

# Make persistent
iptables-save > /etc/iptables/rules.v4
```

### OpenShift SNO VM Firewall
```bash
# RHCOS uses firewalld
sudo firewall-cmd --permanent --add-port=6443/tcp   # API Server
sudo firewall-cmd --permanent --add-port=443/tcp    # HTTPS Ingress
sudo firewall-cmd --permanent --add-port=80/tcp     # HTTP Ingress
sudo firewall-cmd --permanent --add-port=22623/tcp  # Machine Config
sudo firewall-cmd --reload
```

## 🚀 Step 4: OpenShift Configuration

### Update Ingress Controller for LAN Access
```yaml
# ingress-controller-patch.yaml
apiVersion: operator.openshift.io/v1
kind: IngressController
metadata:
  name: default
  namespace: openshift-ingress-operator
spec:
  endpointPublishingStrategy:
    type: HostNetwork
  defaultCertificate:
    name: custom-certs-default
```

```bash
# Apply the configuration
oc apply -f ingress-controller-patch.yaml
```

### Configure OAuth for External Access
```yaml
# oauth-config.yaml
apiVersion: config.openshift.io/v1
kind: OAuth
metadata:
  name: cluster
spec:
  identityProviders:
  - name: htpasswd_provider
    mappingMethod: claim
    type: HTPasswd
    htpasswd:
      fileData:
        name: htpass-secret
```

## 📱 Step 5: Access from LAN Devices

### Web Console Access
```bash
# From any device on the LAN
https://console-openshift-console.apps.openshift-sno.lab.local
```

### CLI Access (oc command)
```bash
# Download oc client and login
oc login https://api.openshift-sno.lab.local:6443
# Enter credentials: kubeadmin / <password-from-install>
```

### API Access
```bash
# REST API access
curl -k https://api.openshift-sno.lab.local:6443/api/v1/namespaces
```

## 🔧 Step 6: SSL Certificate Configuration (Optional)

### Self-Signed Certificate for LAN
```bash
# Generate self-signed cert for *.apps.openshift-sno.lab.local
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout wildcard.key \
  -out wildcard.crt \
  -subj "/CN=*.apps.openshift-sno.lab.local"

# Create secret in OpenShift
oc create secret tls custom-certs-default \
  --cert=wildcard.crt \
  --key=wildcard.key \
  -n openshift-ingress
```

## 🧪 Step 7: Testing LAN Access

### Basic Connectivity Test
```bash
# From any LAN device
ping 192.168.1.100

# Test DNS resolution
nslookup api.openshift-sno.lab.local

# Test HTTPS access
curl -k https://api.openshift-sno.lab.local:6443/version
```

### Application Deployment Test
```yaml
# test-app.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hello-openshift
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hello-openshift
  template:
    metadata:
      labels:
        app: hello-openshift
    spec:
      containers:
      - name: hello-openshift
        image: openshift/hello-openshift
        ports:
        - containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: hello-openshift
spec:
  selector:
    app: hello-openshift
  ports:
  - port: 8080
    targetPort: 8080
---
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: hello-openshift
spec:
  to:
    kind: Service
    name: hello-openshift
  port:
    targetPort: 8080
```

```bash
# Deploy and test
oc apply -f test-app.yaml
oc get route hello-openshift
# Access from LAN: http://hello-openshift-default.apps.openshift-sno.lab.local
```

## 📊 Step 8: Monitoring and Logging Access

### Prometheus Access
```bash
# Access Prometheus from LAN
https://prometheus-k8s-openshift-monitoring.apps.openshift-sno.lab.local
```

### Grafana Access
```bash
# Access Grafana from LAN
https://grafana-openshift-monitoring.apps.openshift-sno.lab.local
```

### ELK Stack (if installed)
```bash
# Access Kibana from LAN
https://kibana-openshift-logging.apps.openshift-sno.lab.local
```

## 🛡️ Security Considerations

### Network Security
- **Firewall Rules**: Only open necessary ports (6443, 80, 443)
- **VPN Access**: Consider VPN for remote access instead of port forwarding
- **Network Segmentation**: Use VLANs to isolate OpenShift traffic

### Authentication
- **Strong Passwords**: Use complex passwords for kubeadmin
- **RBAC**: Implement role-based access control
- **Identity Providers**: Configure LDAP/AD integration for production

### SSL/TLS
- **Valid Certificates**: Use proper certificates in production
- **Certificate Rotation**: Implement automatic certificate renewal
- **mTLS**: Consider mutual TLS for API access

## 🔍 Troubleshooting

### Common Issues

1. **DNS Not Resolving**
   ```bash
   # Check DNS configuration
   dig api.openshift-sno.lab.local
   nslookup console-openshift-console.apps.openshift-sno.lab.local
   ```

2. **Port Access Issues**
   ```bash
   # Test port connectivity
   telnet 192.168.1.100 6443
   nc -zv 192.168.1.100 443
   ```

3. **Certificate Errors**
   ```bash
   # Check certificate details
   openssl s_client -connect api.openshift-sno.lab.local:6443
   ```

4. **Firewall Blocking**
   ```bash
   # Check firewall status
   sudo firewall-cmd --list-all
   iptables -L -n
   ```

### Diagnostic Commands
```bash
# OpenShift cluster status
oc get nodes
oc get clusteroperators

# Network status
oc get svc -A
oc get routes -A

# Ingress controller status
oc get ingresscontroller -n openshift-ingress-operator
oc get pods -n openshift-ingress
```

## 📚 Additional Resources

- [OpenShift Documentation](https://docs.openshift.com/)
- [Red Hat OpenShift Networking](https://docs.openshift.com/container-platform/4.19/networking/understanding-networking.html)
- [Proxmox Network Configuration](https://pve.proxmox.com/wiki/Network_Configuration)

## 🎯 Summary

With this configuration, your OpenShift SNO cluster will be accessible from any device on your LAN network. Users can:

- Access the web console via browser
- Use `oc` CLI from their workstations
- Deploy and access applications via routes
- Monitor cluster health via built-in tools

The cluster maintains full functionality while being exposed securely to your local network environment.
