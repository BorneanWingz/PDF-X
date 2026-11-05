"""Offline OCR using RapidOCR (Apache-2.0, ONNX runtime, bundled models)."""

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
    """Optional detached model set: models/rapidocr with det/cls/rec ONNX + keys."""
    candidate = models_dir() / "rapidocr"
    if not candidate.is_dir():
        return None
    has_rec = any(candidate.glob("rec*.onnx"))
    has_det = any(candidate.glob("det*.onnx"))
    if has_rec and has_det:
        return str(candidate)
    return None


def _get_engine():
    global _engine, _engine_dir
    model_dir = _configured_model_dir()
    if _engine is not None and _engine_dir == model_dir:
        return _engine
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise EngineUnavailable(
            "rapidocr-onnxruntime is not installed; run: uv sync"
        ) from exc
    kwargs = {}
    if model_dir:
        kwargs["det_model_path"] = str(next(Path(model_dir).glob("det*.onnx")))
        kwargs["rec_model_path"] = str(next(Path(model_dir).glob("rec*.onnx")))
        cls_candidates = list(Path(model_dir).glob("cls*.onnx"))
        if cls_candidates:
            kwargs["cls_model_path"] = str(cls_candidates[0])
    _engine = RapidOCR(**kwargs)
    _engine_dir = model_dir
    return _engine


def reset_engine() -> None:
    """Forget the cached engine (used by tests and after model changes)."""
    global _engine, _engine_dir
    _engine = None
    _engine_dir = None


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
