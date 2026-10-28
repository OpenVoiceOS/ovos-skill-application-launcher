"""Shared parts of the golden runners: row execution and the routing tally.

A golden row routes when the skill's own ``launch_app`` or ``close_app``
(run against the fake desktop of conftest.py) launches or terminates the
command of the row's application, and nothing else. A negative row routes
when the skill leaves it unclaimed. Every row reports to the ovoscope
routing tally, and the run fails when the share of rows that route falls
below the ``ovoscope_min_routing_rate`` of pyproject.toml.
"""
import json
from pathlib import Path

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovoscope import End2EndTest
from ovoscope.routing import TALLY

SKILL_ID = "ovos-skill-application-launcher.openvoiceos"
FALLBACK_RESPONSE = f"ovos.skills.fallback.{SKILL_ID}.response"
FALLBACK_PIPELINE = ["ovos-fallback-pipeline-plugin-high"]

END2END_DIR = Path(__file__).parent
LOCALE_ROOT = END2END_DIR.parent.parent / "locale"

# application names a row without an ``app`` field puts in the {application} slot
KNOWN_APPS = ("spotify", "firefox")


def load_rows(lang: str, kind: str = "golden") -> list:
    path = END2END_DIR / f"{kind}_utterances_{lang}.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows, f"{lang}: no {kind} rows"
    return rows


def row_id(row: dict) -> str:
    return f"{row['lang']}-{row['intent_label']}-{row['utterance']}"


def capture(minicroft, utterance: str, lang: str, session_id: str) -> list[Message]:
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
        ignore_messages=["speak", "ovos.utterance.speak", "mycroft.audio.play_sound"],
        source_message=message,
        expected_messages=[],
        test_message_number=False,
        test_boot_sequence=False,
        test_routing=False,
        test_final_session=False,
        verbose=False,
    )
    return test.execute()


def fallback_consumed(messages: list[Message]) -> bool:
    return any(m.msg_type == FALLBACK_RESPONSE and m.data.get("result") is True for m in messages)


def assert_effect(minicroft, fake_desktop, lang: str, row: dict) -> None:
    """Tally whether the skill did what the row asks."""
    skill = minicroft.plugin_skills[SKILL_ID].instance
    skill.attempts.clear()
    skill.calls.clear()
    messages = capture(minicroft, row["utterance"], lang, f"golden-{row_id(row)}")
    words = row["utterance"].lower().split()
    app = row.get("app") or next((a for a in KNOWN_APPS if a in words), None)
    assert app, f"[{lang}] {row['utterance']!r}: row names no application"
    command = fake_desktop.expected_command(app)
    if skill.calls == [(row["intent_label"], command)] and fallback_consumed(messages):
        done = [f"{SKILL_ID}:{row['intent_label']}"]
    else:
        done = ([f"{SKILL_ID}:{intent} of {cmd!r}" for intent, cmd in skill.calls]
                or [f"{SKILL_ID}:{intent} declined {value!r}" for intent, value in skill.attempts])
    TALLY.assert_routed(f"[{lang}] {row['utterance']} ({app})",
                        f"{SKILL_ID}:{row['intent_label']}", done)


def check_negative(minicroft, lang: str, utterance: str) -> None:
    """Tally a claim of a request that belongs to another skill.

    A claim is the matcher handing the request to launch_app/close_app,
    whether or not an installed application then matches.
    """
    skill = minicroft.plugin_skills[SKILL_ID].instance
    skill.attempts.clear()
    messages = capture(minicroft, utterance, lang, f"negative-{lang}-{utterance}")
    claimed = [f"{SKILL_ID}:{intent}" for intent, _ in skill.attempts]
    if not claimed and fallback_consumed(messages):
        claimed = [FALLBACK_RESPONSE]
    TALLY.assert_not_routed(f"[{lang}] {utterance}", claimed, claimed)
