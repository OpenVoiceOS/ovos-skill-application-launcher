"""Multilingual golden-utterance end-to-end coverage for
ovos-skill-application-launcher.

test_golden_utterances.py only exercises en-US; every other locale under
locale/ ships real launch.intent / close.intent templates (padacioso
IntentContainer, see __init__.py register_fallback_intents()) that were
completely untested end-to-end. This suite covers every locale that ships
both a launch.intent and close.intent file.

The skill is a FallbackSkill: it exposes no ovos.intent.matched event, only
a high-priority fallback handler matched by its own padacioso containers
(one IntentContainer per locale, all loaded at initialize() regardless of
which locale MiniCroft boots as primary). The discriminating signal is
ovos.skills.fallback.<skill_id>.response with data.result == True, exactly
as test_golden_utterances.py already asserts for en-US.

Row construction: each row is derived mechanically from that locale's own
launch.intent / close.intent template lines (bracket-expansion choices
already present in the file), never a translation of the English rows.

One MiniCroft is booted PER LOCALE (not one shared instance with every
locale as a secondary_lang -- that boot shape hangs on the ovoscope
harness bug tracked for the alerts skill's multilang suite). The
per-locale MiniCroft fixture is module-scoped and indirectly parametrized
by lang; pytest reuses one boot per distinct lang value across every row
belonging to that lang and tears it down before moving to the next.
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
FALLBACK_RESPONSE = f"ovos.skills.fallback.{SKILL_ID}.response"
FALLBACK_PIPELINE = ["ovos-fallback-pipeline-plugin-high"]

END2END_DIR = Path(__file__).parent

LANGS = [
    "en-US", "ca-ES", "da-DK", "de-DE", "es-ES", "eu-ES", "fa-IR", "fr-FR",
    "gl-ES", "it-IT", "kab", "nl-NL", "oc-FR", "pt-BR", "pt-PT", "sv-SE",
]


def _load_rows(lang):
    path = END2END_DIR / f"golden_utterances_{lang}.jsonl"
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("needs_manual"):
                continue
            rows.append(row)
    return rows


ALL_ROWS = []
for _lang in LANGS:
    for _row in _load_rows(_lang):
        ALL_ROWS.append(_row)


def _golden_id(row):
    return f"{row['lang']}-{row['intent_label']}-{row['utterance']}"


@pytest.fixture(scope="module")
def minicroft(request):
    """One MiniCroft boot per distinct lang value, reused across every row
    of that lang (pytest caches module-scoped indirect fixtures by param
    value and groups tests to minimise re-instantiation)."""
    lang = request.param
    LOG.set_level("CRITICAL")
    mc = get_minicroft([SKILL_ID], max_wait=150, lang=lang)
    skill = mc.plugin_skills[SKILL_ID].instance
    skill.is_running = lambda app: False
    skill.calls = []
    skill.launch_app = lambda app: skill.calls.append(("launch", app)) or True
    skill.close_app = lambda app: skill.calls.append(("close", app)) or True
    yield mc
    ee = getattr(mc.bus, "ee", None)
    if ee is not None:
        events = getattr(ee, "_events", None)
        if events is not None:
            for event in list(events.keys()):
                events.pop(event, None)
            gc.collect()
    mc.stop()


def _capture(minicroft, utterance: str, lang: str, session_id: str) -> List[Message]:
    session = Session(session_id)
    session.lang = lang
    session.pipeline = list(FALLBACK_PIPELINE)

    message = Message(
        "recognizer_loop:utterance",
        {"utterances": [utterance], "lang": lang},
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


KNOWN_BUGS = {}

_PARAMS = [
    pytest.param(row["lang"], row, id=_golden_id(row))
    for row in ALL_ROWS
]


@pytest.mark.timeout(600)
@pytest.mark.parametrize("minicroft,row", _PARAMS, indirect=["minicroft"])
def test_golden_utterance_multilang(minicroft, row):
    skill = minicroft.plugin_skills[SKILL_ID].instance
    skill.calls.clear()
    messages = _capture(minicroft, row["utterance"], row["lang"], f"golden-{_golden_id(row)}")
    matched = _fallback_consumed(messages)
    bug_key = (row["lang"], row["utterance"])
    if bug_key in KNOWN_BUGS and not matched:
        pytest.xfail(reason=f"known-bug: {KNOWN_BUGS[bug_key]}")
    assert matched, (
        f"[{row['lang']}] {row['utterance']!r}: expected the launcher fallback to "
        f"consume it (intent_label={row['intent_label']!r}), got "
        f"{[m.msg_type for m in messages]!r}"
    )
    app = row.get("app") or ("spotify" if "spotify" in row["utterance"].split() else "something")
    assert skill.calls == [(row["intent_label"], app)], (
        f"[{row['lang']}] {row['utterance']!r}: expected {row['intent_label']}_app({app!r}), "
        f"the handler asked for {skill.calls}"
    )
