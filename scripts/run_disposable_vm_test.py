from __future__ import annotations

import argparse
import json
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dotenv import load_dotenv  # noqa: E402

from proxmox_mcp.client import ProxmoxClient  # noqa: E402


MIN_DESTRUCTIVE_VMID = 9000


@dataclass
class TestResources:
    vmid: Optional[int] = None
    vm_name: Optional[str] = None
    vm_node: Optional[str] = None
    guest_ip: Optional[str] = None
    created_disk_devices: list[str] = field(default_factory=list)
    created_disk_configs: dict[str, str] = field(default_factory=dict)
    detached_unused_device: Optional[str] = None
    detached_unused_config: Optional[str] = None
    snapshot_names: list[str] = field(default_factory=list)
    temp_dir: Optional[Path] = None
    private_key_path: Optional[Path] = None
    public_key_path: Optional[Path] = None
    known_hosts_path: Optional[Path] = None
    vm_deleted: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a guarded disposable VM validation workflow"
    )
    parser.add_argument("--template-vmid", type=int, default=8001)
    parser.add_argument("--min-vmid", type=int, default=9000)
    parser.add_argument("--max-vmid", type=int, default=9099)
    parser.add_argument("--name-prefix", default="mcp-test")
    parser.add_argument("--ssh-user", default="ubuntu")
    parser.add_argument("--cloudinit-user", default="ubuntu")
    parser.add_argument("--data-disk-count", type=int, default=4)
    parser.add_argument("--data-disk-size-gb", type=int, default=40)
    parser.add_argument("--expected-vlan-tag", type=int)
    parser.add_argument("--install-command")
    parser.add_argument("--test-command")
    parser.add_argument("--pre-detach-command")
    parser.add_argument("--snapshot-name-prefix", default="mcp-smoke-snap")
    parser.add_argument("--ssh-timeout", type=int, default=300)
    parser.add_argument("--task-timeout", type=int, default=1800)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--yes-delete-disk", action="store_true")
    parser.add_argument("--yes-delete-vm", action="store_true")
    parser.add_argument("--cleanup-on-failure", action="store_true")
    parser.add_argument("--keep-vm-on-success", action="store_true")
    parser.add_argument("--skip-snapshot-cycle", action="store_true")
    parser.add_argument("--skip-stop-cycle", action="store_true")
    parser.add_argument("--skip-cloud-init-wait", action="store_true")
    return parser.parse_args()


def log_step(message: str, **details: Any) -> None:
    payload = {"step": message, **details}
    print(json.dumps(payload, sort_keys=True))


def prompt_yes_no(question: str, *, assume_yes: bool = False) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise RuntimeError(
            f"Refusing destructive action without confirmation in non-interactive mode: {question}"
        )
    answer = input(f"{question} [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def require_safe_vmid(vmid: int) -> None:
    if vmid < MIN_DESTRUCTIVE_VMID:
        raise RuntimeError(
            f"Refusing destructive action on VMID {vmid}; must be >= {MIN_DESTRUCTIVE_VMID}"
        )


def ensure_disposable_vm(vm: dict[str, Any], vmid: int, name_prefix: str) -> None:
    require_safe_vmid(vmid)
    name = str(vm.get("name") or "")
    if not name.startswith(f"{name_prefix}-"):
        raise RuntimeError(
            f"Refusing to operate on non-disposable VM {vmid} named '{name}'"
        )


def wait_for_task_if_present(
    client: ProxmoxClient,
    upid: Any,
    *,
    node: str,
    timeout: int,
    poll_interval: float,
) -> Optional[dict[str, Any]]:
    if isinstance(upid, str) and upid:
        return client.wait_task(
            upid, node=node, timeout=timeout, poll_interval=poll_interval
        )
    return None


def generate_temp_keypair(resources: TestResources, vmid: int) -> str:
    temp_dir = Path(tempfile.mkdtemp(prefix=f"mcp-vmtest-{vmid}-"))
    private_key = temp_dir / "id_ed25519"
    public_key = temp_dir / "id_ed25519.pub"
    known_hosts = temp_dir / "known_hosts"
    cmd = [
        "ssh-keygen",
        "-t",
        "ed25519",
        "-N",
        "",
        "-f",
        str(private_key),
        "-C",
        f"mcp-test-{vmid}",
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

    resources.temp_dir = temp_dir
    resources.private_key_path = private_key
    resources.public_key_path = public_key
    resources.known_hosts_path = known_hosts
    return public_key.read_text(encoding="utf-8").strip()


def cleanup_temp_keys(resources: TestResources) -> None:
    if resources.vm_deleted and resources.temp_dir and resources.temp_dir.exists():
        shutil.rmtree(resources.temp_dir)


def choose_disposable_vmid(client: ProxmoxClient, min_vmid: int, max_vmid: int) -> int:
    all_vms = client.list_vms()
    used_vmids = {int(vm["vmid"]) for vm in all_vms if vm.get("vmid") is not None}
    candidate = next(
        (vmid for vmid in range(min_vmid, max_vmid + 1) if vmid not in used_vmids),
        None,
    )
    if candidate is None:
        raise RuntimeError(
            f"No free disposable VMID found in reserved range {min_vmid}-{max_vmid}"
        )
    require_safe_vmid(candidate)
    return candidate


def locate_template(client: ProxmoxClient, template_vmid: int) -> dict[str, Any]:
    for vm in client.list_vms():
        if int(vm.get("vmid", -1)) == template_vmid:
            if not vm.get("template"):
                raise RuntimeError(f"VMID {template_vmid} exists but is not a template")
            return vm
    raise RuntimeError(f"Template VMID {template_vmid} is not visible")


def ssh_base_command(
    resources: TestResources, ssh_user: str, ip_address: str
) -> list[str]:
    if not resources.private_key_path or not resources.known_hosts_path:
        raise RuntimeError("Temporary SSH keypair not initialized")
    return [
        "ssh",
        "-i",
        str(resources.private_key_path),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={resources.known_hosts_path}",
        f"{ssh_user}@{ip_address}",
    ]


def wait_for_ssh(ip_address: str, timeout: int) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((ip_address, 22), timeout=5):
                return
        except OSError:
            time.sleep(3)
    raise TimeoutError(
        f"SSH on {ip_address}:22 did not become reachable within {timeout}s"
    )


def run_ssh_command(
    resources: TestResources,
    *,
    ssh_user: str,
    ip_address: str,
    command: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    cmd = [*ssh_base_command(resources, ssh_user, ip_address), command]
    return subprocess.run(
        cmd, check=False, capture_output=True, text=True, timeout=timeout
    )


def ensure_ssh_ok(
    resources: TestResources,
    *,
    ssh_user: str,
    ip_address: str,
    command: str,
    timeout: int,
    description: str,
) -> subprocess.CompletedProcess[str]:
    result = run_ssh_command(
        resources,
        ssh_user=ssh_user,
        ip_address=ip_address,
        command=command,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"SSH step failed ({description}) with code {result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def wait_for_ssh_command(
    resources: TestResources,
    *,
    ssh_user: str,
    ip_address: str,
    command: str,
    timeout: int,
    description: str,
) -> subprocess.CompletedProcess[str]:
    deadline = time.time() + timeout
    last_error: Optional[str] = None
    while time.time() < deadline:
        try:
            return ensure_ssh_ok(
                resources,
                ssh_user=ssh_user,
                ip_address=ip_address,
                command=command,
                timeout=min(30, max(10, timeout)),
                description=description,
            )
        except Exception as exc:
            last_error = str(exc)
            time.sleep(5)
    raise RuntimeError(
        f"SSH command did not succeed within {timeout}s ({description}). Last error: {last_error}"
    )


def parse_lsblk_json(output: str) -> tuple[int, list[dict[str, Any]]]:
    payload = json.loads(output)

    def flatten(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for block in blocks:
            result.append(block)
            children = block.get("children") or []
            result.extend(flatten(children))
        return result

    disks = [
        block
        for block in flatten(payload.get("blockdevices", []))
        if block.get("type") == "disk"
    ]
    return len(disks), disks


def wait_for_expected_disk_count(
    resources: TestResources,
    *,
    ssh_user: str,
    ip_address: str,
    timeout: int,
    expected_count: int,
) -> tuple[int, list[dict[str, Any]]]:
    deadline = time.time() + timeout
    last_count: Optional[int] = None
    last_disks: list[dict[str, Any]] = []
    while time.time() < deadline:
        count, disks = verify_disk_count_over_ssh(
            resources,
            ssh_user=ssh_user,
            ip_address=ip_address,
            timeout=timeout,
        )
        last_count = count
        last_disks = disks
        if count == expected_count:
            return count, disks
        time.sleep(3)
    raise RuntimeError(
        f"Expected {expected_count} total guest disks but last observed {last_count}: {last_disks}"
    )


def child_mountpoints(disk: dict[str, Any]) -> list[str]:
    mounts: list[str] = []
    for child in disk.get("children") or []:
        mountpoint = child.get("mountpoint")
        if mountpoint:
            mounts.append(str(mountpoint))
    return mounts


def ensure_test_disks_quiescent(
    disks: list[dict[str, Any]], test_disk_names: set[str]
) -> None:
    for disk in disks:
        name = str(disk.get("name") or "")
        if name not in test_disk_names:
            continue
        if disk.get("mountpoint"):
            raise RuntimeError(
                f"Refusing to detach test disk {name}; it is mounted at {disk.get('mountpoint')}"
            )
        mounts = child_mountpoints(disk)
        if mounts:
            raise RuntimeError(
                f"Refusing to detach test disk {name}; child partitions are mounted at {mounts}. Use --pre-detach-command to quiesce the guest first."
            )


def verify_disk_count_over_ssh(
    resources: TestResources,
    *,
    ssh_user: str,
    ip_address: str,
    timeout: int,
) -> tuple[int, list[dict[str, Any]]]:
    result = ensure_ssh_ok(
        resources,
        ssh_user=ssh_user,
        ip_address=ip_address,
        command="udevadm settle || true; sleep 2; lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT",
        timeout=timeout,
        description="lsblk disk verification",
    )
    return parse_lsblk_json(result.stdout)


def maybe_run_product_command(
    resources: TestResources,
    *,
    ssh_user: str,
    ip_address: str,
    command: Optional[str],
    timeout: int,
    description: str,
) -> None:
    if not command:
        return
    result = ensure_ssh_ok(
        resources,
        ssh_user=ssh_user,
        ip_address=ip_address,
        command=command,
        timeout=timeout,
        description=description,
    )
    log_step(
        description,
        stdout=result.stdout.strip()[:500],
        stderr=result.stderr.strip()[:200],
    )


def parse_net_config(config_value: str) -> dict[str, str]:
    parts = [part.strip() for part in config_value.split(",") if part.strip()]
    parsed: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            parsed[key] = value
    return parsed


def disk_volume_identity(config_value: str) -> str:
    return config_value.split(",", 1)[0].strip()


def snapshot_entry_names(snapshots: list[dict[str, Any]]) -> set[str]:
    return {
        str(snapshot.get("name") or snapshot.get("snapname") or "")
        for snapshot in snapshots
        if snapshot.get("name") or snapshot.get("snapname")
    }


def require_snapshot_state(
    client: ProxmoxClient,
    *,
    node: str,
    vmid: int,
    snapshot_name: str,
    should_exist: bool,
) -> set[str]:
    names = snapshot_entry_names(client.list_snapshots(node, vmid))
    if should_exist and snapshot_name not in names:
        raise RuntimeError(
            f"Snapshot {snapshot_name!r} not found on VM {vmid}; visible snapshots: {sorted(names)}"
        )
    if not should_exist and snapshot_name in names:
        raise RuntimeError(f"Snapshot {snapshot_name!r} still exists on VM {vmid}")
    return names


def current_vm_status(client: ProxmoxClient, vmid: int) -> str:
    _, _, vm = client.resolve_vm(vmid=vmid)
    return str(vm.get("status") or "")


def wait_for_vm_status(
    client: ProxmoxClient,
    *,
    vmid: int,
    expected_status: str,
    timeout: int,
    poll_interval: float,
) -> str:
    deadline = time.time() + timeout
    last_status: Optional[str] = None
    while time.time() < deadline:
        status = current_vm_status(client, vmid)
        last_status = status
        if status == expected_status:
            return status
        time.sleep(poll_interval)

    raise RuntimeError(
        f"VM {vmid} did not reach status={expected_status!r} within {timeout}s; last status={last_status!r}"
    )


def best_effort_cleanup(
    client: ProxmoxClient,
    resources: TestResources,
    *,
    name_prefix: str,
    timeout: int,
    poll_interval: float,
) -> None:
    if resources.vm_deleted or resources.vmid is None:
        return

    try:
        vmid, node, vm = client.resolve_vm(vmid=resources.vmid)
    except Exception:
        return

    ensure_disposable_vm(vm, vmid, name_prefix)
    status = str(vm.get("status") or "")
    if status == "running":
        stop_upid = client.stop_vm(
            node,
            vmid,
            overrule_shutdown=True,
            timeout=min(timeout, 120),
        )
        stop_status = wait_for_task_if_present(
            client,
            stop_upid,
            node=node,
            timeout=timeout,
            poll_interval=poll_interval,
        )
        log_step("cleanup-stopped", upid=stop_upid, status=stop_status)

    delete_upid = client.delete_vm(node, vmid, purge=True)
    delete_status = wait_for_task_if_present(
        client,
        delete_upid,
        node=node,
        timeout=timeout,
        poll_interval=poll_interval,
    )
    resources.vm_deleted = True
    log_step("cleanup-vm-deleted", upid=delete_upid, status=delete_status)


def main() -> int:
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    client = ProxmoxClient.from_env()
    resources = TestResources()

    try:
        if (
            not client.default_node
            or not client.default_storage
            or not client.default_bridge
        ):
            raise RuntimeError(
                ".env must define PROXMOX_DEFAULT_NODE, PROXMOX_DEFAULT_STORAGE, and PROXMOX_DEFAULT_BRIDGE"
            )
        if args.data_disk_count <= 0:
            raise RuntimeError("--data-disk-count must be greater than zero")
        if args.ssh_user != args.cloudinit_user:
            raise RuntimeError(
                f"--ssh-user ({args.ssh_user}) and --cloudinit-user ({args.cloudinit_user}) must match for reliable key-based login"
            )

        template = locate_template(client, args.template_vmid)
        vmid = choose_disposable_vmid(client, args.min_vmid, args.max_vmid)
        vm_name = f"{args.name_prefix}-{vmid}-{int(time.time())}"
        if any(str(vm.get("name")) == vm_name for vm in client.list_vms()):
            raise RuntimeError(f"Disposable VM name collision: {vm_name}")

        resources.vmid = vmid
        resources.vm_name = vm_name
        resources.vm_node = str(template.get("node") or client.default_node)

        log_step(
            "preflight",
            vmid=vmid,
            name=vm_name,
            template_vmid=args.template_vmid,
            template_name=template.get("name"),
            node=client.default_node,
            storage=client.default_storage,
            bridge=client.default_bridge,
        )

        public_key = generate_temp_keypair(resources, vmid)
        log_step("generated-temp-keypair", temp_dir=str(resources.temp_dir))

        clone_upid = client.clone_vm(
            source_node=str(template.get("node")),
            source_vmid=args.template_vmid,
            target_node=client.default_node,
            new_vmid=vmid,
            name=vm_name,
            full=True,
            storage=client.default_storage,
        )
        clone_status = client.wait_task(
            clone_upid,
            node=str(template.get("node")),
            timeout=args.task_timeout,
            poll_interval=args.poll_interval,
        )
        log_step("cloned", upid=clone_upid, status=clone_status)

        clone_vm_vmid, clone_vm_node, clone_vm = client.resolve_vm(vmid=vmid)
        ensure_disposable_vm(clone_vm, clone_vm_vmid, args.name_prefix)

        clone_config = client.vm_config(clone_vm_node, clone_vm_vmid)
        net0 = str(clone_config.get("net0") or "")
        net0_options = parse_net_config(net0)
        if net0_options.get("bridge") != client.default_bridge:
            raise RuntimeError(
                f"Clone network bridge mismatch: expected {client.default_bridge}, got {net0_options.get('bridge')} in net0={net0!r}"
            )
        actual_vlan = net0_options.get("tag")
        if args.expected_vlan_tag is None and actual_vlan is not None:
            raise RuntimeError(
                f"Clone unexpectedly has VLAN tag {actual_vlan} in net0={net0!r}; refusing to continue"
            )
        if args.expected_vlan_tag is not None and str(args.expected_vlan_tag) != str(
            actual_vlan
        ):
            raise RuntimeError(
                f"Clone VLAN tag mismatch: expected {args.expected_vlan_tag}, got {actual_vlan} in net0={net0!r}"
            )
        cloudinit_present = any(
            isinstance(value, str) and "cloudinit" in value
            for value in clone_config.values()
        )
        if not cloudinit_present:
            raise RuntimeError(
                "Clone does not appear cloud-init capable; refusing to rely on injected SSH keys"
            )
        log_step("clone-network-validated", net0=net0)

        cloudinit_result = client.cloudinit_set(
            clone_vm_node,
            clone_vm_vmid,
            {
                "ciuser": args.cloudinit_user,
                "sshkeys": quote(public_key, safe=""),
            },
        )
        cloudinit_status = wait_for_task_if_present(
            client,
            cloudinit_result.get("upid"),
            node=clone_vm_node,
            timeout=args.task_timeout,
            poll_interval=args.poll_interval,
        )
        log_step("cloudinit-updated", result=cloudinit_result, status=cloudinit_status)

        start_upid = client.start_vm(clone_vm_node, clone_vm_vmid)
        start_status = client.wait_task(
            start_upid,
            node=clone_vm_node,
            timeout=args.task_timeout,
            poll_interval=args.poll_interval,
        )
        log_step("started", upid=start_upid, status=start_status)

        ip_address = client.wait_for_vm_ip(
            clone_vm_node,
            clone_vm_vmid,
            timeout=args.ssh_timeout,
            poll_interval=5.0,
        )
        resources.guest_ip = ip_address
        wait_for_ssh(ip_address, args.ssh_timeout)
        log_step("guest-ip", ip_address=ip_address)

        if not args.skip_cloud_init_wait:
            wait_for_ssh_command(
                resources,
                ssh_user=args.ssh_user,
                ip_address=ip_address,
                command="cloud-init status --wait",
                timeout=args.ssh_timeout,
                description="cloud-init status --wait",
            )
            log_step("cloud-init-settled")

        baseline_result = ensure_ssh_ok(
            resources,
            ssh_user=args.ssh_user,
            ip_address=ip_address,
            command="echo guest-ready && uname -a && lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT",
            timeout=args.ssh_timeout,
            description="baseline guest readiness",
        )
        log_step(
            "baseline guest readiness",
            stdout=baseline_result.stdout.strip()[:500],
            stderr=baseline_result.stderr.strip()[:200],
        )
        baseline_lsblk = ensure_ssh_ok(
            resources,
            ssh_user=args.ssh_user,
            ip_address=ip_address,
            command="lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT",
            timeout=args.ssh_timeout,
            description="baseline lsblk",
        )
        baseline_count, baseline_disks = parse_lsblk_json(baseline_lsblk.stdout)
        log_step("baseline-disks", disk_count=baseline_count, disks=baseline_disks)
        baseline_disk_names = {str(disk.get("name") or "") for disk in baseline_disks}

        maybe_run_product_command(
            resources,
            ssh_user=args.ssh_user,
            ip_address=ip_address,
            command=args.install_command,
            timeout=args.ssh_timeout,
            description="install-command",
        )
        maybe_run_product_command(
            resources,
            ssh_user=args.ssh_user,
            ip_address=ip_address,
            command=args.test_command,
            timeout=args.ssh_timeout,
            description="baseline-test-command",
        )

        for index in range(args.data_disk_count):
            add_result = client.add_vm_disk(
                clone_vm_node,
                clone_vm_vmid,
                interface="scsi",
                storage=client.default_storage,
                size_gb=args.data_disk_size_gb,
                format="raw",
            )
            resources.created_disk_devices.append(str(add_result["device"]))
            resources.created_disk_configs[str(add_result["device"])] = str(
                add_result["config"]
            )
            add_status = wait_for_task_if_present(
                client,
                add_result.get("upid"),
                node=clone_vm_node,
                timeout=args.task_timeout,
                poll_interval=args.poll_interval,
            )
            log_step(
                "disk-added", index=index + 1, result=add_result, status=add_status
            )

        after_attach_count, after_attach_disks = wait_for_expected_disk_count(
            resources,
            ssh_user=args.ssh_user,
            ip_address=ip_address,
            timeout=args.ssh_timeout,
            expected_count=baseline_count + args.data_disk_count,
        )
        expected_attach_count = baseline_count + args.data_disk_count
        log_step(
            "after-attach-verify",
            disk_count=after_attach_count,
            disks=after_attach_disks,
        )
        test_disk_names = {
            str(disk.get("name") or "")
            for disk in after_attach_disks
            if str(disk.get("name") or "") not in baseline_disk_names
        }
        if len(test_disk_names) != args.data_disk_count:
            raise RuntimeError(
                f"Expected to identify {args.data_disk_count} guest data disks, found {sorted(test_disk_names)}"
            )
        maybe_run_product_command(
            resources,
            ssh_user=args.ssh_user,
            ip_address=ip_address,
            command=args.test_command,
            timeout=args.ssh_timeout,
            description="post-attach-test-command",
        )
        maybe_run_product_command(
            resources,
            ssh_user=args.ssh_user,
            ip_address=ip_address,
            command=args.pre_detach_command,
            timeout=args.ssh_timeout,
            description="pre-detach-command",
        )
        current_count, current_disks = verify_disk_count_over_ssh(
            resources,
            ssh_user=args.ssh_user,
            ip_address=ip_address,
            timeout=args.ssh_timeout,
        )
        if current_count != expected_attach_count:
            raise RuntimeError(
                f"Guest disk count changed before detach; expected {expected_attach_count}, got {current_count}"
            )
        ensure_test_disks_quiescent(current_disks, test_disk_names)

        detached_device = resources.created_disk_devices[0]
        detach_result = client.detach_vm_disk(
            clone_vm_node, clone_vm_vmid, device=detached_device
        )
        detach_status = wait_for_task_if_present(
            client,
            detach_result.get("upid"),
            node=clone_vm_node,
            timeout=args.task_timeout,
            poll_interval=args.poll_interval,
        )
        resources.detached_unused_device = detach_result.get("retained_as")
        resources.detached_unused_config = detach_result.get("previous_config")
        log_step("disk-detached", result=detach_result, status=detach_status)

        replacement_result = client.add_vm_disk(
            clone_vm_node,
            clone_vm_vmid,
            interface="scsi",
            storage=client.default_storage,
            size_gb=args.data_disk_size_gb,
            format="raw",
        )
        resources.created_disk_devices.append(str(replacement_result["device"]))
        resources.created_disk_configs[str(replacement_result["device"])] = str(
            replacement_result["config"]
        )
        replacement_status = wait_for_task_if_present(
            client,
            replacement_result.get("upid"),
            node=clone_vm_node,
            timeout=args.task_timeout,
            poll_interval=args.poll_interval,
        )
        log_step(
            "replacement-disk-added",
            result=replacement_result,
            status=replacement_status,
        )

        unused_disks = client.list_vm_unused_disks(clone_vm_node, clone_vm_vmid)
        detached_unused = resources.detached_unused_device
        if not detached_unused or detached_unused not in unused_disks:
            raise RuntimeError(
                "Detached disk did not appear under unused disks as expected"
            )
        if resources.detached_unused_config and disk_volume_identity(
            unused_disks[detached_unused]["config"]
        ) != disk_volume_identity(resources.detached_unused_config):
            raise RuntimeError(
                "Detached unused disk config does not match the disk created during this run"
            )

        if prompt_yes_no(
            f"Delete detached test disk {detached_unused} on VM {clone_vm_vmid}?",
            assume_yes=args.yes_delete_disk,
        ):
            delete_disk_result = client.delete_vm_disk_volume(
                clone_vm_node,
                clone_vm_vmid,
                device=detached_unused,
                timeout=args.task_timeout,
                poll_interval=args.poll_interval,
            )
            delete_disk_status = wait_for_task_if_present(
                client,
                delete_disk_result.get("delete_upid"),
                node=clone_vm_node,
                timeout=args.task_timeout,
                poll_interval=args.poll_interval,
            )
            log_step(
                "detached-disk-deleted",
                result=delete_disk_result,
                status=delete_disk_status,
            )
        else:
            raise RuntimeError(
                "Detached disk deletion was declined; stopping before destructive action"
            )

        final_count, final_disks = wait_for_expected_disk_count(
            resources,
            ssh_user=args.ssh_user,
            ip_address=ip_address,
            timeout=args.ssh_timeout,
            expected_count=baseline_count + args.data_disk_count,
        )
        expected_final_count = baseline_count + args.data_disk_count
        log_step("after-disk-cycle-verify", disk_count=final_count, disks=final_disks)
        maybe_run_product_command(
            resources,
            ssh_user=args.ssh_user,
            ip_address=ip_address,
            command=args.test_command,
            timeout=args.ssh_timeout,
            description="post-disk-cycle-test-command",
        )

        if not args.skip_snapshot_cycle:
            snapshot_name = (
                f"{args.snapshot_name_prefix}-{clone_vm_vmid}-{int(time.time())}"
            )
            snapshot_marker_path = f"/var/tmp/{snapshot_name}.txt"
            snapshot_marker_before = f"before-rollback-{snapshot_name}"
            snapshot_marker_after = f"after-rollback-{snapshot_name}"
            ensure_ssh_ok(
                resources,
                ssh_user=args.ssh_user,
                ip_address=ip_address,
                command=(
                    f"printf %s {shlex.quote(snapshot_marker_before)} | "
                    f"sudo tee {shlex.quote(snapshot_marker_path)} >/dev/null"
                ),
                timeout=args.ssh_timeout,
                description="prepare rollback marker",
            )
            snapshot_upid = client.create_snapshot(
                clone_vm_node,
                clone_vm_vmid,
                name=snapshot_name,
                description="Disposable live smoke snapshot",
                vmstate=False,
            )
            snapshot_status = wait_for_task_if_present(
                client,
                snapshot_upid,
                node=clone_vm_node,
                timeout=args.task_timeout,
                poll_interval=args.poll_interval,
            )
            resources.snapshot_names.append(snapshot_name)
            snapshot_names = require_snapshot_state(
                client,
                node=clone_vm_node,
                vmid=clone_vm_vmid,
                snapshot_name=snapshot_name,
                should_exist=True,
            )
            log_step(
                "snapshot-created",
                snapshot_name=snapshot_name,
                upid=snapshot_upid,
                status=snapshot_status,
                snapshots=sorted(snapshot_names),
            )

            ensure_ssh_ok(
                resources,
                ssh_user=args.ssh_user,
                ip_address=ip_address,
                command=(
                    f"printf %s {shlex.quote(snapshot_marker_after)} | "
                    f"sudo tee {shlex.quote(snapshot_marker_path)} >/dev/null"
                ),
                timeout=args.ssh_timeout,
                description="mutate rollback marker",
            )
            mutated_marker = ensure_ssh_ok(
                resources,
                ssh_user=args.ssh_user,
                ip_address=ip_address,
                command=f"sudo cat {shlex.quote(snapshot_marker_path)}",
                timeout=args.ssh_timeout,
                description="verify mutated rollback marker",
            )
            if mutated_marker.stdout.strip() != snapshot_marker_after:
                raise RuntimeError(
                    "Rollback marker did not update before rollback snapshot test"
                )

            rollback_stop_upid = client.stop_vm(
                clone_vm_node,
                clone_vm_vmid,
                overrule_shutdown=True,
                timeout=120,
            )
            rollback_stop_status = wait_for_task_if_present(
                client,
                rollback_stop_upid,
                node=clone_vm_node,
                timeout=600,
                poll_interval=args.poll_interval,
            )
            rollback_stop_vm_status = wait_for_vm_status(
                client,
                vmid=clone_vm_vmid,
                expected_status="stopped",
                timeout=60,
                poll_interval=args.poll_interval,
            )
            log_step(
                "stopped-for-rollback",
                upid=rollback_stop_upid,
                status=rollback_stop_status,
                vm_status=rollback_stop_vm_status,
            )

            rollback_upid = client.rollback_snapshot(
                clone_vm_node,
                clone_vm_vmid,
                snapshot_name,
            )
            rollback_status = wait_for_task_if_present(
                client,
                rollback_upid,
                node=clone_vm_node,
                timeout=args.task_timeout,
                poll_interval=args.poll_interval,
            )
            rollback_vm_status = wait_for_vm_status(
                client,
                vmid=clone_vm_vmid,
                expected_status="stopped",
                timeout=60,
                poll_interval=args.poll_interval,
            )
            log_step(
                "snapshot-rolled-back",
                snapshot_name=snapshot_name,
                upid=rollback_upid,
                status=rollback_status,
                vm_status=rollback_vm_status,
            )

            rollback_restart_upid = client.start_vm(clone_vm_node, clone_vm_vmid)
            rollback_restart_status = client.wait_task(
                rollback_restart_upid,
                node=clone_vm_node,
                timeout=args.task_timeout,
                poll_interval=args.poll_interval,
            )
            log_step(
                "restarted-after-rollback",
                upid=rollback_restart_upid,
                status=rollback_restart_status,
            )

            ip_address = client.wait_for_vm_ip(
                clone_vm_node,
                clone_vm_vmid,
                timeout=args.ssh_timeout,
                poll_interval=5.0,
            )
            resources.guest_ip = ip_address
            wait_for_ssh(ip_address, args.ssh_timeout)
            log_step("guest-ip-after-rollback", ip_address=ip_address)

            restored_marker = wait_for_ssh_command(
                resources,
                ssh_user=args.ssh_user,
                ip_address=ip_address,
                command=f"sudo cat {shlex.quote(snapshot_marker_path)}",
                timeout=args.ssh_timeout,
                description="verify rollback marker restored",
            )
            if restored_marker.stdout.strip() != snapshot_marker_before:
                raise RuntimeError(
                    "Rollback snapshot did not restore the expected guest marker content"
                )
            log_step(
                "rollback-verified",
                snapshot_name=snapshot_name,
                marker_path=snapshot_marker_path,
                marker_value=restored_marker.stdout.strip(),
            )
            maybe_run_product_command(
                resources,
                ssh_user=args.ssh_user,
                ip_address=ip_address,
                command=args.test_command,
                timeout=args.ssh_timeout,
                description="post-rollback-test-command",
            )

            delete_snapshot_upid = client.delete_snapshot(
                clone_vm_node,
                clone_vm_vmid,
                snapshot_name,
            )
            delete_snapshot_status = wait_for_task_if_present(
                client,
                delete_snapshot_upid,
                node=clone_vm_node,
                timeout=args.task_timeout,
                poll_interval=args.poll_interval,
            )
            snapshot_names = require_snapshot_state(
                client,
                node=clone_vm_node,
                vmid=clone_vm_vmid,
                snapshot_name=snapshot_name,
                should_exist=False,
            )
            log_step(
                "snapshot-deleted",
                snapshot_name=snapshot_name,
                upid=delete_snapshot_upid,
                status=delete_snapshot_status,
                snapshots=sorted(snapshot_names),
            )

        if not args.skip_stop_cycle:
            stop_upid = client.stop_vm(
                clone_vm_node,
                clone_vm_vmid,
                overrule_shutdown=True,
                timeout=120,
            )
            stop_status = wait_for_task_if_present(
                client,
                stop_upid,
                node=clone_vm_node,
                timeout=600,
                poll_interval=args.poll_interval,
            )
            post_stop_vm_status = wait_for_vm_status(
                client,
                vmid=clone_vm_vmid,
                expected_status="stopped",
                timeout=60,
                poll_interval=args.poll_interval,
            )
            log_step(
                "force-stopped",
                upid=stop_upid,
                status=stop_status,
                vm_status=post_stop_vm_status,
            )

            restart_upid = client.start_vm(clone_vm_node, clone_vm_vmid)
            restart_status = client.wait_task(
                restart_upid,
                node=clone_vm_node,
                timeout=args.task_timeout,
                poll_interval=args.poll_interval,
            )
            log_step("restarted-after-stop", upid=restart_upid, status=restart_status)

            ip_address = client.wait_for_vm_ip(
                clone_vm_node,
                clone_vm_vmid,
                timeout=args.ssh_timeout,
                poll_interval=5.0,
            )
            resources.guest_ip = ip_address
            wait_for_ssh(ip_address, args.ssh_timeout)
            log_step("guest-ip-after-stop-cycle", ip_address=ip_address)

            restarted_ready = wait_for_ssh_command(
                resources,
                ssh_user=args.ssh_user,
                ip_address=ip_address,
                command="echo restart-ready && uname -a",
                timeout=args.ssh_timeout,
                description="post-stop-cycle guest readiness",
            )
            log_step(
                "post-stop-cycle readiness",
                stdout=restarted_ready.stdout.strip()[:500],
                stderr=restarted_ready.stderr.strip()[:200],
            )
            restarted_lsblk = ensure_ssh_ok(
                resources,
                ssh_user=args.ssh_user,
                ip_address=ip_address,
                command="lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT",
                timeout=args.ssh_timeout,
                description="post-stop-cycle lsblk",
            )
            restarted_count, restarted_disks = parse_lsblk_json(restarted_lsblk.stdout)
            if restarted_count != expected_final_count:
                raise RuntimeError(
                    f"Expected {expected_final_count} guest disks after stop/start cycle, got {restarted_count}: {restarted_disks}"
                )
            log_step(
                "after-stop-cycle-verify",
                disk_count=restarted_count,
                disks=restarted_disks,
            )
            maybe_run_product_command(
                resources,
                ssh_user=args.ssh_user,
                ip_address=ip_address,
                command=args.test_command,
                timeout=args.ssh_timeout,
                description="post-stop-cycle-test-command",
            )

        shutdown_upid = client.shutdown_vm(clone_vm_node, clone_vm_vmid, timeout=120)
        shutdown_status = wait_for_task_if_present(
            client,
            shutdown_upid,
            node=clone_vm_node,
            timeout=600,
            poll_interval=args.poll_interval,
        )
        try:
            final_vm_status = wait_for_vm_status(
                client,
                vmid=clone_vm_vmid,
                expected_status="stopped",
                timeout=60,
                poll_interval=args.poll_interval,
            )
        except RuntimeError:
            final_stop_upid = client.stop_vm(
                clone_vm_node,
                clone_vm_vmid,
                overrule_shutdown=True,
                timeout=120,
            )
            final_stop_status = wait_for_task_if_present(
                client,
                final_stop_upid,
                node=clone_vm_node,
                timeout=600,
                poll_interval=args.poll_interval,
            )
            final_vm_status = wait_for_vm_status(
                client,
                vmid=clone_vm_vmid,
                expected_status="stopped",
                timeout=60,
                poll_interval=args.poll_interval,
            )
            log_step(
                "shutdown-fallback-stop",
                upid=final_stop_upid,
                status=final_stop_status,
                vm_status=final_vm_status,
            )
        log_step(
            "shutdown-complete",
            upid=shutdown_upid,
            status=shutdown_status,
            vm_status=final_vm_status,
        )

        if args.keep_vm_on_success:
            log_step("kept-vm-for-inspection", vmid=clone_vm_vmid, name=vm_name)
            return 0

        if prompt_yes_no(
            f"Delete disposable VM {clone_vm_vmid} ({vm_name}) and its owned test disks?",
            assume_yes=args.yes_delete_vm,
        ):
            delete_upid = client.delete_vm(clone_vm_node, clone_vm_vmid, purge=True)
            delete_status = wait_for_task_if_present(
                client,
                delete_upid,
                node=clone_vm_node,
                timeout=args.task_timeout,
                poll_interval=args.poll_interval,
            )
            resources.vm_deleted = True
            log_step("vm-deleted", upid=delete_upid, status=delete_status)

            remaining_storage_entries = [
                item
                for item in client.storage_content(
                    clone_vm_node, client.default_storage
                )
                if f"vm-{clone_vm_vmid}-" in str(item.get("volid", ""))
            ]
            if remaining_storage_entries:
                raise RuntimeError(
                    f"Found remaining storage entries for deleted VM {clone_vm_vmid}: {remaining_storage_entries}"
                )
            log_step("cleanup-verified", vmid=clone_vm_vmid)
        else:
            raise RuntimeError(
                "Disposable VM deletion was declined; leaving VM for manual inspection"
            )

        return 0
    except Exception as exc:
        log_step("error", error=str(exc), vmid=resources.vmid, name=resources.vm_name)
        if args.cleanup_on_failure:
            try:
                best_effort_cleanup(
                    client,
                    resources,
                    name_prefix=args.name_prefix,
                    timeout=args.task_timeout,
                    poll_interval=args.poll_interval,
                )
            except Exception as cleanup_exc:
                log_step(
                    "cleanup-error",
                    error=str(cleanup_exc),
                    vmid=resources.vmid,
                    name=resources.vm_name,
                )
        if resources.temp_dir and not resources.vm_deleted:
            log_step(
                "preserved-temp-keys",
                temp_dir=str(resources.temp_dir),
                private_key=str(resources.private_key_path)
                if resources.private_key_path
                else None,
                public_key=str(resources.public_key_path)
                if resources.public_key_path
                else None,
            )
        return 1
    finally:
        cleanup_temp_keys(resources)


if __name__ == "__main__":
    raise SystemExit(main())
