"""Bitable API: search records by SN and update cameraOffsetTheta."""

from __future__ import annotations

from typing import Any

from feishu.client import FeishuClient
from feishu.errors import SN_FIELD, THETA_FIELD, FeishuApiError

_TEXT_FIELD_CONV_FAIL = 1254060
_NUMBER_FIELD_CONV_FAIL = 1254061
_FIELD_CONV_FAIL_CODES = frozenset({_TEXT_FIELD_CONV_FAIL, _NUMBER_FIELD_CONV_FAIL})


def _theta_as_text(theta: float) -> str:
    """Format degrees for Bitable text columns (matches plan.md curl, e.g. \"0.1\")."""
    return f"{theta:g}"


def search_record_by_sn(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    view_id: str,
    sn: str,
    *,
    sn_field: str = SN_FIELD,
    theta_field: str = THETA_FIELD,
) -> str:
    """Find exactly one record by SN field; return record_id."""
    path = f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
    body: dict[str, Any] = {
        "automatic_fields": False,
        "field_names": [sn_field, theta_field],
        "filter": {
            "conjunction": "and",
            "conditions": [
                {
                    "field_name": sn_field,
                    "operator": "is",
                    "value": [sn],
                }
            ],
        },
        "sort": [{"field_name": sn_field, "desc": True}],
        "view_id": view_id,
    }

    data = client.request(
        "POST",
        path,
        step="search",
        params={"user_id_type": "user_id"},
        json_body=body,
    )
    items = data.get("data", {}).get("items") or []
    total = data.get("data", {}).get("total", len(items))

    if not items:
        raise FeishuApiError.business(
            "search",
            f"未找到 {sn_field}={sn!r} 的记录（total={total}）。"
            f"请检查序列号、高级权限及字段名（当前 SN={sn_field!r}, "
            f"theta={theta_field!r}）是否与表头完全一致。",
        )
    if len(items) > 1:
        raise FeishuApiError.business(
            "search",
            f"匹配到 {len(items)} 条 {sn_field}={sn!r} 的记录，拒绝更新以避免误写。",
        )

    record_id = items[0].get("record_id")
    if not record_id:
        raise FeishuApiError.business("search", "记录缺少 record_id")
    return str(record_id)


def update_camera_offset_theta(
    client: FeishuClient,
    app_token: str,
    table_id: str,
    record_id: str,
    theta: float,
    *,
    theta_field: str = THETA_FIELD,
) -> dict[str, Any]:
    """Update cameraOffsetTheta; try text then number to match column type."""
    path = (
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    )
    # plan.md used string "0.1"; many tables use text for this column.
    candidates: list[float | str] = [_theta_as_text(theta), theta]
    last_error: FeishuApiError | None = None
    for value in candidates:
        try:
            return _put_theta(client, path, theta_field, value)
        except FeishuApiError as exc:
            if exc.code in _FIELD_CONV_FAIL_CODES:
                last_error = exc
                continue
            raise
    if last_error is not None:
        raise last_error
    raise FeishuApiError.business("update", f"无法写入 {theta_field}")


def _put_theta(
    client: FeishuClient,
    path: str,
    theta_field: str,
    value: float | str,
) -> dict[str, Any]:
    return client.request(
        "PUT",
        path,
        step="update",
        json_body={"fields": {theta_field: value}},
    )
