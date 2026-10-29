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
from ovos_utils.log import LOG
from ovoscope import get_minicroft

from .golden_support import (
    SKILL_ID,
    assert_effect,
    check_negative,
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
def minicroft(fake_desktop):
    """Boot one MiniCroft on a fake desktop (see conftest.py)."""
    LOG.set_level("CRITICAL")
    mc = get_minicroft([SKILL_ID])
    restore = fake_desktop.install(mc.plugin_skills[SKILL_ID].instance)
    yield mc
    restore()
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
def test_golden_utterance(minicroft, fake_desktop, row):
    assert_effect(minicroft, fake_desktop, LANG, row)


@pytest.mark.timeout(60)
@pytest.mark.parametrize("negative", NEGATIVE_UTTERANCES, ids=lambda n: n[0])
def test_negative_confusable_not_claimed(minicroft, negative):
    check_negative(minicroft, LANG, negative[0])
