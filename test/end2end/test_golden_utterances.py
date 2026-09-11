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

_PHAL_IS_RUNNING = "ovos.phal.app_launcher.is_running"
_PHAL_LAUNCH = "ovos.phal.app_launcher.launch"
_PHAL_CLOSE = "ovos.phal.app_launcher.close"

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
    """Boot one MiniCroft with a stand-in PHAL plugin answering the
    ovos.phal.app_launcher.* bus API, so the golden utterances still
    exercise the real bus round trip without depending on any actual
    OS-level launcher being present on the runner.
    """
    LOG.set_level("CRITICAL")
    mc = get_minicroft([SKILL_ID])
    skill = mc.plugin_skills[SKILL_ID].instance

    def _stub_is_running(message):
        mc.bus.emit(message.response({"name": message.data.get("name"), "running": False}))

    def _stub_launch(message):
        mc.bus.emit(message.response({"name": message.data.get("name"), "success": True}))

    def _stub_close(message):
        mc.bus.emit(message.response({"name": message.data.get("name"), "success": True}))

    mc.bus.on(_PHAL_IS_RUNNING, _stub_is_running)
    mc.bus.on(_PHAL_LAUNCH, _stub_launch)
    mc.bus.on(_PHAL_CLOSE, _stub_close)
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


def _capture(minicroft, utterance: str, ignore_speak: bool = True) -> List[Message]:
    session = Session(f"golden-{abs(hash(utterance))}")
    session.lang = LANG
    session.pipeline = list(FALLBACK_PIPELINE)

    message = Message(
        "recognizer_loop:utterance",
        {"utterances": [utterance], "lang": LANG},
        {"session": session.serialize()},
    )

    ignore_messages = ["mycroft.audio.play_sound"]
    if ignore_speak:
        ignore_messages += ["speak", "ovos.utterance.speak"]

    test = End2EndTest(
        minicroft=minicroft,
        skill_ids=[],
        eof_msgs=["ovos.utterance.handled", "complete_intent_failure"],
        flip_points=["recognizer_loop:utterance"],
        ignore_messages=ignore_messages,
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


@pytest.fixture(scope="module")
def minicroft_no_phal():
    """A MiniCroft with no PHAL plugin registered at all, matching a stock
    install of the skill without ovos-PHAL-plugin-app-launcher."""
    LOG.set_level("CRITICAL")
    mc = get_minicroft([SKILL_ID])
    yield mc
    ee = getattr(mc.bus, "ee", None)
    if ee is not None:
        events = getattr(ee, "_events", None)
        if events is not None:
            for event in list(events.keys()):
                events.pop(event, None)
        gc.collect()
    mc.stop()


@pytest.mark.timeout(60)
def test_no_phal_fallback_speaks_error(minicroft_no_phal):
    """On a real bus with no PHAL plugin answering, launching an app must
    speak the no-phal error instead of hanging or crashing."""
    messages = _capture(minicroft_no_phal, "open something", ignore_speak=False)
    spoken = [m.data.get("utterance", "") for m in messages
              if m.msg_type in ("speak", "ovos.utterance.speak")]
    assert spoken, f"expected the launcher to speak a service-unavailable dialog, got {messages!r}"
    assert any("launcher service" in s for s in spoken), spoken


@pytest.fixture(scope="module")
def minicroft_real_phal():
    """A MiniCroft with the REAL ovos-PHAL-plugin-app-launcher package
    (not a hand-written stub) answering the ovos.phal.app_launcher.*
    bus API, so this test exercises the actual published plugin's request/
    response contract instead of a test double that may drift from it.
    """
    from ovos_phal_plugin_app_launcher import AppLauncherPHALPlugin

    LOG.set_level("CRITICAL")
    mc = get_minicroft([SKILL_ID])
    plugin = AppLauncherPHALPlugin(bus=mc.bus, config={"user_commands": {"something": "true"}})
    yield mc
    plugin.shutdown()
    ee = getattr(mc.bus, "ee", None)
    if ee is not None:
        events = getattr(ee, "_events", None)
        if events is not None:
            for event in list(events.keys()):
                events.pop(event, None)
        gc.collect()
    mc.stop()


@pytest.mark.timeout(60)
def test_golden_utterance_against_real_phal_plugin(minicroft_real_phal):
    """One golden utterance running end-to-end against the real, published
    ovos-PHAL-plugin-app-launcher (PyPI 0.0.1a1) rather than a stub.

    ``_fallback_consumed`` alone is not enough: the fallback also reports
    ``result == True`` when the launch actually fails and the skill just
    speaks "error.no.phal" (see ``test_no_phal_fallback_speaks_error``,
    which hits that exact path without a plugin installed). This test must
    additionally see the plugin's own ``.launch.response`` with
    ``success: true`` on the bus, and must NOT see the no-phal error
    dialog, to prove the real plugin was actually exercised.
    """
    messages = _capture(minicroft_real_phal, "open something", ignore_speak=False)
    assert _fallback_consumed(messages), messages

    launch_responses = [m for m in messages if m.msg_type == f"{_PHAL_LAUNCH}.response"]
    assert launch_responses, (
        f"expected a {_PHAL_LAUNCH}.response from the real PHAL plugin, got "
        f"{[m.msg_type for m in messages]!r}"
    )
    assert any(m.data.get("success") is True for m in launch_responses), launch_responses

    spoken = [m.data.get("utterance", "") for m in messages
              if m.msg_type in ("speak", "ovos.utterance.speak")]
    assert not any("launcher service" in s for s in spoken), (
        f"no-phal error dialog was spoken even though the real plugin is installed: {spoken!r}"
    )
