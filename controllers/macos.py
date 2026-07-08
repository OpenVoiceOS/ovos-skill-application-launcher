"""macOS application controller — uses .app bundles, AppleScript, ``open``.

Originally extracted from the OscillateLabsLLC ``skill-mac-application-launcher``
fork and adapted to the cross-platform :class:`ApplicationController` interface.
"""

import os
import plistlib
import subprocess
from os import listdir
from os.path import exists, expanduser, isdir, join
from shutil import which
from typing import Dict, Generator, Iterable, List, Optional, Union

import psutil
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG
from ovos_utils.parse import fuzzy_match, match_one

from .base import ApplicationController


class MacOSApplicationController(ApplicationController):
    """Application controller backed by macOS .app bundles and AppleScript."""

    def __init__(self, settings: Optional[Dict] = None):
        super().__init__(settings)
        self.osascript = which("osascript")
        if not self.osascript:
            LOG.warning("'osascript' not available, window management may be limited")
        else:
            LOG.debug(f"'osascript' found: {self.osascript}")

        self._app_cache: Optional[Dict[str, str]] = None
        self._cache_build_failed = False

        # Try to build the app cache during initialization, but don't crash
        # the skill if it fails — we can retry on first use.
        try:
            _ = self.app_aliases
            LOG.info(f"Discovered {len(self._app_cache or {})} macOS applications")
        except Exception as e:
            LOG.warning(f"Failed to build macOS application cache during init: {e}")
            self._cache_build_failed = True

    # ---- ApplicationController interface --------------------------------

    @property
    def app_aliases(self) -> Dict[str, str]:
        if self._app_cache is None:
            try:
                self._app_cache = self._build_app_aliases()
                self._cache_build_failed = False
            except Exception as e:
                LOG.error(f"Failed to build macOS application aliases: {e}")
                self._cache_build_failed = True
                return {}
        return self._app_cache

    def refresh_app_cache(self) -> None:
        self._app_cache = None
        self._cache_build_failed = False

    def is_cache_valid(self) -> bool:
        return self._app_cache is not None and not self._cache_build_failed

    def _ensure_cache_or_rebuild(self) -> bool:
        if self._cache_build_failed or self._app_cache is None:
            LOG.info("Attempting to rebuild macOS application cache...")
            self.refresh_app_cache()
            _ = self.app_aliases
            return self.is_cache_valid()
        return True

    def _match_app(self, app: str) -> Optional[tuple]:
        """Resolve *app* against the alias cache.

        Returns ``(cmd, score)`` on success, or ``None`` if no match exists
        even after a cache rebuild attempt. Centralises the
        match-then-rebuild-then-rematch dance that used to be duplicated
        across launch_app, switch_to_app, close_by_applescript and
        match_process.
        """
        try:
            return match_one(app.title(), self.app_aliases)
        except (IndexError, ValueError):
            if self.is_cache_valid():
                return None
            LOG.info(f"No match for '{app}', attempting cache rebuild...")
            if not self._ensure_cache_or_rebuild():
                return None
            try:
                return match_one(app.title(), self.app_aliases)
            except (IndexError, ValueError):
                return None

    @staticmethod
    def _escape_applescript(value: str) -> str:
        """Escape backslashes and double quotes for AppleScript string literals.

        macOS app names rarely contain shell-active characters but the
        controller also accepts user-provided app names via the ``aliases``
        setting, so we belt-and-braces escape before interpolating into
        ``tell application "..."``.
        """
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def launch_app(self, app: str) -> bool:
        result = self._match_app(app)
        if result is None:
            return False
        cmd, score = result

        if score >= self.settings.get("thresh", 0.85):
            LOG.info(f"Matched application: {app} (command: {cmd})")
            return self._spawn(cmd)
        return False

    def _spawn(self, cmd: str) -> bool:
        """Launch a resolved app, preferring AppleScript over ``open``.

        When the skill runs under a launchd LaunchAgent, ``subprocess.Popen``
        of ``open`` inherits the agent's restricted spawn context and macOS
        often refuses with ``RBSRequestErrorDomain Code=5 / Launchd job
        spawn failed (errno 163)``. Routing the request through
        ``osascript`` -> ``tell application "X" to activate`` hands the
        launch off to the user's ``loginwindow`` session, which has the
        right entitlements to spawn GUI apps.

        Falls back to ``open`` / ``open -a`` if ``osascript`` is missing
        or the AppleScript call fails.
        """
        if cmd.endswith(".app"):
            app_name = os.path.basename(cmd).replace(".app", "")
        elif "/" in cmd:
            app_name = os.path.basename(cmd)
        else:
            app_name = cmd

        if self.osascript:
            safe_name = self._escape_applescript(app_name)
            applescript = f'''
            tell application "{safe_name}"
                activate
            end tell
            '''
            try:
                result = subprocess.run(
                    [self.osascript, "-e", applescript],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode == 0:
                    return True
                LOG.warning(
                    "AppleScript activate failed for %s (%s); falling back to `open`",
                    app_name,
                    result.stderr.strip(),
                )
            except Exception as e:
                LOG.warning(
                    "AppleScript activate raised for %s (%s); falling back to `open`",
                    app_name,
                    e,
                )

        try:
            if cmd.endswith(".app") or "/" in cmd:
                subprocess.Popen(["open", cmd])
            else:
                subprocess.Popen(["open", "-a", cmd])
            return True
        except Exception as e:
            LOG.exception(f"Failed to launch {app_name} via `open`: {e}")
        return False

    def close_app(self, app: str) -> bool:
        if self.osascript and not self.settings.get("disable_window_manager", False):
            if self.close_by_applescript(app):
                return True
        return self.close_by_process(app)

    def is_running(self, app: str) -> bool:
        for _ in self.match_process(app):
            return True
        return False

    def can_switch_windows(self) -> bool:
        return self.osascript is not None and not self.settings.get("disable_window_manager", False)

    def switch_to_app(self, app: str) -> bool:
        if not self.osascript:
            return False
        result = self._match_app(app)
        if result is None:
            return False
        cmd, score = result

        if score < self.settings.get("thresh", 0.85):
            return False

        app_name = os.path.basename(cmd).replace(".app", "") if cmd.endswith(".app") else cmd
        safe_name = self._escape_applescript(app_name)
        applescript = f'''
        tell application "{safe_name}"
            activate
        end tell
        '''
        try:
            result = subprocess.run(
                [self.osascript, "-e", applescript], capture_output=True, text=True, check=False
            )
            if result.returncode == 0:
                return True
            LOG.error(f"AppleScript error: {result.stderr}")
        except Exception as e:
            LOG.exception(f"Failed to switch to {app}: {e}")
        return False

    # ---- application discovery ------------------------------------------

    def _build_app_aliases(self) -> Dict[str, str]:
        apps = (self.settings.get("user_commands") or {}).copy()
        discovered = 0

        try:
            for app_info in self.get_macos_apps(
                blocklist=self.settings.get("blocklist", []),
                extra_langs=self.settings.get("extra_langs", []),
            ):
                app_name = app_info["name"]
                app_path = app_info["path"]
                apps[app_name] = app_path
                discovered += 1

                for localized_name in app_info.get("localized_names", []):
                    if localized_name != app_name:
                        apps[localized_name] = app_path

                if app_name in self.settings.get("aliases", {}):
                    for alias in self.settings["aliases"][app_name]:
                        apps[alias] = app_path

            LOG.info(f"Discovered {discovered} macOS applications from system directories")
        except Exception as e:
            LOG.error(f"Error during macOS application discovery: {e}")

        return apps

    @staticmethod
    def parse_app_bundle(
        app_path: str, extra_langs: Optional[List[str]] = None
    ) -> Dict[str, Union[str, List[str]]]:
        """Parse a macOS .app bundle's Info.plist for metadata."""
        extra_langs = extra_langs or []
        extra_langs = [standardize_lang_tag(lang) for lang in extra_langs]

        info_plist_path = join(app_path, "Contents", "Info.plist")
        if not exists(info_plist_path):
            return {}

        try:
            with open(info_plist_path, "rb") as f:
                plist_data = plistlib.load(f)
        except Exception as e:
            LOG.debug(f"Failed to parse {info_plist_path}: {e}")
            app_name = os.path.basename(app_path).replace(".app", "")
            return {
                "name": app_name,
                "path": app_path,
                "bundle_id": "",
                "version": "",
                "localized_names": [],
            }

        app_name = plist_data.get("CFBundleName") or plist_data.get("CFBundleDisplayName") or ""
        if not app_name:
            app_name = os.path.basename(app_path).replace(".app", "")

        data = {
            "name": app_name,
            "path": app_path,
            "bundle_id": plist_data.get("CFBundleIdentifier", ""),
            "version": plist_data.get("CFBundleShortVersionString", ""),
            "localized_names": [],
        }

        localized = []
        if "CFBundleDisplayName" in plist_data:
            localized.append(plist_data["CFBundleDisplayName"])
        if "CFBundleName" in plist_data and plist_data["CFBundleName"] != app_name:
            localized.append(plist_data["CFBundleName"])

        data["localized_names"] = list(set(localized))
        return data

    @staticmethod
    def get_macos_apps(
        blocklist: List[str], extra_langs: Optional[List[str]] = None
    ) -> Generator[Dict[str, Union[str, List[str]]], None, None]:
        """Yield .app bundle metadata from standard macOS app directories."""
        app_dirs = [
            "/Applications",
            "/System/Applications",
            "/Applications/Utilities",
            "/System/Library/CoreServices",
            "/System/Applications/Utilities",
            expanduser("~/Applications"),
        ]

        seen: set = set()

        for app_dir in app_dirs:
            if not isdir(app_dir):
                continue
            try:
                for item in listdir(app_dir):
                    if not item.endswith(".app") or item in blocklist:
                        continue

                    app_path = join(app_dir, item)
                    if not isdir(app_path):
                        continue

                    app_info = MacOSApplicationController.parse_app_bundle(
                        app_path, extra_langs=extra_langs
                    )
                    if not app_info or not app_info.get("name"):
                        continue
                    if app_info["name"] in blocklist:
                        continue

                    key = str(app_info["name"]).lower()
                    if key in seen:
                        continue
                    seen.add(key)

                    yield app_info
            except (OSError, PermissionError) as e:
                LOG.debug(f"Could not access {app_dir}: {e}")
                continue

    # ---- process management ---------------------------------------------

    def match_process(self, app: str) -> Iterable[psutil.Process]:
        result = self._match_app(app)
        if result is None:
            return
        cmd, score = result

        if score < self.settings.get("thresh", 0.85):
            return

        if cmd.endswith(".app"):
            app_name = cmd.split("/")[-1].replace(".app", "")
            bundle_name = os.path.basename(cmd).replace(".app", "")
        else:
            app_name = cmd.split(" ")[0].split("/")[-1]
            bundle_name = app_name

        # Iterate without pre-sorting: we yield every fuzzy hit and the
        # caller decides what to do with them. Sorting by create_time
        # was wasteful — match_process doesn't promise any particular
        # ordering and the close_by_process consumer doesn't depend on
        # one either.
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if proc.status() in ["zombie"]:
                    continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            score1 = fuzzy_match(app_name, proc.info["name"])
            score2 = fuzzy_match(bundle_name, proc.info["name"])
            if max(score1, score2) > 0.8:
                yield proc

    def close_by_applescript(self, app: str) -> bool:
        if not self.osascript:
            return False
        result = self._match_app(app)
        if result is None:
            return False
        cmd, score = result

        if score < self.settings.get("thresh", 0.85):
            return False

        app_name = os.path.basename(cmd).replace(".app", "") if cmd.endswith(".app") else cmd
        safe_name = self._escape_applescript(app_name)
        applescript = f'''
        tell application "{safe_name}"
            quit
        end tell
        '''
        try:
            result = subprocess.run(
                [self.osascript, "-e", applescript], capture_output=True, text=True, check=False
            )
            if result.returncode == 0:
                return True
            LOG.debug(f"AppleScript quit failed for {app_name}: {result.stderr}")
        except Exception as e:
            LOG.exception(f"Failed to close {app} via AppleScript: {e}")
        return False

    def close_by_process(self, app: str) -> bool:
        terminated = []
        for proc in self.match_process(app):
            LOG.debug(f"Matched '{app}' to {proc}")
            try:
                LOG.info(f"Terminating process: {proc.info['name']} (PID: {proc.info['pid']})")
                proc.terminate()
                terminated.append(proc.info["pid"])
                if not self.settings.get("terminate_all", False):
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                LOG.error(f"Failed to terminate {proc}")

        if terminated:
            LOG.debug(f"Terminated PIDs: {terminated}")
            return True
        return False
