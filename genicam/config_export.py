"""Export GenICam XML-based configuration snapshots."""

from __future__ import annotations

from pathlib import Path


def export_userset_xml(base_xml: str, userset_symbol: str, output_path: Path) -> None:
    """Persist a userset snapshot as XML text.

    Without vendor SDK FileAccess we keep the device XML with a userset comment so
    calibration pipelines still get deterministic artifacts.
    """
    header = f"<!-- userset={userset_symbol} -->\n"
    output_path.write_text(header + base_xml, encoding="utf-8")

