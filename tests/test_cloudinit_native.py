from __future__ import annotations

from pathlib import Path
from typing import Any

from proxmox_mcp.client import ProxmoxClient
from proxmox_mcp.cloudinit import CloudInitConfig


def _build_client() -> ProxmoxClient:
    client = ProxmoxClient.__new__(ProxmoxClient)
    client.default_storage = "local-lvm"
    client.default_bridge = "vmbr0"
    return client


def test_cloudinit_config_maps_simple_user_and_network_to_native_params() -> None:
    config = CloudInitConfig("ubuntu-22.04")
    config.add_user("ubuntu", ["ssh-ed25519 AAAA"], passwd="secret-pass")
    config.set_network_config(
        dhcp=False,
        ip="10.0.0.25/24",
        gateway="10.0.0.1",
        nameservers=["1.1.1.1", "8.8.8.8"],
    )

    payload = config.to_proxmox_payload()

    assert payload.native_params == {
        "ciuser": "ubuntu",
        "cipassword": "secret-pass",
        "sshkeys": "ssh-ed25519 AAAA",
        "ipconfig0": "ip=10.0.0.25/24,gw=10.0.0.1",
        "nameserver": "1.1.1.1 8.8.8.8",
    }
    assert payload.custom_user_data is None


def test_cloudinit_config_generates_custom_user_data_for_advanced_settings() -> None:
    config = CloudInitConfig("ubuntu-22.04")
    config.set_hostname("web-01")
    config.add_packages(["nginx"])
    config.add_commands(["systemctl enable nginx"])

    payload = config.to_proxmox_payload()

    assert payload.native_params == {}
    assert payload.custom_user_data is not None
    assert "hostname: web-01" in payload.custom_user_data
    assert "- nginx" in payload.custom_user_data
    assert "systemctl enable nginx" in payload.custom_user_data


def test_apply_cloudinit_config_uploads_user_data_snippet(monkeypatch) -> None:
    client = _build_client()
    upload_calls: list[dict[str, Any]] = []
    wait_calls: list[dict[str, Any]] = []
    configure_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        client,
        "ensure_cloudinit_drive",
        lambda node, vmid, storage=None: {"present": True, "device": "ide2"},
    )

    def fake_upload_snippet(node: str, storage: str, file_path: str) -> str:
        upload_calls.append(
            {
                "node": node,
                "storage": storage,
                "file_name": Path(file_path).name,
                "content": Path(file_path).read_text(encoding="utf-8"),
            }
        )
        return "UPID:upload"

    def fake_wait_task(
        upid: str,
        node: str | None = None,
        timeout: int = 0,
        poll_interval: float = 0.0,
    ) -> dict[str, Any]:
        wait_calls.append(
            {
                "upid": upid,
                "node": node,
                "timeout": timeout,
                "poll_interval": poll_interval,
            }
        )
        return {"status": "stopped"}

    def fake_configure_vm(
        node: str, vmid: int, params: dict[str, Any]
    ) -> dict[str, Any]:
        configure_calls.append({"node": node, "vmid": vmid, "params": params})
        return {"upid": "UPID:config"}

    monkeypatch.setattr(client, "upload_snippet", fake_upload_snippet)
    monkeypatch.setattr(client, "wait_task", fake_wait_task)
    monkeypatch.setattr(client, "configure_vm", fake_configure_vm)

    result = client.apply_cloudinit_config(
        "pve1",
        101,
        cloudinit_params={"ciuser": "ubuntu"},
        user_data="#cloud-config\npackages:\n- nginx\n",
        snippet_storage="local",
    )

    assert upload_calls[0]["storage"] == "local"
    assert "packages:" in upload_calls[0]["content"]
    assert configure_calls[0]["params"]["ciuser"] == "ubuntu"
    assert configure_calls[0]["params"]["cicustom"].startswith("user=local:snippets/")
    assert wait_calls == [
        {
            "upid": "UPID:upload",
            "node": "pve1",
            "timeout": 900,
            "poll_interval": 2.0,
        }
    ]
    assert result["upid"] == "UPID:config"


def test_create_cloudinit_vm_clones_template_before_resize(monkeypatch) -> None:
    client = _build_client()
    clone_calls: list[dict[str, Any]] = []
    apply_calls: list[dict[str, Any]] = []
    wait_calls: list[dict[str, Any]] = []
    resize_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        client,
        "resolve_vm_template",
        lambda template, node=None: (
            9000,
            "pve1",
            {"name": "ubuntu-template", "template": 1},
        ),
    )

    def fake_clone_vm(**kwargs: Any) -> str:
        clone_calls.append(kwargs)
        return "UPID:clone"

    def fake_apply_cloudinit_config(
        node: str,
        vmid: int,
        *,
        cloudinit_params: dict[str, Any] | None = None,
        user_data: str | None = None,
        storage: str | None = None,
        snippet_storage: str | None = None,
        timeout: int = 0,
        poll_interval: float = 0.0,
    ) -> dict[str, Any]:
        apply_calls.append(
            {
                "node": node,
                "vmid": vmid,
                "cloudinit_params": cloudinit_params,
                "user_data": user_data,
                "storage": storage,
                "snippet_storage": snippet_storage,
                "timeout": timeout,
                "poll_interval": poll_interval,
            }
        )
        return {"upid": "UPID:config"}

    def fake_wait_task(
        upid: str,
        node: str | None = None,
        timeout: int = 0,
        poll_interval: float = 0.0,
    ) -> dict[str, Any]:
        wait_calls.append(
            {
                "upid": upid,
                "node": node,
                "timeout": timeout,
                "poll_interval": poll_interval,
            }
        )
        return {"status": "stopped"}

    def fake_resize_vm_disk(node: str, vmid: int, disk: str, size_gb: int) -> str:
        resize_calls.append(
            {"node": node, "vmid": vmid, "disk": disk, "size_gb": size_gb}
        )
        return "UPID:resize"

    monkeypatch.setattr(client, "clone_vm", fake_clone_vm)
    monkeypatch.setattr(client, "apply_cloudinit_config", fake_apply_cloudinit_config)
    monkeypatch.setattr(client, "wait_task", fake_wait_task)
    monkeypatch.setattr(client, "_get_primary_disk", lambda node, vmid: ("scsi0", 8))
    monkeypatch.setattr(client, "resize_vm_disk", fake_resize_vm_disk)

    result = client.create_cloudinit_vm(
        node="pve1",
        vmid=101,
        name="web-01",
        template="9000",
        cores=4,
        memory_mb=4096,
        disk_gb=20,
        bridge="vmbr1",
        cloudinit_params={"ciuser": "ubuntu"},
    )

    assert clone_calls == [
        {
            "source_node": "pve1",
            "source_vmid": 9000,
            "target_node": "pve1",
            "new_vmid": 101,
            "name": "web-01",
            "full": True,
            "storage": None,
        }
    ]
    assert apply_calls[0]["cloudinit_params"] == {
        "ciuser": "ubuntu",
        "cores": 4,
        "memory": 4096,
        "net0": "virtio,bridge=vmbr1",
    }
    assert wait_calls == [
        {"upid": "UPID:clone", "node": "pve1", "timeout": 900, "poll_interval": 2.0},
        {"upid": "UPID:config", "node": "pve1", "timeout": 900, "poll_interval": 2.0},
    ]
    assert resize_calls == [
        {"node": "pve1", "vmid": 101, "disk": "scsi0", "size_gb": 12}
    ]
    assert result["upid"] == "UPID:resize"
