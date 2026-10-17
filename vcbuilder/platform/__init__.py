"""Selects the platform implementation (see ``base.Platform``)."""

from __future__ import annotations

import sys

from vcbuilder.errors import UnsupportedPlatformError
from vcbuilder.platform.base import POLL_INTERVAL, Copier, Platform, ToolsStatus

__all__ = ["POLL_INTERVAL", "Copier", "Platform", "ToolsStatus", "current"]


def current() -> Platform:
    """The platform this process runs on. Only macOS is supported for now."""
    if sys.platform == "darwin":
        from vcbuilder.platform.macos import MacOSPlatform

        return MacOSPlatform()
    raise UnsupportedPlatformError(f"sys.platform is {sys.platform!r}")
