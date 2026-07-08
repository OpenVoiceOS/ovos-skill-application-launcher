"""Windows application controller — placeholder.

This module exists so the cross-platform factory has somewhere to dispatch
to on ``sys.platform == "win32"`` and so a future contributor can fill in
the implementation without rearchitecting the skill.

A real implementation would likely:

* Discover installed apps via the Windows registry
  (``HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths``,
  ``HKCU`` likewise) and via Start Menu shortcut enumeration. The
  PowerShell ``Get-StartApps`` cmdlet returns a usable JSON-able list
  if PowerShell is available.
* Launch via ``subprocess.Popen([resolved_exe_path])`` or
  ``os.startfile(...)``.
* Close via ``psutil`` (already a hard dep of the skill) — match by
  process name, ``proc.terminate()``, fall through to ``proc.kill()``.
* Manage windows via ``pygetwindow`` or the ``pywin32`` package.
  Both are optional deps; the controller should feature-detect and
  degrade to "no window switching" if neither is installed
  (``can_switch_windows`` returning False).

Until then, instantiating this controller raises ``NotImplementedError``
with a pointer at this docstring. The factory will not auto-fall-back
to Linux on Windows because that almost certainly produces worse
behaviour than a clear failure.
"""

from typing import Dict, Optional

from ovos_utils.log import LOG

from .base import ApplicationController


class WindowsApplicationController(ApplicationController):
    """Stub controller for Windows. See module docstring for the design sketch."""

    def __init__(self, settings: Optional[Dict] = None):
        super().__init__(settings)
        LOG.error(
            "WindowsApplicationController is not implemented. "
            "See controllers/windows.py for design notes and a starter sketch. "
            "Contributions welcome."
        )
        raise NotImplementedError(
            "Windows support for ovos-skill-application-launcher is not yet implemented. "
            "See controllers/windows.py for the design sketch and contribute a PR upstream."
        )

    @property
    def app_aliases(self) -> Dict[str, str]:  # pragma: no cover
        raise NotImplementedError

    def launch_app(self, app: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def close_app(self, app: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def is_running(self, app: str) -> bool:  # pragma: no cover
        raise NotImplementedError
