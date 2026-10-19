"""Digi release preparation for manual full-archive uploads."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..archive import DEFAULT_EXCLUSION_POLICY, build_deterministic_zip
from ..manifest import (
    ArchiveInfo,
    Manifest,
    ManifestError,
    build_manifest,
    manifest_to_json,
    sha256_file,
)


def _resolved_path(path: Path) -> str:
    """Return an absolute, case-normalized path for safe relationship checks."""
    try:
        return os.path.normcase(str(Path(path).expanduser().resolve(strict=False)))
    except (OSError, RuntimeError) as exc:
        raise ManifestError("Could not resolve release path safely: %s" % path) from exc


def _paths_overlap(left: str, right: str) -> bool:
    try:
        common = os.path.commonpath((left, right))
    except ValueError:
        return False
    return common == left or common == right


def validate_release_roots(windows_root: Path, source_root: Path) -> None:
    """Validate the completed frozen build and the source release root."""
    windows_root = Path(windows_root)
    source_root = Path(source_root)
    required_windows = (
        windows_root / "FlatCAM.exe",
        windows_root / "updater" / "FlatCAMUpdater.exe",
    )
    required_source = (
        source_root / "flatcam.py",
        source_root / "updater_app.py",
        source_root / "services" / "updater",
    )
    missing = [str(path.relative_to(windows_root)) for path in required_windows if not path.is_file()]
    missing.extend(
        str(path.relative_to(source_root))
        for path in required_source
        if not path.is_file() and not path.is_dir()
    )
    if missing:
        raise ManifestError("Release input is missing required paths: %s" % ", ".join(missing))


@dataclass(frozen=True)
class ReleaseArtifact:
    channel: str
    archive_path: Path
    manifest_path: Path
    manifest: Manifest


@dataclass(frozen=True)
class ReleasePreparation:
    artifacts: dict[str, ReleaseArtifact]
    upload_paths: tuple[Path, ...]


def prepare_releases(
    roots: Mapping[str, Path],
    output_dir: Path,
    *,
    version,
    build_string: str = "",
    version_date: str = "",
    minimum_required_version: str = "0",
    release_notes: str = "",
    deletions=(),
    policy=DEFAULT_EXCLUSION_POLICY,
    progress_cb=None,
) -> ReleasePreparation:
    """Build the Windows and Linux full ZIP/manifest pairs for manual upload."""
    if set(roots) != {"windows", "linux"}:
        raise ManifestError("Release roots must contain exactly 'windows' and 'linux'.")
    resolved_output = _resolved_path(output_dir)
    for channel in ("windows", "linux"):
        resolved_root = _resolved_path(roots[channel])
        if _paths_overlap(resolved_output, resolved_root):
            raise ManifestError(
                "Release output directory must not overlap the %s release root." % channel
            )
    deletions = tuple(deletions)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_names = {
        "windows": "flatcam-windows.zip",
        "linux": "flatcam-source.zip",
    }
    staging_dir = Path(tempfile.mkdtemp(prefix=".release-", dir=output_dir))
    staged_artifacts = {}
    try:
        for index, channel in enumerate(("windows", "linux"), start=1):
            channel_dir = staging_dir / channel
            archive_path = channel_dir / archive_names[channel]
            manifest_path = channel_dir / "manifest.json"
            build_deterministic_zip(roots[channel], archive_path, policy)
            archive = ArchiveInfo(
                filename=archive_path.name,
                size=archive_path.stat().st_size,
                sha256=sha256_file(archive_path),
            )
            manifest = build_manifest(
                roots[channel],
                version,
                channel=channel,
                archive=archive,
                build_string=build_string,
                version_date=version_date,
                minimum_required_version=minimum_required_version,
                release_notes=release_notes,
                deletions=deletions,
                exclusions=policy,
            )
            manifest_path.write_text(manifest_to_json(manifest), encoding="utf-8", newline="")
            staged_artifacts[channel] = (archive_path, manifest_path, manifest)
            if progress_cb:
                progress_cb(index * 50, "Prepared %s release files." % channel)

        backups = []
        replaced = []
        try:
            artifacts = {}
            upload_paths = []
            backup_dir = staging_dir / ".backup"
            for channel in ("windows", "linux"):
                final_channel_dir = output_dir / channel
                final_channel_dir.mkdir(parents=True, exist_ok=True)
                staged_archive, staged_manifest, manifest = staged_artifacts[channel]
                for staged_path, final_path in (
                    (staged_archive, final_channel_dir / archive_names[channel]),
                    (staged_manifest, final_channel_dir / "manifest.json"),
                ):
                    backup_path = backup_dir / channel / final_path.name
                    if final_path.exists():
                        backup_path.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(final_path, backup_path)
                        backups.append((final_path, backup_path))
                    os.replace(staged_path, final_path)
                    replaced.append(final_path)
                artifact = ReleaseArtifact(
                    channel,
                    final_channel_dir / archive_names[channel],
                    final_channel_dir / "manifest.json",
                    manifest,
                )
                artifacts[channel] = artifact
                upload_paths.extend((artifact.archive_path, artifact.manifest_path))
        except Exception:
            for final_path in reversed(replaced):
                final_path.unlink(missing_ok=True)
            for final_path, backup_path in reversed(backups):
                if backup_path.exists():
                    os.replace(backup_path, final_path)
            raise
        return ReleasePreparation(artifacts=artifacts, upload_paths=tuple(upload_paths))
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
