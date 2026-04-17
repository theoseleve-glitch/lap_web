"""Tests for UserConfig."""
from __future__ import annotations

from pathlib import Path

from desktop_sync.config import UserConfig


class TestDefaults:
    def test_creates_config_file_on_first_load(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg = UserConfig(path=cfg_path)
        assert cfg_path.is_file()
        assert cfg.auto_upload is False   # Racer default

    def test_default_max_attempts(self, tmp_path):
        cfg = UserConfig(path=tmp_path / "config.json")
        assert cfg.max_upload_attempts == 5


class TestPersistence:
    def test_toggle_auto_upload_persists(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg = UserConfig(path=cfg_path)
        cfg.auto_upload = True
        # Re-read from disk
        cfg2 = UserConfig(path=cfg_path)
        assert cfg2.auto_upload is True

    def test_set_cloud_api_url(self, tmp_path):
        cfg = UserConfig(path=tmp_path / "config.json")
        cfg.cloud_api_url = "https://api.example.com"
        cfg2 = UserConfig(path=tmp_path / "config.json")
        assert cfg2.cloud_api_url == "https://api.example.com"


class TestCorruptFile:
    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text("{{{invalid json")
        cfg = UserConfig(path=cfg_path)
        assert cfg.auto_upload is False
        assert cfg.max_upload_attempts == 5
