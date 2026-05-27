#!/usr/bin/env python3
"""Start the DataMatrix calibration web dashboard."""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="DataMatrix calibration web server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8080, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev)")
    parser.add_argument(
        "--ssl",
        action="store_true",
        help="Serve HTTPS with a local self-signed cert (.certs/dev-*.pem)",
    )
    args = parser.parse_args()

    ssl_keyfile: str | None = None
    ssl_certfile: str | None = None
    if args.ssl:
        from web.dev_ssl import ensure_dev_ssl_files

        key_path, cert_path = ensure_dev_ssl_files()
        ssl_keyfile = str(key_path)
        ssl_certfile = str(cert_path)

    uvicorn.run(
        "web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        ssl_keyfile=ssl_keyfile,
        ssl_certfile=ssl_certfile,
    )


if __name__ == "__main__":
    main()
