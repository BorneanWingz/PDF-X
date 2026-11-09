"""Offline OCR using RapidOCR (Apache-2.0, ONNX runtime, bundled models).

The bundled models are PP-OCRv4 (det + rec + cls), about 16 MB in total, which
is what keeps the portable build usable on a CPU-only machine. A larger model
set can be dropped into ``models/rapidocr`` beside the exe; see
``scripts\\download-ocr-models.ps1``. Detection tuning lives in ``config.py``
and is justified by ``scripts/ocr_benchmark.py``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
import pypdfium2 as pdfium

from ..paths import models_dir
from . import ConversionError, EngineUnavailable

# Module-level OCR engine cache: RapidOCR/ONNX initialisation costs seconds,
# so it happens once per process. _engine_dir tracks the configured model set
# so switching models in models/rapidocr invalidates the cache.
_engine = None
_engine_dir: str | None = None
_engine_tuning: tuple | None = None
# Set when a detached model set could not be loaded and the bundled models were
# used instead, so the failure is visible rather than silent.
_fallback_reason: str | None = None

# NOTE: RapidOCR's stock max_side_len=2000 downscales an A4 page rendered at
# 200 DPI (1654x2338 px) before detection, which merged words across table
# cells ("solids12.450mg perlitre") and cost whole cells in the XLSX output.
# Measured with scripts/ocr_benchmark.py on a degraded A4 scan:
#   200 DPI: 85.7% -> 100% of table/body tokens recovered
#   300 DPI: 92.9% -> 100% with unclip_ratio=1.8
#   clean page: unchanged (no regression)
# The cost is roughly 25% more time per page, which is the right trade for a
# tool whose whole purpose is pulling values out of tables. Both stay
# overridable from config for anyone who prefers the old speed.
DEFAULT_MAX_SIDE_LEN = 3000
DEFAULT_UNCLIP_RATIO = 1.8


def tuning_from_config(config) -> dict:
    """Detection tuning overrides, with the measured defaults applied.

    NOTE: kept as a small pure helper so the defaults stay testable without
    building an engine (which needs ONNX models on disk).
    """
    config = config or {}

    def _number(key: str, fallback, cast):
        value = config.get(key, fallback)
        try:
            return cast(value)
        except (TypeError, ValueError):
            return fallback

    return {
        "max_side_len": _number("ocr_max_side_len", DEFAULT_MAX_SIDE_LEN, int),
        "det_unclip_ratio": _number("ocr_unclip_ratio", DEFAULT_UNCLIP_RATIO, float),
    }


@dataclass
class OcrLine:
    text: str
    confidence: float
    # box in page pixel coordinates: (x0, y0, x1, y1)
    box: tuple[float, float, float, float]


@dataclass
class OcrPage:
    number: int
    width: int
    height: int
    lines: list[OcrLine]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def average_confidence(self) -> float:
        if not self.lines:
            return 0.0
        return sum(line.confidence for line in self.lines) / len(self.lines)


def _configured_model_dir() -> str | None:
    """Optional detached model set: models/rapidocr with det/cls/rec ONNX.

    NOTE: the recogniser's character set is embedded in the ONNX metadata
    (``character``), so a wholesale swap needs no sidecar keys file. A custom
    character set is still honoured via ``rec_keys_path`` when present.
    """
    candidate = models_dir() / "rapidocr"
    if not candidate.is_dir():
        return None
    has_rec = any(candidate.glob("rec*.onnx"))
    has_det = any(candidate.glob("det*.onnx"))
    if has_rec and has_det:
        return str(candidate)
    return None


def _get_engine():
    global _engine, _engine_dir, _engine_tuning, _fallback_reason
    from ..config import load_config

    model_dir = _configured_model_dir()
    try:
        tuning = tuning_from_config(load_config())
    except Exception:  # noqa: BLE001 - a bad config must never block OCR
        tuning = tuning_from_config({})
    # NOTE: the tuned values are part of the cache key - editing config.json
    # must not keep serving an engine built with the previous numbers
    tuning_key = (tuning["max_side_len"], tuning["det_unclip_ratio"])
    if (
        _engine is not None
        and _engine_dir == model_dir
        and _engine_tuning == tuning_key
    ):
        return _engine
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise EngineUnavailable(
            "rapidocr-onnxruntime is not installed; run: uv sync"
        ) from exc

    # NOTE: tuning goes in first, then a detached model set overrides only the
    # model paths - so the measured detection defaults survive a model swap
    kwargs: dict = dict(tuning)
    fallback = None
    if model_dir:
        root = Path(model_dir)
        kwargs["det_model_path"] = str(next(root.glob("det*.onnx")))
        kwargs["rec_model_path"] = str(next(root.glob("rec*.onnx")))
        cls_candidates = list(root.glob("cls*.onnx"))
        if cls_candidates:
            kwargs["cls_model_path"] = str(cls_candidates[0])
        keys = list(root.glob("*.txt"))
        if keys:
            # optional sidecar character set for a custom recogniser
            kwargs["rec_keys_path"] = str(keys[0])

    if model_dir:
        try:
            _engine = RapidOCR(**kwargs)
        except Exception as exc:  # noqa: BLE001
            # NOTE: a half-copied or mismatched detached model set must not take
            # OCR down with it - fall back to the bundled models and say so
            fallback = f"{model_dir}: {exc}"
            kwargs = dict(tuning)
            _engine = RapidOCR(**kwargs)
    else:
        _engine = RapidOCR(**kwargs)

    _fallback_reason = fallback
    _engine_dir = model_dir
    _engine_tuning = tuning_key
    return _engine


def last_fallback_reason() -> str | None:
    """Why the bundled models were used instead of the detached set, if so."""
    return _fallback_reason


def reset_engine() -> None:
    """Forget the cached engine (used by tests and after model changes)."""
    global _engine, _engine_dir, _engine_tuning, _fallback_reason
    _engine = None
    _engine_dir = None
    _engine_tuning = None
    _fallback_reason = None


def _parse_result(raw) -> tuple[list[OcrLine], float]:
    lines: list[OcrLine] = []
    if not raw:
        return lines, 0.0
    total_score = 0.0
    for item in raw:
        # NOTE: RapidOCR returns each detected box as a 4-point polygon;
        # collapse it to an axis-aligned (x0, y0, x1, y1) rectangle here
        box, text, score = item[0], item[1], float(item[2])
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        lines.append(
            OcrLine(
                text=str(text),
                confidence=score,
                box=(min(xs), min(ys), max(xs), max(ys)),
            )
        )
        total_score += score
    average = total_score / len(lines) if lines else 0.0
    return lines, average


def ocr_image(image: Image.Image) -> tuple[list[OcrLine], float]:
    """Run OCR on one image. Returns (lines, elapsed seconds)."""
    engine = _get_engine()
    array = np.asarray(image.convert("RGB"))
    started = time.perf_counter()
    try:
        raw, detail = engine(array)
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"OCR failed: {exc}") from exc
    lines, _ = _parse_result(raw)
    # NOTE: RapidOCR's second value is a list of per-stage timings (summed
    # here); some versions return a single float, and anything unexpected
    # falls back to wall-clock time - this exact mismatch was a past bug.
    if isinstance(detail, (int, float)):
        elapsed = float(detail)
    elif isinstance(detail, (list, tuple)) and detail and all(
        isinstance(value, (int, float)) for value in detail
    ):
        elapsed = float(sum(detail))
    else:
        elapsed = time.perf_counter() - started
    return lines, elapsed


def ocr_pdf(
    src: Path,
    dpi: int = 200,
    pages: list[int] | None = None,
    on_progress=None,
) -> list[OcrPage]:
    doc = pdfium.PdfDocument(str(src))
    results: list[OcrPage] = []
    try:
        count = len(doc)
        indices = [p - 1 for p in pages] if pages else list(range(count))
        for done, index in enumerate(indices, start=1):
            if index < 0 or index >= count:
                raise ConversionError(f"page {index + 1} out of range (1-{count})")
            page = doc[index]
            bitmap = page.render(scale=dpi / 72.0)
            image = bitmap.to_pil().convert("RGB")
            lines, _ = ocr_image(image)
            results.append(
                OcrPage(
                    number=index + 1,
                    width=image.width,
                    height=image.height,
                    lines=lines,
                )
            )
            if on_progress:
                on_progress(done, len(indices))
    finally:
        doc.close()
    return results
