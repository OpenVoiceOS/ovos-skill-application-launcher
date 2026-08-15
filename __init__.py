import os
from functools import lru_cache
from typing import Dict, List, Optional

import langcodes
from langcodes import closest_match, LanguageTagError
from ovos_bus_client.message import Message
from ovos_spec_tools import standardize_lang, expand as expand_template
from ovos_utils.log import LOG
from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.fallback import FallbackSkill
from padacioso import IntentContainer


def _is_valid_bcp47(tag: str) -> bool:
    """Return True if *tag* is a BCP-47 tag that langcodes can parse.

    Some Linux systems expose POSIX locale names like ``sr@latn`` that are not
    valid BCP-47 (the correct form is ``sr-Latn``).  Passing such tags to
    ``langcodes.closest_match`` raises ``LanguageTagError`` and crashes skill
    loading.  We skip them at registration time instead.
    See https://github.com/OpenVoiceOS/ovos-skill-application-launcher/issues/91
    """
    try:
        langcodes.Language.get(tag)
        return True
    except Exception:
        return False

# PHAL API message types
_PHAL_LAUNCH = "ovos.phal.app_launcher.launch"
_PHAL_CLOSE = "ovos.phal.app_launcher.close"
_PHAL_IS_RUNNING = "ovos.phal.app_launcher.is_running"
# how long to wait for the PHAL plugin to respond (seconds)
_PHAL_TIMEOUT = 5


class ApplicationLauncherSkill(FallbackSkill):
    """Skill to handle launching and closing desktop applications via voice commands.

    Intent handling and speech stay in this skill.  All OS-level actions
    (subprocess launch, process enumeration, window management) are delegated to
    the ovos-PHAL-plugin-app-launcher PHAL plugin via bus messages:

    +-----------------------------------------+------------------+--------------------------------------+
    | Message                                 | Payload          | Response payload                     |
    +=========================================+==================+======================================+
    | ovos.phal.app_launcher.launch           | {name}           | {name, success: true} / {name, error}|
    | ovos.phal.app_launcher.close            | {name}           | {name, success: true} / {name, error}|
    | ovos.phal.app_launcher.is_running       | {name}           | {name, running: bool}                |
    +-----------------------------------------+------------------+--------------------------------------+

    The skill uses ``bus.wait_for_response`` so it works across HiveMind: the
    skill can live on an ovos-core node while the PHAL plugin runs on the target
    device.  If the PHAL plugin does not respond within ``_PHAL_TIMEOUT`` seconds
    the skill speaks an error dialog.
    """

    def initialize(self) -> None:
        self.intent_matchers: Dict[str, IntentContainer] = {}
        # per-language slot-value exclusion sets keyed by standardized lang tag;
        # values here must never fill the open-vocabulary {application} slot
        # (OVOS-INTENT-2 §4.3), keeping generic "open/close" phrasings from
        # hijacking utterances owned by other skills
        self.blacklists: Dict[str, List[str]] = {}
        self.register_fallback_intents()
        self.add_event(f"{self.skill_id}.async_prompt", self.handle_async_prompt)

    # ------------------------------------------------------------------
    # Intent matching helpers
    # ------------------------------------------------------------------

    def register_fallback_intents(self) -> None:
        """Register fallback intents from locale files.

        Invalid locale directory names (e.g. POSIX tags like ``sr@latn`` that
        langcodes cannot parse) are skipped with a warning instead of crashing
        skill loading.  Fixes https://github.com/OpenVoiceOS/ovos-skill-application-launcher/issues/91
        """
        intents = ["close", "launch"]
        for lang_dir in os.listdir(f"{self.root_dir}/locale"):
            l2 = standardize_lang(lang_dir)
            if not _is_valid_bcp47(l2):
                LOG.warning(
                    f"[app-launcher] skipping locale dir '{lang_dir}' (normalised: '{l2}'): "
                    f"not a valid BCP-47 tag, cannot use with langcodes.closest_match "
                    f"(issue #91)"
                )
                continue

            for intent_name in intents:
                intent_path = os.path.join(self.root_dir, "locale", lang_dir, f"{intent_name}.intent")
                if not os.path.isfile(intent_path):
                    continue
                if l2 not in self.intent_matchers:
                    self.intent_matchers[l2] = IntentContainer()
                LOG.debug(f"[app-launcher] registering fallback '{l2}' intent: '{intent_name}'")
                with open(intent_path) as fh:
                    samples = [
                        option
                        for line in fh.read().split("\n")
                        if not line.startswith("#") and line.strip()
                        for option in expand_template(line)
                    ]
                    self.intent_matchers[l2].add_intent(intent_name, samples)

            # slot-value exclusion for the {application} slot (OVOS-INTENT-2 §4.3);
            # base name matches the slot, so it applies to every intent above
            blacklist = os.path.join(self.root_dir, "locale", lang_dir, "application.blacklist")
            if os.path.isfile(blacklist):
                with open(blacklist) as f:
                    self.blacklists[l2] = [
                        option
                        for line in f.read().split("\n")
                        if not line.startswith("#") and line.strip()
                        for option in expand_template(line)
                    ]
                LOG.debug(f"'{self.skill_id}' - loaded '{l2}' {{application}} blacklist "
                          f"({len(self.blacklists[l2])} phrases)")

    def _is_blacklisted(self, app: str, lang: str) -> bool:
        """Check whether a candidate {application} value is excluded by a
        `.blacklist` slot-value exclusion (OVOS-INTENT-2 §4.3).

        A blacklist phrase excludes the value when its words occur in the value
        as a contiguous sequence of whole words (not a raw substring), so `door`
        excludes "the door" but not "doorbell".
        """
        if not self.blacklists:
            return False
        try:
            best_lang, score = closest_match(lang, list(self.blacklists.keys()))
        except (LanguageTagError, ValueError):
            return False
        if score > 10:
            return False
        best_lang = standardize_lang(best_lang)
        value = app.lower().split()
        for phrase in self.blacklists.get(best_lang, ()):
            words = phrase.lower().split()
            if not words:
                continue
            for i in range(len(value) - len(words) + 1):
                if value[i:i + len(words)] == words:
                    return True
        return False

    @lru_cache(10)
    def match_app(self, utterance: str, lang: str) -> Optional[Dict]:
        if not self.intent_matchers:
            return None
        try:
            best_lang, score = closest_match(lang, list(self.intent_matchers.keys()))
        except (LanguageTagError, ValueError):
            return None
        if score > 10:
            return None
        best_lang = standardize_lang(best_lang)
        res = self.intent_matchers[best_lang].calc_intent(utterance)
        app = res.get("entities", {}).get("application")
        if app and self._is_blacklisted(app, best_lang):
            # a blacklisted value is never an application; drop it so the
            # fallback declines and the utterance can reach its rightful skill
            LOG.debug(f"'{app}' is blacklisted for the {{application}} slot, ignoring match")
            res["entities"].pop("application", None)
        return res

    def can_answer(self, message: Message) -> bool:
        utterance = message.data["utterances"][0]
        res = self.match_app(utterance, self.lang) or {}
        return bool(res.get("entities", {}).get("application"))

    # ------------------------------------------------------------------
    # Fallback handler
    # ------------------------------------------------------------------

    @fallback_handler(priority=4)
    def handle_fallback(self, message) -> bool:
        """Handle fallback utterances for launching and closing applications."""
        utterance = message.data.get("utterance", "")
        res = self.match_app(utterance, self.lang) or {}
        app = res.get("entities", {}).get("application")
        if not app:
            return False

        LOG.debug(f"[app-launcher] intent match: {res}")
        if res["name"] == "launch":
            running_resp = self.bus.wait_for_response(
                message.forward(_PHAL_IS_RUNNING, {"name": app}),
                reply_type=f"{_PHAL_IS_RUNNING}.response",
                timeout=_PHAL_TIMEOUT,
            )
            if running_resp is None:
                # the is_running probe already timed out; a launch request
                # would hit the same unresponsive plugin and time out again,
                # so don't make the user wait through a second timeout
                LOG.warning("[app-launcher] PHAL plugin did not respond to is_running request")
                self.speak_dialog("error.no.phal")
                return True
            if running_resp.data.get("running"):
                self.bus.emit(message.forward(f"{self.skill_id}.async_prompt", {"app": app}))
                return True
            return self._launch_app(app, message)
        elif res["name"] == "close":
            return self._close_app(app, message)
        return False

    def handle_async_prompt(self, message: Message) -> None:
        """Tell the user the app is already running and ask whether to open
        a new window of it.

        The PHAL plugin contract has no "switch to window" verb, so this
        never claims to bring an existing window to front; the only real
        outcome of a "yes" here is launching a new instance.
        """
        app = message.data["app"]
        self.speak_dialog("already_running", {"application": app})

        launch = None
        for _ in range(5):
            launch = self.ask_yesno("confirm_launch")
            LOG.debug(f"[app-launcher] confirm_launch: {launch}")
            if launch in ("yes", "no"):
                break

        # only an explicit "yes" launches the app; "no" or an unclear/
        # unanswered prompt (None) must never fall through to launching
        if launch == "yes":
            self._launch_app(app, message)

    # ------------------------------------------------------------------
    # PHAL delegation helpers
    # ------------------------------------------------------------------

    def _launch_app(self, app: str, message: Message) -> bool:
        """Emit a launch request to the PHAL plugin and speak the result."""
        resp = self.bus.wait_for_response(
            message.forward(_PHAL_LAUNCH, {"name": app}),
            reply_type=f"{_PHAL_LAUNCH}.response",
            timeout=_PHAL_TIMEOUT,
        )
        if resp is None:
            LOG.warning("[app-launcher] PHAL plugin did not respond to launch request")
            self.speak_dialog("error.no.phal")
            return False
        if resp.data.get("success"):
            self.acknowledge()
            return True
        error = resp.data.get("error", "unknown error")
        LOG.warning(f"[app-launcher] launch failed: {error}")
        self.speak_dialog("error.launch", {"application": app})
        return False

    def _close_app(self, app: str, message: Message) -> bool:
        """Emit a close request to the PHAL plugin and speak the result."""
        resp = self.bus.wait_for_response(
            message.forward(_PHAL_CLOSE, {"name": app}),
            reply_type=f"{_PHAL_CLOSE}.response",
            timeout=_PHAL_TIMEOUT,
        )
        if resp is None:
            LOG.warning("[app-launcher] PHAL plugin did not respond to close request")
            self.speak_dialog("error.no.phal")
            return False
        if resp.data.get("success"):
            self.acknowledge()
            return True
        error = resp.data.get("error", "unknown error")
        LOG.warning(f"[app-launcher] close failed: {error}")
        self.speak_dialog("error.close", {"application": app})
        return False
