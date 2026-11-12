"""Fetch an optional promotion and update manifest with a 2 s timeout.

Design rules (see project notes): the call must never block or break the
app. Any failure means "no banner or update prompt". The remote file can point
to a release page or a Play Store listing without redistributing the exe.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse
import urllib.request

_MAX_BYTES = 64 * 1024
_USER_AGENT = "PDFToolbox/0.1 (promo-check)"
_VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")


def fetch_promo(url: str, timeout: float = 2.0) -> dict | None:
    """Return the parsed promo dict, or None on any failure.

    NOTE: every failure path returns None on purpose - the banner must never
    block startup, surface an error, or retry (offline-first design rule).
    """
    if not url:
        return None
    try:
        # NOTE: byte cap prevents a hostile/huge response from eating memory
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(_MAX_BYTES)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return None
        # NOTE: anything that is not a literal JSON true/false counts as
        # disabled, so a typo in the hosted file can never pop a banner
        if not isinstance(data.get("active"), bool):
            data["active"] = False
        return data
    except Exception:  # noqa: BLE001 - offline, blocked, malformed: all silent
        return None


def _version_key(version: str) -> tuple[int, ...] | None:
    if (
        not isinstance(version, str)
        or len(version) > 64
        or not _VERSION_PATTERN.fullmatch(version)
    ):
        return None
    try:
        parts = [int(part) for part in version.split(".")]
    except ValueError:
        return None
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_key = _version_key(candidate)
    current_key = _version_key(current)
    return (
        candidate_key is not None
        and current_key is not None
        and candidate_key > current_key
    )


def is_below_minimum(current: str, minimum: str, latest: str) -> bool:
    current_key = _version_key(current)
    minimum_key = _version_key(minimum)
    latest_key = _version_key(latest)
    return (
        current_key is not None
        and minimum_key is not None
        and latest_key is not None
        and minimum_key <= latest_key
        and current_key < minimum_key
    )


def is_https_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.netloc)
