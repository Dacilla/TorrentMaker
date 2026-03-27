"""Tests for torrent_utils/config_loader.py"""
import pytest
import configparser
from unittest.mock import patch


# ---------------------------------------------------------------------------
# load_settings
# ---------------------------------------------------------------------------

class TestLoadSettings:
    def test_generates_template_when_missing(self, tmp_path, monkeypatch):
        """When settings.ini is absent, a template is created and sys.exit is called."""
        from torrent_utils import config_loader
        monkeypatch.setattr(config_loader, "SETTINGS_FILE", str(tmp_path / "settings.ini"))
        with pytest.raises(SystemExit):
            config_loader.load_settings()
        assert (tmp_path / "settings.ini").exists()

    def test_returns_settings_when_complete(self, tmp_path, monkeypatch):
        """When all required keys are present, settings are returned without exit."""
        from torrent_utils import config_loader

        # Build a complete ini from the master template
        cfg = configparser.ConfigParser()
        cfg.read_dict(config_loader.CONFIG_STRUCTURE)
        ini_path = tmp_path / "settings.ini"
        with open(ini_path, "w") as f:
            cfg.write(f)

        monkeypatch.setattr(config_loader, "SETTINGS_FILE", str(ini_path))
        settings = config_loader.load_settings()
        assert settings is not None
        assert "TMDB_API" in [k.upper() for k in settings.keys()]

    def test_adds_missing_fields_without_exit(self, tmp_path, monkeypatch):
        """Existing ini missing a new field gets it added; no sys.exit."""
        from torrent_utils import config_loader

        # Write an ini with only a subset of keys
        partial_cfg = configparser.ConfigParser()
        partial_cfg["DEFAULT"] = {"TMDB_API": "mykey"}
        ini_path = tmp_path / "settings.ini"
        with open(ini_path, "w") as f:
            partial_cfg.write(f)

        monkeypatch.setattr(config_loader, "SETTINGS_FILE", str(ini_path))
        settings = config_loader.load_settings()
        # User's value must be preserved
        assert settings.get("TMDB_API") == "mykey"
        # A field that was missing must now be present (e.g. QBIT_HOST)
        assert "qbit_host" in settings


# ---------------------------------------------------------------------------
# validate_settings
# ---------------------------------------------------------------------------

class TestValidateSettings:
    def _settings(self, overrides=None):
        d = {"TMDB_API": "key", "HUNO_API": "token", "QBIT_HOST": "http://localhost:8080"}
        if overrides:
            d.update(overrides)
        cfg = configparser.ConfigParser()
        cfg["DEFAULT"] = d
        return cfg["DEFAULT"]

    def test_passes_when_all_present(self):
        from torrent_utils.config_loader import validate_settings
        settings = self._settings()
        assert validate_settings(settings, ["TMDB_API", "HUNO_API"]) is True

    def test_exits_when_field_missing(self):
        from torrent_utils.config_loader import validate_settings
        settings = self._settings({"HUNO_API": ""})
        with pytest.raises(SystemExit):
            validate_settings(settings, ["TMDB_API", "HUNO_API"])

    def test_exits_when_field_absent(self):
        from torrent_utils.config_loader import validate_settings
        # NONEXISTENT_KEY not in settings at all
        settings = self._settings()
        with pytest.raises(SystemExit):
            validate_settings(settings, ["NONEXISTENT_KEY"])
