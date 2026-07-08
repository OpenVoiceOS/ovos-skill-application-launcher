"""Linux application controller — uses .desktop files and wmctrl."""

import configparser
import os
import shlex
import subprocess
from os import listdir
from os.path import expanduser, isdir, join
from shutil import which
from typing import Dict, Generator, Iterable, List, Optional, Tuple, Union

import psutil
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG
from ovos_utils.parse import fuzzy_match, match_one

from .base import ApplicationController


WindowMatch = Tuple[str, psutil.Process, float, str]

# Cap wmctrl invocations so a wedged X server can't hang the skill.
_WMCTRL_TIMEOUT = 5


class LinuxApplicationController(ApplicationController):
    """Application controller backed by ``.desktop`` files and ``wmctrl``."""

    def __init__(self, settings: Optional[Dict] = None):
        super().__init__(settings)
        self.wmctrl: Optional[str] = None
        if not self.settings.get("disable_window_manager", False):
            self.wmctrl = which("wmctrl")
            if not self.wmctrl:
                LOG.warning(
                    "'wmctrl' not available, will not be able to manage windows directly only processes"
                )
            else:
                LOG.debug(f"'wmctrl' found: {self.wmctrl}")
        else:
            LOG.debug("window manager disabled for LinuxApplicationController")

        self._app_cache: Optional[Dict[str, str]] = None

    # ---- ApplicationController interface --------------------------------

    @property
    def app_aliases(self) -> Dict[str, str]:
        if self._app_cache is None:
            self._app_cache = self._build_app_aliases()
        return self._app_cache

    def refresh_app_cache(self) -> None:
        self._app_cache = None

    def launch_app(self, app: str) -> bool:
        try:
            cmd, score = match_one(app.title(), self.app_aliases)
        except (IndexError, ValueError):
            return False
        if score >= self.settings.get("thresh", 0.85):
            LOG.info(f"Matched application: {app} (command: {cmd})")
            try:
                subprocess.Popen(shlex.split(cmd), shell=self.settings.get("shell", False))
                return True
            except Exception as e:
                LOG.error(f"Failed to launch {app}: {e}")
        return False

    def close_app(self, app: str) -> bool:
        if self.wmctrl and not self.settings.get("disable_window_manager", False):
            return self.close_by_window(app) or self.close_by_process(app)
        return self.close_by_process(app)

    def is_running(self, app: str) -> bool:
        if self.wmctrl is not None and self.match_window(app):
            return True
        for _ in self.match_process(app):
            return True
        return False

    def can_switch_windows(self) -> bool:
        return self.wmctrl is not None and not self.settings.get("disable_window_manager", False)

    def switch_to_app(self, app: str) -> bool:
        wins = self.match_window(app)
        if not wins:
            return False
        return self.switch_window(wins[0][0])

    # ---- application discovery ------------------------------------------

    def _build_app_aliases(self) -> Dict[str, str]:
        """Build a {speech-friendly name: command} map from .desktop files."""
        apps = (self.settings.get("user_commands") or {}).copy()
        norm = lambda k: (
            k.replace(".desktop", "").replace("-", " ").replace("_", " ").split(".")[-1].title()
        )

        for app in self.get_desktop_apps(
            skip_categories=self.settings.get(
                "skip_categories", ["Settings", "ConsoleOnly", "Building"]
            ),
            skip_keywords=self.settings.get("skip_keywords", []),
            target_categories=self.settings.get("target_categories", []),
            target_keywords=self.settings.get("target_keywords", []),
            blacklist=self.settings.get("blacklist", []),
            extra_langs=self.settings.get("extra_langs", []),
            require_icon=self.settings.get("require_icon", True),
            require_categories=self.settings.get("require_categories", True),
        ):
            cmd = app["Exec"].split(" ")[0].split("/")[-1].split(".")[0]
            names = [cmd]
            for k, v in app.items():
                if k.startswith("Name"):
                    names.append(v)
            names += [norm(n) for n in names]

            for name in set(names):
                if 3 <= len(name) <= 20:
                    apps[name] = cmd
                if name in self.settings.get("aliases", {}):
                    for alias in self.settings["aliases"][name]:
                        apps[alias] = cmd
                # KDE likes to replace every C with a K
                if name.startswith("K") and "KDE" in app.get("Categories", []):
                    alias = "C" + name[1:]
                    if alias not in apps:
                        apps[alias] = cmd
            LOG.debug(f"found app {app['Name']} with aliases: {names}")

        return apps

    @staticmethod
    def parse_desktop_file(
        file_path: str, extra_langs: Optional[List[str]] = None
    ) -> Dict[str, Union[str, List[str]]]:
        """Parse a .desktop file to extract relevant application metadata."""
        extra_langs = extra_langs or []
        extra_langs = [standardize_lang_tag(lang) for lang in extra_langs]

        config = configparser.ConfigParser(interpolation=None, delimiters=("=", ":"))
        config.optionxform = str  # keep case-sensitivity of keys
        config.read(file_path)

        data = {}

        LIST_KEYS = ["Categories", "Keywords", "MimeType"]
        LIST_DELIM = ";"
        if "Desktop Entry" in config:
            keys = config["Desktop Entry"].keys()
            for key in keys:
                v = config["Desktop Entry"].get(key)
                if key in LIST_KEYS:
                    v = [v for v in v.split(LIST_DELIM) if v]

                if "[" in key:
                    lang = standardize_lang_tag(key.split("[")[-1].split("]")[0])
                    k = key.split("[")[0]
                    key = f"{k}[{lang}]"

                data[key] = v

        keys_of_interest = [
            "Name",
            "GenericName",
            "Categories",
            "Comment",
            "Keywords",
            "Exec",
            "Type",
            "Icon",
        ]
        for lang in extra_langs:
            keys_of_interest += [f"Name[{lang}]", f"GenericName[{lang}]", f"Comment[{lang}]"]

        return {k: v for k, v in data.items() if k in keys_of_interest}

    @staticmethod
    def get_desktop_apps(
        skip_categories: List[str],
        skip_keywords: List[str],
        target_categories: List[str],
        target_keywords: List[str],
        blacklist: List[str],
        extra_langs: Optional[List[str]],
        require_icon: bool,
        require_categories: bool,
    ) -> Generator[Dict[str, Union[str, List[str]]], None, None]:
        """Yield .desktop application metadata that matches the given criteria."""
        for p in [
            "/usr/share/applications/",
            "/usr/local/share/applications/",
            expanduser("~/.local/share/applications/"),
        ]:
            if not isdir(p):
                continue
            for f in listdir(p):
                if not f.endswith(".desktop") or f in blacklist:
                    continue
                file_path = join(p, f)

                app_info = LinuxApplicationController.parse_desktop_file(file_path, extra_langs=extra_langs)

                if not app_info:
                    continue
                if "Exec" not in app_info:
                    continue
                if app_info["Name"] in blacklist:
                    continue
                if app_info.get("Type") != "Application":
                    continue
                if "Icon" not in app_info and require_icon:
                    continue
                if "Categories" not in app_info and (target_categories or require_categories):
                    continue
                if "Keywords" not in app_info and target_keywords:
                    continue

                if skip_categories and any(c in skip_categories for c in app_info.get("Categories", [])):
                    continue
                if skip_keywords and any(c in skip_keywords for c in app_info.get("Keywords", [])):
                    continue

                yield app_info

    # ---- process management ---------------------------------------------

    def match_process(self, app: str) -> Iterable[psutil.Process]:
        try:
            cmd, _ = match_one(app.title(), self.app_aliases)
        except (IndexError, ValueError):
            return
        cmd = cmd.split(" ")[0].split("/")[-1]

        processes = sorted(
            psutil.process_iter(["pid", "name", "create_time"]),
            key=lambda proc: proc.info["create_time"],
            reverse=True,
        )
        for proc in processes:
            if proc.status() in ["zombie"]:
                continue
            score = fuzzy_match(cmd, proc.info["name"])
            if score > 0.9:
                yield proc

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

    # ---- window management ----------------------------------------------

    def match_window(self, app: str) -> List[WindowMatch]:
        windows = self.get_window_process_mapping()
        candidates: List[WindowMatch] = []
        best = 0
        for win in windows:
            score = max(fuzzy_match(win[1].name(), app), fuzzy_match(win[-1], app))
            if score < self.settings.get("thresh", 0.85):
                continue
            if score > best:
                candidates = []
            if score >= best:
                candidates.append(win)
                best = score
        return candidates

    def close_by_window(self, app: str) -> bool:
        candidates = self.match_window(app)
        if not candidates:
            return False
        for win in candidates:
            LOG.debug(f"Closing window '{win[0]}' : {win[-1]}")
            self.close_window(win[0])
            if not self.settings.get("terminate_all", False):
                break
        return True

    def switch_window(self, window_id) -> bool:
        try:
            result = subprocess.run([self.wmctrl, "-iR", window_id], timeout=_WMCTRL_TIMEOUT)
            if result.returncode == 0:
                return True
        except subprocess.TimeoutExpired:
            LOG.error("'wmctrl -iR' timed out after %ss", _WMCTRL_TIMEOUT)
            return False
        except Exception:
            pass
        LOG.error("'wmctrl' command failed.")
        return False

    def close_window(self, window_id) -> bool:
        try:
            result = subprocess.run([self.wmctrl, "-ic", window_id], timeout=_WMCTRL_TIMEOUT)
            if result.returncode == 0:
                return True
        except subprocess.TimeoutExpired:
            LOG.error("'wmctrl -ic' timed out after %ss", _WMCTRL_TIMEOUT)
            return False
        except Exception:
            pass
        LOG.error("'wmctrl' command failed.")
        return False

    def get_window_process_mapping(self) -> List[WindowMatch]:
        """Return a list of (window_id, process, create_time, title) tuples."""
        windows: List[WindowMatch] = []
        try:
            result = subprocess.run(
                [self.wmctrl, "-lp"],
                capture_output=True,
                text=True,
                timeout=_WMCTRL_TIMEOUT,
            )
            if result.returncode != 0:
                LOG.error("wmctrl command failed.")
                return []

            for line in result.stdout.splitlines():
                fields = line.split()
                window_id = fields[0]
                pid = fields[2]
                window_title = " ".join(fields[4:])
                try:
                    process = psutil.Process(int(pid))
                    windows.append((window_id, process, process.create_time(), window_title))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    LOG.error(f"Unable to retrieve process for PID: {pid}")
        except subprocess.TimeoutExpired:
            LOG.error("'wmctrl -lp' timed out after %ss", _WMCTRL_TIMEOUT)
            return []
        except Exception as e:
            LOG.error(f"Error retrieving window-process mapping: {e}")

        return windows[::-1]
