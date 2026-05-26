"""CLI and orchestration: update cameraOffsetTheta(°) in Feishu Bitable by S/N."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from feishu.bitable import search_record_by_sn, update_camera_offset_theta
from feishu.client import FeishuClient
from feishu.config import FeishuSettings, load_dotenv_if_present
from feishu.errors import FeishuApiError, THETA_FIELD
from feishu.wiki import get_bitable_app_token


def run_update(
    settings: FeishuSettings,
    *,
    sn: str,
    view_id: str,
    theta: float,
) -> dict[str, Any]:
    """Execute the four-step Feishu flow; return update API response data."""
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
            view_id,
            sn,
        )
        result = update_camera_offset_theta(
            client,
            app_token,
            settings.table_id,
            record_id,
            theta,
        )
    return {
        "app_token": app_token,
        "record_id": record_id,
        "sn": sn,
        "theta": theta,
        "field": THETA_FIELD,
        "update": result.get("data", {}),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Update cameraOffsetTheta(°) in Feishu Bitable for a device S/N.",
    )
    parser.add_argument(
        "--sn",
        required=True,
        help="Device serial number (matches Bitable column S/N*).",
    )
    parser.add_argument(
        "--view-id",
        required=True,
        help="Bitable view_id (from table URL).",
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
            view_id=args.view_id.strip(),
            theta=args.theta,
        )
    except ValueError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 1
    except FeishuApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(
        f"已更新 record_id={summary['record_id']} "
        f"S/N={summary['sn']!r} {THETA_FIELD}={summary['theta']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
