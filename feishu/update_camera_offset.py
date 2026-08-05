"""CLI and orchestration: update cameraOffsetTheta in Feishu Bitable by SN."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from feishu.bitable import search_record_by_sn, update_camera_offset_theta
from feishu.client import FeishuClient
from feishu.config import FeishuSettings, load_dotenv_if_present
from feishu.errors import FeishuApiError
from feishu.wiki import get_bitable_app_token


def run_update(
    settings: FeishuSettings,
    *,
    sn: str,
    theta: float,
    view_id: str | None = None,
) -> dict[str, Any]:
    """
    Execute the four-step Feishu flow; return update API response data.

    ``sn`` matches the Bitable S/N column (Web UI frame number / 车架号),
    default ``S/N*`` (override with ``FEISHU_SN_FIELD``).
    """
    resolved_view_id = (view_id or settings.view_id).strip()
    if not resolved_view_id:
        raise ValueError("view_id is required (set FEISHU_VIEW_ID or pass view_id).")

    with FeishuClient(settings.app_id, settings.app_secret) as client:
        app_token = get_bitable_app_token(
            client,
            settings.wiki_token,
            obj_type=settings.obj_type,
        )
        record_id = search_record_by_sn(
            client,
            app_token,
            settings.table_id,
            resolved_view_id,
            sn,
            sn_field=settings.sn_field,
            theta_field=settings.theta_field,
        )
        result = update_camera_offset_theta(
            client,
            app_token,
            settings.table_id,
            record_id,
            theta,
            theta_field=settings.theta_field,
        )
    return {
        "app_token": app_token,
        "record_id": record_id,
        "sn": sn,
        "theta": theta,
        "field": settings.theta_field,
        "sn_field": settings.sn_field,
        "update": result.get("data", {}),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Update cameraOffsetTheta in Feishu Bitable for a device S/N "
            "(default column S/N*; override with FEISHU_SN_FIELD)."
        ),
    )
    parser.add_argument(
        "--sn",
        required=True,
        help="Device serial number (matches Bitable S/N column, default S/N*).",
    )
    parser.add_argument(
        "--view-id",
        default=None,
        help="Bitable view_id (defaults to FEISHU_VIEW_ID from .env).",
    )
    parser.add_argument(
        "--theta",
        type=float,
        required=True,
        help="cameraOffsetTheta value in degrees.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv_if_present()
    args = _build_parser().parse_args(argv)

    try:
        settings = FeishuSettings.from_env()
        summary = run_update(
            settings,
            sn=args.sn.strip(),
            theta=args.theta,
            view_id=args.view_id.strip() if args.view_id else None,
        )
    except ValueError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 1
    except FeishuApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        f"已更新 record_id={summary['record_id']} "
        f"{summary['sn_field']}={summary['sn']!r} "
        f"{summary['field']}={summary['theta']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
