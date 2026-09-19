"""Regression checks for sparse settings and the versionless factory snapshot."""

import json
import os
import stat
from copy import deepcopy
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets
from Bookmark import BookmarkManager
from defaults import AppDefaults, AppOptions, Excellon, Gerber, Geometry


@pytest.mark.parametrize("existing", [False, True])
def test_bookmark_rebuild_preserves_defaults_and_runtime_identity(existing):
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    defaults = AppDefaults(beta=False)
    original = deepcopy(defaults.get("global_bookmarks"))
    options = AppOptions(version="1.0")
    runtime = {}
    if existing:
        options["global_bookmarks"] = runtime
    storage = {"1": ["Example", "https://example.com"]}
    manager = BookmarkManager(
        SimpleNamespace(
            defaults=defaults,
            options=options,
            install_bookmarks=lambda **kwargs: None,
        ),
        storage,
    )
    try:
        assert defaults.get("global_bookmarks") == original
        assert options["global_bookmarks"] == storage
        assert options["global_bookmarks"] is not defaults.get("global_bookmarks")
        assert options["global_bookmarks"]["1"] is not manager.bm_dict["1"]
        if existing:
            assert options["global_bookmarks"] is runtime
    finally:
        manager.close()
        manager.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("target", ["format_lower_in", "excellon_format_lower_in"])
def test_propagation_uses_factory_for_missing_keys(monkeypatch, target):
    for cls in (Excellon, Gerber, Geometry):
        monkeypatch.setattr(cls, "defaults", deepcopy(cls.defaults))
    if target == "format_lower_in":
        del Excellon.defaults["excellon_format_lower_in"]
    Excellon.defaults[target] = -1
    defaults = AppDefaults(beta=False)
    del defaults.defaults["excellon_format_lower_in"]
    defaults.propagate_defaults()
    assert Excellon.defaults[target] == defaults.factory_defaults["excellon_format_lower_in"]


def test_propagation_preserves_falsy_override_and_unmapped_baseline(monkeypatch):
    for cls in (Excellon, Gerber, Geometry):
        monkeypatch.setattr(cls, "defaults", deepcopy(cls.defaults))
    Geometry.defaults["multidepth"] = True
    defaults = AppDefaults(beta=False)
    defaults["excellon_format_lower_in"] = 0
    defaults.propagate_defaults()
    assert Excellon.defaults["excellon_format_lower_in"] == 0
    assert "use_buffer_for_union" not in Gerber.defaults
    assert Geometry.defaults["multidepth"] is True


@pytest.mark.parametrize("change", ["value", "obsolete", "unchanged"])
def test_factory_snapshot_matches_current_defaults(tmp_path, change):
    path = tmp_path / "factory_defaults.FlatConfig"
    saved = deepcopy(AppDefaults.factory_defaults)
    if change == "value":
        saved["global_version_check"] = not saved["global_version_check"]
    elif change == "obsolete":
        saved["obsolete_preference"] = True
    path.write_text(json.dumps(saved))
    os.utime(path, (1_700_000_000, 1_700_000_000))
    original_mtime = path.stat().st_mtime_ns
    path.chmod(stat.S_IREAD)
    try:
        AppDefaults.save_factory_defaults(str(path), "2.0")
        assert json.loads(path.read_text()) == AppDefaults.factory_defaults
        if change == "unchanged":
            assert path.stat().st_mtime_ns == original_mtime
    finally:
        path.chmod(stat.S_IWRITE | stat.S_IREAD)
