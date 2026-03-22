# Disposable VM Test Recipe

## Purpose

This recipe is the safest repeatable path for validating the core MCP workflow against a real Proxmox cluster without touching existing VMs or non-disposable storage assets.

Target workflow:

1. clone a disposable VM from a template
2. start it
3. verify guest access over external SSH
4. install and test software in the guest over external SSH
5. add a data disk
6. verify the guest sees the new disk
7. detach the disk non-destructively
8. optionally delete the detached disk volume
9. create, roll back, and delete a disposable snapshot
10. stop the VM immediately and start it again
11. shut it down cleanly
12. destroy the disposable VM

## Guardrails

- Never delete or destroy any VMID below `9000`.
- Use a reserved disposable VMID range only. Recommended: `9000-9099`.
- Use a disposable name prefix only: `mcp-test-<vmid>-<timestamp>`.
- Never run clone, disk, or delete operations against any VM that does not match the disposable prefix/range.
- Never remove a disk unless it was created during the current test run.
- Treat the following steps as destructive because they can permanently remove data:
  - deleting a disk volume
  - deleting the disposable VM
  - deleting any resource that was not created during the current clone-based test run

## Prerequisites

- `.env` is present and valid.
- `PROXMOX_MCP_PROFILES="core"`.
- Default node, storage, and bridge are correct.
- A known template VM is available for cloning.
- For full in-guest install/test steps, the template must support reliable external SSH access as `ubuntu`.
- The template should already have your SSH public key installed, or the clone workflow should inject it via cloud-init.
- The external test script should fetch the guest IP through this project by reading the address reported to Proxmox via QEMU guest agent.

## Opt-In Live Smoke Command

Run the guarded smoke workflow with automatic cleanup of disposable resources on failure:

```bash
uv run python scripts/run_disposable_vm_test.py \
  --yes-delete-disk \
  --yes-delete-vm \
  --cleanup-on-failure
```

Defaults now cover:

- clone/start/guest readiness
- disk add/detach/delete-volume cycle
- snapshot create/rollback/delete
- immediate stop plus restart
- graceful shutdown and final VM deletion

## External SSH Reliability Notes

For this recipe, guest operations are intentionally performed over external SSH rather than an MCP guest-exec helper.

Key-management boundary:

- the external test script generates a temporary SSH keypair
- the MCP core server accepts the public key and applies it to the clone via cloud-init
- the external test script uses the private key for SSH
- the external test script deletes the temporary keypair after cleanup

Recommended SSH assumptions:

- user: `ubuntu`
- key-based auth only
- no interactive password prompts
- `StrictHostKeyChecking=accept-new` or a disposable known-hosts file for test automation

Recommended SSH command shape:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new ubuntu@<vm-ip> '<command>'
```

Before product install/test steps, wait for cloud-init to settle if the guest uses cloud-init:

```bash
ssh ubuntu@<vm-ip> 'cloud-init status --wait'
```

IP-discovery boundary:

- the script should use the project client to query QEMU guest agent network data
- the script should wait until the cloned VM reports an IPv4 address
- that reported IPv4 address is then used for external SSH

## Current Known-Good Example

The live-tested environment used during validation had:

- node: `pve1`
- storage: `local-vmx`
- bridge: `vmbr0`
- template VMID: `8001`
- template name: `ubuntu-2404-cloudinit-template`

Treat those as examples, not hardcoded requirements.

## Preflight Checklist

1. Verify the core tool surface is present:
   - `proxmox-clone-vm`
   - `proxmox-start-vm`
   - `proxmox-guest-shell`
   - `proxmox-vm-disk-list`
   - `proxmox-vm-disk-add`
   - `proxmox-vm-disk-remove`
   - `proxmox-delete-vm`
2. Verify the template VM exists and is marked as a template.
3. Select a free VMID above `9000` in the reserved disposable range.
4. Confirm the chosen disposable name does not already exist.
5. Confirm the template’s guest agent is expected to work if in-guest testing is required.

## Step-by-Step Recipe

## Product Validation Variant

If your goal is product validation rather than a minimal MCP smoke test, use this stricter sequence:

1. Clone template VM `8001`.
2. The new VMID must be greater than `9000`.
3. Generate a temporary SSH keypair outside the MCP server.
4. Apply the public key to the clone with `proxmox-cloudinit-set` before first boot.
5. Start the VM and let it settle.
6. Confirm you can obtain the guest IP and log in over external SSH as `ubuntu`.
7. Attach `4` data disks of `40 GB` each.
8. Detach one of those data disks.
9. Attach a new `40 GB` data disk.
10. Delete the detached disk.
11. Verify the guest sees `4` attached data disks.
12. Create, roll back, and delete a disposable snapshot.
13. Stop the VM immediately, start it again, and confirm the guest still sees the expected disks.
14. Shut off the VM cleanly.
15. Delete the disposable VM and its owned test disks.

Important clarification:

- Count data disks separately from the OS disk.
- In a typical Ubuntu guest, the OS disk still exists, so total visible disk devices will usually be `5` (`1` OS disk + `4` data disks).
- The intended success condition is therefore: the guest returns to exactly four attached test/data disks after the detach/add/delete cycle.

The default recipe below remains a lower-risk version for incremental verification.

### 1. Clone the template

Example:

```json
{
  "source_vmid": 8001,
  "new_vmid": 8100,
  "name": "mcp-test-8100-<timestamp>",
  "storage": "local-vmx",
  "wait": true
}
```

Tool: `proxmox-clone-vm`

Expected result:
- clone task completes with `exitstatus=OK`

### 2. Start the disposable VM

Before first boot, inject the externally generated public key via cloud-init.

Example:

```json
{
  "vmid": 9100,
  "ciuser": "ubuntu",
  "sshkeys": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... disposable-test-key"
}
```

Tool: `proxmox-cloudinit-set`

Recommended timing:
- run this after cloning
- run it before the first start of the cloned VM

### 3. Start the disposable VM

Example:

```json
{
  "vmid": 9100,
  "wait": true
}
```

Tool: `proxmox-start-vm`

Expected result:
- start task completes with `exitstatus=OK`

### 4. Verify guest access

Example:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new ubuntu@<vm-ip> \
  'echo guest-ready && uname -a && lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT'
```

Expected result:
- SSH login succeeds as `ubuntu`
- baseline guest disk state is visible

Stop if:
- guest IP cannot be determined reliably
- SSH login fails repeatedly
- cloud-init never settles

### 5. Install/test software in guest

Example pattern:

```bash
ssh ubuntu@<vm-ip> 'sudo ./install.sh && ./run-tests.sh'
```

Expected result:
- exit code `0`

### 6. Record baseline disk state

Example:

```json
{
  "vmid": 8100
}
```

Tool: `proxmox-vm-disk-list`

Expected result:
- active system disk only
- no unexpected `unused_disks`

### 7. Add a disposable data disk

Example:

```json
{
  "vmid": 8100,
  "interface": "scsi",
  "storage": "local-vmx",
  "size_gb": 2,
  "format": "raw"
}
```

Tool: `proxmox-vm-disk-add`

Expected result:
- returns a new device, for example `scsi0`

### 8. Verify the guest sees the new disk

Example:

```bash
ssh ubuntu@<vm-ip> 'udevadm settle || true; sleep 2; lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT'
```

Expected result:
- guest now shows an additional disk (for example `sda`)

### 9. Detach the disk non-destructively

Example:

```json
{
  "vmid": 8100,
  "device": "scsi0",
  "mode": "detach",
  "wait": true
}
```

Tool: `proxmox-vm-disk-remove`

Expected result:
- disk disappears from active devices
- disk appears under `unused_disks`
- guest returns to baseline disk count

### 10. Optional destructive disk cleanup

This permanently deletes the backing test disk from storage.

Example:

```json
{
  "vmid": 8100,
  "device": "unused0",
  "mode": "delete-volume",
  "wait": true
}
```

Tool: `proxmox-vm-disk-remove`

Expected result:
- unused test disk is deleted from storage

### 11. Create, roll back, and delete a disposable snapshot

This snapshot must be created on the disposable VM only.

Example create:

```json
{
  "vmid": 8100,
  "snapname": "mcp-smoke-snap-8100-<timestamp>",
  "description": "Disposable live smoke snapshot"
}
```

Tool: `proxmox-create-snapshot`

Expected result:
- snapshot appears in `proxmox-list-snapshots`

Example rollback:

```json
{
  "vmid": 8100,
  "snapname": "mcp-smoke-snap-8100-<timestamp>",
  "wait": true
}
```

Tool: `proxmox-rollback-snapshot`

Expected result:
- after the VM is started again, guest-visible state reverts to the snapshot point

Example delete:

```json
{
  "vmid": 8100,
  "snapname": "mcp-smoke-snap-8100-<timestamp>"
}
```

Tool: `proxmox-delete-snapshot`

Expected result:
- disposable snapshot no longer appears in `proxmox-list-snapshots`

### 12. Stop the VM immediately and start it again

Example stop:

```json
{
  "vmid": 8100,
  "overrule_shutdown": true,
  "wait": true
}
```

Tool: `proxmox-stop-vm`

Expected result:
- VM power state becomes `stopped`

Example start:

```json
{
  "vmid": 8100,
  "wait": true
}
```

Tool: `proxmox-start-vm`

Expected result:
- VM becomes reachable again over external SSH
- guest still shows the expected disk layout

Use `overrule_shutdown`, not `hard`; `hard` is only a deprecated alias kept through `0.2.x` and planned for removal in `0.3.0`.

### 13. Shut down the disposable VM cleanly

Example:

```json
{
  "vmid": 8100,
  "wait": true,
  "timeout": 120
}
```

Tool: `proxmox-shutdown-vm`

Expected result:
- VM power state becomes `stopped`

### 14. Destroy the disposable VM

This permanently deletes the disposable VM and any purged resources.

Example:

```json
{
  "vmid": 8100,
  "purge": true,
  "wait": true
}
```

Tool: `proxmox-delete-vm`

Expected result:
- VM is no longer visible
- no `vm-<vmid>-*` artifacts remain on the target storage

## Stop Conditions

Stop immediately if any of the following occur:

- resolved VM name or VMID does not match the disposable guardrails
- selected disk target was not created during this test run
- storage identity is ambiguous
- guest access fails and would require manual changes to a non-disposable VM
- task status or Proxmox responses point at an unexpected VM or storage object

## What Was Proven Live

This recipe has already been proven live in two stages:

- infrastructure-only pass
  - clone
  - start
  - add disk
  - non-destructive detach
  - cleanup
- full guest-access pass
  - clone
  - start
  - guest shell access
  - guest-visible disk add
  - guest-visible non-destructive detach
  - guest-visible replacement disk add/delete-volume
  - snapshot create/rollback/delete
  - immediate stop/start
  - graceful shutdown
  - cleanup

The remaining optional step is an actual product-specific install/test command payload for your software.
