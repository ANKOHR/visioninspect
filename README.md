# VisionInspect

VisionInspect is a deterministic image inspection pipeline for invoices, receipts, forms, equipment photos, and other image files. It runs named checks, records measured values with each finding, creates annotated PNG evidence, and summarizes directory batches.

## Honesty boundary

VisionInspect uses deterministic rule-based image-analysis heuristics. It is **not a trained vision model**. It uses no neural networks and no learned features. Every result comes from a named check with a stated measurement and threshold. The tool does not recognize semantic objects, read arbitrary document fields, or infer facts that its checks do not measure. A human should review flagged material before making consequential decisions.

## Quickstart

Requirements: Python 3.10 or newer and Pillow. The project has no torch, TensorFlow, CUDA, or GPU package dependency, and its checks run on the CPU.

```powershell
python -m pip install -e ".[dev]"
visioninspect fixtures --out .\fixtures
visioninspect inspect .\fixtures\clean_document.png --profile invoice --out .\clean-report.json
visioninspect inspect .\fixtures\wrong_aspect.png --annotated .\aspect-annotated.png
visioninspect batch .\fixtures --profile general --out .\batch-report.json
visioninspect report --input .\batch-report.json --format html --out .\batch-report.html
visioninspect rules
```

The same commands work as `python -m visioninspect` if the `visioninspect` executable is not on `PATH`. Each inspection appends a UTC timestamped record to `vi-audit.jsonl`. Timestamps are kept out of the JSON inspection reports and annotations so the same input and options produce byte-identical report and annotation outputs.

## Architecture

```text
image bytes
    |
    v
magic-byte and decoder integrity check
    |
    v
Pillow CPU decode --> dimensions and aspect checks
    |                         |
    +--> grayscale Laplacian variance and exposure histogram
    +--> metadata consistency checks
                              |
                              v
             JSON findings with measured evidence pointers
                    |                         |
                    v                         v
          annotated PNG output       batch and HTML/Markdown reports
```

The check engine reads the original bytes, verifies the image with Pillow, decodes it, and computes each reported measurement from those bytes. If decoding fails, the integrity finding explains why pixel-dependent checks could not run. Full-frame outlines mark findings that do not have a reliable localized region, such as blur or metadata concerns. Invalid files receive a deterministic diagnostic PNG.

## Check catalogue

| Check | What it measures | Failure condition |
| --- | --- | --- |
| `format_integrity` | Magic-byte format, Pillow-decoded format, file byte count, SHA-256, and decoder verification | Unknown signature, decode or verify failure, or disagreement between signature and decoder |
| `dimensions` | Decoded width, height, pixel count, and selected-profile width and height bounds | Either dimension falls outside the profile bounds |
| `aspect_ratio` | Decoded width divided by height and selected-profile ratio bounds | Ratio falls outside the profile bounds |
| `blur` | Variance of the 3 by 3 grayscale Laplacian response | Variance is below 30.0 |
| `exposure` | Mean grayscale luminance and the fraction of pixels clipped at luma 0 to 8 and 247 to 255 | Mean luminance is below 35.0 or above 250.0 |
| `metadata_consistency` | Declared dimensions versus decoded dimensions, metadata presence, software tag, and declared profile versus selected profile | Metadata is absent, declared dimensions disagree, or a declared profile conflicts with the selected profile |
| `document_field_plausibility` | For invoice, receipt, and form profiles, counts separate horizontal bands with a text-like amount of dark pixels. It does not read words. | Fewer than four such bands are measured |

Profile bounds are explicit in `visioninspect/engine.py` and are included in report measurements. Supported profiles are `general`, `invoice`, `receipt`, `equipment`, and `form`. The default is `general`.

The blur measurement converts to Pillow grayscale mode `L`. Images whose longest side exceeds 1024 pixels are resized to a maximum side of 1024 using bilinear resampling before blur and exposure analysis. Exposure clipping fractions are reported for both histogram ends; the mean-luminance thresholds drive the current status. The document-field plausibility check is a layout count only. It does not use OCR and does not validate invoice values or other semantic fields.

## Fixtures and determinism

`visioninspect fixtures --out DIR` creates six local PNGs and a `fixtures-manifest.json`. They are all synthetic, fictional, labelled as fixtures in that manifest, and require no external downloads. The generator uses Python's `random.Random` with the fixed seed `20260928`; its seed is recorded in the manifest. No randomness is used by inspection or annotation.

Reports use sorted JSON keys, fixed numeric rounding, no timestamps, and stable check ordering. Annotations use a fixed Pillow drawing path, colors, default font, and PNG encoder settings. The test suite checks fixture regeneration, intended defect detection, report bytes, annotation bytes, profiles, batch totals, the HTML honesty banner, and CLI subcommands.

## Evidence and audit trail

Each finding includes an evidence pointer with the file path, check name, and measured values. Batch reports include counts for each check status, pass rates per profile, per-image reports, and the complete finding list. The separate append-only `vi-audit.jsonl` records each inspected file, selected profile, checks run, findings, and UTC timestamp. The audit trail is operational history and is not embedded in deterministic reports.

## Development

```powershell
python -m pytest
```

The runtime dependencies are Pillow and the Python standard library. Pytest is only needed for development.
