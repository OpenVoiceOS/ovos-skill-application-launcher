"""End-to-end intent-routing coverage for ovos-skill-application-launcher.

The skill does not register regular intents; it exposes a single fallback
handler (priority 4) that matches "open/launch/close <application>" utterances
through its own padacioso containers and then launches or closes the desktop
application.

These tests drive the real high-priority fallback pipeline with a table of
utterances and assert only the *discriminating* bus signal for each case,
rather than a full ordered message skeleton:

* a matched utterance is consumed by the skill's fallback handler
  (``ovos.skills.fallback.<skill_id>.response`` carries ``result: True``);
* a blacklisted / deictic utterance is declined so the fallback returns no
  result and the utterance is free to reach its rightful skill
  (OVOS-INTENT-2 §4.3 slot-value exclusion).

Asserting the presence/absence of that single signal keeps the tests immune to
message-sequence drift in ovos-core (extra ``ovos.intent.matched`` /
activation frames, reordering of the fallback ping/pong handshake, etc.).

The real launch/close code paths spawn OS processes and inspect the running
process table, which is not deterministic on a CI runner, so the instance's
launch/close side effects are neutralised while the intent-matching and
fallback routing under test run for real.
"""
from typing import List

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

SKILL_ID = "ovos-skill-application-launcher.openvoiceos"
LANG = "en-US"
HANDLER = "ApplicationLauncherSkill.handle_fallback"
FALLBACK_RESPONSE = f"ovos.skills.fallback.{SKILL_ID}.response"

# priority-4 handler lives in the high-priority fallback range
FALLBACK_PIPELINE = ["ovos-fallback-pipeline-plugin-high"]

# utterance -> intent the skill's padacioso matcher should resolve. Every verb
# alias from launch.intent / close.intent is represented so a change to the
# open-vocabulary phrasings is caught end-to-end.
LAUNCH_UTTERANCES = [
    "open firefox",
    "launch spotify",
    "start gimp",
    "run blender",
    "fire up kcalc",
    "open the app spotify",
]
CLOSE_UTTERANCES = [
    "close chrome",
    "quit gimp",
    "kill firefox",
    "exit spotify",
    "terminate blender",
    "shut down kcalc",
    "close the window firefox",
]

# utterances whose slot value is excluded by application.blacklist and MUST NOT
# be consumed by the launcher fallback (OVOS-INTENT-2 §4.3). Each cites the
# skill that rightfully owns the phrasing.
BLACKLIST_UTTERANCES = [
    "open it",                 # anaphoric pronoun
    "close that",              # deictic
    "open the door",           # home automation
    "open the garage door",    # home automation
    "close the blinds",        # home automation
    "open the news",           # ovos-skill-news
    "open the weather",        # weather skill
    "shut down the computer",  # power / system skill
]


@pytest.fixture(scope="module")
def minicroft():
    """Boot one MiniCroft and neutralise the OS-facing launch/close effects."""
    LOG.set_level("CRITICAL")
    mc = get_minicroft([SKILL_ID])
    skill = mc.plugin_skills[SKILL_ID].instance
    # keep intent matching real; neutralise the OS-facing effects so the
    # outcome does not depend on which applications happen to be installed
    # or running on the runner
    skill.is_running = lambda app: False
    skill.launch_app = lambda app: True
    skill.close_app = lambda app: True
    yield mc
    mc.stop()


def _capture(minicroft, utterance: str) -> List[Message]:
    """Drive *utterance* through the fallback pipeline, return the bus messages."""
    session = Session(f"e2e-{abs(hash(utterance))}")
    session.lang = LANG
    session.pipeline = list(FALLBACK_PIPELINE)

    message = Message(
        "recognizer_loop:utterance",
        {"utterances": [utterance], "lang": LANG},
        {"session": session.serialize()},
    )

    test = End2EndTest(
        minicroft=minicroft,
        skill_ids=[],
        eof_msgs=["ovos.utterance.handled", "complete_intent_failure"],
        flip_points=["recognizer_loop:utterance"],
        ignore_messages=["speak", "ovos.utterance.speak",
                         "mycroft.audio.play_sound"],
        source_message=message,
        # subset assertion only: we inspect the returned messages ourselves
        # instead of matching a brittle full ordered skeleton
        expected_messages=[],
        test_message_number=False,
        test_boot_sequence=False,
        test_routing=False,
        test_final_session=False,
        verbose=False,
    )
    return test.execute()


def _fallback_consumed(messages: List[Message]) -> bool:
    """True if the launcher fallback handled the utterance (result: True)."""
    for m in messages:
        if m.msg_type == FALLBACK_RESPONSE and m.data.get("result") is True:
            return True
    return False


@pytest.mark.parametrize("utterance", LAUNCH_UTTERANCES + CLOSE_UTTERANCES)
def test_application_utterance_is_handled(minicroft, utterance):
    """Every launch/close phrasing must be consumed by the launcher fallback."""
    messages = _capture(minicroft, utterance)
    assert _fallback_consumed(messages), (
        f"expected {utterance!r} to be handled by the launcher fallback, "
        f"got {[m.msg_type for m in messages]}")


@pytest.mark.parametrize("utterance", BLACKLIST_UTTERANCES)
def test_blacklisted_utterance_is_declined(minicroft, utterance):
    """Blacklisted / deictic phrasings must fall through, not be hijacked."""
    messages = _capture(minicroft, utterance)
    assert not _fallback_consumed(messages), (
        f"{utterance!r} was unexpectedly hijacked by the launcher fallback; "
        f"its {{application}} slot value should be blacklisted "
        f"(OVOS-INTENT-2 §4.3)")
