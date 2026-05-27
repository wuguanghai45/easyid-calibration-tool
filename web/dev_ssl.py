"""Generate or reuse a self-signed TLS certificate for local HTTPS."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CERT_DIR = REPO_ROOT / ".certs"
KEY_FILE = CERT_DIR / "dev-key.pem"
CERT_FILE = CERT_DIR / "dev-cert.pem"


def ensure_dev_ssl_files() -> tuple[Path, Path]:
    """Create .certs/dev-*.pem via openssl if missing."""
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    if KEY_FILE.is_file() and CERT_FILE.is_file():
        return KEY_FILE, CERT_FILE

    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError(
            "openssl not found. Install OpenSSL or add it to PATH to use --ssl, "
            "or access the app at http://localhost:<port> on this machine."
        )

    san = "subjectAltName=DNS:localhost,IP:127.0.0.1"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(KEY_FILE),
            "-out",
            str(CERT_FILE),
            "-days",
            "3650",
            "-nodes",
            "-subj",
            "/CN=localhost",
            "-addext",
            san,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return KEY_FILE, CERT_FILE
