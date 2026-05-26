"""Feishu Open API error types and user-facing hints."""

from __future__ import annotations

# Field names must match the Bitable column headers exactly.
SN_FIELD = "S/N*"
MODEL_FIELD = "Model*"
THETA_FIELD = "cameraOffsetTheta(°)"

# Known API error codes -> Chinese hints (step name is appended in the message).
_CODE_HINTS: dict[int, str] = {
    99991672: (
        "应用未开通知识库 API 权限，请在开放平台为应用开通 "
        "wiki:node:read（或 wiki:wiki / wiki:wiki:readonly）并重新发布"
    ),
    131005: "wiki_token 无效或知识库节点不存在",
    131006: "应用无知识库节点阅读权限，请为应用授权该知识库文档",
    1254003: "app_token 错误，请检查 wiki 节点是否为多维表格",
    1254004: "table_id 错误",
    1254005: "view_id 错误",
    1254024: f"字段名不匹配，请核对表中列名（如 {SN_FIELD}）",
    1254045: f"字段名不存在或无权限，请核对 {SN_FIELD}、{THETA_FIELD}",
    1254060: f"{THETA_FIELD} 为文本列，应传字符串（如 \"0.1\"）",
    1254061: f"{THETA_FIELD} 为数字列，应传数值",
    1254302: "无多维表格编辑/高级权限，请为应用添加文档可管理权限",
}


class FeishuApiError(Exception):
    """Raised when a Feishu API returns code != 0 or business rules fail."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        msg: str | None = None,
        step: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.api_msg = msg
        self.step = step

    @classmethod
    def from_response(cls, step: str, code: int, msg: str) -> FeishuApiError:
        hint = _CODE_HINTS.get(code)
        if hint:
            text = f"[{step}] {hint}（code={code}, msg={msg}）"
        else:
            text = f"[{step}] 飞书 API 失败（code={code}, msg={msg}）"
        return cls(text, code=code, msg=msg, step=step)

    @classmethod
    def business(cls, step: str, message: str) -> FeishuApiError:
        return cls(f"[{step}] {message}", step=step)
