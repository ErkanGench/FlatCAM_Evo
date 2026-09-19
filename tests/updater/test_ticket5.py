"""Focused tests for the Ticket 5 local release preparation workflow."""

import hashlib
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from services.updater import release as release_module
from services.updater.manifest import ManifestError, parse_manifest
from services.updater.release import prepare_releases


class Signal:
    def __init__(self):
        self.emissions = []
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def disconnect(self, *args):
        if args:
            self._slots.remove(args[0])
        else:
            self._slots.clear()

    def emit(self, *args):
        self.emissions.append(args)
        for slot in tuple(self._slots):
            slot(*args)


class Progress:
    def __init__(self, *args):
        self.canceled = Signal()
        self.closed = False
        self.visible = False

    def setWindowTitle(self, _title):
        pass

    def setWindowModality(self, _modality):
        pass

    def setAutoClose(self, _value):
        pass

    def setAutoReset(self, _value):
        pass

    def setCancelButton(self, _button):
        pass

    def show(self):
        self.visible = True

    def close(self):
        self.closed = True
        self.visible = False

    def isVisible(self):
        return self.visible


@pytest.fixture
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _make_source(root: Path) -> Path:
    (root / "services" / "updater").mkdir(parents=True)
    (root / "flatcam.py").write_text("print('source')", encoding="utf-8")
    (root / "updater_app.py").write_text("print('updater')", encoding="utf-8")
    (root / "services" / "updater" / "manifest.py").write_text("manifest", encoding="utf-8")
    return root


def _make_windows(root: Path) -> Path:
    (root / "updater").mkdir(parents=True)
    (root / "FlatCAM.exe").write_bytes(b"frozen-build")
    (root / "updater" / "FlatCAMUpdater.exe").write_bytes(b"stable-updater")
    (root / "payload.py").write_text("payload", encoding="utf-8")
    return root


def _workflow_app(source_root: Path):
    from appMain import App

    app = App.__new__(App)
    app.ui = object()
    app.app_home = str(source_root)
    app.version = "3.4.5"
    app.version_date = "2026/5/01"
    app.log = MagicMock()
    app.inform = Signal()
    app.worker_task = Signal()
    app.update_progress = Signal()
    app.release_prepared = Signal()
    app._update_progress_dialog = None
    app._update_dialog = None
    app._release_preparation_in_progress = False
    app._update_in_progress = False
    app._rollback_in_progress = False
    return app


def _patch_dialogs(monkeypatch, windows_root, output_root, notes=("", True), answer=None):
    directories = iter((str(windows_root), str(output_root)))
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: next(directories),
    )
    monkeypatch.setattr(QtWidgets.QInputDialog, "getMultiLineText", lambda *args, **kwargs: notes)
    if answer is not None:
        monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *args, **kwargs: answer)


def test_general_preferences_expose_non_persisted_prepare_control(qapp):
    from appGUI.preferences.general.GeneralAppPrefGroupUI import GeneralAppPrefGroupUI
    from appGUI.preferences.OptionsGroupUI import OptionsGroupUI

    app = SimpleNamespace(decimals=4, options={"global_languages": ["English"]})
    previous_app = OptionsGroupUI.app
    OptionsGroupUI.app = app
    try:
        group = GeneralAppPrefGroupUI(app)
    finally:
        OptionsGroupUI.app = previous_app

    assert group.prepare_update_files_btn.text() == "Prepare Update Files"
    assert "does not upload" in group.prepare_update_files_btn.toolTip()


def test_general_preferences_expose_automatic_update_toggle_without_disabling_statistics(qapp):
    from appGUI.preferences.general.GeneralAppPrefGroupUI import GeneralAppPrefGroupUI
    from appGUI.preferences.OptionsGroupUI import OptionsGroupUI

    app = SimpleNamespace(decimals=4, options={"global_languages": ["English"]})
    previous_app = OptionsGroupUI.app
    OptionsGroupUI.app = app
    try:
        group = GeneralAppPrefGroupUI(app)
    finally:
        OptionsGroupUI.app = previous_app

    assert group.version_check_cb.text() == "Check for updates automatically"
    assert "manual" in group.version_check_cb.toolTip().lower()
    group.version_check_cb.setChecked(False)
    assert group.send_stats_cb.isEnabled()


def test_preferences_lifecycle_wires_prepare_control_without_persisting_it():
    from appGUI.preferences.PreferencesUIManager import PreferencesUIManager

    prepare_button = SimpleNamespace(clicked=Signal())
    app = SimpleNamespace(prepare_update_files=MagicMock())
    ui = SimpleNamespace(
        app=app,
        general_pref_form=SimpleNamespace(
            general_app_group=SimpleNamespace(prepare_update_files_btn=prepare_button)
        ),
        pref_tab_area=SimpleNamespace(tabBarClicked=Signal()),
        pref_save_button=SimpleNamespace(clicked=Signal()),
        pref_apply_button=SimpleNamespace(clicked=Signal()),
        pref_close_button=SimpleNamespace(clicked=Signal()),
        pref_defaults_button=SimpleNamespace(clicked=Signal()),
    )
    manager = PreferencesUIManager.__new__(PreferencesUIManager)
    manager.ui = ui
    manager.on_tab_clicked = MagicMock()
    manager.on_save_button = MagicMock()
    manager.on_pref_close_button = MagicMock()
    manager.on_restore_defaults_preferences = MagicMock()
    manager.defaults_form_fields = {}

    manager.pref_connect()
    prepare_button.clicked.emit()

    app.prepare_update_files.assert_called_once_with()
    assert "prepare_update_files" not in manager.defaults_form_fields

    manager.pref_disconnect()
    prepare_button.clicked.emit()
    app.prepare_update_files.assert_called_once_with()


@pytest.mark.parametrize(
    "cancel_step",
    ("windows", "output", "notes", "confirmation"),
)
def test_prepare_workflow_cancellation_is_a_no_op(monkeypatch, tmp_path, cancel_step):
    from appMain import App

    source = _make_source(tmp_path / "source")
    windows = _make_windows(tmp_path / "windows")
    output = tmp_path / "output"
    output.mkdir()
    app = _workflow_app(source)

    if cancel_step == "windows":
        monkeypatch.setattr(QtWidgets.QFileDialog, "getExistingDirectory", lambda *a, **k: "")
    else:
        directories = iter((str(windows), "" if cancel_step == "output" else str(output)))
        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getExistingDirectory",
            lambda *a, **k: next(directories),
        )
        monkeypatch.setattr(
            QtWidgets.QInputDialog,
            "getMultiLineText",
            lambda *a, **k: ("", False) if cancel_step == "notes" else ("notes", True),
        )
        monkeypatch.setattr(
            QtWidgets.QMessageBox,
            "question",
            lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Cancel,
        )

    App.prepare_update_files(app)

    assert app.worker_task.emissions == []
    assert app._release_preparation_in_progress is False


def test_prepare_workflow_confirms_current_identity_and_source_root(monkeypatch, tmp_path):
    from appMain import App

    source = _make_source(tmp_path / "source")
    windows = _make_windows(tmp_path / "windows")
    output = tmp_path / "output"
    output.mkdir()
    app = _workflow_app(source)
    _patch_dialogs(
        monkeypatch,
        windows,
        output,
        notes=("release notes", True),
        answer=QtWidgets.QMessageBox.StandardButton.Cancel,
    )
    question_text = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda parent, title, text, *args, **kwargs: question_text.append(text)
        or QtWidgets.QMessageBox.StandardButton.Cancel,
    )

    App.prepare_update_files(app)

    assert "Version: 3.4.5" in question_text[0]
    assert "Build: 2026/5/01" in question_text[0]
    assert "Date: 2026/5/01" in question_text[0]
    assert str(source) in question_text[0]
    assert app.worker_task.emissions == []


def test_prepare_workflow_rejects_incomplete_inputs_before_worker_dispatch(monkeypatch, tmp_path):
    from appMain import App

    source = tmp_path / "invalid-source"
    source.mkdir()
    windows = tmp_path / "invalid-windows"
    windows.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    app = _workflow_app(source)
    _patch_dialogs(
        monkeypatch,
        windows,
        output,
        notes=("notes", True),
        answer=QtWidgets.QMessageBox.StandardButton.Yes,
    )

    App.prepare_update_files(app)

    assert app.worker_task.emissions == []
    assert app._release_preparation_in_progress is False
    assert "required" in app.inform.emissions[-1][0].lower()


def test_prepare_workflow_dispatches_once_to_worker_stack(monkeypatch, tmp_path):
    from appMain import App

    source = _make_source(tmp_path / "source")
    windows = _make_windows(tmp_path / "windows")
    output = tmp_path / "output"
    output.mkdir()
    app = _workflow_app(source)
    _patch_dialogs(
        monkeypatch,
        windows,
        output,
        notes=("notes", True),
        answer=QtWidgets.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QtWidgets, "QProgressDialog", Progress)

    App.prepare_update_files(app)
    App.prepare_update_files(app)

    assert len(app.worker_task.emissions) == 1
    task = app.worker_task.emissions[0][0]
    assert task["fcn"] == app._prepare_releases_worker
    assert app._release_preparation_in_progress is True


def test_worker_failure_resets_state_and_logs_full_details(monkeypatch, tmp_path):
    from appMain import App

    source = _make_source(tmp_path / "source")
    app = _workflow_app(source)
    progress = Progress()
    progress.show()
    app._update_progress_dialog = progress
    app._release_preparation_in_progress = True
    monkeypatch.setattr(
        "appMain.prepare_releases",
        MagicMock(side_effect=OSError("archive failed")),
    )

    App._prepare_releases_worker(app, tmp_path / "windows", source, tmp_path / "output", "notes")
    result = app.release_prepared.emissions[0][0]
    App.on_release_prepared(app, result)

    assert result["success"] is False
    assert app._release_preparation_in_progress is False
    assert progress.closed is True
    assert app.log.error.called
    assert "archive failed" in app.inform.emissions[-1][0]


def test_release_core_failure_leaves_no_partial_final_pair(monkeypatch, tmp_path):
    windows = _make_windows(tmp_path / "windows")
    linux = _make_source(tmp_path / "linux")
    output = tmp_path / "output"
    calls = []
    original_zip = release_module.build_deterministic_zip

    def fail_linux(root, destination, policy=release_module.DEFAULT_EXCLUSION_POLICY):
        if Path(root) == linux.resolve():
            raise OSError("linux archive failed")
        calls.append(destination)
        return original_zip(root, destination, policy)

    monkeypatch.setattr(release_module, "build_deterministic_zip", fail_linux)

    with pytest.raises(OSError, match="linux archive failed"):
        prepare_releases(
            {"windows": windows, "linux": linux},
            output,
            version="3.4.5",
            build_string="2026/5/01",
            version_date="2026/5/01",
        )

    assert calls
    assert not (output / "windows" / "flatcam-windows.zip").exists()
    assert not (output / "windows" / "manifest.json").exists()
    assert not (output / "linux" / "flatcam-source.zip").exists()
    assert not (output / "linux" / "manifest.json").exists()
    assert not list(output.rglob("*.part"))


@pytest.mark.parametrize("layout", ("equal_windows", "nested_windows", "nested_linux", "roots_inside_output"))
def test_release_rejects_overlapping_output_before_staging_and_preserves_files(
    monkeypatch, tmp_path, layout
):
    if layout == "roots_inside_output":
        output = tmp_path / "publish"
        output.mkdir()
        windows = _make_windows(output / "windows")
        linux = _make_source(output / "linux")
    else:
        windows = _make_windows(tmp_path / "windows")
        linux = _make_source(tmp_path / "linux")
        if layout == "equal_windows":
            output = windows
        elif layout == "nested_windows":
            output = windows / "publish"
            output.mkdir()
        else:
            output = linux / "publish"
            output.mkdir()

    sentinels = []
    for root in (windows, linux):
        sentinel = root / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        sentinels.append(sentinel)
    output_sentinel = output / "existing.txt"
    output_sentinel.write_text("existing", encoding="utf-8")

    staging_calls = []
    archive_calls = []
    original_mkdtemp = release_module.tempfile.mkdtemp

    def record_staging(*args, **kwargs):
        path = Path(original_mkdtemp(*args, **kwargs))
        staging_calls.append(path)
        return str(path)

    def unexpected_archive(*args, **kwargs):
        archive_calls.append(args)
        raise AssertionError("archive generation must not run")

    monkeypatch.setattr(release_module.tempfile, "mkdtemp", record_staging)
    monkeypatch.setattr(release_module, "build_deterministic_zip", unexpected_archive)

    with pytest.raises(Exception) as error:
        prepare_releases(
            {"windows": windows, "linux": linux},
            output,
            version="3.4.5",
            build_string="2026/5/01",
            version_date="2026/5/01",
        )

    assert isinstance(error.value, ManifestError)
    assert not staging_calls
    assert not archive_calls
    assert all(path.read_text(encoding="utf-8") == "keep" for path in sentinels)
    assert output_sentinel.read_text(encoding="utf-8") == "existing"


@pytest.mark.skipif(os.name != "nt", reason="Windows path comparisons are case-insensitive")
def test_release_rejects_case_insensitive_output_overlap_before_staging(monkeypatch, tmp_path):
    windows = _make_windows(tmp_path / "WindowsBuild")
    linux = _make_source(tmp_path / "LinuxSource")
    output = Path(str(windows).upper())
    sentinel = windows / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    staging_calls = []

    original_mkdtemp = release_module.tempfile.mkdtemp

    def record_staging(*args, **kwargs):
        path = Path(original_mkdtemp(*args, **kwargs))
        staging_calls.append(path)
        return str(path)

    monkeypatch.setattr(release_module.tempfile, "mkdtemp", record_staging)

    with pytest.raises(Exception) as error:
        prepare_releases(
            {"windows": windows, "linux": linux},
            output,
            version="3.4.5",
            build_string="2026/5/01",
            version_date="2026/5/01",
        )

    assert isinstance(error.value, ManifestError)
    assert not staging_calls
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_end_to_end_preparation_has_four_verified_platform_upload_files(monkeypatch, tmp_path):
    windows = _make_windows(tmp_path / "windows")
    linux = _make_source(tmp_path / "linux")
    for root in (windows, linux):
        (root / "tests").mkdir()
        (root / "tests" / "test_not_payload.py").write_text("no", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "README.md").write_text("no", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "HEAD").write_text("no", encoding="utf-8")
        (root / ".venv").mkdir()
        (root / ".venv" / "pyvenv.cfg").write_text("no", encoding="utf-8")
        (root / "user_config").mkdir()
        (root / "user_config" / "settings.json").write_text("no", encoding="utf-8")
        (root / "make_freeze.py").write_text("no", encoding="utf-8")
    output = tmp_path / "upload"
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("network call"))

    preparation = prepare_releases(
        {"windows": windows, "linux": linux},
        output,
        version="3.4.5",
        build_string="2026/5/01",
        version_date="2026/5/01",
        minimum_required_version="0",
        release_notes="Ticket 5",
    )

    expected_paths = (
        output / "windows" / "flatcam-windows.zip",
        output / "windows" / "manifest.json",
        output / "linux" / "flatcam-source.zip",
        output / "linux" / "manifest.json",
    )
    assert preparation.upload_paths == expected_paths
    for channel, archive_name in (("windows", "flatcam-windows.zip"), ("linux", "flatcam-source.zip")):
        manifest_path = output / channel / "manifest.json"
        manifest = parse_manifest(manifest_path.read_bytes())
        archive_path = output / channel / manifest.archive.filename
        assert manifest.channel == channel
        assert manifest.version == "3.4.5"
        assert manifest.build_string == "2026/5/01"
        assert manifest.version_date == "2026/5/01"
        assert manifest.minimum_required_version == "0"
        assert manifest.release_notes == "Ticket 5"
        assert manifest.archive.filename == archive_name
        archive_bytes = archive_path.read_bytes()
        assert manifest.archive.size == len(archive_bytes)
        assert manifest.archive.sha256 == hashlib.sha256(archive_bytes).hexdigest()
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
        assert "make_freeze.py" not in names
        assert not any(name.startswith(("updater/", "tests/", "docs/", ".git/", ".venv/", "user_config/")) for name in names)
        assert names == {entry.path for entry in manifest.files}


def test_release_validation_requires_completed_windows_and_source_roots(tmp_path):
    validator = getattr(release_module, "validate_release_roots", None)
    assert callable(validator)

    with pytest.raises(ManifestError, match="FlatCAM.exe"):
        validator(tmp_path / "missing-windows", _make_source(tmp_path / "source"))

    windows = _make_windows(tmp_path / "windows")
    invalid_source = tmp_path / "invalid-source"
    invalid_source.mkdir()
    with pytest.raises(ManifestError, match="flatcam.py"):
        validator(windows, invalid_source)


def test_successful_result_resets_state_reports_paths_and_opens_output(monkeypatch, tmp_path):
    from appMain import App

    source = _make_source(tmp_path / "source")
    app = _workflow_app(source)
    progress = Progress()
    progress.show()
    app._update_progress_dialog = progress
    app._release_preparation_in_progress = True
    paths = tuple(
        tmp_path / name
        for name in (
            "windows/manifest.json",
            "windows/flatcam-windows.zip",
            "linux/manifest.json",
            "linux/flatcam-source.zip",
        )
    )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"file")
    opened = []
    monkeypatch.setattr(
        "appMain.QtGui.QDesktopServices.openUrl",
        lambda url: opened.append(url) or True,
    )

    App.on_release_prepared(
        app,
        {"success": True, "output_dir": str(tmp_path), "upload_paths": [str(path) for path in paths]},
    )

    assert app._release_preparation_in_progress is False
    assert progress.closed is True
    assert all(str(path) in app.inform.emissions[-1][0] for path in paths)
    assert opened
