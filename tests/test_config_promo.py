"""Config persistence and promo-banner tests (all offline)."""

from __future__ import annotations

import json
from pathlib import Path

from pdftoolbox import promo
from pdftoolbox.config import DEFAULTS, load_config, save_config


class TestConfig:
    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        config = load_config(tmp_path / "absent.json")
        assert config["dpi"] == DEFAULTS["dpi"]
        assert config["promo"]["timeout_seconds"] == 2.0

    def test_roundtrip_and_merge(self, tmp_path: Path) -> None:
        target = tmp_path / "config.json"
        save_config({"dpi": 300, "promo": {"active": None, "url": "https://x/y.json"}}, target)
        loaded = load_config(target)
        assert loaded["dpi"] == 300
        assert loaded["promo"]["url"] == "https://x/y.json"
        assert loaded["promo"]["timeout_seconds"] == 2.0  # default preserved
        assert loaded["ocr_dpi"] == DEFAULTS["ocr_dpi"]

    def test_same_folder_default_and_persistence(self, tmp_path: Path) -> None:
        # NOTE: GUI checkbox state; default False so legacy configs behave
        assert DEFAULTS["same_folder"] is False
        target = tmp_path / "config.json"
        save_config({"same_folder": True}, target)
        assert load_config(target)["same_folder"] is True

    def test_last_dir_default_and_persistence(self, tmp_path: Path) -> None:
        # NOTE: folder of the last imported file; empty means "no memory yet"
        assert DEFAULTS["last_dir"] == ""
        target = tmp_path / "config.json"
        save_config({"last_dir": "C:\\scans"}, target)
        assert load_config(target)["last_dir"] == "C:\\scans"

    def test_legacy_config_gets_last_dir_default(self, tmp_path: Path) -> None:
        target = tmp_path / "config.json"
        target.write_text(json.dumps({"dpi": 300}), encoding="utf-8")
        assert load_config(target)["last_dir"] == ""

    def test_placeholder_promo_url_migrates_to_update_manifest(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "config.json"
        target.write_text(
            json.dumps(
                {"promo": {"url": "https://example.invalid/pdf-toolbox/promo.json"}}
            ),
            encoding="utf-8",
        )

        assert load_config(target)["promo"]["url"] == DEFAULTS["promo"]["url"]

    def test_corrupt_file_returns_defaults(self, tmp_path: Path) -> None:
        target = tmp_path / "config.json"
        target.write_text("{not json", encoding="utf-8")
        assert load_config(target)["dpi"] == DEFAULTS["dpi"]

    def test_non_dict_json_returns_defaults(self, tmp_path: Path) -> None:
        target = tmp_path / "config.json"
        target.write_text("[1, 2, 3]", encoding="utf-8")
        assert load_config(target)["dpi"] == DEFAULTS["dpi"]


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, _limit: int = -1) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args) -> None:
        return None


class TestPromo:
    def test_release_manifest_has_version_policy_and_secure_download(self) -> None:
        manifest_path = Path(__file__).resolve().parents[1] / "promo.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert not promo.is_newer_version(
            manifest["minimum_version"], manifest["latest_version"]
        )
        assert not promo.is_below_minimum(
            manifest["latest_version"],
            manifest["minimum_version"],
            manifest["latest_version"],
        )
        assert promo.is_https_url(manifest["download_url"])

    def test_empty_url_is_none(self) -> None:
        assert promo.fetch_promo("") is None

    def test_unreachable_host_fails_silently(self) -> None:
        # port 9 (discard) refuses quickly; must never raise
        assert promo.fetch_promo("http://127.0.0.1:9/promo.json", timeout=0.5) is None

    def test_valid_payload(self, monkeypatch) -> None:
        payload = json.dumps({"active": True, "message": "hi", "url": "https://x"}).encode()
        monkeypatch.setattr(
            promo.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(payload)
        )
        data = promo.fetch_promo("https://example/promo.json")
        assert data == {"active": True, "message": "hi", "url": "https://x"}

    def test_missing_active_is_coerced_false(self, monkeypatch) -> None:
        payload = json.dumps({"message": "hi", "url": "https://x"}).encode()
        monkeypatch.setattr(
            promo.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(payload)
        )
        data = promo.fetch_promo("https://example/promo.json")
        assert data["active"] is False

    def test_malformed_json_is_none(self, monkeypatch) -> None:
        monkeypatch.setattr(
            promo.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(b"{oops")
        )
        assert promo.fetch_promo("https://example/promo.json") is None

    def test_non_dict_is_none(self, monkeypatch) -> None:
        monkeypatch.setattr(
            promo.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(b"[1,2]")
        )
        assert promo.fetch_promo("https://example/promo.json") is None

    def test_version_comparison_handles_numeric_release_parts(self) -> None:
        assert promo.is_newer_version("0.1.10", "0.1.9")
        assert not promo.is_newer_version("0.1.9.0", "0.1.9")
        assert promo.is_below_minimum("0.1.6", "0.1.7", "0.1.8")
        assert not promo.is_below_minimum("0.1.7", "0.1.7", "0.1.8")

    def test_invalid_or_inconsistent_versions_do_not_block(self) -> None:
        assert not promo.is_below_minimum("dev", "0.1.7", "0.1.8")
        assert not promo.is_below_minimum("0.1.6", "0.1.9", "0.1.8")

    def test_update_download_requires_https(self) -> None:
        assert promo.is_https_url("https://example.com/download")
        assert not promo.is_https_url("http://example.com/download")
        assert not promo.is_https_url("https://[")
