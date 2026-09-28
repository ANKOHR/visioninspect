from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from visioninspect import HONESTY_STATEMENT
from visioninspect.engine import annotated_image_bytes, batch_inspect, canonical_json_bytes, inspect_image, write_annotation
from visioninspect.fixtures import generate_fixtures
from visioninspect.reports import render_html


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    destination = tmp_path / "fixtures"
    generate_fixtures(destination)
    return destination


def _finding_checks(report: dict) -> list[str]:
    return [item["check"] for item in report["findings"]]


def test_fixture_generation_is_deterministic_and_fictional(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest_one = generate_fixtures(first)
    manifest_two = generate_fixtures(second)
    assert manifest_one == manifest_two
    assert manifest_one["random_seed"] == 20260928
    assert all(item["fictional"] for item in manifest_one["fixtures"])
    assert (first / "fixtures-manifest.json").read_bytes() == (second / "fixtures-manifest.json").read_bytes()
    for item in manifest_one["fixtures"]:
        assert (first / item["file"]).read_bytes() == (second / item["file"]).read_bytes()


def test_clean_fixture_passes_all_checks(fixture_dir: Path) -> None:
    report = inspect_image(fixture_dir / "clean_document.png")
    assert report["overall_status"] == "pass"
    assert report["summary"]["checks_run"] == 6
    assert report["findings"] == []
    assert "not a trained vision model" in report["header"]["honesty_statement"]
    assert all(check["status"] == "pass" for check in report["checks"])


def test_document_profile_checks_layout_without_reading_words(fixture_dir: Path) -> None:
    report = inspect_image(fixture_dir / "clean_document.png", profile="invoice")
    check = next(item for item in report["checks"] if item["check"] == "document_field_plausibility")
    assert check["status"] == "pass"
    assert check["measurements"]["text_like_band_count"] >= check["measurements"]["minimum_expected_band_count"]
    assert check["measurements"]["words_read"] is False
    assert report["overall_status"] == "pass"


@pytest.mark.parametrize(
    ("filename", "expected_check"),
    [
        ("blurred_photo.png", "blur"),
        ("underexposed.png", "exposure"),
        ("wrong_aspect.png", "aspect_ratio"),
        ("truncated_corrupt.png", "format_integrity"),
        ("metadata_stripped.png", "metadata_consistency"),
    ],
)
def test_each_defect_fails_only_its_intended_check(fixture_dir: Path, filename: str, expected_check: str) -> None:
    report = inspect_image(fixture_dir / filename)
    assert _finding_checks(report) == [expected_check]
    finding = report["findings"][0]
    assert finding["evidence"]["file"] == report["file"]
    assert finding["evidence"]["check"] == expected_check
    assert finding["evidence"]["measured_values"]
    assert finding["status"] == "fail"


def test_inspection_report_and_annotation_are_byte_deterministic(fixture_dir: Path, tmp_path: Path) -> None:
    path = fixture_dir / "underexposed.png"
    first = inspect_image(path)
    second = inspect_image(path)
    first_bytes = canonical_json_bytes(first)
    second_bytes = canonical_json_bytes(second)
    assert first_bytes == second_bytes
    annotation_one = tmp_path / "one.png"
    annotation_two = tmp_path / "two.png"
    write_annotation(first, annotation_one)
    write_annotation(second, annotation_two)
    assert annotation_one.read_bytes() == annotation_two.read_bytes()
    assert annotation_one.read_bytes() == annotated_image_bytes(first)


def test_wrong_profile_reports_aspect_and_metadata_expected_and_measured(fixture_dir: Path) -> None:
    report = inspect_image(fixture_dir / "clean_document.png", profile="equipment")
    assert _finding_checks(report) == ["aspect_ratio", "metadata_consistency"]
    checks = {check["check"]: check for check in report["checks"]}
    aspect = checks["aspect_ratio"]["measurements"]
    assert aspect["profile"] == "equipment"
    assert aspect["width_over_height"] < aspect["expected_width_over_height"]["min"]
    metadata = checks["metadata_consistency"]["measurements"]
    assert metadata["selected_profile"] == "equipment"
    assert metadata["expected_declared_profile"] == "equipment"
    assert metadata["declared_profile"] == "invoice"
    assert metadata["measured_declared_profile"] == "invoice"
    assert metadata["profile_match"] is False


def test_batch_aggregates_planted_defects_and_html_has_honesty_banner(fixture_dir: Path, tmp_path: Path) -> None:
    annotated = tmp_path / "annotated"
    report = batch_inspect(fixture_dir, annotated_dir=annotated)
    assert report["summary"] == {"image_count": 6, "flagged_image_count": 5, "finding_count": 5}
    assert {item["check"] for item in report["findings"]} == {
        "blur",
        "exposure",
        "aspect_ratio",
        "format_integrity",
        "metadata_consistency",
    }
    assert report["check_counts"]["blur"]["fail"] == 1
    assert report["check_counts"]["exposure"]["fail"] == 1
    assert report["check_counts"]["aspect_ratio"]["fail"] == 1
    assert report["check_counts"]["format_integrity"]["fail"] == 1
    assert report["check_counts"]["metadata_consistency"]["fail"] == 1
    assert report["profile_summaries"]["general"]["image_count"] == 6
    assert len(list(annotated.glob("*.annotated.png"))) == 5
    rendered = render_html(report)
    assert HONESTY_STATEMENT in rendered
    assert "not a trained vision model" in rendered
    assert "no neural networks and no learned features" in rendered


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "visioninspect", *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_fixtures_inspect_batch_report_and_rules_smoke(fixture_dir: Path, tmp_path: Path) -> None:
    generated = tmp_path / "cli-fixtures"
    result = _run_cli("fixtures", "--out", str(generated))
    assert result.returncode == 0, result.stderr
    assert "synthetic fictional" in result.stdout
    assert (generated / "fixtures-manifest.json").exists()

    inspect_out = tmp_path / "inspect.json"
    annotated = tmp_path / "inspect.annotated.png"
    audit = tmp_path / "inspect-audit.jsonl"
    result = _run_cli(
        "inspect",
        str(fixture_dir / "blurred_photo.png"),
        "--out",
        str(inspect_out),
        "--annotated",
        str(annotated),
        "--audit",
        str(audit),
    )
    assert result.returncode == 0, result.stderr
    assert "not a trained vision model" in result.stdout
    assert json.loads(inspect_out.read_text(encoding="utf-8"))["findings"][0]["check"] == "blur"
    assert annotated.exists()
    assert len(audit.read_text(encoding="utf-8").splitlines()) == 1

    batch_out = tmp_path / "batch.json"
    batch_audit = tmp_path / "batch-audit.jsonl"
    result = _run_cli(
        "batch",
        str(fixture_dir),
        "--out",
        str(batch_out),
        "--annotated-dir",
        str(tmp_path / "batch-annotations"),
        "--audit",
        str(batch_audit),
    )
    assert result.returncode == 0, result.stderr
    batch = json.loads(batch_out.read_text(encoding="utf-8"))
    assert batch["summary"]["finding_count"] == 5
    assert len(batch_audit.read_text(encoding="utf-8").splitlines()) == 6

    html_out = tmp_path / "batch.html"
    result = _run_cli("report", "--input", str(batch_out), "--format", "html", "--out", str(html_out))
    assert result.returncode == 0, result.stderr
    assert "not a trained vision model" in html_out.read_text(encoding="utf-8")

    markdown_out = tmp_path / "batch.md"
    result = _run_cli("report", "--input", str(batch_out), "--format", "md", "--out", str(markdown_out))
    assert result.returncode == 0, result.stderr
    assert "rule-based image-analysis heuristics" in markdown_out.read_text(encoding="utf-8")

    result = _run_cli("rules")
    assert result.returncode == 0, result.stderr
    assert "format_integrity" in result.stdout
    assert "no learned features" in result.stdout


def test_project_text_contains_no_em_dash() -> None:
    candidates = [PROJECT_ROOT / "README.md", PROJECT_ROOT / "pyproject.toml"]
    candidates += list((PROJECT_ROOT / "visioninspect").glob("*.py"))
    candidates += list((PROJECT_ROOT / "tests").glob("*.py"))
    for path in candidates:
        assert "\u2014" not in path.read_text(encoding="utf-8"), str(path)
