from __future__ import annotations

from typing import Any

from proxmox_mcp.client import ProxmoxClient


class _FakeExecEndpoint:
    def __init__(self) -> None:
        self.post_calls: list[dict[str, Any]] = []

    def post(self, **kwargs: Any) -> dict[str, Any]:
        self.post_calls.append(kwargs)
        return {"pid": 4321}


class _FakeExecStatusEndpoint:
    def __init__(self) -> None:
        self.get_calls: list[dict[str, Any]] = []
        self.responses = [
            {"exited": 0},
            {"exited": 1, "exitcode": 0, "out-data": "ok\n"},
        ]

    def get(self, **kwargs: Any) -> dict[str, Any]:
        self.get_calls.append(kwargs)
        return self.responses.pop(0)


class _FakeAgent:
    def __init__(self) -> None:
        self.exec = _FakeExecEndpoint()
        self._exec_status = _FakeExecStatusEndpoint()

    def __call__(self, endpoint: str) -> Any:
        if endpoint == "exec-status":
            return self._exec_status
        raise AssertionError(f"unexpected agent endpoint: {endpoint}")


class _FakeQemuVm:
    def __init__(self) -> None:
        self.agent = _FakeAgent()


class _FakeQemuCollection:
    def __init__(self) -> None:
        self.vm = _FakeQemuVm()

    def __call__(self, vmid: int) -> _FakeQemuVm:
        return self.vm


class _FakeNode:
    def __init__(self) -> None:
        self.qemu = _FakeQemuCollection()


class _FakeNodes:
    def __init__(self) -> None:
        self.node = _FakeNode()

    def __call__(self, node: str) -> _FakeNode:
        return self.node


class _FakeApi:
    def __init__(self) -> None:
        self.nodes = _FakeNodes()


def _build_client() -> tuple[ProxmoxClient, _FakeAgent]:
    client = ProxmoxClient.__new__(ProxmoxClient)
    client._api = _FakeApi()
    agent = client._api.nodes("pve").qemu(101).agent
    return client, agent


def test_qga_exec_posts_expected_payload() -> None:
    client, agent = _build_client()

    result = client.qga_exec("pve", 101, command="bash", args=["-lc", "echo hi"])

    assert result == {"pid": 4321}
    assert agent.exec.post_calls[-1] == {"command": "bash", "args": ["-lc", "echo hi"]}


def test_qga_exec_wait_polls_until_exit(monkeypatch) -> None:
    client, agent = _build_client()
    monkeypatch.setattr("proxmox_mcp.client.time.sleep", lambda _: None)

    result = client.qga_exec_wait("pve", 101, pid=4321, timeout=5, poll_interval=0.01)

    assert result["exitcode"] == 0
    assert result["out-data"] == "ok\n"
    assert agent._exec_status.get_calls == [{"pid": 4321}, {"pid": 4321}]
