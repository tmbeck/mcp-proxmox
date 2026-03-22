from __future__ import annotations

from typing import Any, cast

from proxmox_mcp.client import ProxmoxClient


class _FakeStatusEndpoint:
    def __init__(self, result: Any) -> None:
        self.result = result

    def get(self) -> Any:
        return self.result


class _FakeTaskResource:
    def __init__(self, result: Any) -> None:
        self.status = _FakeStatusEndpoint(result)


class _FakeClusterTasks:
    def __init__(self, result: Any) -> None:
        self.result = result

    def __call__(self, upid: str) -> _FakeTaskResource:
        return _FakeTaskResource(self.result)


class _FakeNodeTasks:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.list_result: Any = []

    def __call__(self, upid: str) -> _FakeTaskResource:
        return _FakeTaskResource(self.result)

    def get(self, **kwargs: Any) -> Any:
        return self.list_result


class _FakeNode:
    def __init__(self, result: Any, list_result: Any) -> None:
        self.tasks = _FakeNodeTasks(result)
        self.tasks.list_result = list_result


class _FakeNodes:
    def __init__(self, result: Any, list_result: Any) -> None:
        self.result = result
        self.list_result = list_result

    def __call__(self, node: str) -> _FakeNode:
        return _FakeNode(self.result, self.list_result)


class _FakeCluster:
    def __init__(self, result: Any) -> None:
        self.tasks = _FakeClusterTasks(result)


class _FakeApi:
    def __init__(
        self, cluster_result: Any, node_result: Any, node_list_result: Any = None
    ) -> None:
        self.cluster = _FakeCluster(cluster_result)
        self.nodes = _FakeNodes(node_result, node_list_result)


def test_task_status_falls_back_to_node_lookup_when_cluster_result_is_not_mapping() -> (
    None
):
    client = ProxmoxClient.__new__(ProxmoxClient)
    client._api = cast(
        Any, _FakeApi(cluster_result=[], node_result={"status": "stopped"})
    )

    result = client.task_status("UPID:test", node="pve1")

    assert result == {"status": "stopped"}


def test_task_status_falls_back_to_node_task_list_when_status_endpoint_is_not_mapping() -> (
    None
):
    client = ProxmoxClient.__new__(ProxmoxClient)
    client._api = cast(
        Any,
        _FakeApi(
            cluster_result=[],
            node_result=[],
            node_list_result=[
                {"upid": "UPID:test", "status": "stopped", "exitstatus": "OK"}
            ],
        ),
    )

    result = client.task_status("UPID:test", node="pve1")

    assert result == {"upid": "UPID:test", "status": "stopped", "exitstatus": "OK"}
