"""
MacOS Application Controller

This module provides the MacOSApplicationController class for managing macOS applications
independently of voice assistant functionality. It handles application discovery, launching,
closing, and process management using native macOS APIs.
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


class MacOSApplicationController:
    """Controller class for managing macOS applications - launching, closing, and discovery."""

    def __init__(self, settings: Optional[Dict] = None):
        """Initialize the macOS application controller.

        Args:
            settings: Dictionary containing configuration settings
        """
        self.settings = settings if settings is not None else {}
        self.osascript = which("osascript")
        if not self.osascript:
            LOG.warning("'osascript' not available, window management may be limited")
        else:
            LOG.debug(f"'osascript' found: {self.osascript}")

        self._app_cache = None
        self._cache_build_failed = False

        # Try to build the app cache during initialization
        try:
            _ = self.app_aliases  # This will trigger cache building
            LOG.info(f"Successfully discovered {len(self._app_cache)} applications and aliases")
        except Exception as e:
            LOG.warning(f"Failed to build application cache during initialization: {e}")
            self._cache_build_failed = True

    @property
    def app_aliases(self) -> Dict[str, str]:
        """Get application aliases, using cache if available."""
        if self._app_cache is None:
            try:
                self._app_cache = self._build_app_aliases()
                self._cache_build_failed = False
            except Exception as e:
                LOG.error(f"Failed to build application aliases: {e}")
                self._cache_build_failed = True
                # Return empty dict to prevent crashes, but allow retry later
                return {}
        return self._app_cache

    def refresh_app_cache(self) -> None:
        """Force refresh of the application cache."""
        self._app_cache = None
        self._cache_build_failed = False

    def is_cache_valid(self) -> bool:
        """Check if the application cache is valid and available."""
        return self._app_cache is not None and not self._cache_build_failed

    def _ensure_cache_or_rebuild(self) -> bool:
        """Ensure cache is available, rebuild if necessary. Returns True if cache is available."""
        if self._cache_build_failed or self._app_cache is None:
            LOG.info("Attempting to rebuild application cache...")
            self.refresh_app_cache()
            # Trigger cache rebuild
            _ = self.app_aliases
            return self.is_cache_valid()
        return True

    def _build_app_aliases(self) -> Dict[str, str]:
        """Build application aliases based on macOS app bundles and settings."""
        apps = self.settings.get("user_commands", {}).copy()
        discovered_count = 0

        # Add system applications and user applications
        try:
            for app_info in self.get_macos_apps(
                blocklist=self.settings.get("blocklist", []), extra_langs=self.settings.get("extra_langs", [])
            ):
                app_name = app_info["name"]
                app_path = app_info["path"]

                # Add the main app name
                apps[app_name] = app_path
                discovered_count += 1

                # Add localized names if available
                for localized_name in app_info.get("localized_names", []):
                    if localized_name != app_name:
                        apps[localized_name] = app_path

                # Add speech-friendly aliases from settings
                if app_name in self.settings.get("aliases", {}):
                    for alias in self.settings["aliases"][app_name]:
                        apps[alias] = app_path

            LOG.info(f"Discovered {discovered_count} applications from system directories")

        except Exception as e:
            LOG.error(f"Error during application discovery: {e}")
            # Continue with whatever apps we have from user_commands

        return apps

    def launch_app(self, app: str) -> bool:
        """Launch an application by name if a match is found.

        Args:
            app: The name of the application to launch.

        Returns:
            True if the application is launched successfully, False otherwise.
        """
        try:
            cmd, score = match_one(app.title(), self.app_aliases)
        except (IndexError, ValueError):
            # No matches found - try rebuilding cache if it failed before
            if not self.is_cache_valid():
                LOG.info(f"No match found for '{app}', attempting cache rebuild...")
                if self._ensure_cache_or_rebuild():
                    try:
                        cmd, score = match_one(app.title(), self.app_aliases)
                    except (IndexError, ValueError):
                        return False
                else:
                    return False
            else:
                return False

        if score >= self.settings.get("thresh", 0.85):
            LOG.info(f"Matched application: {app} (command: {cmd})")
            try:
                # On macOS, use 'open' command to launch applications
                if cmd.endswith(".app") or "/" in cmd:
                    # Full path to app bundle
                    subprocess.Popen(["open", cmd])
                else:
                    # Application name - let macOS find it
                    subprocess.Popen(["open", "-a", cmd])
                return True
            except Exception as e:
                LOG.exception(f"Failed to launch {app}: {e}")
        return False

    def close_app(self, app: str) -> bool:
        """Close an application using AppleScript or process termination."""
        # Try AppleScript first for graceful closure
        if self.osascript and not self.settings.get("disable_window_manager", False):
            if self.close_by_applescript(app):
                return True
        # Fall back to process termination
        return self.close_by_process(app)

    def is_running(self, app: str) -> bool:
        """Check if an application is running."""
        for _ in self.match_process(app):
            return True
        return False

    def switch_to_app(self, app: str) -> bool:
        """Switch to an application using AppleScript."""
        if not self.osascript:
            return False

        try:
            cmd, score = match_one(app.title(), self.app_aliases)
        except (IndexError, ValueError):
            # No matches found - try rebuilding cache if it failed before
            if not self.is_cache_valid():
                LOG.info(f"No match found for '{app}', attempting cache rebuild...")
                if self._ensure_cache_or_rebuild():
                    try:
                        cmd, score = match_one(app.title(), self.app_aliases)
                    except (IndexError, ValueError):
                        return False
                else:
                    return False
            else:
                return False

        if score < self.settings.get("thresh", 0.85):
            return False

        # Extract app name for AppleScript
        if cmd.endswith(".app"):
            app_name = os.path.basename(cmd).replace(".app", "")
        else:
            app_name = cmd

        applescript = f'''
        tell application "{app_name}"
            activate
        end tell
        '''

        try:
            result = subprocess.run([self.osascript, "-e", applescript], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                return True
            else:
                LOG.error(f"AppleScript error: {result.stderr}")
        except Exception as e:
            LOG.exception(f"Failed to switch to {app}: {e}")

        return False

    def close_by_applescript(self, app: str) -> bool:
        """Close an application gracefully using AppleScript."""
        if not self.osascript:
            return False

        try:
            cmd, score = match_one(app.title(), self.app_aliases)
        except (IndexError, ValueError):
            # No matches found - try rebuilding cache if it failed before
            if not self.is_cache_valid():
                LOG.info(f"No match found for '{app}', attempting cache rebuild...")
                if self._ensure_cache_or_rebuild():
                    try:
                        cmd, score = match_one(app.title(), self.app_aliases)
                    except (IndexError, ValueError):
                        return False
                else:
                    return False
            else:
                return False

        if score < self.settings.get("thresh", 0.85):
            return False

        # Extract app name for AppleScript
        if cmd.endswith(".app"):
            app_name = os.path.basename(cmd).replace(".app", "")
        else:
            app_name = cmd

        applescript = f'''
        tell application "{app_name}"
            quit
        end tell
        '''

        try:
            result = subprocess.run([self.osascript, "-e", applescript], capture_output=True, text=True, check=False)
            if result.returncode == 0:
                return True
            LOG.debug(f"AppleScript quit failed for {app_name}: {result.stderr}")
        except Exception as e:
            LOG.exception(f"Failed to close {app} via AppleScript: {e}")

        return False

    def match_process(self, app: str) -> Iterable[psutil.Process]:
        """Match running processes by application name."""
        try:
            cmd, score = match_one(app.title(), self.app_aliases)
        except (IndexError, ValueError):
            # No matches found - try rebuilding cache if it failed before
            if not self.is_cache_valid():
                LOG.info(f"No match found for '{app}', attempting cache rebuild...")
                if self._ensure_cache_or_rebuild():
                    try:
                        cmd, score = match_one(app.title(), self.app_aliases)
                    except (IndexError, ValueError):
                        return
                else:
                    return
            else:
                return

        if score < self.settings.get("thresh", 0.85):
            return

        # Extract the actual executable name
        if cmd.endswith(".app"):
            # For .app bundles, the executable is usually inside Contents/MacOS/
            app_name = cmd.split("/")[-1].replace(".app", "")
            # Also try the bundle name itself
            bundle_name = os.path.basename(cmd).replace(".app", "")
        else:
            app_name = cmd.split(" ")[0].split("/")[-1]
            bundle_name = app_name

        # Retrieve the list of processes and sort by their start time (descending order)
        processes = sorted(
            psutil.process_iter(["pid", "name", "create_time"]),
            key=lambda proc: proc.info["create_time"],
            reverse=True,
        )
        for proc in processes:
            if proc.status() in ["zombie"]:
                continue
            # Try matching against both the app name and bundle name
            score1 = fuzzy_match(app_name, proc.info["name"])
            score2 = fuzzy_match(bundle_name, proc.info["name"])
            if max(score1, score2) > 0.8:  # Slightly lower threshold for process matching
                yield proc

    def close_by_process(self, app: str) -> bool:
        """Close the application with the given name by terminating its process.

        Args:
            app: The name of the application to close.

        Returns:
            True if the application was terminated successfully, False otherwise.
        """
        terminated = []
        for proc in self.match_process(app):
            LOG.debug(f"Matched '{app}' to {proc}")
            try:
                LOG.info(f"Terminating process: {proc.info['name']} (PID: {proc.info['pid']})")
                proc.terminate()  # or process.kill() to forcefully kill
                terminated.append(proc.info["pid"])
                if not self.settings.get("terminate_all", False):
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                LOG.error(f"Failed to terminate {proc}")

        if terminated:
            LOG.debug(f"Terminated PIDs: {terminated}")
            return True
        return False

    @staticmethod
    def parse_app_bundle(app_path: str, extra_langs: Optional[List[str]] = None) -> Dict[str, Union[str, List[str]]]:
        """Parse a macOS .app bundle to extract relevant application metadata.

        Args:
            app_path: Path to the .app bundle.
            extra_langs: List of additional languages to consider.

        Returns:
            A dictionary containing the parsed application metadata.
        """
        extra_langs = extra_langs or []
        extra_langs = [standardize_lang_tag(lang) for lang in extra_langs]

        info_plist_path = join(app_path, "Contents", "Info.plist")
        if not exists(info_plist_path):
            return {}

        try:
            with open(info_plist_path, "rb") as f:
                plist_data = plistlib.load(f)
        except (plistlib.InvalidFileException, Exception) as e:
            # Handle malformed plist files gracefully
            LOG.debug(f"Failed to parse {info_plist_path}: {e}")
            # Fall back to just using the app name from the directory
            app_name = os.path.basename(app_path).replace(".app", "")
            return {"name": app_name, "path": app_path, "bundle_id": "", "version": "", "localized_names": []}

        app_name = plist_data.get("CFBundleName") or plist_data.get("CFBundleDisplayName") or ""
        if not app_name:
            # Fall back to the .app directory name
            app_name = os.path.basename(app_path).replace(".app", "")

        data = {
            "name": app_name,
            "path": app_path,
            "bundle_id": plist_data.get("CFBundleIdentifier", ""),
            "version": plist_data.get("CFBundleShortVersionString", ""),
            "localized_names": [],
        }

        # Look for localized names
        localized_names = []
        if "CFBundleDisplayName" in plist_data:
            localized_names.append(plist_data["CFBundleDisplayName"])
        if "CFBundleName" in plist_data and plist_data["CFBundleName"] != app_name:
            localized_names.append(plist_data["CFBundleName"])

        data["localized_names"] = list(set(localized_names))

        return data

    @staticmethod
    def get_macos_apps(
        blocklist: List[str], extra_langs: Optional[List[str]] = None
    ) -> Generator[Dict[str, Union[str, List[str]]], None, None]:
        """Retrieve macOS .app bundles that match the given criteria.

        Args:
            blocklist: List of applications to ignore.
            extra_langs: Additional languages to consider.

        Yields:
            Dictionaries containing metadata of matching macOS applications.
        """
        # Standard macOS application directories - ordered by priority
        app_dirs = [
            "/Applications",
            "/System/Applications",
            "/Applications/Utilities",
            "/System/Library/CoreServices",
            "/System/Applications/Utilities",
            expanduser("~/Applications"),
        ]

        seen_apps = set()  # Track apps we've already found to avoid duplicates

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

                    app_info = MacOSApplicationController.parse_app_bundle(app_path, extra_langs=extra_langs)

                    if not app_info or not app_info.get("name"):
                        continue

                    if app_info["name"] in blocklist:
                        continue

                    # Avoid duplicates (prefer system apps over user apps)
                    app_key = str(app_info["name"]).lower()
                    if app_key in seen_apps:
                        continue
                    seen_apps.add(app_key)

                    yield app_info
            except (OSError, PermissionError) as e:
                LOG.debug(f"Could not access {app_dir}: {e}")
                continue
