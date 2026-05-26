"""Wiki API: resolve Bitable app_token from a knowledge-base node token."""

from __future__ import annotations

from feishu.client import FeishuClient
from feishu.errors import FeishuApiError


def get_bitable_app_token(
    client: FeishuClient,
    wiki_token: str,
    *,
    obj_type: str = "wiki",
) -> str:
    """Return Bitable app_token (obj_token) for a wiki node."""
    data = client.request(
        "GET",
        "/wiki/v2/spaces/get_node",
        step="get_node",
        params={"token": wiki_token, "obj_type": obj_type},
    )
    node = data.get("data", {}).get("node") or {}
    obj_token = node.get("obj_token")
    node_obj_type = node.get("obj_type")

    if not obj_token:
        raise FeishuApiError.business(
            "get_node", "响应中未包含 obj_token"
        )
    if node_obj_type != "bitable":
        raise FeishuApiError.business(
            "get_node",
            f"该知识库节点不是多维表格（obj_type={node_obj_type!r}）",
        )
    return str(obj_token)
