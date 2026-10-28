"""Multilingual golden-utterance end-to-end coverage for
ovos-skill-application-launcher.

Every locale under locale/ ships launch.intent / close.intent templates
(padacioso IntentContainer, see __init__.py register_fallback_intents()).
This suite runs every row of every golden_utterances_<lang>.jsonl file,
including the machine-generated rows marked needs_manual, so each shipped
locale is exercised.

The skill is a FallbackSkill: it exposes no ovos.intent.matched event, only
a high-priority fallback handler matched by its own padacioso containers
(one IntentContainer per locale, all loaded at initialize() regardless of
which locale MiniCroft boots as primary).

Rows are natural requests a speaker of the locale makes, each naming a real
application. A row's ``app`` field holds that application. The skill's own
launch_app/close_app run against the fake desktop in conftest.py, and the test
asserts the effect: the skill launched or terminated the command of ``app``.
A row rewritten from an older template-made row keeps the old text in
``rewritten_from``.

negative_utterances_<lang>.jsonl holds requests for other skills that share
the launcher's verbs ("open the garage door", "close the blinds"). Each one
must leave the fallback unclaimed.

Every row reports to the ovoscope routing tally, and the run fails when the
share of rows that route falls below ``ovoscope_min_routing_rate``.

One MiniCroft is booted PER LOCALE (not one shared instance with every
locale as a secondary_lang -- that boot shape hangs on the ovoscope
harness bug tracked for the alerts skill's multilang suite). The
per-locale MiniCroft fixture is module-scoped and indirectly parametrized
by lang; pytest reuses one boot per distinct lang value across every row
belonging to that lang and tears it down before moving to the next.
"""
import gc

import pytest
from ovos_utils.bracket_expansion import expand_template
from ovos_utils.log import LOG
from ovoscope import get_minicroft

from .golden_support import (
    END2END_DIR,
    LOCALE_ROOT,
    SKILL_ID,
    assert_effect,
    check_negative,
    load_rows,
    row_id,
)

LANGS = sorted(p.stem.split("golden_utterances_", 1)[1]
               for p in END2END_DIR.glob("golden_utterances_*.jsonl"))
assert LANGS, "no golden_utterances_<lang>.jsonl files found"
NEGATIVE_LANGS = sorted(p.stem.split("negative_utterances_", 1)[1]
                        for p in END2END_DIR.glob("negative_utterances_*.jsonl"))
ROWS = {lang: load_rows(lang) for lang in LANGS}


@pytest.fixture(scope="module")
def minicroft(request, fake_desktop):
    """One MiniCroft boot per distinct lang value, reused across every row
    of that lang (pytest caches module-scoped indirect fixtures by param
    value and groups tests to minimise re-instantiation)."""
    lang = request.param
    LOG.set_level("CRITICAL")
    mc = get_minicroft([SKILL_ID], max_wait=150, lang=lang)
    restore = fake_desktop.install(mc.plugin_skills[SKILL_ID].instance)
    yield mc
    restore()
    ee = getattr(mc.bus, "ee", None)
    if ee is not None:
        events = getattr(ee, "_events", None)
        if events is not None:
            for event in list(events.keys()):
                events.pop(event, None)
            gc.collect()
    mc.stop()


@pytest.mark.timeout(600)
@pytest.mark.parametrize("minicroft,row", [pytest.param(lang, row, id=row_id(row))
                                          for lang in LANGS for row in ROWS[lang]],
                         indirect=["minicroft"])
def test_golden_utterance_multilang(minicroft, fake_desktop, row):
    assert_effect(minicroft, fake_desktop, row["lang"], row)


@pytest.mark.timeout(600)
@pytest.mark.parametrize("minicroft,row", [pytest.param(lang, row, id=f"{lang}-negative-{row['utterance']}")
                                          for lang in NEGATIVE_LANGS for row in load_rows(lang, "negative")],
                         indirect=["minicroft"])
def test_negative_utterance_multilang(minicroft, row):
    check_negative(minicroft, row["lang"], row["utterance"])


def test_every_locale_ships_every_en_us_intent_file():
    reference = {p.name for p in (LOCALE_ROOT / "en-US").glob("*.intent")}
    assert reference, "en-US ships no .intent files"
    locales = [d for d in LOCALE_ROOT.iterdir() if d.is_dir()]
    missing = {d.name: sorted(reference - {p.name for p in d.glob("*.intent")}) for d in locales}
    missing = {lang: files for lang, files in missing.items() if files}
    assert not missing, f"locales missing en-US intent files: {missing}"
    empty = {d.name: sorted(name for name in reference if not any(
        line.strip() and not line.startswith("#")
        for line in (d / name).read_text(encoding="utf-8").splitlines())) for d in locales}
    empty = {lang: files for lang, files in empty.items() if files}
    assert not empty, f"intent files with no template line: {empty}"
    for d in locales:
        for name in reference:
            for line in (d / name).read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.startswith("#"):
                    assert list(expand_template(line)), f"{d.name}/{name}: {line!r} expands to nothing"


def test_every_shipping_locale_has_a_golden_file():
    golden = {p.stem.split("_", 2)[2]
              for p in END2END_DIR.glob("golden_utterances_*.jsonl")}
    shipping = {d.name for d in LOCALE_ROOT.iterdir()
                if d.is_dir() and any(d.rglob("*.intent"))}
    assert golden == shipping, (
        f"golden files {sorted(golden ^ shipping)} differ from shipping locales"
    )

