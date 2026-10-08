"""The fallback reads every transcript, not only the first one.

`can_answer` read `utterances[0]` and `handle_fallback` read `utterance`,
which the fallback pipeline sets to that same first transcript
(`ovos_core/intent_services/service.py:988`, from `utterances[0]` in
`fallback_service.py:323`). So both read one entry of the n-best list, and the
entries are not interchangeable.

A Farsi launch phrase shows it. `locale/fa-IR/launch.intent` holds
"راه‌اندازی {application}" with a zero-width non-joiner inside the verb. When
the first transcript is a phrase that matches no intent and a later one is
this launch phrase, reading only `utterances[0]`, or the `utterance` key the
pipeline sets to that same entry, leaves the launch phrase unmatched.

The entries are transcriptions of one utterance, so reading all of them must
not widen the `application.blacklist` slot-value exclusion
(OVOS-INTENT-2 §4.3) either: a hit on any entry declines the round.

No application is launched here: `launch_app` records its argument.
"""
import importlib.util
import os
import sys

import pytest
from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZWNJ = "‌"
FA_LAUNCH = f"راه{ZWNJ}اندازی spotify"
# a first transcript that matches no intent
FA_NOISE = "سلام دنیا"


def _load_skill_module():
    spec = importlib.util.spec_from_file_location(
        "appl_skill_every_utterance", os.path.join(REPO, "__init__.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["appl_skill_every_utterance"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def skill():
    module = _load_skill_module()
    sk = module.ApplicationLauncherSkill(skill_id="test.app.launcher.utterances",
                                         bus=FakeBus())
    sk.applist = {"Spotify": "spotify", "Firefox": "firefox"}
    sk.launched = []
    sk.launch_app = lambda app: (sk.launched.append(app), True)[1]
    sk.is_running = lambda app: False
    return sk


def _ping(utterances, lang="fa-IR"):
    """The message `can_answer` reads. The fallback pipeline's ping carries the
    n-best list and no `utterance` key."""
    return Message("ovos.skills.fallback.ping",
                   {"utterances": list(utterances), "lang": lang})


def _request(utterances, lang="fa-IR"):
    """The message the handler reads. The pipeline's request adds `utterance`,
    set to the first entry of the list, so it is set here too; reading it
    instead of the list is the defect."""
    return Message("ovos.skills.fallback.test.request",
                   {"utterances": list(utterances), "utterance": utterances[0],
                    "lang": lang, "skill_id": "test.app.launcher.utterances"})


def test_the_container_matches_the_launch_phrase_and_not_the_noise():
    """The control for the tests below: the launch phrase matches
    and the noise phrase does not. Without this, a test that passes
    on the joined form would prove nothing about reading the whole list."""
    module = _load_skill_module()
    sk = module.ApplicationLauncherSkill(skill_id="test.app.launcher.control",
                                         bus=FakeBus())
    assert sk.match_app(FA_LAUNCH, "fa-IR")["entities"]["application"] == "spotify"
    assert not sk.match_app(FA_NOISE, "fa-IR").get("entities", {}).get("application")


def test_can_answer_reads_past_the_first_transcript(skill):
    assert skill.can_answer(_ping([FA_NOISE, FA_LAUNCH])) is True


def test_the_fallback_launches_from_a_later_transcript(skill):
    assert skill.handle_fallback(_request([FA_NOISE, FA_LAUNCH])) is True
    assert skill.launched == ["spotify"]


def test_a_one_entry_list_launches(skill):
    """The positive control for the two tests above: this phrasing launches
    when it is the only transcript. Without it, a launch from a two-entry list
    would prove nothing about which entry was read."""
    assert skill.handle_fallback(_request([FA_LAUNCH])) is True
    assert skill.launched == ["spotify"]


def test_the_first_transcript_key_is_not_read(skill):
    """`utterance` carries the first transcript, and the first transcript is
    the one that does not match. The handler must launch from the entry of
    `utterances` that does."""
    msg = _request([FA_NOISE, FA_LAUNCH])
    assert msg.data["utterance"] == FA_NOISE
    assert skill.handle_fallback(msg) is True
    assert skill.launched == ["spotify"]


def test_an_unmatched_list_is_declined(skill):
    assert skill.handle_fallback(_request([FA_NOISE])) is False
    assert skill.launched == []
    assert skill.can_answer(_ping([FA_NOISE])) is False


def test_the_first_clean_match_wins_over_a_later_one(skill):
    """Two transcripts can each name a different application. The order of
    `utterances` ranks them, so the first clean match must win; dropping that
    rule and keeping the last match instead would launch Spotify for a user
    who said "open firefox"."""
    assert skill.handle_fallback(
        _request(["open firefox", "open spotify"], lang="en-US")) is True
    assert skill.launched == ["firefox"]


# The `application.blacklist` slot-value exclusion reaches the whole n-best
# list. "open the blinds" belongs to Home Assistant; "the blinds" is on the
# en-US list and "the blind" is not, so a second transcript of the same speech
# must not hand the utterance to this skill.
BLACKLISTED_UTT = "open the blinds"
CLEAN_UTT = "open the blind"


def test_a_clean_transcript_launches(skill):
    """The positive control for the two tests below: with nothing blacklisted
    in the list, this phrasing does match and does launch. Without it, a
    declined list would prove nothing about the blacklist."""
    assert skill.handle_fallback(_request([CLEAN_UTT], lang="en-US")) is True
    assert skill.launched == ["the blind"]


def test_a_blacklisted_transcript_declines_the_whole_list(skill):
    assert skill.handle_fallback(
        _request([BLACKLISTED_UTT, CLEAN_UTT], lang="en-US")) is False
    assert skill.launched == []


def test_a_blacklisted_later_transcript_also_declines(skill):
    """Order must not matter: the exclusion is evidence about the utterance,
    not about the entry that carried it."""
    assert skill.can_answer(
        _ping([CLEAN_UTT, BLACKLISTED_UTT], lang="en-US")) is False
