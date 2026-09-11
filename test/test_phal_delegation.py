"""Tests verifying skill delegates OS actions to PHAL plugin via bus messages."""
import unittest
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

_PHAL_LAUNCH = "ovos.phal.app_launcher.launch"
_PHAL_CLOSE = "ovos.phal.app_launcher.close"
_PHAL_IS_RUNNING = "ovos.phal.app_launcher.is_running"


def _make_skill():
    """Build a minimal skill instance without touching OVOSSkill.__init__."""
    from ovos_skill_application_launcher import ApplicationLauncherSkill
    bus = FakeBus()
    skill = MagicMock(spec=ApplicationLauncherSkill)
    # wire the real methods we want to test
    skill._launch_app = ApplicationLauncherSkill._launch_app.__get__(skill)
    skill._close_app = ApplicationLauncherSkill._close_app.__get__(skill)
    skill.handle_fallback = ApplicationLauncherSkill.handle_fallback.__get__(skill)
    # match_app is lru_cache'd; bind the underlying function so it can be called directly
    skill.match_app = ApplicationLauncherSkill.match_app.__wrapped__.__get__(skill)
    skill.bus = bus
    skill.intent_matchers = {}
    skill.blacklists = {}
    skill._is_blacklisted = ApplicationLauncherSkill._is_blacklisted.__get__(skill)
    skill.lang = "en-US"
    skill.skill_id = "test.skill"
    skill.settings = {}
    return skill, bus


class TestLaunchDelegation(unittest.TestCase):

    def test_launch_emits_phal_launch(self):
        skill, bus = _make_skill()
        resp = Message(f"{_PHAL_LAUNCH}.response", {"name": "Firefox", "success": True})
        with patch.object(bus, "wait_for_response", return_value=resp) as mock_wait:
            skill.acknowledge = MagicMock()
            result = skill._launch_app("Firefox", Message("test"))
        mock_wait.assert_called_once()
        sent_msg = mock_wait.call_args[0][0]
        self.assertEqual(sent_msg.msg_type, _PHAL_LAUNCH)
        self.assertEqual(sent_msg.data["name"], "Firefox")
        self.assertTrue(result)
        skill.acknowledge.assert_called_once()

    def test_launch_speaks_error_on_phal_timeout(self):
        skill, bus = _make_skill()
        with patch.object(bus, "wait_for_response", return_value=None):
            skill.speak_dialog = MagicMock()
            result = skill._launch_app("Firefox", Message("test"))
        skill.speak_dialog.assert_called_once_with("error.no.phal")
        self.assertFalse(result)

    def test_launch_speaks_error_on_phal_error(self):
        skill, bus = _make_skill()
        resp = Message(f"{_PHAL_LAUNCH}.response", {"name": "Firefox", "error": "not found"})
        with patch.object(bus, "wait_for_response", return_value=resp):
            skill.speak_dialog = MagicMock()
            result = skill._launch_app("Firefox", Message("test"))
        skill.speak_dialog.assert_called_once_with("error.launch", {"application": "Firefox"})
        self.assertFalse(result)

    def test_no_subprocess_in_skill(self):
        """subprocess must never be imported or called from the skill."""
        import ovos_skill_application_launcher as mod
        self.assertFalse(hasattr(mod, "subprocess"),
                         "skill module must not import subprocess after PHAL split")


class TestCloseDelegation(unittest.TestCase):

    def test_close_emits_phal_close(self):
        skill, bus = _make_skill()
        resp = Message(f"{_PHAL_CLOSE}.response", {"name": "Firefox", "success": True})
        with patch.object(bus, "wait_for_response", return_value=resp):
            skill.acknowledge = MagicMock()
            result = skill._close_app("Firefox", Message("test"))
        self.assertTrue(result)

    def test_close_timeout_speaks_error(self):
        skill, bus = _make_skill()
        with patch.object(bus, "wait_for_response", return_value=None):
            skill.speak_dialog = MagicMock()
            result = skill._close_app("Firefox", Message("test"))
        skill.speak_dialog.assert_called_once_with("error.no.phal")
        self.assertFalse(result)


class TestIsRunningCheck(unittest.TestCase):

    def test_fallback_checks_is_running_before_launch(self):
        from padacioso import IntentContainer
        skill, bus = _make_skill()
        ic = IntentContainer()
        ic.add_intent("launch", ["open {application}", "launch {application}"])
        skill.intent_matchers = {"en-US": ic}

        is_running_resp = Message(f"{_PHAL_IS_RUNNING}.response", {"name": "firefox", "running": True})
        async_prompts = []
        bus.on(f"{skill.skill_id}.async_prompt", async_prompts.append)

        def _wait(msg, reply_type=None, timeout=5):
            if msg.msg_type == _PHAL_IS_RUNNING:
                return is_running_resp
            return None

        with patch.object(bus, "wait_for_response", side_effect=_wait):
            msg = Message("recognizer_loop:utterance",
                          {"utterance": "open firefox", "utterances": ["open firefox"]})
            result = skill.handle_fallback(msg)

        self.assertTrue(result)
        self.assertTrue(len(async_prompts) > 0)

    def test_fallback_launches_when_not_running(self):
        from padacioso import IntentContainer
        skill, bus = _make_skill()
        ic = IntentContainer()
        ic.add_intent("launch", ["open {application}", "launch {application}"])
        skill.intent_matchers = {"en-US": ic}

        is_running_resp = Message(f"{_PHAL_IS_RUNNING}.response", {"name": "firefox", "running": False})
        launch_resp = Message(f"{_PHAL_LAUNCH}.response", {"name": "firefox", "success": True})

        def _wait(msg, reply_type=None, timeout=5):
            if msg.msg_type == _PHAL_IS_RUNNING:
                return is_running_resp
            if msg.msg_type == _PHAL_LAUNCH:
                return launch_resp
            return None

        skill.acknowledge = MagicMock()
        with patch.object(bus, "wait_for_response", side_effect=_wait):
            msg = Message("recognizer_loop:utterance",
                          {"utterance": "open firefox", "utterances": ["open firefox"]})
            result = skill.handle_fallback(msg)

        self.assertTrue(result)
        skill.acknowledge.assert_called_once()

    def test_fallback_skips_launch_call_when_no_phal(self):
        """If the is_running probe times out (no PHAL plugin installed),
        handle_fallback must not make a second wait_for_response call for
        launch -- that would just time out again and double the wait."""
        from padacioso import IntentContainer
        skill, bus = _make_skill()
        ic = IntentContainer()
        ic.add_intent("launch", ["open {application}", "launch {application}"])
        skill.intent_matchers = {"en-US": ic}

        skill.speak_dialog = MagicMock()
        with patch.object(bus, "wait_for_response", return_value=None) as mock_wait:
            msg = Message("recognizer_loop:utterance",
                          {"utterance": "open firefox", "utterances": ["open firefox"]})
            result = skill.handle_fallback(msg)

        mock_wait.assert_called_once()
        self.assertEqual(mock_wait.call_args[0][0].msg_type, _PHAL_IS_RUNNING)
        skill.speak_dialog.assert_called_once_with("error.no.phal")
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
