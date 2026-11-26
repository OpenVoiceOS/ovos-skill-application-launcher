"""Golden-utterance end-to-end coverage for ovos-skill-application-launcher (en-US).

The golden corpus (``golden_utterances.jsonl``) is a vendored slice of the
shared ovoscope golden-utterance dataset, keyed by
``skill_id == "ovos-skill-application-launcher.openvoiceos"``.

This skill does not register regular padatious/adapt intents; it exposes a
single high-priority fallback handler that matches "open/launch/close
<application>" utterances through its own padacioso containers (see
``test/end2end/test_intents_en_us.py`` for the full rationale). There is
therefore no ``ovos.intent.matched`` event to key on -- the discriminating
signal is ``ovos.skills.fallback.<skill_id>.response`` with
``data.result == True``, which is what this suite asserts for every golden
row instead. The skill's own launch_app/close_app run against the fake desktop
of conftest.py, and a row passes when the skill launched or terminated the
command of its application. Every row reports to the ovoscope routing
tally.
"""
import gc
import json
from pathlib import Path

import pytest
from ovos_bus_client.message import Message
from ovos_utils.log import LOG
from ovoscope import get_minicroft

from .golden_support import (
    SKILL_ID,
    assert_effect,
    capture,
    check_negative,
    fallback_consumed,
    row_id,
)

LANG = "en-US"
GOLDEN_PATH = Path(__file__).parent / "golden_utterances.jsonl"

# utterances lifted verbatim from OTHER skills' golden-utterance slices,
# picked for lexical overlap with the launcher's "open/launch/run/close/
# quit/kill/exit/terminate <app>" vocabulary.
NEGATIVE_UTTERANCES = [
    ("what color is this", "ovos-skill-color-picker.openvoiceos"),
    ("take a picture", "ovos-skill-camera.openvoiceos"),
    ("count to ten", "ovos-skill-count.openvoiceos"),
    ("what happened today in history", "ovos-skill-days-in-history.openvoiceos"),
    ("open the garage door", "ovos-skill-homeassistant.openvoiceos"),
    ("close the blinds", "ovos-skill-homeassistant.openvoiceos"),
    ("shut down the computer", "ovos-skill-system.openvoiceos"),
    ("stop the timer", "ovos-skill-alerts.openvoiceos"),
    # overloaded verbs owned by other skills; must stay out of launch.intent /
    # close.intent even though they share vocabulary with "open"/"close"
    ("turn off the lights", "ovos-skill-homeassistant.openvoiceos"),
    ("stop the music", "ovos-ocp-audio-plugin.openvoiceos"),
    ("pause the music", "ovos-ocp-audio-plugin.openvoiceos"),
    ("please open the door", "ovos-skill-homeassistant.openvoiceos"),
]


GOLDEN_ROWS = [pytest.param(row, id=row_id(row))
               for row in map(json.loads, GOLDEN_PATH.read_text(encoding="utf-8").splitlines())]


@pytest.fixture(scope="module")
def minicroft(fake_phal):
    """Boot one MiniCroft with a stand-in PHAL plugin (see conftest.py)."""
    LOG.set_level("CRITICAL")
    mc = get_minicroft([SKILL_ID])
    skill = mc.plugin_skills[SKILL_ID].instance
    skill.calls = fake_phal(mc.bus)
    yield mc
    # see test_intents_en_us.py's teardown docstring for why the listener
    # dict is drained before mc.stop() takes pyee's non-reentrant lock.
    ee = getattr(mc.bus, "ee", None)
    if ee is not None:
        events = getattr(ee, "_events", None)
        if events is not None:
            for event in list(events.keys()):
                events.pop(event, None)
        gc.collect()
    mc.stop()


@pytest.mark.timeout(60)
@pytest.mark.parametrize("row", GOLDEN_ROWS)
def test_golden_utterance(minicroft, row):
    assert_effect(minicroft, LANG, row)


@pytest.mark.timeout(60)
@pytest.mark.parametrize("negative", NEGATIVE_UTTERANCES, ids=lambda n: n[0])
def test_negative_confusable_not_claimed(minicroft, negative):
    check_negative(minicroft, LANG, negative[0])


def _boot_and_stop(setup=None):
    LOG.set_level("CRITICAL")
    mc = get_minicroft([SKILL_ID])
    teardown = setup(mc) if setup else None
    yield mc
    if teardown:
        teardown()
    ee = getattr(mc.bus, "ee", None)
    if ee is not None:
        events = getattr(ee, "_events", None)
        if events is not None:
            for event in list(events.keys()):
                events.pop(event, None)
        gc.collect()
    mc.stop()


def _spoken(messages: list[Message]) -> list[str]:
    return [m.data.get("utterance", "") for m in messages
            if m.msg_type in ("speak", "ovos.utterance.speak")]


@pytest.fixture(scope="module")
def minicroft_no_phal():
    """A MiniCroft with no PHAL plugin on the bus: a stock install of the
    skill without ovos-PHAL-plugin-app-launcher."""
    yield from _boot_and_stop()


@pytest.mark.timeout(60)
def test_no_phal_fallback_speaks_error(minicroft_no_phal):
    """With no PHAL plugin answering, a launch request speaks the
    error_no_phal dialog instead of hanging or crashing."""
    messages = capture(minicroft_no_phal, "open firefox", LANG, "no-phal", ignore_speak=False)
    spoken = _spoken(messages)
    assert any("launcher service" in s for s in spoken), spoken


@pytest.fixture(scope="module")
def minicroft_real_phal():
    """A MiniCroft with the published ovos-PHAL-plugin-app-launcher on the
    bus, so the request and response contract is the plugin's own."""
    from ovos_phal_plugin_app_launcher import AppLauncherPHALPlugin

    def setup(mc):
        # the plugin checks the host's real processes, so the name must be
        # one that no process on the runner carries
        plugin = AppLauncherPHALPlugin(bus=mc.bus, config={"user_commands": {"something": "true"}})
        return plugin.shutdown

    yield from _boot_and_stop(setup)


@pytest.mark.timeout(60)
def test_golden_utterance_against_real_phal_plugin(minicroft_real_phal):
    """The fallback also reports ``result == True`` when it only speaks
    error_no_phal, so the plugin's own launch response with
    ``success: true`` must be on the bus and the error must not be spoken."""
    messages = capture(minicroft_real_phal, "open something", LANG, "real-phal", ignore_speak=False)
    assert fallback_consumed(messages), [m.msg_type for m in messages]
    launches = [m for m in messages if m.msg_type == "ovos.phal.app_launcher.launch.response"]
    assert [m.data.get("success") for m in launches] == [True], launches
    assert not any("launcher service" in s for s in _spoken(messages)), _spoken(messages)
