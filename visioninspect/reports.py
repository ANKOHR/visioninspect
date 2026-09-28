"""Markdown and HTML renderers for inspection and batch reports."""

from __future__ import annotations

import html
import json
from typing import Any

from . import HONESTY_STATEMENT


def _all_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(report.get("reports"), list):
        return [finding for item in report["reports"] for finding in item.get("findings", [])]
    return list(report.get("findings", []))


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# VisionInspect report",
        "",
        f"> {HONESTY_STATEMENT}",
        "",
    ]
    summary = report.get("summary", {})
    lines.extend(["## Summary", ""])
    if "image_count" in summary:
        lines.append(f"- Images inspected: {summary['image_count']}")
        lines.append(f"- Flagged images: {summary.get('flagged_image_count', 0)}")
        lines.append(f"- Findings: {summary.get('finding_count', 0)}")
    else:
        lines.append(f"- File: `{report.get('file', '')}`")
        lines.append(f"- Profile: {report.get('profile', '')}")
        lines.append(f"- Overall status: {report.get('overall_status', '')}")
        lines.append(f"- Checks run: {summary.get('checks_run', 0)}")
    if report.get("check_counts"):
        lines.extend(["", "## Check counts", "", "| Check | Pass | Warn | Fail |", "| --- | ---: | ---: | ---: |"])
        for name, counts in sorted(report["check_counts"].items()):
            lines.append(f"| {name} | {counts['pass']} | {counts['warn']} | {counts['fail']} |")
    if report.get("profile_summaries"):
        lines.extend(["", "## Profile pass rates", "", "| Profile | Images | Passed | Pass rate |", "| --- | ---: | ---: | ---: |"])
        for name, stats in sorted(report["profile_summaries"].items()):
            lines.append(f"| {name} | {stats['image_count']} | {stats['passed_image_count']} | {stats['pass_rate']:.2%} |")
    findings = _all_findings(report)
    lines.extend(["", "## Findings", ""])
    if not findings:
        lines.append("No findings.")
    for finding in findings:
        lines.extend(
            [
                f"### {finding['check']}: {finding['status']}",
                "",
                f"- File: `{finding['file']}`",
                f"- Reason: {finding['message']}",
                "- Evidence measurements:",
                "",
                "```json",
                json.dumps(finding["evidence"]["measured_values"], ensure_ascii=False, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_html(report: dict[str, Any]) -> str:
    findings = _all_findings(report)
    summary = report.get("summary", {})
    body: list[str] = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>VisionInspect report</title>",
        "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#17212b}"
        ".honesty{padding:1rem;border:2px solid #8b1e1e;background:#fff1f1;font-weight:700}"
        "table{border-collapse:collapse;width:100%}td,th{padding:.5rem;border:1px solid #bbb;text-align:left}"
        "pre{overflow:auto;background:#f3f5f7;padding:1rem}.finding{border-top:1px solid #bbb;padding:1rem 0}</style></head><body>",
        "<h1>VisionInspect report</h1>",
        f'<p class="honesty">{html.escape(HONESTY_STATEMENT)}</p>',
        "<h2>Summary</h2><ul>",
    ]
    if "image_count" in summary:
        body.extend(
            [
                f"<li>Images inspected: {summary['image_count']}</li>",
                f"<li>Flagged images: {summary.get('flagged_image_count', 0)}</li>",
                f"<li>Findings: {summary.get('finding_count', 0)}</li>",
            ]
        )
    else:
        body.extend(
            [
                f"<li>File: {html.escape(str(report.get('file', '')))}</li>",
                f"<li>Profile: {html.escape(str(report.get('profile', '')))}</li>",
                f"<li>Overall status: {html.escape(str(report.get('overall_status', '')))}</li>",
                f"<li>Checks run: {summary.get('checks_run', 0)}</li>",
            ]
        )
    body.append("</ul>")
    if report.get("check_counts"):
        body.extend(["<h2>Check counts</h2><table><thead><tr><th>Check</th><th>Pass</th><th>Warn</th><th>Fail</th></tr></thead><tbody>"])
        for name, counts in sorted(report["check_counts"].items()):
            body.append(f"<tr><td>{html.escape(name)}</td><td>{counts['pass']}</td><td>{counts['warn']}</td><td>{counts['fail']}</td></tr>")
        body.append("</tbody></table>")
    if report.get("profile_summaries"):
        body.extend(["<h2>Profile pass rates</h2><table><thead><tr><th>Profile</th><th>Images</th><th>Passed</th><th>Pass rate</th></tr></thead><tbody>"])
        for name, stats in sorted(report["profile_summaries"].items()):
            body.append(f"<tr><td>{html.escape(name)}</td><td>{stats['image_count']}</td><td>{stats['passed_image_count']}</td><td>{stats['pass_rate']:.2%}</td></tr>")
        body.append("</tbody></table>")
    body.append("<h2>Findings</h2>")
    if not findings:
        body.append("<p>No findings.</p>")
    for finding in findings:
        body.extend(
            [
                '<section class="finding">',
                f"<h3>{html.escape(finding['check'])}: {html.escape(finding['status'])}</h3>",
                f"<p><strong>File:</strong> {html.escape(finding['file'])}</p>",
                f"<p><strong>Reason:</strong> {html.escape(finding['message'])}</p>",
                "<h4>Evidence measurements</h4>",
                f"<pre>{html.escape(json.dumps(finding['evidence']['measured_values'], ensure_ascii=False, indent=2, sort_keys=True))}</pre>",
                "</section>",
            ]
        )
    body.append("</body></html>")
    return "\n".join(body) + "\n"
