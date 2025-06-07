import configparser
import os
import shlex
import subprocess
from os import listdir
from os.path import expanduser, isdir, join
from shutil import which
from typing import Dict, List, Union, Generator, Optional, Iterable, Tuple
from functools import lru_cache
import psutil
from langcodes import closest_match
from ovos_bus_client.message import Message
from ovos_utils.bracket_expansion import expand_template
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG
from ovos_utils.parse import match_one, fuzzy_match
from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.fallback import FallbackSkill
from padacioso import IntentContainer

WindowMatch = Tuple[str, psutil.Process, float, str]  # for easy typing


class ApplicationLauncherSkill(FallbackSkill):
    """Skill to handle launching and closing desktop applications via voice commands."""

    def initialize(self) -> None:
        """Initialize the skill by setting up application aliases, commands, and intent matchers."""
        if "aliases" not in self.settings:
            self.settings["aliases"] = {
                # "name from .desktop file": ["speech", "friendly", "names"]
                "kcalc": ["calculator"]
            }
        # these are user defined commands mapped to voice
        if "user_commands" not in self.settings:
            # "application name": "bash command"
            self.settings["user_commands"] = {}

        self.wmctrl = None
        if not self.settings.get("disable_window_manager", False):
            self.wmctrl = which("wmctrl")
            if not self.wmctrl:
                LOG.warning("'wmctrl' not available, will not be able to manage windows directly only processes")
            else:
                LOG.debug(f"'wmctrl' found: {self.wmctrl}")
        else:
            LOG.debug(f"window manager disabled for {self.skill_id}")

        self.applist = self.get_app_aliases()
        # this is a regex based intent parser
        # we handle this in fallback stage to
        # allow more control over matching application names
        self.intent_matchers = {}
        self.register_fallback_intents()
        self.add_event(f"{self.skill_id}.async_prompt", self.handle_async_prompt)

    @lru_cache(10)
    def match_app(self, utterance: str, lang: str) -> Optional[Dict]:
        best_lang, score = closest_match(lang, list(self.intent_matchers.keys()))
        if score >= 10:
            # unsupported lang
            return None
        best_lang = standardize_lang_tag(best_lang)
        res = self.intent_matchers[best_lang].calc_intent(utterance)
        return res

    def register_fallback_intents(self) -> None:
        """Register fallback intents from locale files."""
        intents = ["close", "launch"]
        for lang in os.listdir(f"{self.root_dir}/locale"):
            for intent_name in intents:
                launch = join(self.root_dir, "locale", lang, f"{intent_name}.intent")
                if not os.path.isfile(launch):
                    continue
                l2 = standardize_lang_tag(lang)
                if l2 not in self.intent_matchers:
                    self.intent_matchers[l2] = IntentContainer()
                LOG.debug(f"'{self.skill_id}' - registering fallback '{l2}' intent: '{intent_name}'")
                with open(launch) as f:
                    samples = [option for line in f.read().split("\n")
                               if not line.startswith("#") and line.strip()
                               for option in expand_template(line)]
                    self.intent_matchers[l2].add_intent(intent_name, samples)

    def can_answer(self, message: Message) -> bool:
        utterance = message.data["utterances"][0]
        res = self.match_app(utterance, self.lang)
        return bool(res.get('entities', {}).get("application"))

    @fallback_handler(priority=4)
    def handle_fallback(self, message) -> bool:
        """Handle fallback utterances for launching and closing applications."""
        utterance = message.data.get("utterance", "")
        res = self.match_app(utterance, self.lang)
        app = res.get('entities', {}).get("application")
        if app:
            LOG.debug(f"Application name match: {res}")
            if res["name"] == "launch":
                if self.is_running(app):
                    self.bus.emit(message.forward(f"{self.skill_id}.async_prompt", {"app": app}))
                    return True
                return self.launch_app(app)
            elif res["name"] == "close":
                return self.close_app(app)
        return False

    def handle_async_prompt(self, message: Message):
        app = message.data["app"]
        # in order for fallback to not time out we can't ask user questions in the other handler
        # so we consume the utterance first, and then proceed to ask the user to clarify action
        launch = True
        switch = False

        self.speak_dialog("already_running", {"application": app})

        if self.wmctrl and not self.settings.get("disable_window_manager", False):
            for i in range(5):
                if switch not in ["no", "yes"]:
                    switch = self.ask_yesno("confirm_switch")
                    LOG.debug(f"user confirmation: {switch}")
                    if switch and switch == "yes":
                        win = self.match_window(app)
                        window_id = win[0][0] if win else None
                        self.switch_window(window_id)
                        return True
        if not switch:
            for i in range(5):
                if launch not in ["no", "yes"]:
                    launch = self.ask_yesno("confirm_launch")
                    LOG.debug(f"user confirmation: {launch}")
                    if launch == "no":
                        return True  # no action

        # launch
        self.launch_app(app)

    def launch_app(self, app: str) -> bool:
        """Launch an application by name if a match is found.

        Args:
            app: The name of the application to launch.

        Returns:
            True if the application is launched successfully, False otherwise.
        """
        cmd, score = match_one(app.title(), self.applist)
        if score >= self.settings.get("thresh", 0.85):
            LOG.info(f"Matched application: {app} (command: {cmd})")
            try:
                # Launch the application in a new process without blocking
                subprocess.Popen(shlex.split(cmd), shell=self.settings.get("shell", False))
                self.acknowledge()
                return True
            except Exception as e:
                LOG.error(f"Failed to launch {app}: {e}")
        return False

    def close_app(self, app: str) -> bool:
        if self.wmctrl and not self.settings.get("disable_window_manager", False):
            return self.close_by_window(app) or self.close_by_process(app)
        return self.close_by_process(app)

    def is_running(self, app: str) -> bool:
        """ check if a application is running"""
        if self.wmctrl is not None and self.match_window(app):
            return True
        for p in self.match_process(app):
            return True
        return False

    #########
    # process management
    def match_process(self, app: str) -> Iterable[psutil.Process]:
        cmd, _ = match_one(app.title(), self.applist)
        cmd = cmd.split(" ")[0].split("/")[-1]

        # Retrieve the list of processes and sort by their start time (descending order)
        processes = sorted(psutil.process_iter(['pid', 'name', 'create_time']),
                           key=lambda proc: proc.info['create_time'], reverse=True)
        for proc in processes:
            if proc.status() in ["zombie"]:
                continue
            score = fuzzy_match(cmd, proc.info['name'])
            if score > 0.9:
                yield proc

    def close_by_process(self, app: str) -> bool:
        """Close the application with the given name.

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
                terminated.append(proc.info['pid'])
                if not self.settings.get("terminate_all", False):
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                LOG.error(f"Failed to terminate {proc}")

        if terminated:
            self.acknowledge()
            LOG.debug(f"Terminated PIDs: {terminated}")
            return True
        return False

    #########
    # .desktop file management
    def get_app_aliases(self) -> Dict[str, str]:
        """Fetch application aliases based on desktop files and settings."""
        apps = self.settings.get("user_commands") or {}
        norm = lambda k: k.replace(".desktop", "").replace("-", " ").replace("_", " ").split(".")[-1].title()

        for app in self.get_desktop_apps(
                skip_categories=self.settings.get("skip_categories",
                                                  ['Settings', 'ConsoleOnly', 'Building']),
                skip_keywords=self.settings.get("skip_keywords", []),
                target_categories=self.settings.get("target_categories", []),
                target_keywords=self.settings.get("target_keywords", []),
                blacklist=self.settings.get("blacklist", []),
                extra_langs=self.native_langs,
                require_icon=self.settings.get("require_icon", True),
                require_categories=self.settings.get("require_categories", True)
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
                # speech friendly aliases
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
    def parse_desktop_file(file_path: str, extra_langs: Optional[List[str]] = None) -> Dict[str, Union[str, List[str]]]:
        """Parse a .desktop file to extract relevant application metadata.

        Args:
            file_path: Path to the .desktop file.
            extra_langs: List of additional languages to consider.

        Returns:
            A dictionary containing the parsed application metadata.
        """
        extra_langs = extra_langs or []
        extra_langs = [standardize_lang_tag(l) for l in extra_langs]

        config = configparser.ConfigParser(interpolation=None, delimiters=('=', ':'))
        config.optionxform = str  # To keep case-sensitivity of keys
        config.read(file_path)

        data = {}

        LIST_KEYS = ["Categories", "Keywords", "MimeType"]
        LIST_DELIM = ";"
        if 'Desktop Entry' in config:
            keys = config['Desktop Entry'].keys()
            for key in keys:
                v = config['Desktop Entry'].get(key)
                if key in LIST_KEYS:
                    v = [v for v in v.split(LIST_DELIM) if v]

                if "[" in key:
                    l = standardize_lang_tag(key.split("[")[-1].split("]")[0])
                    k = key.split("[")[0]
                    key = f"{k}[{l}]"

                data[key] = v

        keys_of_interest = [
            'Name',
            'GenericName',
            "Categories",
            "Comment",
            'Keywords',
            "Exec",
            "Type",
            #   'MimeType', # for future usage
            'Icon',  # future usage in a UI
            #   'DBusActivatable'  # for future usage instead of subprocess
        ]
        for l in extra_langs:
            keys_of_interest += [f"Name[{l}]", f"GenericName[{l}]", f"Comment[{l}]"]

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
            require_categories: bool
    ) -> Generator[Dict[str, Union[str, List[str]]], None, None]:
        """Retrieve .desktop application files that match the given criteria.

        Args:
            skip_categories: Categories of applications to skip.
            skip_keywords: Keywords to skip.
            target_categories: Categories of applications to target.
            target_keywords: Keywords to target.
            blacklist: List of applications to ignore.
            extra_langs: Additional languages to consider.
            require_icon: Whether an application must have an icon to be included.
            require_categories: Whether an application must have a category to be included.

        Yields:
            Dictionaries containing metadata of matching desktop applications.
        """
        for p in ["/usr/share/applications/", "/usr/local/share/applications/",
                  expanduser("~/.local/share/applications/")]:
            if not isdir(p):
                continue
            for f in listdir(p):
                if not f.endswith(".desktop") or f in blacklist:
                    continue
                file_path = join(p, f)

                app_info = ApplicationLauncherSkill.parse_desktop_file(file_path, extra_langs=extra_langs)

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

    #########
    # Window management
    def match_window(self, app: str) -> List[WindowMatch]:
        windows = self.get_window_process_mapping()
        candidates = []
        best = 0
        for win in windows:
            score = max(fuzzy_match(win[1].name(), app),
                        fuzzy_match(win[-1], app))  # pick best match, process name or window name
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

        self.acknowledge()
        return True

    def switch_window(self, window_id) -> bool:
        try:
            result = subprocess.run([self.wmctrl, '-iR', window_id])
            if result.returncode == 0:
                self.acknowledge()
                return True
        except Exception as e:
            pass
        LOG.error("'wmctrl' command failed.")
        return False

    def close_window(self, window_id) -> bool:
        try:
            result = subprocess.run([self.wmctrl, '-ic', window_id])
            if result.returncode == 0:
                return True
        except Exception as e:
            pass

        LOG.error("'wmctrl' command failed.")
        return False

    def get_window_process_mapping(self) -> List[WindowMatch]:
        """Get a mapping of window objects to process objects on Linux."""
        windows = []

        try:
            # Get the list of windows with wmctrl
            result = subprocess.run([self.wmctrl, '-lp'], capture_output=True, text=True)
            # windows are returned sorted by order of creation, but we dont have that timestamp
            # TODO - is this true or just coincidence in my tests? i don't think it is ensured
            if result.returncode != 0:
                LOG.error("wmctrl command failed.")
                return []

            # Process each line in the wmctrl output
            for line in result.stdout.splitlines():
                # wmctrl output format: 0x04400007  0  12345  <hostname>  <window_title>
                fields = line.split()
                window_id = fields[0]  # Window ID
                pid = fields[2]  # Process ID (PID)

                window_title = " ".join(fields[4:])  # Window title (everything after hostname)
                try:
                    # Get process object using the PID
                    process = psutil.Process(int(pid))
                    # Map window ID to the process object
                    windows.append((window_id, process, process.create_time(), window_title))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    LOG.error(f"Unable to retrieve process for PID: {pid}")

        except Exception as e:
            LOG.error(f"Error retrieving window-process mapping: {e}")

        return windows[::-1]


if __name__ == "__main__":
    import time

    LOG.set_level("DEBUG")
    from ovos_utils.fakebus import FakeBus
    from ovos_bus_client.message import Message

    s = ApplicationLauncherSkill(skill_id="fake.test", bus=FakeBus())
    s.handle_fallback(Message("", {"utterance": "open firefox", "lang": "en-US"}))
    time.sleep(2)
    # s.handle_fallback(Message("", {"utterance": "kill firefox"}))
    exit()
    # s.handle_fallback(Message("", {"utterance": "kill firefox"}))
    time.sleep(2)
    s.handle_fallback(Message("", {"utterance": "launch firefox", "lang": "en-UK"}))
    s.handle_fallback(Message("", {"utterance": "Abrir Firefox", "lang": "pt-pt"}))
