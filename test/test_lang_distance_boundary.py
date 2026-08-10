"""The language-distance boundary used to pick an intent matcher and a
blacklist."""
import importlib.util
import os
import sys
from unittest.mock import Mock

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MACROLANGUAGE_PAIRS = [("arz", "ar"), ("wuu", "zh")]
REGIONAL_PAIRS = [("ar-SA", "ar"), ("en-AU", "en-GB"), ("pt-BR", "pt-PT")]
UNRELATED_PAIRS = [("en", "zh"), ("es", "fr"), ("fr-CH", "de-CH"), ("af", "nl")]


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location(
        "appl_skill_boundary", os.path.join(REPO, "__init__.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appl_skill_boundary"] = mod
    spec.loader.exec_module(mod)
    return mod


def _match_app(module, requested, available):
    skill = module.ApplicationLauncherSkill.__new__(module.ApplicationLauncherSkill)
    matcher = Mock()
    matcher.calc_intent.return_value = {"name": "launch",
                                        "entities": {"application": "firefox"}}
    skill.intent_matchers = {available: matcher}
    skill.blacklists = {}
    return module.ApplicationLauncherSkill.match_app.__wrapped__(
        skill, "open firefox", requested)


def _is_blacklisted(module, requested, available):
    skill = module.ApplicationLauncherSkill.__new__(module.ApplicationLauncherSkill)
    skill.blacklists = {available: ["firefox"]}
    return module.ApplicationLauncherSkill._is_blacklisted(skill, "firefox", requested)


def test_macrolanguage_matcher_is_used(module):
    for member, macro in MACROLANGUAGE_PAIRS:
        assert _match_app(module, member, macro) is not None, member


def test_regional_matcher_is_used(module):
    for requested, available in REGIONAL_PAIRS:
        assert _match_app(module, requested, available) is not None, requested


def test_unrelated_matcher_is_rejected(module):
    for requested, available in UNRELATED_PAIRS:
        assert _match_app(module, requested, available) is None, requested


def test_macrolanguage_blacklist_applies(module):
    for member, macro in MACROLANGUAGE_PAIRS:
        assert _is_blacklisted(module, member, macro) is True, member


def test_regional_blacklist_applies(module):
    for requested, available in REGIONAL_PAIRS:
        assert _is_blacklisted(module, requested, available) is True, requested


def test_unrelated_blacklist_does_not_apply(module):
    for requested, available in UNRELATED_PAIRS:
        assert _is_blacklisted(module, requested, available) is False, requested
