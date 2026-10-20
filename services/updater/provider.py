"""Select the configured update provider: GitHub Releases (default) or the legacy Digi share."""

from __future__ import annotations

PROVIDER_GITHUB = "github"
PROVIDER_DIGI = "digi"


def _setting(app, key):
    options = getattr(app, "options", None) or {}
    defaults = getattr(app, "defaults", None) or {}
    value = options.get(key)
    if value is None:
        value = defaults.get(key)
    return value


def update_provider(app) -> str:
    """Return "github" or "digi"; anything unknown is GitHub."""
    value = str(_setting(app, "global_update_provider") or "").strip().lower()
    return PROVIDER_DIGI if value == PROVIDER_DIGI else PROVIDER_GITHUB


def provider_url(app, provider=None) -> str:
    """The configured address of the selected provider."""
    provider = provider or update_provider(app)
    key = "global_legacy_update_url" if provider == PROVIDER_DIGI else "global_update_url"
    value = _setting(app, key)
    if value is None:
        from defaults import AppDefaults

        value = AppDefaults.factory_defaults.get(key)
    return value


def create_update_checker(app, provider=None, url=None):
    """Build the checker of the selected provider, or of an explicit provider and address."""
    provider = provider if provider in (PROVIDER_GITHUB, PROVIDER_DIGI) else update_provider(app)
    url = url or provider_url(app, provider)
    if provider == PROVIDER_DIGI:
        from .digi.checker import UpdateChecker

        checker = UpdateChecker(app, share_url=url)
    else:
        from .github.checker import GitHubUpdateChecker

        checker = GitHubUpdateChecker(app, repository_url=url)
    checker.provider = provider
    return checker


def run_provider_check(app, checker, *, forced=False):
    """Run the check with the keyword the checker's provider expects."""
    provider = getattr(checker, "provider", None) or update_provider(app)
    url = provider_url(app, provider)
    if provider == PROVIDER_DIGI:
        return checker.run_check(forced=forced, share_url=url)
    return checker.run_check(forced=forced, repository_url=url)


def checker_for(app):
    """Return app.update_checker, rebuilding it when the provider changed."""
    checker = getattr(app, "update_checker", None)
    if checker is None or getattr(checker, "provider", update_provider(app)) != update_provider(app):
        checker = create_update_checker(app)
        app.update_checker = checker
    return checker
