import os
from functools import lru_cache
from typing import Dict, List, Optional

from ovos_bus_client.message import Message
from ovos_spec_tools import closest_lang, expand as expand_template, standardize_lang
from ovos_utils.log import LOG
from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.fallback import FallbackSkill
from padacioso import IntentContainer

# key `match_app` sets on its result when it dropped a blacklisted
# {application} value, so a caller can tell an excluded value apart from
# a transcript that simply did not match
BLACKLISTED = "blacklisted_application"

# bus API of ovos-PHAL-plugin-app-launcher
_PHAL_LAUNCH = "ovos.phal.app_launcher.launch"
_PHAL_CLOSE = "ovos.phal.app_launcher.close"
_PHAL_IS_RUNNING = "ovos.phal.app_launcher.is_running"
# seconds to wait for the PHAL plugin to answer
_PHAL_TIMEOUT = 5


class ApplicationLauncherSkill(FallbackSkill):
    """Launch and close desktop applications by voice.

    The skill matches the request and speaks the result. The
    ovos-PHAL-plugin-app-launcher PHAL plugin does all OS-level work, over the
    bus, so the plugin can run on another device than the skill:

    =================================== ========== ==================================
    Message                             Payload    Response payload
    =================================== ========== ==================================
    ovos.phal.app_launcher.launch       {name}     {name, success: true} / {name, error}
    ovos.phal.app_launcher.close        {name}     {name, success: true} / {name, error}
    ovos.phal.app_launcher.is_running   {name}     {name, running: bool}
    =================================== ========== ==================================

    When the plugin does not answer within ``_PHAL_TIMEOUT`` seconds, the
    skill speaks the error_no_phal dialog.
    """

    def initialize(self) -> None:
        # a regex based intent parser per language; the fallback stage gives
        # more control over matching application names
        self.intent_matchers: Dict[str, IntentContainer] = {}
        # per-language slot-value exclusion sets keyed by standardized lang tag;
        # values here must never fill the open-vocabulary {application} slot
        # (OVOS-INTENT-2 §4.3), keeping generic "open/close" phrasings from
        # hijacking utterances owned by other skills
        self.blacklists: Dict[str, List[str]] = {}
        self.register_fallback_intents()
        self.add_event(f"{self.skill_id}.async_prompt", self.handle_async_prompt)

    @lru_cache(10)
    def match_app(self, utterance: str, lang: str) -> Optional[Dict]:
        best_lang = closest_lang(lang, list(self.intent_matchers.keys()))
        if best_lang is None:
            # unsupported lang
            return None
        best_lang = standardize_lang(best_lang)
        res = self.intent_matchers[best_lang].calc_intent(utterance)
        app = res.get("entities", {}).get("application")
        if app and self._is_blacklisted(app, best_lang):
            # a blacklisted value is never an application; drop it so the
            # fallback declines and the utterance can reach its rightful skill
            LOG.debug(f"'{app}' is blacklisted for the {{application}} slot, ignoring match")
            res["entities"].pop("application", None)
            # a dropped value and no match at all are both an absent
            # entities.application, and the caller must tell them apart: a
            # dropped value is a positive reason to decline the whole round
            res[BLACKLISTED] = app
        return res

    def _is_blacklisted(self, app: str, lang: str) -> bool:
        """Check whether a candidate {application} value is excluded by a
        `.blacklist` slot-value exclusion (OVOS-INTENT-2 §4.3).

        A blacklist phrase excludes the value when its words occur in the value
        as a contiguous sequence of whole words (not a raw substring), so `door`
        excludes "the door" but not "doorbell".
        """
        if not self.blacklists:
            return False
        best_lang = closest_lang(lang, list(self.blacklists.keys()))
        if best_lang is None:
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

    def register_fallback_intents(self) -> None:
        """Register fallback intents from locale files."""
        intents = ["close", "launch"]
        for lang in os.listdir(f"{self.root_dir}/locale"):
            l2 = standardize_lang(lang)
            for intent_name in intents:
                launch = os.path.join(self.root_dir, "locale", lang, f"{intent_name}.intent")
                if not os.path.isfile(launch):
                    continue
                if l2 not in self.intent_matchers:
                    self.intent_matchers[l2] = IntentContainer()
                LOG.debug(f"'{self.skill_id}' - registering fallback '{l2}' intent: '{intent_name}'")
                with open(launch) as f:
                    samples = [option for line in f.read().split("\n")
                               if not line.startswith("#") and line.strip()
                               for option in expand_template(line)]
                    # the utterance normalizer turns a zero width non-joiner into a space
                    samples += [s.replace("\u200c", " ") for s in samples if "\u200c" in s]
                    self.intent_matchers[l2].add_intent(intent_name, samples)

            # slot-value exclusion for the {application} slot (OVOS-INTENT-2 §4.3);
            # base name matches the slot, so it applies to every intent above
            blacklist = os.path.join(self.root_dir, "locale", lang, "application.blacklist")
            if os.path.isfile(blacklist):
                with open(blacklist) as f:
                    self.blacklists[l2] = [option for line in f.read().split("\n")
                                           if not line.startswith("#") and line.strip()
                                           for option in expand_template(line)]
                LOG.debug(f"'{self.skill_id}' - loaded '{l2}' {{application}} blacklist "
                          f"({len(self.blacklists[l2])} phrases)")

    def _match_utterances(self, message: Message) -> Optional[Dict]:
        """The first transcript in the message that names an application, or
        None if no transcript does or any of them names an excluded value.

        The fallback pipeline hands over the whole n-best list in
        ``message.data["utterances"]``. Its ``utterance`` key holds the first
        entry of that list, so both methods read one transcript before, and the
        transcripts are not interchangeable: a Farsi launch phrase is written
        with a zero-width non-joiner inside the verb, and the container matches
        that form alone. Reading one entry drops a match the skill owns, so
        every entry is read.

        The entries are transcriptions of ONE utterance, so the
        `application.blacklist` slot-value exclusion (OVOS-INTENT-2 §4.3) is
        evidence about that utterance and not about the entry that carried it.
        A hit on any entry declines the whole round; otherwise reading every
        entry would make each gap in a blacklist N times easier to hit, and
        "open the blinds" would be answered here because "open the blind"
        transcribed beside it.

        The first clean match wins, so the order of ``utterances`` is trusted
        to rank the transcripts; the container's ``conf`` is not read.
        """
        match = None
        for utterance in message.data.get("utterances") or []:
            res = self.match_app(utterance, self.lang)
            if not res:
                continue
            if res.get(BLACKLISTED):
                LOG.debug(f"'{res[BLACKLISTED]}' is blacklisted in transcript "
                          f"'{utterance}', declining the whole n-best list")
                return None
            if match is None and res.get("entities", {}).get("application"):
                match = res
        return match

    def can_answer(self, message: Message) -> bool:
        return self._match_utterances(message) is not None

    @fallback_handler(priority=4)
    def handle_fallback(self, message) -> bool:
        """Handle fallback utterances for launching and closing applications."""
        res = self._match_utterances(message)
        if not res:
            return False
        app = res["entities"]["application"]
        LOG.debug(f"Application name match: {res}")
        if res["name"] == "close":
            return self._close_app(app, message)
        if res["name"] != "launch":
            return False
        running = self._ask_phal(_PHAL_IS_RUNNING, app, message)
        if running is None:
            # a launch request would wait on the same silent plugin again,
            # so speak the error after the first timeout
            LOG.warning(f"PHAL plugin did not answer {_PHAL_IS_RUNNING}")
            self.speak_dialog("error_no_phal")
            return True
        if running.data.get("running"):
            self.bus.emit(message.forward(f"{self.skill_id}.async_prompt", {"app": app}))
            return True
        return self._launch_app(app, message)

    def handle_async_prompt(self, message: Message) -> None:
        """Say that the application is already running and ask whether to
        open a new window of it.

        The fallback must not time out, so the handler consumes the utterance
        first and the question is asked here. The PHAL plugin has no verb to
        switch to a window, so the only outcome of a "yes" is a new instance.
        """
        app = message.data["app"]
        self.speak_dialog("already_running", {"application": app})

        launch = None
        for _ in range(5):
            launch = self.ask_yesno("confirm_launch")
            LOG.debug(f"user confirmation: {launch}")
            if launch in ("yes", "no"):
                break

        # only an explicit "yes" launches the app; "no" or an unclear/
        # unanswered prompt (None) must never fall through to launching
        if launch == "yes":
            self._launch_app(app, message)

    def _ask_phal(self, msg_type: str, app: str, message: Message) -> Optional[Message]:
        return self.bus.wait_for_response(message.forward(msg_type, {"name": app}),
                                          reply_type=f"{msg_type}.response",
                                          timeout=_PHAL_TIMEOUT)

    def _launch_app(self, app: str, message: Message) -> bool:
        """Ask the PHAL plugin to launch *app* and speak the result."""
        return self._delegate(_PHAL_LAUNCH, "error_launch", app, message)

    def _close_app(self, app: str, message: Message) -> bool:
        """Ask the PHAL plugin to close *app* and speak the result."""
        return self._delegate(_PHAL_CLOSE, "error_close", app, message)

    def _delegate(self, msg_type: str, error_dialog: str, app: str, message: Message) -> bool:
        resp = self._ask_phal(msg_type, app, message)
        if resp is None:
            LOG.warning(f"PHAL plugin did not answer {msg_type}")
            self.speak_dialog("error_no_phal")
            return False
        if resp.data.get("success"):
            self.acknowledge()
            return True
        LOG.warning(f"{msg_type} failed for '{app}': {resp.data.get('error', 'unknown error')}")
        self.speak_dialog(error_dialog, {"application": app})
        return False
