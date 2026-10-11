"""Shared parts of the golden runners: row execution, the expected failures
and the per-locale gates.

A golden row passes when the skill's own ``launch_app`` or ``close_app``
(run against the fake desktop of conftest.py) launches or terminates the
command of the row's application. ``KNOWN_BUGS`` names every row that does
not, with the kind of failure. Each listed row runs as a strict expected
failure: a listed row that passes fails the run and must leave the list, and
a listed row that fails in another way than listed fails the run too.

Each locale must pass at least ``MIN_MATCH_RATE`` of its rows, and each
intent at least ``MIN_MATCHED_ROWS_PER_INTENT`` of its own rows. A locale in
``GOLDEN_LOCALE_GAPS`` runs as a non-strict expected failure on rate, and
still fails when its rate drops more than ``GAP_TOLERANCE`` below the stored
one. ``GOLDEN_INTENT_GAPS`` exempts an intent from the floor in one locale,
with the measured reason; an entry whose intent now matches a row fails.
"""
import json
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovoscope import End2EndTest

SKILL_ID = "ovos-skill-application-launcher.openvoiceos"
FALLBACK_RESPONSE = f"ovos.skills.fallback.{SKILL_ID}.response"
FALLBACK_PIPELINE = ["ovos-fallback-pipeline-plugin-high"]

END2END_DIR = Path(__file__).parent
LOCALE_ROOT = END2END_DIR.parent.parent / "locale"

# application names a row without an ``app`` field puts in the {application} slot
KNOWN_APPS = ("spotify", "firefox")

MIN_MATCH_RATE = 0.8
# Every intent with rows in a locale must match at least this many of them,
# so the locale rate cannot hide an intent that never matches.
MIN_MATCHED_ROWS_PER_INTENT = 1
GAP_TOLERANCE = 0.10

# the two kinds of failure a row can have
SLOT = ("the slot keeps an article, object marker or extra word, so the "
        "skill's launch_app/close_app score falls below 0.85 and nothing happens")
NO_LINE = "no intent line covers this phrasing, so the fallback declines it"

LINES_NEED_NOUN = ("the natural polite and imperative requests need the application noun "
                   "('la aplicación', 'appen') that a speaker leaves out; a line without the "
                   "noun takes other skills' requests")
OBJECT_MARKER = ("the Persian object marker را stays in the slot, so the skill's launch_app/"
                 "close_app score falls below 0.85; the lines do not take it out")
NO_IMPERATIVE_LINES = ("the locale ships only infinitive lines, and its rows are imperative or "
                       "polite requests; an imperative line without the application noun takes "
                       "other skills' requests")
NO_ROW_TAKES_EFFECT = ("no row of this intent takes effect: the locale's lines cover the "
                       "infinitive only, and its rows are imperative or polite requests")

# {(lang, utterance): SLOT or NO_LINE}
KNOWN_BUGS = {
    ('ca-ES', 'tanca el firefox'): SLOT,
    ('ca-ES', 'pots obrir el gimp'): NO_LINE,
    ('ca-ES', 'podries tancar el vlc'): NO_LINE,
    ('da-DK', 'åbn spotify'): NO_LINE,
    ('da-DK', 'kan du åbne gimp'): NO_LINE,
    ('da-DK', 'kan du lukke vlc'): NO_LINE,
    ('de-DE', 'lass firefox laufen'): NO_LINE,
    ('de-DE', 'kannst du gimp öffnen'): NO_LINE,
    ('de-DE', 'könntest du vlc schließen'): SLOT,
    ('en-US', 'close the spotify app'): SLOT,
    ('es-CO', 'abra spotify'): NO_LINE,
    ('es-CO', 'ejecute spotify'): NO_LINE,
    ('es-CO', 'inicia spotify'): NO_LINE,
    ('es-CO', 'cierre spotify'): NO_LINE,
    ('es-CO', 'cierra spotify'): NO_LINE,
    ('es-CO', 'salga de spotify'): NO_LINE,
    ('es-CO', 'me puede abrir firefox'): NO_LINE,
    ('es-CO', 'podría cerrar thunderbird'): NO_LINE,
    ('es-ES', 'abre firefox'): NO_LINE,
    ('es-ES', 'ejecuta spotify'): NO_LINE,
    ('es-ES', 'abre la calculadora'): NO_LINE,
    ('es-ES', 'cierra firefox'): NO_LINE,
    ('es-ES', 'termina spotify'): NO_LINE,
    ('es-ES', 'cierra el thunderbird'): NO_LINE,
    ('es-ES', 'inicia spotify'): NO_LINE,
    ('es-ES', 'sal de spotify'): NO_LINE,
    ('es-ES', 'puedes abrir gimp'): NO_LINE,
    ('es-ES', 'podrías cerrar vlc'): NO_LINE,
    ('fa-IR', 'فایرفاکس را اجرا کن'): SLOT,
    ('fa-IR', 'فایرفاکس را ببند'): SLOT,
    ('fr-FR', 'tu peux ouvrir gimp'): NO_LINE,
    ('fr-FR', 'tu pourrais fermer vlc'): NO_LINE,
    ('gl-ES', 'abre firefox'): NO_LINE,
    ('gl-ES', 'executa spotify'): NO_LINE,
    ('gl-ES', 'abre a calculadora'): NO_LINE,
    ('gl-ES', 'pecha firefox'): NO_LINE,
    ('gl-ES', 'remata spotify'): NO_LINE,
    ('gl-ES', 'pecha o thunderbird'): NO_LINE,
    ('gl-ES', 'inicia spotify'): NO_LINE,
    ('gl-ES', 'sae de spotify'): NO_LINE,
    ('gl-ES', 'podes abrir gimp'): NO_LINE,
    ('gl-ES', 'poderías pechar vlc'): NO_LINE,
    ('it-IT', 'puoi aprire gimp'): NO_LINE,
    ('it-IT', 'potresti chiudere vlc'): NO_LINE,
    ('nl-NL', 'kun je gimp openen'): NO_LINE,
    ('nl-NL', 'wil je vlc afsluiten'): NO_LINE,
    ('pl-PL', 'uruchom gimp'): NO_LINE,
    ('pl-PL', 'czy możesz otworzyć thunderbird'): NO_LINE,
    ('pl-PL', 'czy możesz zamknąć vlc'): NO_LINE,
    ('pt-BR', 'você pode abrir o gimp'): NO_LINE,
    ('pt-BR', 'pode fechar o vlc'): NO_LINE,
    ('pt-PT', 'podes abrir o gimp'): NO_LINE,
    ('pt-PT', 'podias fechar o vlc'): NO_LINE,
    ('ru-RU', 'выйди из spotify'): NO_LINE,
    ('ru-RU', 'открой firefox'): NO_LINE,
    ('ru-RU', 'запусти spotify'): NO_LINE,
    ('ru-RU', 'закрой thunderbird'): NO_LINE,
    ('ru-RU', 'можешь закрыть vlc'): NO_LINE,
    ('sv-SE', 'kan du öppna gimp'): NO_LINE,
    ('sv-SE', 'kan du stänga vlc'): NO_LINE,
}

# {lang: (effect pass rate measured in two runs, reason)}
GOLDEN_LOCALE_GAPS = {
    'ca-ES': (0.625, LINES_NEED_NOUN),
    'da-DK': (0.7, LINES_NEED_NOUN),
    'de-DE': (0.7, LINES_NEED_NOUN),
    'es-CO': (0.0, NO_IMPERATIVE_LINES),
    'es-ES': (0.0, NO_IMPERATIVE_LINES),
    'fa-IR': (0.667, OBJECT_MARKER),
    'gl-ES': (0.0, NO_IMPERATIVE_LINES),
    'pl-PL': (0.667, LINES_NEED_NOUN),
    'pt-BR': (0.75, LINES_NEED_NOUN),
    'pt-PT': (0.778, LINES_NEED_NOUN),
    'ru-RU': (0.5, LINES_NEED_NOUN),
    'sv-SE': (0.75, LINES_NEED_NOUN),
}

# {lang: {intent: reason}}
GOLDEN_INTENT_GAPS = {
    'es-CO': {'close': NO_ROW_TAKES_EFFECT, 'launch': NO_ROW_TAKES_EFFECT},
    'es-ES': {'close': NO_ROW_TAKES_EFFECT, 'launch': NO_ROW_TAKES_EFFECT},
    'gl-ES': {'close': NO_ROW_TAKES_EFFECT, 'launch': NO_ROW_TAKES_EFFECT},
}

# {lang: {utterance: claimed intent}}: a negative row the matcher hands to
# launch_app/close_app on purpose; every other claim fails
NEGATIVE_KNOWN_CLAIMS = {
    "en-US": {"start a timer for five minutes": "launch"},
    "fa-IR": {"پرده\u200cهای اتاق خواب را ببند": "close"},
    "kab": {"sexsi tafat": "close"},
}


class WrongFailure(RuntimeError):
    """A listed row failed in another way than listed."""


class Result(NamedTuple):
    passed: bool
    kind: str
    attempts: list
    calls: list
    expected: str


# {(lang, utterance, intent_label): Result}, filled by the row tests and used
# by the locale gates, so a row never runs twice in one session
RESULTS = {}


def load_rows(lang: str, kind: str = "golden") -> list:
    path = END2END_DIR / f"{kind}_utterances_{lang}.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows, f"{lang}: no {kind} rows"
    return rows


def row_id(row: dict) -> str:
    return f"{row['lang']}-{row['intent_label']}-{row['utterance']}"


def row_param(lang: str, row: dict, *values):
    """A pytest param that runs a listed row as a strict expected failure."""
    marks = []
    reason = KNOWN_BUGS.get((lang, row["utterance"]))
    if reason:
        marks.append(pytest.mark.xfail(raises=AssertionError, strict=True, reason=f"known-bug: {reason}"))
    return pytest.param(*values, id=row_id(row), marks=marks)


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


def run_row(minicroft, fake_desktop, lang: str, row: dict) -> Result:
    key = (lang, row["utterance"], row["intent_label"])
    if key not in RESULTS:
        skill = minicroft.plugin_skills[SKILL_ID].instance
        skill.attempts.clear()
        skill.calls.clear()
        messages = capture(minicroft, row["utterance"], lang, f"golden-{row_id(row)}")
        words = row["utterance"].lower().split()
        app = row.get("app") or next((a for a in KNOWN_APPS if a in words), None)
        assert app, f"[{lang}] {row['utterance']!r}: row names no application"
        command = fake_desktop.expected_command(app)
        expected = f"{row['intent_label']} of {command!r}"
        passed = skill.calls == [(row["intent_label"], command)] and fallback_consumed(messages)
        if passed:
            kind = ""
        elif skill.calls:
            kind = "WRONG_COMMAND"
        elif skill.attempts:
            kind = SLOT
        else:
            kind = NO_LINE
        RESULTS[key] = Result(passed, kind, list(skill.attempts), list(skill.calls), expected)
    return RESULTS[key]


def assert_effect(minicroft, fake_desktop, lang: str, row: dict) -> None:
    """Fail unless the skill did what the row asks. A listed row raises
    AssertionError only for the failure kind it is listed with."""
    result = run_row(minicroft, fake_desktop, lang, row)
    if result.passed:
        return
    message = (f"[{lang}] {row['utterance']!r}: expected {result.expected}; "
               f"the handler passed {result.attempts} and the skill did {result.calls}")
    listed = KNOWN_BUGS.get((lang, row["utterance"]))
    if listed and result.kind != listed:
        raise WrongFailure(f"{message}; listed as {listed!r} but the failure is {result.kind!r}")
    raise AssertionError(message)


def check_locale_gate(lang: str, rows: list, minicroft, fake_desktop) -> None:
    """The rate gate and the per-intent floor of one locale."""
    results = [run_row(minicroft, fake_desktop, lang, row) for row in rows]
    misses = [f"{row['utterance']!r}: expected {result.expected}, {result.kind}"
              for row, result in zip(rows, results) if not result.passed]
    rate = sum(result.passed for result in results) / len(rows)
    print(f"[{lang}] {rate:.1%} of {len(rows)} rows take effect", *misses, sep="\n  ")
    matched = Counter(row["intent_label"] for row, result in zip(rows, results) if result.passed)
    labels = {row["intent_label"] for row in rows}
    exempt = GOLDEN_INTENT_GAPS.get(lang, {})
    starved = sorted(label for label in labels
                     if matched[label] < MIN_MATCHED_ROWS_PER_INTENT and label not in exempt)
    stale = sorted(label for label in exempt
                   if label not in labels or matched[label] >= MIN_MATCHED_ROWS_PER_INTENT)
    assert not stale, f"[{lang}] GOLDEN_INTENT_GAPS entries that now match or have no rows: {stale}"
    assert not starved, (
        f"[{lang}] intents with fewer than {MIN_MATCHED_ROWS_PER_INTENT} matched rows: {starved}"
    )
    if lang in GOLDEN_LOCALE_GAPS:
        measured, reason = GOLDEN_LOCALE_GAPS[lang]
        assert rate >= measured - GAP_TOLERANCE, (
            f"[{lang}] {rate:.1%} of rows take effect, more than {GAP_TOLERANCE:.0%} below "
            f"the measured {measured:.0%} of the gap entry"
        )
        assert rate < MIN_MATCH_RATE, (
            f"[{lang}] {rate:.1%} of rows take effect: remove the GOLDEN_LOCALE_GAPS entry"
        )
        pytest.xfail(f"[{lang}] {rate:.1%}: {reason}")
    assert rate >= MIN_MATCH_RATE, (
        f"[{lang}] {rate:.1%} of rows take effect, below {MIN_MATCH_RATE:.0%}:\n  " + "\n  ".join(misses)
    )


def check_negative(minicroft, lang: str, row: dict) -> None:
    skill = minicroft.plugin_skills[SKILL_ID].instance
    skill.attempts.clear()
    utterance = row["utterance"]
    messages = capture(minicroft, utterance, lang, f"negative-{lang}-{utterance}")
    # a claim is the matcher handing the request to launch_app/close_app,
    # whether or not an installed application then matches
    if not skill.attempts and not fallback_consumed(messages):
        return
    claimed = skill.attempts[0][0] if skill.attempts else None
    known = NEGATIVE_KNOWN_CLAIMS.get(lang, {}).get(utterance)
    assert known is not None and known == claimed, (
        f"[{lang}] {utterance!r} belongs to another skill, but the launcher "
        f"claimed it as {claimed!r} ({skill.attempts})"
    )
