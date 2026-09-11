"""Unit tests for locale loading and the sr@latn fix (issue #91)."""
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from ovos_skill_application_launcher import ApplicationLauncherSkill, _is_valid_bcp47


class TestIsValidBCP47(unittest.TestCase):
    """_is_valid_bcp47 helper."""

    def test_valid_tags(self):
        for tag in ("en-US", "pt-PT", "de-DE", "sr-Latn", "zh-CN"):
            with self.subTest(tag=tag):
                self.assertTrue(_is_valid_bcp47(tag))

    def test_invalid_posix_sr_at_latn(self):
        self.assertFalse(_is_valid_bcp47("sr@latn"))

    def test_garbage_tag(self):
        self.assertFalse(_is_valid_bcp47("not_a_tag!!"))


class TestRegisterFallbackIntents(unittest.TestCase):
    """register_fallback_intents must skip invalid POSIX locale dirs without crashing."""

    def _make_skill_and_run(self, locale_dirs):
        """Build a minimal skill, wire register_fallback_intents, run it."""
        skill = MagicMock(spec=ApplicationLauncherSkill)
        skill.intent_matchers = {}
        skill.skill_id = "test.skill"

        with tempfile.TemporaryDirectory() as td:
            skill.root_dir = td
            for lang_dir, intents in locale_dirs.items():
                ldir = os.path.join(td, "locale", lang_dir)
                os.makedirs(ldir, exist_ok=True)
                for intent_name, lines in intents.items():
                    with open(os.path.join(ldir, f"{intent_name}.intent"), "w") as fh:
                        fh.write("\n".join(lines))

            ApplicationLauncherSkill.register_fallback_intents(skill)
            return dict(skill.intent_matchers)

    def test_valid_locale_loaded(self):
        matchers = self._make_skill_and_run({
            "en-US": {"launch": ["open {application}", "launch {application}"]}
        })
        self.assertIn("en-US", matchers)

    def test_sr_at_latn_skipped_no_crash(self):
        """sr@latn must not crash skill loading (issue #91)."""
        matchers = self._make_skill_and_run({
            "en-US": {"launch": ["open {application}"]},
            "sr@latn": {"launch": ["otvori {application}"]},
        })
        self.assertIn("en-US", matchers)
        self.assertNotIn("sr@latn", matchers)

    def test_empty_locale_dir_skipped(self):
        matchers = self._make_skill_and_run({
            "en-US": {"launch": ["open {application}"]},
            "de-DE": {},
        })
        self.assertIn("en-US", matchers)
        self.assertNotIn("de-DE", matchers)

    def test_multiple_valid_locales(self):
        matchers = self._make_skill_and_run({
            "en-US": {"launch": ["open {application}"], "close": ["close {application}"]},
            "pt-PT": {"launch": ["abrir {application}"]},
        })
        self.assertIn("en-US", matchers)
        self.assertIn("pt-PT", matchers)


class TestMatchApp(unittest.TestCase):

    def _make_skill(self, matchers):
        from padacioso import IntentContainer
        skill = MagicMock(spec=ApplicationLauncherSkill)
        skill.intent_matchers = matchers
        skill.blacklists = {}
        skill._is_blacklisted = ApplicationLauncherSkill._is_blacklisted.__get__(skill)
        skill.lang = "en-US"
        # bind lru_cache'd method
        import functools
        skill.match_app = functools.lru_cache(10)(
            lambda utt, lang: ApplicationLauncherSkill.match_app.__wrapped__(skill, utt, lang)
        )
        return skill

    def test_match_app_launch(self):
        from padacioso import IntentContainer
        ic = IntentContainer()
        ic.add_intent("launch", ["open {application}", "launch {application}"])

        skill = MagicMock(spec=ApplicationLauncherSkill)
        skill.intent_matchers = {"en-US": ic}
        skill.blacklists = {}
        skill._is_blacklisted = ApplicationLauncherSkill._is_blacklisted.__get__(skill)

        # match_app is lru_cache'd; call the underlying function directly
        res = ApplicationLauncherSkill.match_app.__wrapped__(skill, "open firefox", "en-US")
        self.assertIsNotNone(res)
        self.assertEqual(res.get("entities", {}).get("application"), "firefox")

    def test_match_app_no_matchers(self):
        skill = MagicMock(spec=ApplicationLauncherSkill)
        skill.intent_matchers = {}
        skill.blacklists = {}
        skill._is_blacklisted = ApplicationLauncherSkill._is_blacklisted.__get__(skill)
        res = ApplicationLauncherSkill.match_app(skill, "open firefox", "en-US")
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
