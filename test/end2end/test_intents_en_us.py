"""E2E intent-routing tests for ovos-skill-application-launcher.

Verifies that the skill calls bus.wait_for_response with the correct
ovos.phal.app_launcher.* message types in response to voice utterances,
and that it speaks an error when the PHAL plugin does not respond.

Run: pytest test/end2end/ -v
"""
import os
import unittest
from unittest.mock import MagicMock, patch, call

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

_PHAL_LAUNCH = "ovos.phal.app_launcher.launch"
_PHAL_CLOSE = "ovos.phal.app_launcher.close"
_PHAL_IS_RUNNING = "ovos.phal.app_launcher.is_running"

SKILL_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _make_skill():
    """Return an ApplicationLauncherSkill-like mock with real en-US matchers."""
    from ovos_skill_application_launcher import ApplicationLauncherSkill
    from padacioso import IntentContainer
    from ovos_spec_tools import expand as expand_template

    bus = FakeBus()
    skill = MagicMock(spec=ApplicationLauncherSkill)
    skill._launch_app = ApplicationLauncherSkill._launch_app.__get__(skill)
    skill._close_app = ApplicationLauncherSkill._close_app.__get__(skill)
    skill.handle_fallback = ApplicationLauncherSkill.handle_fallback.__get__(skill)
    skill.match_app = ApplicationLauncherSkill.match_app.__wrapped__.__get__(skill)
    skill._is_blacklisted = ApplicationLauncherSkill._is_blacklisted.__get__(skill)
    skill.bus = bus
    skill.lang = "en-US"
    skill.skill_id = "ovos-skill-application-launcher.openvoiceos"
    skill.settings = {}
    skill.acknowledge = MagicMock()
    skill.speak_dialog = MagicMock()

    ic = IntentContainer()
    for intent_name in ("launch", "close"):
        intent_path = os.path.join(SKILL_ROOT, "locale", "en-US", f"{intent_name}.intent")
        if os.path.isfile(intent_path):
            with open(intent_path) as fh:
                samples = [
                    opt
                    for line in fh.read().split("\n")
                    if not line.startswith("#") and line.strip()
                    for opt in expand_template(line)
                ]
            ic.add_intent(intent_name, samples)
    skill.intent_matchers = {"en-US": ic}
    skill.blacklists = {}
    return skill, bus


def _run_utterance(utterance, expect_action):
    """Run a single utterance and return the list of msg_types passed to wait_for_response."""
    skill, bus = _make_skill()
    called_with = []

    def _wait(msg, reply_type=None, timeout=5):
        called_with.append(msg.msg_type)
        if msg.msg_type == _PHAL_IS_RUNNING:
            return Message(f"{_PHAL_IS_RUNNING}.response", {"running": False})
        if msg.msg_type == _PHAL_LAUNCH:
            return Message(f"{_PHAL_LAUNCH}.response", {"name": utterance, "success": True})
        if msg.msg_type == _PHAL_CLOSE:
            return Message(f"{_PHAL_CLOSE}.response", {"name": utterance, "success": True})
        return None

    with patch.object(bus, "wait_for_response", side_effect=_wait):
        msg = Message("test", {"utterance": utterance, "utterances": [utterance], "lang": "en-US"})
        skill.handle_fallback(msg)

    return called_with


class TestLaunchIntentEmitsPHAL(unittest.TestCase):
    """Launch utterances must call wait_for_response with is_running then launch."""

    def test_launch_something(self):
        types = _run_utterance("launch something", _PHAL_LAUNCH)
        self.assertIn(_PHAL_IS_RUNNING, types)
        self.assertIn(_PHAL_LAUNCH, types)

    def test_open_something(self):
        self.assertIn(_PHAL_LAUNCH, _run_utterance("open something", _PHAL_LAUNCH))

    def test_run_something(self):
        self.assertIn(_PHAL_LAUNCH, _run_utterance("run something", _PHAL_LAUNCH))


class TestCloseIntentEmitsPHAL(unittest.TestCase):
    """Close utterances must call wait_for_response with close."""

    def test_close_something(self):
        self.assertIn(_PHAL_CLOSE, _run_utterance("close something", _PHAL_CLOSE))

    def test_kill_something(self):
        self.assertIn(_PHAL_CLOSE, _run_utterance("kill something", _PHAL_CLOSE))

    def test_exit_something(self):
        self.assertIn(_PHAL_CLOSE, _run_utterance("exit something", _PHAL_CLOSE))

    def test_quit_something(self):
        self.assertIn(_PHAL_CLOSE, _run_utterance("quit something", _PHAL_CLOSE))

    def test_terminate_something(self):
        self.assertIn(_PHAL_CLOSE, _run_utterance("terminate something", _PHAL_CLOSE))


class TestPHALTimeoutGraceful(unittest.TestCase):
    """When PHAL plugin is absent the skill speaks error instead of crashing."""

    def test_launch_timeout_speaks_error(self):
        skill, bus = _make_skill()
        with patch.object(bus, "wait_for_response", return_value=None):
            msg = Message("test", {"utterance": "open firefox", "utterances": ["open firefox"]})
            skill.handle_fallback(msg)
        skill.speak_dialog.assert_called()
        self.assertEqual(skill.speak_dialog.call_args[0][0], "error.no.phal")


if __name__ == "__main__":
    unittest.main()
