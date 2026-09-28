"""Append-only run history, separate from deterministic inspection reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def append_audit(report: dict[str, Any], audit_path: str | Path = "vi-audit.jsonl") -> None:
    """Append one timestamped audit record per inspected image."""
    reports = report.get("reports")
    if not isinstance(reports, list):
        reports = [report]
    destination = Path(audit_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8", newline="\n") as stream:
        for item in reports:
            record = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "file": item["file"],
                "profile": item["profile"],
                "checks_run": [check["check"] for check in item["checks"]],
                "findings": item["findings"],
            }
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
