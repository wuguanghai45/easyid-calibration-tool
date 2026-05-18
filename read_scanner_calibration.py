#!/usr/bin/env python3
"""CLI tool for scanner calibration data collection."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read scanner config, result and image for factory calibration.",
    )
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--sn", help="Scanner serial number.")
    target_group.add_argument("--ip", help="Scanner IPv4 address.")

    parser.add_argument(
        "--output",
        default="./calibration_out",
        help="Base output directory.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=2000,
        help="Frame timeout in milliseconds.",
    )
    parser.add_argument(
        "--buffer-count",
        type=int,
        default=3,
        help="SDK frame buffer count for grabbing.",
    )
    parser.add_argument(
        "--no-clear-buffer",
        action="store_true",
        help="Do not call eidClearFrameBuffer before capture.",
    )
    parser.add_argument(
        "--dump-features",
        action="store_true",
        help="Dump feature tree candidates to feature_dump.json.",
    )
    return parser.parse_args()


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def make_session_dir(base_output: Path, identity: str) -> Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_identity = identity.replace(":", "_").replace("/", "_")
    session_dir = base_output / f"{safe_identity}_{timestamp}"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def main() -> int:
    setup_logging()
    args = parse_args()
    from scanner_reader import CaptureOptions, ScannerReader
    from scanner_utils import write_json

    identity = args.sn or args.ip
    base_output = Path(args.output).expanduser().resolve()
    session_dir = make_session_dir(base_output, identity)
    logging.info("Session output: %s", session_dir)

    reader = ScannerReader()
    capture_options = CaptureOptions(
        timeout_ms=args.timeout_ms,
        buffer_count=args.buffer_count,
        clear_buffer=not args.no_clear_buffer,
    )

    try:
        device_info = reader.connect(serial_number=args.sn, ip=args.ip)
        write_json(session_dir / "device_info.json", device_info)
        logging.info("Device connected: %s", device_info.get("serial_number") or "unknown")

        if args.dump_features:
            feature_map = reader.dump_feature_candidates(session_dir)
            logging.info("Feature dump saved, roots: %s", ", ".join(feature_map.keys()))

        config_outputs = reader.export_configs(session_dir)
        logging.info("Config exported: %s", config_outputs)

        scan_payload = reader.capture_scan(session_dir, capture_options)
        logging.info(
            "Capture completed: read_state=%s code_num=%s image=%s",
            scan_payload.get("read_state_name"),
            scan_payload.get("code_num"),
            scan_payload.get("image_path"),
        )
        logging.info("Done. Output folder: %s", session_dir)
        return 0
    except Exception as exc:
        logging.exception("Calibration read failed: %s", exc)
        return 1
    finally:
        reader.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
