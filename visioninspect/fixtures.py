"""Generate deterministic, fictional synthetic inspection fixtures."""

from __future__ import annotations

import io
import json
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, PngImagePlugin

from .engine import FIXTURE_RANDOM_SEED, canonical_json_bytes


def _png_bytes(image: Image.Image, metadata: dict[str, str] | None = None) -> bytes:
    output = io.BytesIO()
    save_options: dict[str, Any] = {"format": "PNG", "optimize": False, "compress_level": 9}
    if metadata:
        png_info = PngImagePlugin.PngInfo()
        for key in sorted(metadata):
            png_info.add_text(key, metadata[key])
        save_options["pnginfo"] = png_info
    image.save(output, **save_options)
    return output.getvalue()


def _metadata(image: Image.Image, profile: str) -> dict[str, str]:
    return {
        "Description": "Synthetic fictional VisionInspect test fixture",
        "Software": "VisionInspect synthetic fixture generator",
        "vi_height": str(image.height),
        "vi_profile": profile,
        "vi_width": str(image.width),
    }


def _draw_document(size: tuple[int, int], profile: str = "invoice") -> Image.Image:
    image = Image.new("RGB", size, (242, 240, 232))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    width, height = size
    margin = max(22, width // 16)
    draw.rectangle((margin // 2, margin // 2, width - margin // 2, height - margin // 2), outline=(95, 100, 105), width=3)
    draw.text((margin, margin), "INVOICE  FICTIONAL SAMPLE", fill=(28, 35, 42), font=font)
    draw.line((margin, margin + 34, width - margin, margin + 34), fill=(30, 50, 70), width=4)
    for index in range(9):
        y = margin + 75 + index * max(27, height // 34)
        if y >= height - margin - 40:
            break
        if index in (0, 4, 8):
            draw.rectangle((margin, y, width - margin, y + 18), outline=(65, 75, 82), width=2)
        elif index in (1, 2, 5, 6):
            labels = {1: "Invoice number: INV-0001", 2: "Bill to: Fictional Sample Buyer", 5: "Description: Sample item", 6: "Amount: 123.45"}
            draw.text((margin + 7, y + 3), labels[index], fill=(75, 80, 85), font=font)
        else:
            draw.line((margin, y + 9, width - margin - (index % 3) * 35, y + 9), fill=(75, 80, 85), width=2)
    draw.text((margin, height - margin - 20), f"Synthetic fixture profile: {profile}", fill=(75, 80, 85), font=font)
    return image


def _draw_pattern(size: tuple[int, int], rng: random.Random, dark: bool = False) -> Image.Image:
    background = (18, 18, 18) if dark else (132, 153, 165)
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    width, height = size
    for index in range(14):
        x = (index * 47 + 23) % width
        y = (index * 61 + 17) % height
        radius = 9 + (index * 7) % 33
        tone = 75 + (index * 19) % 150
        if dark:
            tone = 5 + (index * 13) % 40
        color = (tone, min(255, tone + 11), min(255, tone + 19))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline=(35, 45, 52), width=2)
    for index in range(1200):
        x = rng.randrange(width)
        y = rng.randrange(height)
        if dark:
            shade = 7 + rng.randrange(35)
        else:
            shade = 45 + rng.randrange(190)
        image.putpixel((x, y), (shade, min(255, shade + 5), min(255, shade + 9)))
    for y in range(20, height, 55):
        if dark:
            draw.line((0, y, width - 1, y), fill=(48, 48, 48), width=3)
        else:
            draw.line((0, y, width - 1, y), fill=(38, 47, 51), width=3)
    return image


def generate_fixtures(output_dir: str | Path) -> dict[str, Any]:
    """Write a deterministic fixture set and a manifest identifying each file."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(FIXTURE_RANDOM_SEED)

    clean = _draw_document((768, 1086), "invoice")
    blurred = _draw_pattern((800, 600), rng).filter(ImageFilter.GaussianBlur(radius=9))
    dark = _draw_pattern((800, 600), rng, dark=True)
    wrong_aspect = _draw_document((1200, 240), "general")
    stripped = _draw_document((768, 1086), "invoice")

    files: dict[str, bytes] = {
        "clean_document.png": _png_bytes(clean, _metadata(clean, "invoice")),
        "blurred_photo.png": _png_bytes(blurred, _metadata(blurred, "general")),
        "underexposed.png": _png_bytes(dark, _metadata(dark, "general")),
        "wrong_aspect.png": _png_bytes(wrong_aspect, _metadata(wrong_aspect, "general")),
        "metadata_stripped.png": _png_bytes(stripped),
    }
    valid_for_truncation = _png_bytes(_draw_document((768, 1086), "general"), _metadata(_draw_document((768, 1086), "general"), "general"))
    files["truncated_corrupt.png"] = valid_for_truncation[: len(valid_for_truncation) // 2]

    for name, content in files.items():
        (root / name).write_bytes(content)
    manifest = {
        "label": "Every file listed here is a synthetic, fictional test fixture generated locally.",
        "random_seed": FIXTURE_RANDOM_SEED,
        "generator_uses_external_downloads": False,
        "fixtures": [
            {"file": name, "planted_defect": defect, "fictional": True}
            for name, defect in (
                ("clean_document.png", None),
                ("blurred_photo.png", "blur"),
                ("underexposed.png", "exposure"),
                ("wrong_aspect.png", "aspect_ratio"),
                ("truncated_corrupt.png", "format_integrity"),
                ("metadata_stripped.png", "metadata_consistency"),
            )
        ],
    }
    (root / "fixtures-manifest.json").write_bytes(canonical_json_bytes(manifest))
    return manifest
