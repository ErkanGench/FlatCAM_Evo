"""GitHub Releases update provider."""

from ..common import DownloadCancelled, TransportError
from .checker import GitHubUpdateChecker
from .staging import StagedUpdate, StagingError, stage_update
from .transport import (
    DEFAULT_REPOSITORY,
    API_HOST,
    GITHUB_HOST,
    DELETIONS_ASSET_NAME,
    GitHubRelease,
    GitHubReleaseTransport,
    ReleaseAsset,
    canonical_version,
    is_windows_asset_name,
    normalize_repository,
    windows_asset_name,
)
