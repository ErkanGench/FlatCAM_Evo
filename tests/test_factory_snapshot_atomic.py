"""Transactional-write guarantees for AppDefaults.save_factory_defaults.

Verifies that the factory snapshot is written atomically: existing bytes
survive serialization or replacement failure, temp artifacts are cleaned,
and Windows read-only mode is restored on failure.
"""

import json
import os
import stat
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from defaults import AppDefaults


OLD_VALUES = {"global_version_check": False, "obsolete_preference": True}


def _write_read_only_snapshot(path, data):
    """Write *data* as a read-only factory snapshot."""
    path.write_text(json.dumps(data))
    path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


# -- dump failure with existing read-only snapshot --------------------------

class TestDumpFailurePreservesExisting:
    """If simplejson.dump raises, the existing read-only snapshot survives intact."""

    def test_existing_bytes_survive_dump_failure(self, tmp_path):
        dest = tmp_path / "factory_defaults.FlatConfig"
        _write_read_only_snapshot(dest, OLD_VALUES)
        original_bytes = dest.read_bytes()

        with patch("defaults.simplejson.dump", side_effect=RuntimeError("disk full")):
            AppDefaults.save_factory_defaults(str(dest), "2.0")

        assert dest.read_bytes() == original_bytes
        assert json.loads(dest.read_text()) == OLD_VALUES

    def test_no_temp_artifacts_after_dump_failure(self, tmp_path):
        dest = tmp_path / "factory_defaults.FlatConfig"
        _write_read_only_snapshot(dest, OLD_VALUES)

        with patch("defaults.simplejson.dump", side_effect=RuntimeError("disk full")):
            AppDefaults.save_factory_defaults(str(dest), "2.0")

        leftovers = [f for f in tmp_path.iterdir() if f.name.startswith(".factory_tmp")]
        assert leftovers == []

    def test_read_only_mode_restored_after_dump_failure(self, tmp_path):
        dest = tmp_path / "factory_defaults.FlatConfig"
        _write_read_only_snapshot(dest, OLD_VALUES)

        with patch("defaults.simplejson.dump", side_effect=RuntimeError("disk full")):
            AppDefaults.save_factory_defaults(str(dest), "2.0")

        mode = dest.stat().st_mode
        assert mode & stat.S_IWRITE == 0  # still read-only


# -- replace failure with existing read-only snapshot -----------------------

class TestReplaceFailurePreservesExisting:
    """If os.replace raises, the existing snapshot survives and mode is restored."""

    def test_existing_bytes_survive_replace_failure(self, tmp_path):
        dest = tmp_path / "factory_defaults.FlatConfig"
        _write_read_only_snapshot(dest, OLD_VALUES)
        original_bytes = dest.read_bytes()

        with patch("defaults.os.replace", side_effect=OSError("access denied")):
            AppDefaults.save_factory_defaults(str(dest), "2.0")

        assert dest.read_bytes() == original_bytes

    def test_no_temp_artifacts_after_replace_failure(self, tmp_path):
        dest = tmp_path / "factory_defaults.FlatConfig"
        _write_read_only_snapshot(dest, OLD_VALUES)

        with patch("defaults.os.replace", side_effect=OSError("access denied")):
            AppDefaults.save_factory_defaults(str(dest), "2.0")

        leftovers = [f for f in tmp_path.iterdir() if f.name.startswith(".factory_tmp")]
        assert leftovers == []

    def test_read_only_mode_restored_after_replace_failure(self, tmp_path):
        dest = tmp_path / "factory_defaults.FlatConfig"
        _write_read_only_snapshot(dest, OLD_VALUES)

        with patch("defaults.os.replace", side_effect=OSError("access denied")):
            AppDefaults.save_factory_defaults(str(dest), "2.0")

        mode = dest.stat().st_mode
        assert mode & stat.S_IWRITE == 0  # restored to read-only


# -- missing destination failure --------------------------------------------

class TestMissingDestinationFailure:
    """If no file exists and writing fails, no truncated destination is left."""

    def test_no_destination_after_dump_failure(self, tmp_path):
        dest = tmp_path / "factory_defaults.FlatConfig"

        with patch("defaults.simplejson.dump", side_effect=RuntimeError("disk full")):
            AppDefaults.save_factory_defaults(str(dest), "2.0")

        assert not dest.exists()

    def test_no_temp_artifacts_after_missing_dest_dump_failure(self, tmp_path):
        dest = tmp_path / "factory_defaults.FlatConfig"

        with patch("defaults.simplejson.dump", side_effect=RuntimeError("disk full")):
            AppDefaults.save_factory_defaults(str(dest), "2.0")

        leftovers = [f for f in tmp_path.iterdir() if f.name.startswith(".factory_tmp")]
        assert leftovers == []


# -- successful write to read-only existing ---------------------------------

class TestSuccessfulReadOnlyUpdate:
    """Successful update of a read-only snapshot produces correct content and mode."""

    def test_read_only_snapshot_updated_successfully(self, tmp_path):
        dest = tmp_path / "factory_defaults.FlatConfig"
        _write_read_only_snapshot(dest, OLD_VALUES)

        AppDefaults.save_factory_defaults(str(dest), "2.0")

        assert json.loads(dest.read_text()) == AppDefaults.factory_defaults
        mode = dest.stat().st_mode
        assert mode & stat.S_IWRITE == 0  # read-only again

    def test_no_temp_artifacts_after_success(self, tmp_path):
        dest = tmp_path / "factory_defaults.FlatConfig"
        _write_read_only_snapshot(dest, OLD_VALUES)

        AppDefaults.save_factory_defaults(str(dest), "2.0")

        leftovers = [f for f in tmp_path.iterdir() if f.name.startswith(".factory_tmp")]
        assert leftovers == []
