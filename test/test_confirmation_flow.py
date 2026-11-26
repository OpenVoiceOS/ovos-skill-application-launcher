"""Regression tests for the launch-confirmation flow (handle_async_prompt).

The skill delegates the actual launch to the PHAL plugin via
``bus.wait_for_response`` (see ``_launch_app``). The PHAL contract has no
"switch to window" verb, so this flow never promises to switch to the
running app -- it only ever offers to open a new window/instance. These
tests assert that an unclear/negative answer never triggers that bus call,
and that the dialogs spoken never claim a switch is possible.
"""
import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PHAL_LAUNCH = "ovos.phal.app_launcher.launch"

# dialog names that would falsely promise switching to the existing window;
# handle_async_prompt must never speak these
_SWITCH_DIALOGS = {"confirm_switch", "switch"}


def _load_skill_module():
    spec = importlib.util.spec_from_file_location(
        "appl_skill_confirm", os.path.join(REPO, "__init__.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["appl_skill_confirm"] = module
    spec.loader.exec_module(module)
    return module


def _make_skill(settings=None):
    module = _load_skill_module()
    skill = module.ApplicationLauncherSkill(skill_id="test.app.launcher.confirm", bus=FakeBus())
    skill.speak_dialog = MagicMock()
    skill.settings = settings or {}
    return skill


def _prompt_message():
    return Message("test", {"app": "firefox"})


@pytest.fixture
def skill():
    return _make_skill()


def test_no_answer_does_not_launch(skill):
    """Answering "no" to confirm_launch must never launch the app."""
    skill.ask_yesno = MagicMock(return_value="no")
    with patch.object(skill.bus, "wait_for_response") as wfr:
        skill.handle_async_prompt(_prompt_message())
    wfr.assert_not_called()


def test_unclear_answer_does_not_launch(skill):
    """An unclear/unanswered prompt (ask_yesno returns None every retry)
    must never fall through to launching the app."""
    skill.ask_yesno = MagicMock(return_value=None)
    with patch.object(skill.bus, "wait_for_response") as wfr:
        skill.handle_async_prompt(_prompt_message())
    wfr.assert_not_called()


def test_yes_answer_launches(skill):
    """Answering "yes" launches a new instance of the app via PHAL."""
    skill.ask_yesno = MagicMock(return_value="yes")
    with patch.object(skill.bus, "wait_for_response",
                       return_value=Message(f"{_PHAL_LAUNCH}.response",
                                             {"name": "firefox", "success": True})) as wfr:
        skill.handle_async_prompt(_prompt_message())
    assert wfr.call_args[0][0].msg_type == _PHAL_LAUNCH
    assert wfr.call_args[0][0].data == {"name": "firefox"}


def test_confirmed_prompt_never_promises_a_switch(skill):
    """A confirmed prompt must launch, and no dialog spoken along the way
    may promise switching to the already-running window (no such PHAL
    verb exists)."""
    skill.ask_yesno = MagicMock(return_value="yes")
    with patch.object(skill.bus, "wait_for_response",
                       return_value=Message(f"{_PHAL_LAUNCH}.response",
                                             {"name": "firefox", "success": True})):
        skill.handle_async_prompt(_prompt_message())

    dialogs_spoken = {call.args[0] for call in skill.speak_dialog.call_args_list}
    assert not dialogs_spoken & _SWITCH_DIALOGS
    prompts_asked = {call.args[0] for call in skill.ask_yesno.call_args_list}
    assert not prompts_asked & _SWITCH_DIALOGS
