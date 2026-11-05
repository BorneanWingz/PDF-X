"""Optional promo banner: fetch a small JSON with a 2 s timeout.

Design rules (see project notes): the call must never block or break the
app. Any failure means "no banner". The remote file can later point to a
Play Store listing without redistributing the exe.
"""

from __future__ import annotations

import json
import urllib.request

_MAX_BYTES = 64 * 1024
_USER_AGENT = "PDFToolbox/0.1 (promo-check)"


def fetch_promo(url: str, timeout: float = 2.0) -> dict | None:
    """Return the parsed promo dict, or None on any failure."""
    if not url:
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(_MAX_BYTES)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return None
        if not isinstance(data.get("active"), bool):
            data["active"] = False
        return data
    except Exception:  # noqa: BLE001 - offline, blocked, malformed: all silent
        return None
