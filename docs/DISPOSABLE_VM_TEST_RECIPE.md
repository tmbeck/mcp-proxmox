# Disposable VM Test Recipe

## Purpose

This recipe is the safest repeatable path for validating the core MCP workflow against a real Proxmox cluster without touching existing VMs or non-disposable storage assets.

Target workflow:

1. clone a disposable VM from a template
2. start it
3. verify guest access
4. install and test software in the guest
5. add a data disk
6. verify the guest sees the new disk
7. detach the disk non-destructively
8. optionally delete the detached disk volume
9. destroy the disposable VM

## Guardrails

- Use a reserved VMID range only. Recommended: `8100-8199`.
- Use a disposable name prefix only: `mcp-test-<vmid>-<timestamp>`.
- Never run clone, disk, or delete operations against any VM that does not match the disposable prefix/range.
- Never remove a disk unless it was created during the current test run.
- Ask for confirmation before any destructive action:
  - deleting a disk volume
  - deleting the disposable VM

## Prerequisites

- `.env` is present and valid.
- `PROXMOX_MCP_PROFILES="core"`.
- Default node, storage, and bridge are correct.
- A known template VM is available for cloning.
- For full in-guest install/test steps, the template must have QEMU guest agent installed and running.

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
3. Select a free VMID in the reserved range.
4. Confirm the chosen disposable name does not already exist.
5. Confirm the template’s guest agent is expected to work if in-guest testing is required.

## Step-by-Step Recipe

### 1. Clone the template

Example:

```json
{
  "source_vmid": 8001,
  "new_vmid": 8100,
  "name": "mcp-test-8100-<timestamp>",
  "storage": "local-vmx",
  "confirm": true,
  "wait": true
}
```

Tool: `proxmox-clone-vm`

Expected result:
- clone task completes with `exitstatus=OK`

### 2. Start the disposable VM

Example:

```json
{
  "vmid": 8100,
  "wait": true
}
```

Tool: `proxmox-start-vm`

Expected result:
- start task completes with `exitstatus=OK`

### 3. Verify guest access

Example:

```json
{
  "vmid": 8100,
  "script": "echo guest-ready && uname -a && lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT",
  "wait": true
}
```

Tool: `proxmox-guest-shell`

Expected result:
- exit code `0`
- baseline guest disk state is visible

Stop if:
- guest agent is unavailable
- command execution fails repeatedly

### 4. Install/test software in guest

Example pattern:

```json
{
  "vmid": 8100,
  "script": "sudo ./install.sh && ./run-tests.sh",
  "wait": true,
  "timeout": 1800
}
```

Tool: `proxmox-guest-shell`

Expected result:
- exit code `0`

### 5. Record baseline disk state

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

### 6. Add a disposable data disk

Example:

```json
{
  "vmid": 8100,
  "interface": "scsi",
  "storage": "local-vmx",
  "size_gb": 2,
  "format": "raw",
  "confirm": true
}
```

Tool: `proxmox-vm-disk-add`

Expected result:
- returns a new device, for example `scsi0`

### 7. Verify the guest sees the new disk

Example:

```json
{
  "vmid": 8100,
  "script": "udevadm settle || true; sleep 2; lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT",
  "wait": true
}
```

Tool: `proxmox-guest-shell`

Expected result:
- guest now shows an additional disk (for example `sda`)

### 8. Detach the disk non-destructively

Example:

```json
{
  "vmid": 8100,
  "device": "scsi0",
  "mode": "detach",
  "wait": true,
  "confirm": true
}
```

Tool: `proxmox-vm-disk-remove`

Expected result:
- disk disappears from active devices
- disk appears under `unused_disks`
- guest returns to baseline disk count

### 9. Optional destructive disk cleanup

Only after explicit confirmation.

Example:

```json
{
  "vmid": 8100,
  "device": "unused0",
  "mode": "delete-volume",
  "wait": true,
  "confirm": true
}
```

Tool: `proxmox-vm-disk-remove`

Expected result:
- unused test disk is deleted from storage

### 10. Destroy the disposable VM

Only after explicit confirmation.

Example:

```json
{
  "vmid": 8100,
  "purge": true,
  "wait": true,
  "confirm": true
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
  - cleanup

The remaining optional step is an actual product-specific install/test command payload for your software.
