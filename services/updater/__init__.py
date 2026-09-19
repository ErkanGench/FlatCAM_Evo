"""Small, UI-independent updater and release-preparation primitives."""

from .manifest import (
    ArchiveInfo,
    DeletionEntry,
    FileEntry,
    Manifest,
    ManifestError,
    compare_versions,
    is_newer,
    manifest_to_json,
    parse_manifest,
    parse_version,
    select_channel,
    sha256_file,
    validate_relative_path,
)
from .release import (
    DEFAULT_EXCLUSION_POLICY,
    ExclusionPolicy,
    ReleaseArtifact,
    ReleasePreparation,
    prepare_releases,
)
from .transport import (
    DigiPublicShareTransport,
    DownloadCancelled,
    RemoteFile,
    ShareMetadata,
    TransportError,
)

__all__ = [
    "ArchiveInfo",
    "DEFAULT_EXCLUSION_POLICY",
    "DeletionEntry",
    "DigiPublicShareTransport",
    "DownloadCancelled",
    "ExclusionPolicy",
    "FileEntry",
    "Manifest",
    "ManifestError",
    "ReleaseArtifact",
    "ReleasePreparation",
    "RemoteFile",
    "ShareMetadata",
    "TransportError",
    "compare_versions",
    "is_newer",
    "manifest_to_json",
    "parse_manifest",
    "parse_version",
    "prepare_releases",
    "select_channel",
    "sha256_file",
    "validate_relative_path",
]
