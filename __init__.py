"""Cross-platform OVOS skill for launching and closing desktop applications.

All platform-specific work (application discovery, launching, closing,
window management) is delegated to a controller selected at runtime by
:func:`controllers.get_controller`. To add a new platform, implement
:class:`controllers.base.ApplicationController` rather than touching this
file.
"""

import os
from functools import lru_cache
from os.path import join
from typing import Dict, Iterable, List, Optional, Union

from langcodes import closest_match
from ovos_bus_client.message import Message
from ovos_utils.bracket_expansion import expand_template
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG
from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.fallback import FallbackSkill
from padacioso import IntentContainer

from ovos_skill_application_launcher.controllers import (
    ApplicationController,
    get_controller,
)
from ovos_skill_application_launcher.controllers.linux import LinuxApplicationController


class ApplicationLauncherSkill(FallbackSkill):
    """Skill to handle launching and closing desktop applications via voice commands."""

    def initialize(self) -> None:
        """Initialize the skill, settings defaults, controller and intent matchers."""
        if "aliases" not in self.settings:
            self.settings["aliases"] = {
                # "name from .desktop file": ["speech", "friendly", "names"]
                "kcalc": ["calculator"],
            }
        if "user_commands" not in self.settings:
            # "application name": "bash command"
            self.settings["user_commands"] = {}

        self.controller: ApplicationController = get_controller(
            settings=self.settings,
            native_langs=self.native_langs,
        )

        self.intent_matchers: Dict[str, IntentContainer] = {}
        self.register_fallback_intents()
        self.add_event(f"{self.skill_id}.async_prompt", self.handle_async_prompt)

    @lru_cache(10)
    def match_app(self, utterance: str, lang: str) -> Optional[Dict]:
        best_lang, score = closest_match(lang, list(self.intent_matchers.keys()))
        if score >= 10:
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
                if self.controller.is_running(app):
                    self.bus.emit(message.forward(f"{self.skill_id}.async_prompt", {"app": app}))
                    return True
                return self.launch_app(app)
            elif res["name"] == "close":
                return self.close_app(app)
        return False

    def handle_async_prompt(self, message: Message):
        app = message.data["app"]
        # In order for fallback to not time out we can't ask user questions
        # in the other handler, so we consume the utterance first and then
        # proceed to ask the user to clarify action.
        launch: Union[bool, str] = True
        switch: Union[bool, str] = False

        self.speak_dialog("already_running", {"application": app})

        if self.controller.can_switch_windows():
            for _ in range(5):
                if switch not in ["no", "yes"]:
                    switch = self.ask_yesno("confirm_switch")
                    LOG.debug(f"user confirmation: {switch}")
                    if switch and switch == "yes":
                        if self.controller.switch_to_app(app):
                            self.acknowledge()
                        return True
        if switch != "yes":
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
        if self.controller.launch_app(app):
            self.acknowledge()
            return True
        return False

    def close_app(self, app: str) -> bool:
        """Close an application by name."""
        if self.controller.close_app(app):
            self.acknowledge()
            return True
        return False

    def is_running(self, app: str) -> bool:
        """Check if an application is running."""
        return self.controller.is_running(app)

    # ---- Backward-compatibility shims --------------------------------------
    #
    # These methods used to live directly on the skill class. Third-party
    # callers may import the skill and call them statically (or via instance),
    # so we keep them here as thin delegates that always go through a Linux
    # controller — preserving the historical Linux-only contract for the
    # public API surface, regardless of which controller the live skill is
    # actually using.

    @property
    def applist(self) -> Dict[str, str]:
        """Backward-compatible alias for ``self.controller.app_aliases``."""
        return self.controller.app_aliases

    @property
    def wmctrl(self):
        """Backward-compatible accessor for the Linux wmctrl path, if any.

        Returns the wmctrl path on Linux installs, ``None`` everywhere else.
        """
        return getattr(self.controller, "wmctrl", None)

    def get_app_aliases(self) -> Dict[str, str]:
        """Fetch application aliases (delegates to the active controller)."""
        return self.controller.app_aliases

    def match_process(self, app: str) -> Iterable:
        return self.controller.match_process(app)

    def close_by_process(self, app: str) -> bool:
        if hasattr(self.controller, "close_by_process"):
            return self.controller.close_by_process(app)
        return False

    def close_by_window(self, app: str) -> bool:
        if hasattr(self.controller, "close_by_window"):
            return self.controller.close_by_window(app)
        return False

    def match_window(self, app: str):
        if hasattr(self.controller, "match_window"):
            return self.controller.match_window(app)
        return []

    def get_window_process_mapping(self):
        if hasattr(self.controller, "get_window_process_mapping"):
            return self.controller.get_window_process_mapping()
        return []

    def switch_window(self, window_id) -> bool:
        if hasattr(self.controller, "switch_window"):
            return self.controller.switch_window(window_id)
        return False

    def close_window(self, window_id) -> bool:
        if hasattr(self.controller, "close_window"):
            return self.controller.close_window(window_id)
        return False

    @staticmethod
    def parse_desktop_file(
        file_path: str, extra_langs: Optional[List[str]] = None
    ) -> Dict[str, Union[str, List[str]]]:
        """Parse a .desktop file. Linux-only; preserved for backwards compat."""
        return LinuxApplicationController.parse_desktop_file(file_path, extra_langs)

    @staticmethod
    def get_desktop_apps(
        skip_categories,
        skip_keywords,
        target_categories,
        target_keywords,
        blacklist,
        extra_langs,
        require_icon,
        require_categories,
    ):
        """Yield .desktop application metadata. Linux-only; preserved for backwards compat."""
        return LinuxApplicationController.get_desktop_apps(
            skip_categories=skip_categories,
            skip_keywords=skip_keywords,
            target_categories=target_categories,
            target_keywords=target_keywords,
            blacklist=blacklist,
            extra_langs=extra_langs,
            require_icon=require_icon,
            require_categories=require_categories,
        )


if __name__ == "__main__":
    import time

    LOG.set_level("DEBUG")
    from ovos_utils.fakebus import FakeBus

    s = ApplicationLauncherSkill(skill_id="fake.test", bus=FakeBus())
    s.handle_fallback(Message("", {"utterance": "open firefox", "lang": "en-US"}))
    time.sleep(2)
