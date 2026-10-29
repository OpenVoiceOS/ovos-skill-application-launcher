"""Regression tests for the launch-confirmation flow (handle_async_prompt).

Bug: answering "no" to the confirm_switch prompt made `if not switch:` treat
the non-empty string "no" as falsy-equivalent-to-truthy in a way that skipped
the confirm_launch prompt entirely, and the function unconditionally called
self.launch_app(app) at the end regardless of the user's actual answer. This
meant "no" (and any unclear answer) fell through to launching the app anyway.
"""
import importlib.util
import os
import sys
from unittest.mock import MagicMock

import pytest
from ovos_utils.fakebus import FakeBus

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_skill_module():
    spec = importlib.util.spec_from_file_location(
        "appl_skill_confirm", os.path.join(REPO, "__init__.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["appl_skill_confirm"] = module
    spec.loader.exec_module(module)
    return module


def _make_skill():
    module = _load_skill_module()
    skill = module.ApplicationLauncherSkill(skill_id="test.app.launcher.confirm", bus=FakeBus())
    skill.speak_dialog = MagicMock()
    skill.launch_app = MagicMock(return_value=True)
    skill.switch_window = MagicMock()
    skill.match_window = MagicMock(return_value=None)
    # disable the window-manager branch so only the confirm_launch prompt is exercised
    skill.wmctrl = None
    return skill


@pytest.fixture
def skill():
    return _make_skill()


def test_no_answer_does_not_launch(skill):
    """Answering "no" to confirm_launch must never launch the app."""
    skill.ask_yesno = MagicMock(return_value="no")
    skill.handle_async_prompt(type("Msg", (), {"data": {"app": "firefox"}})())
    skill.launch_app.assert_not_called()


def test_unclear_answer_does_not_launch(skill):
    """An unclear/unanswered prompt (ask_yesno returns None every retry)
    must never fall through to launching the app."""
    skill.ask_yesno = MagicMock(return_value=None)
    skill.handle_async_prompt(type("Msg", (), {"data": {"app": "firefox"}})())
    skill.launch_app.assert_not_called()


def test_yes_answer_launches(skill):
    """Answering "yes" to confirm_launch must launch the app."""
    skill.ask_yesno = MagicMock(return_value="yes")
    skill.handle_async_prompt(type("Msg", (), {"data": {"app": "firefox"}})())
    skill.launch_app.assert_called_once_with("firefox")


def test_switch_no_still_asks_launch_and_respects_no(skill):
    """Answering "no" to confirm_switch must fall through to the
    confirm_launch prompt (not straight to launching), and answering "no"
    there must not launch either.

    Regression coverage: this must fail if the confirm_launch gate is
    reverted to `if not switch:` (the original bug), because that mutant
    skips asking confirm_launch entirely - it would only ask confirm_switch
    once and then fall straight through to launch_app.
    """
    skill.wmctrl = "/usr/bin/wmctrl"
    answers = iter(["no", "no"])  # first call is confirm_switch, second confirm_launch
    prompts_asked = []

    def _ask_yesno(prompt, *a, **kw):
        prompts_asked.append(prompt)
        return next(answers)

    skill.ask_yesno = MagicMock(side_effect=_ask_yesno)
    skill.handle_async_prompt(type("Msg", (), {"data": {"app": "firefox"}})())
    skill.launch_app.assert_not_called()
    skill.switch_window.assert_not_called()
    assert prompts_asked == ["confirm_switch", "confirm_launch"]
    assert skill.ask_yesno.call_count == 2
