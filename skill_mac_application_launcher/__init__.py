"""
OVOS Application Launcher Skill for macOS

This skill handles launching and closing desktop applications via voice commands on macOS.
It uses native macOS APIs including AppleScript for window management and the 'open' command for launching apps.
"""

import os
from functools import lru_cache
from os.path import join
from typing import Dict, Generator, Iterable, List, Optional, Union

from langcodes import closest_match
from ovos_bus_client.message import Message
from ovos_utils.bracket_expansion import expand_template
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG
from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.fallback import FallbackSkill
from padacioso import IntentContainer

# Import the macOS application controller
from skill_mac_application_launcher.macos_controller import MacOSApplicationController


class MacApplicationLauncherSkill(FallbackSkill):
    """Skill to handle launching and closing desktop applications via voice commands on macOS."""

    def initialize(self) -> None:
        """Initialize the skill by setting up application aliases, commands, and intent matchers."""
        if "aliases" not in self.settings:
            self.settings["aliases"] = {
                # "app name": ["speech", "friendly", "names"]
                "Calculator": ["calculator", "calc"],
                "Safari": ["browser", "web browser"],
                "Finder": ["file manager", "files"],
                "Terminal": ["command line", "shell"],
                "System Preferences": ["preferences", "settings"],
                "Activity Monitor": ["task manager", "processes"],
            }
        # these are user defined commands mapped to voice
        if "user_commands" not in self.settings:
            # "application name": "command or app path"
            self.settings["user_commands"] = {}

        # Initialize the macOS application controller
        controller_settings = dict(self.settings)
        controller_settings["extra_langs"] = self.native_langs
        self.macos_controller = MacOSApplicationController(controller_settings)

        # this is a regex based intent parser
        # we handle this in fallback stage to
        # allow more control over matching application names
        self.intent_matchers = {}
        self.register_fallback_intents()
        self.add_event(f"{self.skill_id}.async_prompt", self.handle_async_prompt)

    def refresh_application_cache(self) -> bool:
        """Refresh the application cache. Returns True if successful."""
        try:
            self.macos_controller.refresh_app_cache()
            return self.macos_controller.is_cache_valid()
        except Exception as e:
            LOG.error(f"Failed to refresh application cache: {e}")
            return False

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
                with open(launch, encoding="utf-8") as f:
                    samples = [
                        option
                        for line in f.read().split("\n")
                        if not line.startswith("#") and line.strip()
                        for option in expand_template(line)
                    ]
                    self.intent_matchers[l2].add_intent(intent_name, samples)

    def can_answer(self, message: Message) -> bool:
        utterance = message.data["utterances"][0]
        res = self.match_app(utterance, self.lang)
        if res is None:
            return False
        return bool(res.get("entities", {}).get("application"))

    @fallback_handler(priority=4)
    def handle_fallback(self, message) -> bool:
        """Handle fallback utterances for launching and closing applications."""
        utterance = message.data.get("utterance", "")
        res = self.match_app(utterance, self.lang)
        if res is None:
            return False
        app = res.get("entities", {}).get("application")
        if app:
            LOG.debug(f"Application name match: {res}")
            if res["name"] == "launch":
                if self.macos_controller.is_running(app):
                    self.bus.emit(message.forward(f"{self.skill_id}.async_prompt", {"app": app}))
                    return True
                return self.launch_app(app)
            if res["name"] == "close":
                return self.close_app(app)
        return False

    def handle_async_prompt(self, message: Message):
        app = message.data["app"]
        # in order for fallback to not time out we can't ask user questions in the other handler
        # so we consume the utterance first, and then proceed to ask the user to clarify action
        launch = True
        switch = False

        self.speak_dialog("already_running", {"application": app})

        # On macOS, we can switch to applications using AppleScript
        if not self.settings.get("disable_window_manager", False):
            for _ in range(5):
                if switch not in ["no", "yes"]:
                    switch = self.ask_yesno("confirm_switch")
                    LOG.debug(f"user confirmation: {switch}")
                    if switch and switch == "yes":
                        if self.macos_controller.switch_to_app(app):
                            self.acknowledge()
                        return True
        if not switch:
            for _ in range(5):
                if launch not in ["no", "yes"]:
                    launch = self.ask_yesno("confirm_launch")
                    LOG.debug(f"user confirmation: {launch}")
                    if launch == "no":
                        return True  # no action

        # launch
        self.launch_app(app)

    def launch_app(self, app: str) -> bool:
        """Launch an application by name if a match is found."""
        if self.macos_controller.launch_app(app):
            self.acknowledge()
            return True
        return False

    def close_app(self, app: str) -> bool:
        """Close an application using AppleScript or process termination."""
        if self.macos_controller.close_app(app):
            self.acknowledge()
            return True
        return False

    # Legacy methods for backward compatibility - delegate to controller
    def is_running(self, app: str) -> bool:
        """Check if an application is running."""
        return self.macos_controller.is_running(app)

    def get_app_aliases(self) -> Dict[str, str]:
        """Fetch application aliases based on macOS app bundles and settings."""
        return self.macos_controller.app_aliases

    @property
    def applist(self) -> Dict[str, str]:
        """Get the application list (for backward compatibility)."""
        return self.macos_controller.app_aliases

    def switch_to_app(self, app: str) -> bool:
        """Switch to an application using AppleScript."""
        return self.macos_controller.switch_to_app(app)

    def close_by_applescript(self, app: str) -> bool:
        """Close an application gracefully using AppleScript."""
        return self.macos_controller.close_by_applescript(app)

    def close_by_process(self, app: str) -> bool:
        """Close the application with the given name by terminating its process."""
        return self.macos_controller.close_by_process(app)

    def match_process(self, app: str) -> Iterable:
        """Match running processes by application name."""
        return self.macos_controller.match_process(app)

    @staticmethod
    def parse_app_bundle(app_path: str, extra_langs: Optional[List[str]] = None) -> Dict[str, Union[str, List[str]]]:
        """Parse a macOS .app bundle to extract relevant application metadata."""
        return MacOSApplicationController.parse_app_bundle(app_path, extra_langs)

    @staticmethod
    def get_macos_apps(
        blocklist: List[str], extra_langs: Optional[List[str]] = None
    ) -> Generator[Dict[str, Union[str, List[str]]], None, None]:
        """Retrieve macOS .app bundles that match the given criteria."""
        return MacOSApplicationController.get_macos_apps(blocklist, extra_langs)


if __name__ == "__main__":
    import time

    LOG.set_level("DEBUG")
    from ovos_utils.fakebus import FakeBus

    controller = MacOSApplicationController(
        {
            "thresh": 0.85,
            "aliases": {
                "Calculator": ["calculator", "calc"],
                "Safari": ["browser", "web browser"],
            },
            "user_commands": {},
            "blocklist": [],
            "extra_langs": ["en-US"],
        }
    )

    print("Testing MacOSApplicationController...")
    print(f"Found {len(controller.app_aliases)} applications")

    # Test launching and closing
    if "Safari" in controller.app_aliases:
        print("Testing Safari launch...")
        controller.launch_app("Safari")
        time.sleep(2)
        print("Testing Safari close...")
        controller.close_app("Safari")

    # Test the full skill
    s = MacApplicationLauncherSkill(skill_id="fake.test", bus=FakeBus())
    print("ApplicationLauncherSkill initialized successfully")
    exit()
