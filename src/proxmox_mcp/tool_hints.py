from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations


READ_ONLY_QUERY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

DATA_LOSS_TOOL_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)


def conditional_data_loss_meta(
    warning: str,
    *,
    parameter: str,
    values: list[Any],
) -> dict[str, Any]:
    return {
        "proxmox": {
            "data_loss_warning": warning,
            "destructive_when": {
                "parameter": parameter,
                "values": values,
            },
        }
    }
