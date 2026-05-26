"""HTTP client for Feishu Open APIs with tenant_access_token caching."""

from __future__ import annotations

import time
from typing import Any

import httpx

from feishu.errors import FeishuApiError

BASE_URL = "https://open.feishu.cn/open-apis"
AUTH_URL = f"{BASE_URL}/auth/v3/app_access_token/internal"
# Refresh when fewer than this many seconds remain before expiry.
_TOKEN_REFRESH_MARGIN_SEC = 25 * 60


class FeishuClient:
    """Shared HTTP session and access token cache."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._timeout = timeout
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._http = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> FeishuClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get_tenant_access_token(self) -> str:
        now = time.monotonic()
        if self._token and now < self._token_expires_at - _TOKEN_REFRESH_MARGIN_SEC:
            return self._token

        resp = self._http.post(
            AUTH_URL,
            json={"app_id": self._app_id, "app_secret": self._app_secret},
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        resp.raise_for_status()
        data = resp.json()
        code = data.get("code", -1)
        if code != 0:
            raise FeishuApiError.from_response(
                "auth",
                int(code),
                str(data.get("msg", "unknown")),
            )

        token = data.get("tenant_access_token") or data.get("app_access_token")
        if not token:
            raise FeishuApiError.business(
                "auth", "响应中未包含 tenant_access_token"
            )

        expire = int(data.get("expire", 7200))
        self._token = str(token)
        self._token_expires_at = now + expire
        return self._token

    def _parse_response(self, resp: httpx.Response, step: str) -> dict[str, Any]:
        """Parse Feishu JSON body; raise FeishuApiError instead of HTTPStatusError."""
        try:
            data = resp.json()
        except ValueError:
            if resp.is_success:
                raise FeishuApiError.business(
                    step, f"响应不是有效 JSON（HTTP {resp.status_code}）"
                ) from None
            raise FeishuApiError.business(
                step,
                f"HTTP {resp.status_code}: {resp.text[:200] or resp.reason_phrase}",
            ) from None

        code = data.get("code", -1)
        if code != 0:
            raise FeishuApiError.from_response(
                step,
                int(code),
                str(data.get("msg", "unknown")),
            )
        if not resp.is_success:
            raise FeishuApiError.business(
                step,
                f"HTTP {resp.status_code}: {data.get('msg', resp.reason_phrase)}",
            )
        return data

    def request(
        self,
        method: str,
        path: str,
        *,
        step: str,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = self.get_tenant_access_token()
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
        if json_body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"

        resp = self._http.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=headers,
        )
        return self._parse_response(resp, step)
