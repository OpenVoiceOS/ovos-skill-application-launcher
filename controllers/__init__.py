"""Cross-platform application controllers for the OVOS application launcher skill.

The skill itself is platform-agnostic and delegates all OS-specific work
(application discovery, launching, closing, window management) to a
controller selected at runtime by :func:`get_controller`.

To add support for a new platform, implement
:class:`controllers.base.ApplicationController` and add a branch to
:func:`get_controller`.
"""

import sys
from typing import Dict, Optional

from ovos_utils.log import LOG

from .base import ApplicationController


def get_controller(
    settings: Optional[Dict] = None,
    native_langs: Optional[list] = None,
) -> ApplicationController:
    """Return an :class:`ApplicationController` appropriate for the host OS.

    The platform can be forced via the ``controller_override`` setting,
    which accepts ``"linux"``, ``"macos"``, or ``"windows"``. This is
    primarily useful for testing and for unusual environments (e.g.
    running Linux apps on macOS via XQuartz).

    Args:
        settings: Skill settings dict, forwarded verbatim to the controller.
        native_langs: List of OVOS native languages, used by the Linux
            controller for parsing localized fields in ``.desktop`` files.

    Returns:
        A concrete :class:`ApplicationController` instance.
    """
    settings = settings or {}
    if native_langs is not None:
        settings = {**settings, "extra_langs": native_langs}

    override = settings.get("controller_override")
    platform = (override or sys.platform).lower()

    if platform in ("linux", "linux2"):
        from .linux import LinuxApplicationController
        LOG.debug("application launcher: using LinuxApplicationController")
        return LinuxApplicationController(settings)
    if platform in ("darwin", "macos", "mac"):
        from .macos import MacOSApplicationController
        LOG.debug("application launcher: using MacOSApplicationController")
        return MacOSApplicationController(settings)
    if platform in ("win32", "windows", "win"):
        from .windows import WindowsApplicationController
        LOG.debug("application launcher: using WindowsApplicationController")
        return WindowsApplicationController(settings)

    LOG.warning(
        "application launcher: unknown platform %s, falling back to Linux controller",
        platform,
    )
    from .linux import LinuxApplicationController
    return LinuxApplicationController(settings)


__all__ = ["ApplicationController", "get_controller"]
