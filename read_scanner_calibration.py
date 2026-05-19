#!/usr/bin/env python3
"""CLI tool for scanner calibration data collection."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import socket
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read scanner config, result and image for factory calibration.",
    )
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--sn", help="Scanner serial number.")
    target_group.add_argument("--ip", help="Scanner IPv4 address.")
    target_group.add_argument(
        "--list-devices",
        action="store_true",
        help="List GigE devices via GVCP discovery and exit.",
    )
    parser.add_argument(
        "--interface",
        help="Host NIC name filter (GVCP interface_name, substring match).",
    )
    parser.add_argument(
        "--diag",
        action="store_true",
        help="Print extra diagnostics for GVCP/GVSP workflow.",
    )

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
        help="Reserved for GVSP buffer sizing (currently informational).",
    )
    parser.add_argument(
        "--no-clear-buffer",
        action="store_true",
        help="Reserved compatibility flag in pure GVCP mode.",
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


def _print_device_table(devices: list[dict[str, str]]) -> None:
    headers = ["#", "serial_number", "ip_address", "interface_name", "model_name", "mac_address"]
    rows: list[list[str]] = []
    for idx, dev in enumerate(devices, start=1):
        rows.append(
            [
                str(idx),
                dev.get("serial_number", ""),
                dev.get("ip_address", ""),
                dev.get("interface_name", ""),
                dev.get("model_name", ""),
                dev.get("mac_address", ""),
            ]
        )

    widths = [len(header) for header in headers]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(value))

    header_line = " | ".join(header.ljust(widths[i]) for i, header in enumerate(headers))
    divider_line = "-+-".join("-" * widths[i] for i in range(len(headers)))
    print(header_line)
    print(divider_line)
    for row in rows:
        print(" | ".join(value.ljust(widths[i]) for i, value in enumerate(row)))


def _collect_local_ipv4_addresses() -> list[str]:
    host_name = socket.gethostname()
    addresses = set()
    try:
        for result in socket.getaddrinfo(host_name, None, socket.AF_INET, socket.SOCK_DGRAM):
            ip = result[4][0]
            if ip and ip != "127.0.0.1":
                addresses.add(ip)
    except Exception:
        pass
    return sorted(addresses)


def _print_discovery_diagnostics(reader: object | None = None) -> None:
    host_name = socket.gethostname()
    ipv4_list = _collect_local_ipv4_addresses()

    logging.info("Diagnostic mode enabled:")
    logging.info("  hostname: %s", host_name)
    logging.info("  local_ipv4: %s", ", ".join(ipv4_list) if ipv4_list else "(none)")
    if reader is not None:
        gvcp_devices = reader.enum_devices()
        logging.info("  gvcp_device_count: %d", len(gvcp_devices))


def main() -> int:
    setup_logging()
    args = parse_args()
    base_output = Path(args.output).expanduser()
    if not base_output.is_absolute():
        base_output = (Path.cwd() / base_output).resolve()
    else:
        base_output = base_output.resolve()

    from scanner_reader import CaptureOptions, ScannerReader
    from scanner_utils import write_json

    reader = ScannerReader()

    try:
        if args.list_devices:
            devices = reader.enum_devices(interface_name=args.interface)
            if not devices:
                logging.info("No scanner device found.")
                if args.diag:
                    _print_discovery_diagnostics(reader)
                return 0
            _print_device_table(devices)
            return 0

        identity = args.sn or args.ip
        session_dir = make_session_dir(base_output, identity)
        logging.info("Session output: %s", session_dir)

        capture_options = CaptureOptions(
            timeout_ms=args.timeout_ms,
            buffer_count=args.buffer_count,
            clear_buffer=not args.no_clear_buffer,
        )

        device_info = reader.connect(serial_number=args.sn, ip=args.ip, interface_name=args.interface)
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
