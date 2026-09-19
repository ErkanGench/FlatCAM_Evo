"""Tests for version-independent defaults persistence and safe .get() fallbacks.

Ticket 6: Ensure defaults dict is no longer versioned, preferences survive app
version changes, and all reads use .get() with factory-default fallbacks.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from defaults import AppDefaults, AppOptions


class FakeSignal:
    def __init__(self):
        self.emissions = []

    def emit(self, *args):
        self.emissions.append(args)


class TestVersionIndependentPreferences:
    """Preferences must survive app version changes without orphaning or reset."""

    def test_preferences_filename_is_stable_across_versions(self, tmp_path):
        """The preferences filename must not include the app version."""
        from appMain import App

        app1 = App.__new__(App)
        app1.data_path = str(tmp_path)
        app1.version = "1.0"
        path1 = app1.defaults_path()

        app2 = App.__new__(App)
        app2.data_path = str(tmp_path)
        app2.version = "2.0"
        path2 = app2.defaults_path()

        assert path1 == path2, "Preferences filename must be version-independent"
        assert "1.0" not in path1
        assert "2.0" not in path2

    def test_factory_defaults_filename_is_stable_across_versions(self, tmp_path):
        """The factory defaults filename must not include the app version."""
        from appMain import App

        app1 = App.__new__(App)
        app1.data_path = str(tmp_path)
        app1.version = "1.0"
        path1 = app1.factory_defaults_path()

        app2 = App.__new__(App)
        app2.data_path = str(tmp_path)
        app2.version = "2.0"
        path2 = app2.factory_defaults_path()

        assert path1 == path2, "Factory defaults filename must be version-independent"

    def test_saved_preferences_survive_version_change(self, tmp_path):
        """User preferences saved in version 1.0 load correctly in version 2.0."""
        defaults_v1 = AppDefaults(beta=False, version="1.0")
        defaults_v1["units"] = "IN"
        defaults_v1["global_version_check"] = False
        defaults_v1["global_update_url"] = "https://custom.example.com"

        filename = tmp_path / "current_defaults.FlatConfig"
        defaults_v1.write(str(filename))

        defaults_v2 = AppDefaults(beta=False, version="2.0")
        inform = FakeSignal()
        defaults_v2.load(str(filename), inform)

        assert defaults_v2["units"] == "IN"
        assert defaults_v2["global_version_check"] is False
        assert defaults_v2["global_update_url"] == "https://custom.example.com"

    def test_missing_keys_in_old_file_fall_back_to_factory_defaults(self, tmp_path):
        """New keys added in later versions fall back to factory defaults without KeyError."""
        old_data = {
            "units": "MM",
            "global_version_check": True,
        }
        filename = tmp_path / "current_defaults.FlatConfig"
        filename.write_text(json.dumps(old_data))

        defaults = AppDefaults(beta=False, version="2.0")
        inform = FakeSignal()
        defaults.load(str(filename), inform)

        assert defaults["units"] == "MM"
        assert defaults["global_version_check"] is True
        assert defaults["global_update_url"] == AppDefaults.factory_defaults["global_update_url"]
        assert defaults["global_worker_number"] == AppDefaults.factory_defaults["global_worker_number"]

    def test_user_overrides_win_over_factory_defaults_including_falsy_values(self, tmp_path):
        """User overrides (including False, 0, empty strings) must not be replaced by defaults."""
        saved_data = {
            "global_version_check": False,
            "global_worker_number": 0,
            "global_last_folder": "",
            "units": "IN",
        }
        filename = tmp_path / "current_defaults.FlatConfig"
        filename.write_text(json.dumps(saved_data))

        defaults = AppDefaults(beta=False, version="2.0")
        inform = FakeSignal()
        defaults.load(str(filename), inform)

        assert defaults["global_version_check"] is False
        assert defaults["global_worker_number"] == 0
        assert defaults["global_last_folder"] == ""
        assert defaults["units"] == "IN"

    def test_first_run_creates_factory_defaults(self, tmp_path):
        """First run with no existing file loads factory defaults."""
        filename = tmp_path / "current_defaults.FlatConfig"
        assert not filename.exists()

        defaults = AppDefaults(beta=False, version="1.0")
        inform = FakeSignal()
        defaults.load(str(filename), inform)

        assert defaults["units"] == AppDefaults.factory_defaults["units"]
        assert defaults["global_version_check"] == AppDefaults.factory_defaults["global_version_check"]
        assert defaults["global_update_url"] == AppDefaults.factory_defaults["global_update_url"]


class TestSafeGetFallbacks:
    """All defaults/options reads must use .get() with factory-default fallbacks."""

    def test_nested_defaults_are_independent_from_factory_and_snapshot(self):
        """Runtime and restore snapshots must not share mutable factory values."""
        defaults = AppDefaults(beta=False, version="1.0")
        other_defaults = AppDefaults(beta=False, version="1.0")

        defaults["global_bookmarks"]["custom"] = {
            "title": "Custom",
            "url": "https://example.com",
        }
        defaults["document_font_sizes"].append("999")

        assert "custom" not in AppDefaults.factory_defaults["global_bookmarks"]
        assert "custom" not in other_defaults["global_bookmarks"]
        assert "999" not in AppDefaults.factory_defaults["document_font_sizes"]
        assert "999" not in other_defaults["document_font_sizes"]
        assert "custom" not in defaults.current_defaults["global_bookmarks"]

    def test_appdefaults_get_uses_factory_baseline_without_literal(self):
        """Missing application preferences resolve through the canonical baseline."""
        defaults = AppDefaults(beta=False, version="1.0")
        del defaults.defaults["global_update_url"]

        assert defaults.get("global_update_url") == AppDefaults.factory_defaults["global_update_url"]

    def test_appdefaults_getitem_raises_on_missing_key(self):
        """AppDefaults subscript access raises KeyError on missing keys (baseline)."""
        defaults = AppDefaults(beta=False, version="1.0")
        with pytest.raises(KeyError):
            _ = defaults["nonexistent_key"]

    def test_appdefaults_get_returns_factory_default_for_missing_key(self):
        """AppDefaults.get() should return factory default for missing keys."""
        defaults = AppDefaults(beta=False, version="1.0")
        del defaults.defaults["units"]

        result = defaults.get("units", AppDefaults.factory_defaults.get("units"))
        assert result == "MM"

    def test_appoptions_get_returns_value_when_present(self):
        """AppOptions.get() returns the value when key exists."""
        options = AppOptions(version="1.0")
        options["units"] = "IN"

        result = options.get("units", "MM")
        assert result == "IN"

    def test_appoptions_get_returns_fallback_when_missing(self):
        """AppOptions.get() returns fallback when key is missing."""
        options = AppOptions(version="1.0")

        result = options.get("nonexistent_key", "fallback_value")
        assert result == "fallback_value"

    def test_appoptions_load_restores_baseline_before_sparse_overlay(self, tmp_path):
        """Sparse imports restore missing keys while preserving falsy overrides."""
        filename = tmp_path / "preferences.FlatConfig"
        filename.write_text(json.dumps({
            "global_version_check": False,
            "global_worker_number": 0,
            "global_last_folder": "",
        }))

        baseline = AppDefaults(beta=False, version="1.0")
        options = AppOptions(version="1.0", baseline=baseline)
        options["global_update_url"] = "https://stale.example.com"
        options.load(str(filename), FakeSignal())

        assert options["global_version_check"] is False
        assert options["global_worker_number"] == 0
        assert options["global_last_folder"] == ""
        assert options["global_update_url"] == AppDefaults.factory_defaults["global_update_url"]

    def test_appoptions_nested_values_are_independent_from_baseline(self):
        """Option values copied from a baseline must be safe to mutate."""
        baseline = AppDefaults(beta=False, version="1.0")
        options = AppOptions(version="1.0", baseline=baseline)

        options["global_bookmarks"]["custom"] = {"title": "Custom"}

        assert "custom" not in baseline["global_bookmarks"]
        assert "custom" not in AppDefaults.factory_defaults["global_bookmarks"]

    def test_safe_read_pattern_for_application_preferences(self):
        """Demonstrate the safe read pattern: options.get(key, defaults.get(key, factory[key]))."""
        defaults = AppDefaults(beta=False, version="1.0")
        options = AppOptions(version="1.0")

        options["units"] = "IN"
        del defaults.defaults["global_update_url"]

        units = options.get("units", defaults.get("units", AppDefaults.factory_defaults.get("units")))
        assert units == "IN"

        update_url = options.get(
            "global_update_url",
            defaults.get("global_update_url", AppDefaults.factory_defaults.get("global_update_url"))
        )
        assert update_url == AppDefaults.factory_defaults["global_update_url"]


class TestMigrationBehavior:
    """Migration should merge missing keys, not reset on version mismatch."""

    def test_no_migration_reset_on_version_mismatch(self, tmp_path):
        """Version mismatch in saved file should not trigger reset to factory defaults."""
        old_data = {
            "version": "1.0",
            "units": "IN",
            "global_version_check": False,
        }
        filename = tmp_path / "current_defaults.FlatConfig"
        filename.write_text(json.dumps(old_data))

        defaults = AppDefaults(beta=False, version="2.0")
        inform = FakeSignal()
        defaults.load(str(filename), inform)

        assert defaults.old_defaults_found is False
        assert defaults["units"] == "IN"
        assert defaults["global_version_check"] is False

    def test_beta_mode_does_not_reset_on_version_mismatch(self, tmp_path):
        """Even in beta mode, version mismatch should not reset preferences."""
        old_data = {
            "version": "1.0",
            "units": "IN",
        }
        filename = tmp_path / "current_defaults.FlatConfig"
        filename.write_text(json.dumps(old_data))

        defaults = AppDefaults(beta=True, version="2.0")
        inform = FakeSignal()
        defaults.load(str(filename), inform)

        assert defaults["units"] == "IN"


class TestLegacyCompatibility:
    """Legacy versioned files must be discovered and migrated."""

    def test_legacy_file_discovered_when_stable_file_missing(self, tmp_path):
        """Legacy versioned file is found when stable file doesn't exist."""
        legacy_file = tmp_path / "current_defaults_1.0.FlatConfig"
        legacy_file.write_text(json.dumps({
            "units": "IN",
            "global_version_check": False,
        }))

        found = AppDefaults.find_legacy_defaults_file(str(tmp_path), "1.0")
        assert found == str(legacy_file)

    def test_legacy_file_with_current_version_preferred(self, tmp_path):
        """Legacy file matching current version is preferred over others."""
        legacy_10 = tmp_path / "current_defaults_1.0.FlatConfig"
        legacy_10.write_text(json.dumps({"units": "IN"}))
        
        legacy_20 = tmp_path / "current_defaults_2.0.FlatConfig"
        legacy_20.write_text(json.dumps({"units": "MM"}))

        found = AppDefaults.find_legacy_defaults_file(str(tmp_path), "2.0")
        assert found == str(legacy_20)

    def test_most_recent_legacy_selected_when_no_exact_match(self, tmp_path):
        """Most recent legacy file is selected when no exact version match."""
        legacy_10 = tmp_path / "current_defaults_1.0.FlatConfig"
        legacy_10.write_text(json.dumps({"units": "IN"}))
        
        legacy_20 = tmp_path / "current_defaults_2.0.FlatConfig"
        legacy_20.write_text(json.dumps({"units": "MM"}))

        found = AppDefaults.find_legacy_defaults_file(str(tmp_path), "3.0")
        # Should pick 2.0 as most recent
        assert found == str(legacy_20)

    def test_legacy_selection_uses_filename_for_mtime_ties(self, tmp_path):
        """Equal mtimes use a deterministic filename tiebreaker."""
        legacy_a = tmp_path / "current_defaults_1.0.FlatConfig"
        legacy_b = tmp_path / "current_defaults_2.0.FlatConfig"
        legacy_a.write_text(json.dumps({"units": "IN"}))
        legacy_b.write_text(json.dumps({"units": "MM"}))

        import os

        tie_mtime = 1_700_000_000
        os.utime(legacy_a, (tie_mtime, tie_mtime))
        os.utime(legacy_b, (tie_mtime, tie_mtime))

        found = AppDefaults.find_legacy_defaults_file(str(tmp_path), "3.0")
        assert found == str(legacy_b)

    def test_non_lexical_version_ordering_uses_mtime(self, tmp_path):
        """Non-lexically-ordered versions (9.9 vs 10.0) select most recently modified."""
        import time
        
        # Create 9.9 first (lexically larger than 10.0 in string comparison)
        legacy_99 = tmp_path / "current_defaults_9.9.FlatConfig"
        legacy_99.write_text(json.dumps({"units": "IN"}))
        
        # Wait a bit to ensure different mtime
        time.sleep(0.01)
        
        # Create 10.0 second (lexically smaller but more recent)
        legacy_100 = tmp_path / "current_defaults_10.0.FlatConfig"
        legacy_100.write_text(json.dumps({"units": "MM"}))

        found = AppDefaults.find_legacy_defaults_file(str(tmp_path), "11.0")
        # Should pick 10.0 as most recently modified, not 9.9 (lexically larger)
        assert found == str(legacy_100)

    def test_startup_discovery_loads_legacy_preferences(self, tmp_path):
        """Startup flow discovers and loads legacy file when stable file missing."""
        from appMain import App
        
        # Create legacy file with user preferences
        legacy_file = tmp_path / "current_defaults_1.0.FlatConfig"
        legacy_file.write_text(json.dumps({
            "units": "IN",
            "global_version_check": False,
            "global_update_url": "https://custom.example.com",
        }))
        
        # Create app instance and call startup discovery
        app = App.__new__(App)
        app.data_path = str(tmp_path)
        app.version = "2.0"
        app.beta = False
        app.log = MagicMock()
        app.inform = FakeSignal()
        
        # Simulate startup discovery
        current_defaults_path = app.defaults_path()
        assert not os.path.isfile(current_defaults_path)
        
        legacy_path = AppDefaults.find_legacy_defaults_file(app.data_path, str(app.version))
        assert legacy_path == str(legacy_file)
        
        # Load from legacy file
        defaults = AppDefaults(beta=False, version="2.0")
        inform = FakeSignal()
        defaults.load(legacy_path, inform)
        
        # Verify user preferences preserved
        assert defaults["units"] == "IN"
        assert defaults["global_version_check"] is False
        assert defaults["global_update_url"] == "https://custom.example.com"

    def test_no_legacy_file_returns_none(self, tmp_path):
        """Returns None when no legacy files exist."""
        found = AppDefaults.find_legacy_defaults_file(str(tmp_path), "1.0")
        assert found is None

    def test_version_field_stripped_on_load(self, tmp_path):
        """Obsolete 'version' field is stripped from loaded data."""
        data = {
            "version": "1.0",
            "units": "IN",
        }
        filename = tmp_path / "current_defaults.FlatConfig"
        filename.write_text(json.dumps(data))

        defaults = AppDefaults(beta=False, version="2.0")
        inform = FakeSignal()
        defaults.load(str(filename), inform)

        assert "version" not in defaults.defaults
        assert defaults["units"] == "IN"

    def test_version_field_stripped_on_save(self, tmp_path):
        """Obsolete 'version' field is not written to file."""
        defaults = AppDefaults(beta=False, version="2.0")
        defaults["units"] = "IN"
        
        filename = tmp_path / "current_defaults.FlatConfig"
        defaults.write(str(filename))
        
        saved_data = json.loads(filename.read_text())
        assert "version" not in saved_data
        assert saved_data["units"] == "IN"

    def test_factory_defaults_file_updated_with_new_keys(self, tmp_path):
        """Factory defaults file is rewritten if missing new keys."""
        factory_file = tmp_path / "factory_defaults.FlatConfig"
        
        # Write incomplete factory defaults (missing some keys)
        incomplete = {"units": "MM", "first_run": True}
        factory_file.write_text(json.dumps(incomplete))
        os.chmod(str(factory_file), stat.S_IWRITE)
        
        # Save factory defaults - should rewrite with all keys
        AppDefaults.save_factory_defaults(str(factory_file), "2.0")
        
        saved_data = json.loads(factory_file.read_text())
        # Should have all factory keys
        assert "global_version_check" in saved_data
        assert "global_update_url" in saved_data
        assert len(saved_data) >= len(AppDefaults.factory_defaults)
