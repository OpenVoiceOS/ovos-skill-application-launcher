"""Abstract base class for platform-specific application controllers."""

import abc
from typing import Dict, Iterable, Optional


class ApplicationController(abc.ABC):
    """Platform-agnostic interface for launching/closing/inspecting apps.

    Subclasses implement the OS-specific bits (process discovery, GUI
    activation, application listing) and the skill class consumes them
    through this interface alone.
    """

    def __init__(self, settings: Optional[Dict] = None):
        self.settings = settings if settings is not None else {}

    # ---- application discovery ------------------------------------------

    @property
    @abc.abstractmethod
    def app_aliases(self) -> Dict[str, str]:
        """Return a {speech-friendly name: launch command} mapping."""

    def refresh_app_cache(self) -> None:
        """Drop any cached application list and rebuild on next access.

        Default implementation is a no-op; subclasses with caches should
        override.
        """

    # ---- launching / closing / state ------------------------------------

    @abc.abstractmethod
    def launch_app(self, app: str) -> bool:
        """Launch *app* by name. Return True on success."""

    @abc.abstractmethod
    def close_app(self, app: str) -> bool:
        """Close *app* by name. Return True on success."""

    @abc.abstractmethod
    def is_running(self, app: str) -> bool:
        """Return True if *app* is currently running."""

    # ---- window / focus management --------------------------------------

    def can_switch_windows(self) -> bool:
        """Return True if this controller can switch focus to a running app.

        Used by the skill to decide whether to offer the "switch instead
        of launching another instance?" prompt. Default False; controllers
        that support window management should override.
        """
        return False

    def switch_to_app(self, app: str) -> bool:
        """Bring *app* to the foreground. Return True on success.

        Default implementation is a no-op stub; controllers that support
        window management should override.
        """
        return False

    # ---- process introspection ------------------------------------------

    def match_process(self, app: str) -> Iterable:
        """Yield processes that look like they belong to *app*.

        Default implementation yields nothing. Override on platforms
        where process introspection is meaningful (Linux, macOS, Windows).
        """
        return iter(())
