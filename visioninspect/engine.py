"""Image inspection rules, measurements, and deterministic annotations."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

from . import HONESTY_STATEMENT

SCHEMA_VERSION = "1.0"
BLUR_THRESHOLD = 30.0
DARK_MEAN_THRESHOLD = 35.0
BRIGHT_MEAN_THRESHOLD = 250.0
FIXTURE_RANDOM_SEED = 20260928

PROFILE_CONFIG: dict[str, dict[str, Any]] = {
    "general": {
        "aspect_min": 0.25,
        "aspect_max": 4.0,
        "width_min": 1,
        "width_max": 12000,
        "height_min": 1,
        "height_max": 12000,
    },
    "invoice": {
        "aspect_min": 0.58,
        "aspect_max": 0.88,
        "width_min": 600,
        "width_max": 8000,
        "height_min": 800,
        "height_max": 12000,
    },
    "receipt": {
        "aspect_min": 0.22,
        "aspect_max": 0.75,
        "width_min": 250,
        "width_max": 3000,
        "height_min": 500,
        "height_max": 10000,
    },
    "equipment": {
        "aspect_min": 0.80,
        "aspect_max": 2.50,
        "width_min": 640,
        "width_max": 12000,
        "height_min": 480,
        "height_max": 12000,
    },
    "form": {
        "aspect_min": 0.60,
        "aspect_max": 0.95,
        "width_min": 500,
        "width_max": 8000,
        "height_min": 650,
        "height_max": 10000,
    },
}

_MAGIC_FORMATS = (
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"BM", "BMP"),
    (b"II*\x00", "TIFF"),
    (b"MM\x00*", "TIFF"),
)


def canonical_json_bytes(value: Any) -> bytes:
    """Return stable UTF-8 JSON bytes with sorted keys and a trailing newline."""
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _path_label(path: Path) -> str:
    return path.expanduser().resolve().as_posix()


def _signature_format(data: bytes) -> str | None:
    for signature, name in _MAGIC_FORMATS:
        if data.startswith(signature):
            return name
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def _decode_image(data: bytes) -> tuple[Image.Image | None, str | None, str | None]:
    """Verify and load an image, returning a detached copy and an error label."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            decoded_format = probe.format
            probe.verify()
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            return source.copy(), decoded_format, None
    except Exception as exc:  # Pillow reports format-specific decode failures.
        return None, None, f"{type(exc).__name__}: {exc}"


def _format_check(path: Path, data: bytes, image: Image.Image | None, decoded_format: str | None, decode_error: str | None) -> dict[str, Any]:
    signature_format = _signature_format(data)
    errors: list[str] = []
    if signature_format is None:
        errors.append("unrecognized_magic_bytes")
    if image is None:
        errors.append("decode_or_integrity_failure")
    if image is not None and signature_format != decoded_format:
        errors.append("magic_and_decoder_format_disagree")
    measurements: dict[str, Any] = {
        "byte_count": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "signature_format": signature_format,
        "decoded_format": decoded_format,
        "decode_success": image is not None,
        "integrity_errors": errors,
    }
    if decode_error is not None:
        measurements["decode_error"] = decode_error
    status = "fail" if errors else "pass"
    message = "Image bytes match a supported decoder format and pass integrity checks."
    if errors:
        message = "Image bytes are unrecognized, truncated, corrupt, or inconsistent with the decoder format."
    return _check_record("format_integrity", status, message, measurements, path)


def _check_record(name: str, status: str, message: str, measurements: dict[str, Any], path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "check": name,
        "status": status,
        "message": message,
        "measurements": measurements,
    }
    if status != "pass":
        result["evidence"] = {
            "file": _path_label(path),
            "check": name,
            "measured_values": measurements,
        }
    return result


def _dimensions_check(path: Path, size: tuple[int, int], config: dict[str, Any]) -> dict[str, Any]:
    width, height = size
    passed = (
        config["width_min"] <= width <= config["width_max"]
        and config["height_min"] <= height <= config["height_max"]
    )
    measurements = {
        "width": width,
        "height": height,
        "pixel_count": width * height,
        "expected_width": {"min": config["width_min"], "max": config["width_max"]},
        "expected_height": {"min": config["height_min"], "max": config["height_max"]},
    }
    status = "pass" if passed else "fail"
    message = "Image dimensions are within the selected profile range." if passed else "Image dimensions are outside the selected profile range."
    return _check_record("dimensions", status, message, measurements, path)


def _aspect_check(path: Path, size: tuple[int, int], profile: str, config: dict[str, Any]) -> dict[str, Any]:
    width, height = size
    ratio = width / height
    passed = config["aspect_min"] <= ratio <= config["aspect_max"]
    measurements = {
        "width_over_height": round(ratio, 6),
        "expected_width_over_height": {"min": config["aspect_min"], "max": config["aspect_max"]},
        "profile": profile,
    }
    status = "pass" if passed else "fail"
    message = "Image aspect ratio is within the selected profile range." if passed else "Image aspect ratio is outside the selected profile range."
    return _check_record("aspect_ratio", status, message, measurements, path)


def _gray_measurements(image: Image.Image) -> tuple[Image.Image, bool]:
    gray = image.convert("L")
    scaled = False
    longest = max(gray.size)
    if longest > 1024:
        scale = 1024 / longest
        size = (max(1, round(gray.width * scale)), max(1, round(gray.height * scale)))
        gray = gray.resize(size, Image.Resampling.BILINEAR)
        scaled = True
    return gray, scaled


def _blur_check(path: Path, image: Image.Image) -> dict[str, Any]:
    gray, scaled = _gray_measurements(image)
    kernel = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)
    laplacian = gray.filter(kernel)
    score = ImageStat.Stat(laplacian).var[0]
    status = "fail" if score < BLUR_THRESHOLD else "pass"
    message = "Laplacian variance is below the blur threshold." if status == "fail" else "Laplacian variance is at or above the blur threshold."
    measurements = {
        "laplacian_variance": round(score, 6),
        "threshold_minimum": BLUR_THRESHOLD,
        "analysis_size": {"width": gray.width, "height": gray.height},
        "downscaled_for_analysis": scaled,
        "grayscale_conversion": "Pillow L mode",
        "laplacian_kernel": [0, 1, 0, 1, -4, 1, 0, 1, 0],
    }
    return _check_record("blur", status, message, measurements, path)


def _exposure_check(path: Path, image: Image.Image) -> dict[str, Any]:
    gray, scaled = _gray_measurements(image)
    histogram = gray.histogram()
    total = sum(histogram)
    mean = sum(index * count for index, count in enumerate(histogram)) / total
    shadows = sum(histogram[:9]) / total
    highlights = sum(histogram[247:]) / total
    too_dark = mean < DARK_MEAN_THRESHOLD
    too_bright = mean > BRIGHT_MEAN_THRESHOLD
    status = "fail" if too_dark or too_bright else "pass"
    if too_dark:
        message = "Mean luminance is below the underexposure threshold."
    elif too_bright:
        message = "Mean luminance is above the overexposure threshold."
    else:
        message = "Mean luminance is within the broad exposure range."
    measurements = {
        "mean_luminance": round(mean, 6),
        "shadow_clipping_fraction_luma_0_to_8": round(shadows, 6),
        "highlight_clipping_fraction_luma_247_to_255": round(highlights, 6),
        "underexposure_mean_threshold": DARK_MEAN_THRESHOLD,
        "overexposure_mean_threshold": BRIGHT_MEAN_THRESHOLD,
        "analysis_size": {"width": gray.width, "height": gray.height},
        "downscaled_for_analysis": scaled,
    }
    return _check_record("exposure", status, message, measurements, path)


def _metadata_values(image: Image.Image) -> dict[str, Any]:
    info = image.info
    lowered = {str(key).casefold(): value for key, value in info.items()}
    try:
        exif = image.getexif()
    except Exception:
        exif = {}

    def first_value(*keys: str) -> Any:
        for key in keys:
            value = lowered.get(key.casefold())
            if value not in (None, "", b""):
                return value
        return None

    declared_width = first_value("vi_width", "imagewidth", "pixelxdimension")
    declared_height = first_value("vi_height", "imageheight", "pixelydimension")
    if declared_width is None:
        declared_width = exif.get(40962) or exif.get(256)
    if declared_height is None:
        declared_height = exif.get(40963) or exif.get(257)
    try:
        declared_width = int(declared_width) if declared_width is not None else None
    except (TypeError, ValueError):
        declared_width = str(declared_width)
    try:
        declared_height = int(declared_height) if declared_height is not None else None
    except (TypeError, ValueError):
        declared_height = str(declared_height)

    declared_profile = first_value("vi_profile", "document_profile")
    software = first_value("software")
    if software is None:
        software = exif.get(305)
    make = first_value("make") or exif.get(271)
    model = first_value("model") or exif.get(272)
    keys = sorted(str(key) for key, value in info.items() if value not in (None, "", b""))
    exif_names = {305: "Software", 271: "Make", 272: "Model", 306: "DateTime", 274: "Orientation"}
    for tag_id, tag_name in exif_names.items():
        if exif.get(tag_id) not in (None, "", b""):
            keys.append(f"EXIF:{tag_name}")
    keys = sorted(set(keys))
    return {
        "metadata_keys": keys,
        "metadata_present": bool(keys),
        "declared_width": declared_width,
        "declared_height": declared_height,
        "declared_profile": str(declared_profile) if declared_profile is not None else None,
        "software_tag": str(software) if software is not None else None,
        "make_tag": str(make) if make is not None else None,
        "model_tag": str(model) if model is not None else None,
    }


def _metadata_check(path: Path, image: Image.Image, profile: str, size: tuple[int, int]) -> dict[str, Any]:
    values = _metadata_values(image)
    width, height = size
    mismatches: list[str] = []
    if not values["metadata_present"]:
        mismatches.append("metadata_absent")
    if values["declared_width"] is not None and values["declared_width"] != width:
        mismatches.append("declared_width_does_not_match_image")
    if values["declared_height"] is not None and values["declared_height"] != height:
        mismatches.append("declared_height_does_not_match_image")
    declared_profile = values["declared_profile"]
    profile_match: bool | None = None
    if profile != "general" and declared_profile is not None:
        profile_match = declared_profile.casefold() == profile.casefold()
        if not profile_match:
            mismatches.append("declared_profile_does_not_match_selected_profile")
    measurements = {
        **values,
        "actual_width": width,
        "actual_height": height,
        "selected_profile": profile,
        "expected_declared_profile": profile if profile != "general" else None,
        "measured_declared_profile": declared_profile,
        "profile_match": profile_match,
        "mismatches": mismatches,
        "software_tag_present": values["software_tag"] is not None,
    }
    status = "fail" if mismatches else "pass"
    message = "Metadata dimensions and declared profile are consistent with the image and selected profile." if status == "pass" else "Metadata is absent or conflicts with decoded image dimensions or the selected profile."
    return _check_record("metadata_consistency", status, message, measurements, path)


def _document_field_check(path: Path, image: Image.Image, profile: str) -> dict[str, Any]:
    """Count horizontal bands of text-like dark pixels, without reading text."""
    gray, scaled = _gray_measurements(image)
    crop_x = max(1, round(gray.width * 0.05))
    crop_y = max(1, round(gray.height * 0.05))
    gray = gray.crop((crop_x, crop_y, gray.width - crop_x, gray.height - crop_y))
    width, height = gray.size
    pixels = gray.load()
    min_row_pixels = max(4, round(width * 0.006))
    max_row_pixels = max(min_row_pixels, round(width * 0.35))
    active_rows: list[int] = []
    for y in range(height):
        dark_pixels = sum(pixels[x, y] < 150 for x in range(width))
        if min_row_pixels <= dark_pixels <= max_row_pixels:
            active_rows.append(y)
    bands: list[list[int]] = []
    for row in active_rows:
        if not bands or row - bands[-1][-1] > 3:
            bands.append([row])
        else:
            bands[-1].append(row)
    min_bands = 4
    measurements = {
        "profile": profile,
        "text_like_band_count": len(bands),
        "text_like_row_count": len(active_rows),
        "minimum_expected_band_count": min_bands,
        "dark_pixel_threshold_luma_below": 150,
        "row_coverage_fraction_min": 0.006,
        "row_coverage_fraction_max": 0.35,
        "analysis_size": {"width": width, "height": height},
        "downscaled_for_analysis": scaled,
        "words_read": False,
    }
    passed = len(bands) >= min_bands
    status = "pass" if passed else "fail"
    message = (
        "The page has enough separate text-like horizontal bands for a basic document layout heuristic."
        if passed
        else "The page has too few separate text-like horizontal bands for the selected document profile."
    )
    return _check_record("document_field_plausibility", status, message, measurements, path)


def inspect_image(path: str | Path, profile: str = "general") -> dict[str, Any]:
    """Inspect one image and return a timestamp-free, JSON-compatible report."""
    if profile not in PROFILE_CONFIG:
        raise ValueError(f"Unknown profile: {profile}")
    image_path = Path(path).expanduser()
    data = image_path.read_bytes()
    image, decoded_format, decode_error = _decode_image(data)
    checks = [_format_check(image_path, data, image, decoded_format, decode_error)]
    if image is not None:
        config = PROFILE_CONFIG[profile]
        size = image.size
        checks.extend(
            [
                _dimensions_check(image_path, size, config),
                _aspect_check(image_path, size, profile, config),
                _blur_check(image_path, image),
                _exposure_check(image_path, image),
                _metadata_check(image_path, image, profile, size),
            ]
        )
        if profile in {"invoice", "receipt", "form"}:
            checks.append(_document_field_check(image_path, image, profile))
    findings = []
    for check in checks:
        if check["status"] != "pass":
            findings.append(
                {
                    "file": _path_label(image_path),
                    "check": check["check"],
                    "status": check["status"],
                    "message": check["message"],
                    "measured_values": check["measurements"],
                    "evidence": check["evidence"],
                }
            )
    counts = {status: sum(check["status"] == status for check in checks) for status in ("pass", "warn", "fail")}
    overall = "fail" if counts["fail"] else "warn" if counts["warn"] else "pass"
    return {
        "schema_version": SCHEMA_VERSION,
        "header": {
            "title": "VisionInspect inspection report",
            "honesty_statement": HONESTY_STATEMENT,
        },
        "honesty_statement": HONESTY_STATEMENT,
        "file": _path_label(image_path),
        "profile": profile,
        "overall_status": overall,
        "summary": {
            "checks_run": len(checks),
            "pass_count": counts["pass"],
            "warn_count": counts["warn"],
            "fail_count": counts["fail"],
            "finding_count": len(findings),
        },
        "checks": checks,
        "findings": findings,
    }


def write_json_report(report: dict[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(report))
    return destination


def _annotation_source(report: dict[str, Any]) -> tuple[Image.Image, bool]:
    source = Path(report["file"])
    try:
        with Image.open(source) as image:
            image.load()
            return image.convert("RGB"), True
    except Exception:
        placeholder = Image.new("RGB", (840, 190), "#f5f5f5")
        return placeholder, False


def annotated_image_bytes(report: dict[str, Any]) -> bytes:
    """Render deterministic full-frame evidence labels into PNG bytes."""
    image, decoded = _annotation_source(report)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    if decoded:
        width, height = image.size
        inset = max(2, min(12, width // 100, height // 100))
        labels = [f"{item['check']}: {item['status']}" for item in report["findings"]]
        if labels:
            draw.rectangle((inset, inset, max(inset, width - 1 - inset), max(inset, height - 1 - inset)), outline=(220, 30, 30), width=max(2, min(6, width // 250 + 1)))
            label = " | ".join(labels)
            box = draw.textbbox((0, 0), label, font=font)
            label_width = min(width - 2 * inset, box[2] - box[0] + 8)
            label_height = box[3] - box[1] + 6
            draw.rectangle((inset, inset, inset + label_width, inset + label_height), fill=(255, 255, 255))
            draw.text((inset + 4, inset + 3), label, fill=(170, 0, 0), font=font)
    else:
        title = "VisionInspect: image integrity failure"
        draw.text((16, 16), title, fill=(170, 0, 0), font=font)
        for index, finding in enumerate(report["findings"][:5]):
            draw.text((16, 42 + index * 22), f"{finding['check']}: {finding['message']}", fill=(30, 30, 30), font=font)
    result = io.BytesIO()
    image.save(result, format="PNG", optimize=False, compress_level=9)
    return result.getvalue()


def write_annotation(report: dict[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(annotated_image_bytes(report))
    return destination


def batch_inspect(directory: str | Path, profile: str = "general", annotated_dir: str | Path | None = None) -> dict[str, Any]:
    """Inspect image files under a directory and summarize the findings."""
    root = Path(directory).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    extensions = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
    paths = sorted(
        (item for item in root.rglob("*") if item.is_file() and item.suffix.casefold() in extensions),
        key=lambda item: (item.relative_to(root).as_posix().casefold(), item.relative_to(root).as_posix()),
    )
    reports = [inspect_image(path, profile) for path in paths]
    if annotated_dir is not None:
        annotation_root = Path(annotated_dir)
        for report in reports:
            if report["findings"]:
                original = Path(report["file"])
                relative = original.relative_to(root.resolve())
                target = annotation_root / relative.parent / f"{relative.name}.annotated.png"
                write_annotation(report, target)

    check_counts: dict[str, dict[str, int]] = {}
    for report in reports:
        for check in report["checks"]:
            counts = check_counts.setdefault(check["check"], {"pass": 0, "warn": 0, "fail": 0})
            counts[check["status"]] += 1
    profile_summaries: dict[str, dict[str, Any]] = {}
    for profile_name in sorted({report["profile"] for report in reports}):
        group = [report for report in reports if report["profile"] == profile_name]
        passed = sum(report["overall_status"] == "pass" for report in group)
        profile_summaries[profile_name] = {
            "image_count": len(group),
            "passed_image_count": passed,
            "pass_rate": round(passed / len(group), 6) if group else 0.0,
        }
    findings = [finding for report in reports for finding in report["findings"]]
    overall = "fail" if findings else "pass"
    return {
        "schema_version": SCHEMA_VERSION,
        "header": {
            "title": "VisionInspect batch inspection report",
            "honesty_statement": HONESTY_STATEMENT,
        },
        "honesty_statement": HONESTY_STATEMENT,
        "input_directory": _path_label(root),
        "profile": profile,
        "overall_status": overall,
        "summary": {
            "image_count": len(reports),
            "flagged_image_count": sum(bool(report["findings"]) for report in reports),
            "finding_count": len(findings),
        },
        "check_counts": check_counts,
        "profile_summaries": profile_summaries,
        "reports": reports,
        "findings": findings,
    }
