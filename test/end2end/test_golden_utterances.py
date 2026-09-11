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
row instead.
"""
import gc
import json
from pathlib import Path
from typing import List

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG
from ovoscope import End2EndTest, get_minicroft

SKILL_ID = "ovos-skill-application-launcher.openvoiceos"
LANG = "en-US"
FALLBACK_RESPONSE = f"ovos.skills.fallback.{SKILL_ID}.response"
FALLBACK_PIPELINE = ["ovos-fallback-pipeline-plugin-high"]

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


def _load_golden_rows():
    rows = []
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("needs_manual"):
                continue
            rows.append(row)
    return rows


GOLDEN_ROWS = [pytest.param(r, id=r["utterance"]) for r in _load_golden_rows()]


@pytest.fixture(scope="module")
def minicroft():
    """Boot one MiniCroft and neutralise the OS-facing launch/close effects."""
    LOG.set_level("CRITICAL")
    mc = get_minicroft([SKILL_ID])
    skill = mc.plugin_skills[SKILL_ID].instance
    skill.is_running = lambda app: False
    skill.launch_app = lambda app: True
    skill.close_app = lambda app: True
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


def _capture(minicroft, utterance: str) -> List[Message]:
    session = Session(f"golden-{abs(hash(utterance))}")
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
        expected_messages=[],
        test_message_number=False,
        test_boot_sequence=False,
        test_routing=False,
        test_final_session=False,
        verbose=False,
    )
    return test.execute()


def _fallback_consumed(messages: List[Message]) -> bool:
    for m in messages:
        if m.msg_type == FALLBACK_RESPONSE and m.data.get("result") is True:
            return True
    return False


@pytest.mark.timeout(60)
@pytest.mark.parametrize("row", GOLDEN_ROWS, ids=lambda r: r["utterance"])
def test_golden_utterance(minicroft, row):
    messages = _capture(minicroft, row["utterance"])
    assert _fallback_consumed(messages), (
        f"{row['utterance']!r}: expected the launcher fallback to consume it "
        f"(intent_label={row['intent_label']!r}), got "
        f"{[m.msg_type for m in messages]!r}"
    )


@pytest.mark.timeout(60)
@pytest.mark.parametrize("negative", NEGATIVE_UTTERANCES, ids=lambda n: n[0])
def test_negative_confusable_not_claimed(minicroft, negative):
    text, source_skill = negative
    messages = _capture(minicroft, text)
    assert not _fallback_consumed(messages), (
        f"{text!r} (from {source_skill}) was incorrectly claimed by {SKILL_ID}"
    )
