"""Update provider package.

Importing this package registers all built-in providers. Custom providers can
be added by registering additional :class:`UpdateProvider` subclasses.
"""

from quiver.providers import (  # noqa: F401  (registration side effect)
    codeberg,
    command,
    github,
    gitlab,
    url,
)
from quiver.providers.base import (
    Asset,
    ProviderError,
    Release,
    UpdateProvider,
    get_provider,
    known_providers,
    normalize_github_repo,
    register,
    select_asset,
)

__all__ = [
    "Asset",
    "ProviderError",
    "Release",
    "UpdateProvider",
    "get_provider",
    "known_providers",
    "normalize_github_repo",
    "register",
    "select_asset",
]
