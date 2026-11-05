"""Conversion and OCR engines.

The ``pdf_*``, ``images_*`` and ``text_*`` modules use only permissive
dependencies and are always available. ``office`` and ``ocr`` depend on
optional external engines and raise :class:`EngineUnavailable` when those
are missing.
"""

from __future__ import annotations


class EngineUnavailable(RuntimeError):
    """Raised when an optional engine or plugin is not installed."""


class ConversionError(RuntimeError):
    """Raised when a conversion fails for a file-specific reason."""
