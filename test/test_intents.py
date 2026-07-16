"""Unit tests for the en-US intent matching and the {application} slot-value
exclusion (application.blacklist, OVOS-INTENT-2 §4.3)."""
import importlib.util
import os
import sys

import pytest
from ovos_utils.fakebus import FakeBus

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_skill_module():
    spec = importlib.util.spec_from_file_location(
        "appl_skill", os.path.join(REPO, "__init__.py"))
    module = importlib.util.module_from_spec(spec)
    # ovos-workshop resolves root_dir via sys.modules[__module__].__file__
    sys.modules["appl_skill"] = module
    spec.loader.exec_module(module)
    return module


def _load_skill():
    module = _load_skill_module()
    return module.ApplicationLauncherSkill(skill_id="test.app.launcher", bus=FakeBus())


@pytest.fixture(scope="module")
def skill():
    return _load_skill()


@pytest.mark.parametrize("utterance,intent", [
    ("open firefox", "launch"),
    ("launch spotify", "launch"),
    ("start the app spotify", "launch"),
    ("run gimp", "launch"),
    ("close chrome", "close"),
    ("quit gimp", "close"),
    ("kill firefox", "close"),
])
def test_application_is_matched(skill, utterance, intent):
    res = skill.match_app(utterance, "en-US")
    assert res["name"] == intent
    assert res["entities"].get("application")


@pytest.mark.parametrize("utterance", [
    "open it",            # anaphoric pronoun
    "close that",         # deictic
    "open the door",      # home automation
    "open the garage door",
    "close the blinds",
    "open the news",      # ovos-skill-news
    "open the camera",    # camera skill
    "open the weather",   # weather skill
    "shut down the computer",  # power/system skill
])
def test_blacklisted_values_leave_slot_unresolved(skill, utterance):
    res = skill.match_app(utterance, "en-US")
    # the intent may still match, but the {application} slot MUST be dropped so
    # the fallback declines and another skill can handle the utterance
    assert not res["entities"].get("application"), utterance


def test_blacklist_uses_whole_word_sequences(skill):
    # "doorbell" contains "door" as a substring but not as a whole word,
    # so it must still be treated as an application name
    res = skill.match_app("open doorbell", "en-US")
    assert res["entities"].get("application") == "doorbell"


def test_parse_desktop_file_tolerates_posix_locale(tmp_path):
    # .desktop files ship POSIX-style locale modifiers (e.g. "sr@latn") that are
    # not valid BCP-47 tags; parsing must not crash on them (OVOS-INTENT-2 §2)
    ApplicationLauncherSkill = _load_skill_module().ApplicationLauncherSkill
    desktop = tmp_path / "example.desktop"
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Example\n"
        "Name[sr@latn]=Primer\n"
        "Exec=example\n"
    )
    data = ApplicationLauncherSkill.parse_desktop_file(str(desktop))
    assert data["Name"] == "Example"
